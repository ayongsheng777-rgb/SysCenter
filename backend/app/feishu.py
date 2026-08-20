# -*- coding: utf-8 -*-
"""飞书集成（SysCenter）

两部分能力：
1) 单向推送（保留）：自定义机器人 webhook + HMAC 签名，被 scheduler 健康检查 / 手动告警调用。
2) 双向 bot 智能体（新增）：WebSocket 长连接（lark_oapi），主动出向连接飞书，
   绕开本机公网入向 80/443 封锁（与 OmniCraft 同因）。能收消息、做指令路由、
   带门禁（仅管理员/白名单机器人响应）、断线自动重连。

为什么用 WS 而非 Webhook 回调：飞书事件订阅强制要 HTTPS 公网回调地址，本机入向被封，过不去。
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.parse
from typing import Any, Awaitable, Callable

import httpx

from . import db
from .config import settings
from . import sensitive

log = logging.getLogger("feishu")

FEISHU_BASE = "https://open.feishu.cn/open-apis"


# ==================== 1) 单向推送（webhook，原样保留） ====================
def _sign(secret: str) -> tuple[str, str]:
    """生成飞书自定义机器人签名所需的 timestamp 与 sign。"""
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode("utf-8"))
    return timestamp, sign


def _build_payload(content: dict) -> dict:
    """注入签名（若配置了 secret）。"""
    payload = dict(content)
    if settings.feishu_secret:
        ts, sign = _sign(settings.feishu_secret)
        payload["timestamp"] = ts
        payload["sign"] = sign
    return payload


async def send_text(text: str) -> tuple[bool, str]:
    """发送纯文本告警。返回 (ok, msg)。"""
    if not settings.feishu_enabled or not settings.feishu_webhook:
        return False, "飞书未启用或未配置 webhook"
    payload = _build_payload({
        "msg_type": "text",
        "content": {"text": text},
    })
    try:
        async with httpx.AsyncClient(timeout=10.0, proxy=settings.ai_proxy or None) as cli:
            r = await cli.post(settings.feishu_webhook, json=payload)
            data = r.json() if r.content else {}
        if data.get("code") == 0 or data.get("StatusMessage") == "success":
            return True, "ok"
        return False, str(data)
    except Exception as e:
        return False, f"请求失败: {type(e).__name__} {e}"


async def send_card(title: str, lines: list[str], template: str = "red") -> tuple[bool, str]:
    """发送卡片消息。lines 为文本行列表。"""
    if not settings.feishu_enabled or not settings.feishu_webhook:
        return False, "飞书未启用或未配置 webhook"
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": ln}} for ln in lines if ln]
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": elements or [{"tag": "div", "text": {"tag": "plain_text", "content": "（无内容）"}}],
        },
    }
    payload = _build_payload(card)
    try:
        async with httpx.AsyncClient(timeout=10.0, proxy=settings.ai_proxy or None) as cli:
            r = await cli.post(settings.feishu_webhook, json=payload)
            data = r.json() if r.content else {}
        if data.get("code") == 0 or data.get("StatusMessage") == "success":
            return True, "ok"
        return False, str(data)
    except Exception as e:
        return False, f"请求失败: {type(e).__name__} {e}"


async def notify(level: str, source: str, message: str, payload: dict | None = None):
    """统一入口：落库告警日志 + 推送飞书（被手动告警 /api/notify 调用，单次落库）。"""
    await db.save_alert(level, source, message, payload)
    icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(level, "ℹ️")
    title = f"{icon} SysCenter 告警"
    ok, msg = await send_card(title, [f"**级别**：{level}", f"**来源**：{source}", f"**内容**：{message}"])
    if not ok:
        log.warning("飞书推送失败: %s", msg)
    return ok, msg


async def send(level: str, source: str, message: str, payload: dict | None = None):
    """仅推送飞书，不落库（落库由调用方负责，用于避免调度器重复写入告警，P2-02）。"""
    icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(level, "ℹ️")
    title = f"{icon} SysCenter 告警"
    ok, msg = await send_card(title, [f"**级别**：{level}", f"**来源**：{source}", f"**内容**：{message}"])
    if not ok:
        log.warning("飞书推送失败: %s", msg)
    return ok, msg


# ==================== 2) 双向 bot（WebSocket 长连接） ====================
class FeishuService:
    """飞书 bot 智能体：WS 长连接收消息 + 指令路由 + 配对门禁 + AI 中转。"""

    def __init__(self,
                 get_cred: Callable[[], tuple[str, str]],
                 enabled: Callable[[], bool],
                 get_admin_users: Callable[[], list],
                 get_trusted_bots: Callable[[], list]) -> None:
        self._get_cred = get_cred
        self._enabled = enabled
        self._get_admin_users = get_admin_users
        self._get_trusted_bots = get_trusted_bots
        self._running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._started_at = ""
        self._recent_msg_ids: set[str] = set()

    # ---------------- 生命周期 ----------------
    def is_online(self) -> bool:
        c = self._client
        return bool(self._running and c is not None and getattr(c, "_conn", None) is not None)

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._loop = loop or asyncio.get_event_loop()
        self._started_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self._thread = threading.Thread(target=self._run, daemon=True, name="syscenter-feishu-ws")
        self._thread.start()
        log.info("[feishu] WS 长连接启动中")

    async def stop(self) -> None:
        self._running = False
        client = self._client
        self._client = None
        if client is not None:
            try:
                conn = getattr(client, "_conn", None)
                if conn is not None:
                    import lark_oapi.ws.client as _ws_mod
                    loop = getattr(_ws_mod, "loop", None)
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(conn.close(), loop)
            except Exception:  # noqa: BLE001
                pass
        log.info("[feishu] WS 长连接已停止")

    async def restart(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        await self.stop()
        if self._thread:
            for _ in range(50):
                if not self._thread.is_alive():
                    break
                await asyncio.sleep(0.1)
        self.start(loop)

    def status(self) -> dict:
        app_id, app_secret = self._get_cred()
        return {
            "enabled": bool(self._enabled()),
            "cred_configured": bool(app_id and app_secret),
            "bot_online": self.is_online(),
            "started_at": self._started_at,
            "admins": self._get_admin_users(),
        }

    # ---------------- WS 线程 ----------------
    def _run(self) -> None:
        import lark_oapi as lark
        import lark_oapi.ws.client as _ws_mod
        thread_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(thread_loop)
        _ws_mod.loop = thread_loop

        while self._running:
            app_id, app_secret = self._get_cred()
            if not (app_id and app_secret and self._enabled()):
                time.sleep(30)
                continue
            try:
                handler = (lark.EventDispatcherHandler.builder("", "")
                           .register_p2_im_message_receive_v1(self._on_message)
                           .build())
                client = lark.ws.Client(app_id, app_secret, event_handler=handler,
                                        log_level=lark.LogLevel.WARNING)
                self._client = client
                log.info("[feishu] WS 连接建立（app_id=%s…）", app_id[:10])
                client.start()          # 阻塞至断连
            except Exception as e:  # noqa: BLE001
                log.error("[feishu] WS 异常：%s", e)
            self._client = None
            if self._running:
                log.info("[feishu] WS 断开，10s 后重连…")
                time.sleep(10)

    # ---------------- 事件回调（SDK 线程，同步） ----------------
    def _on_message(self, data) -> None:
        try:
            event = getattr(data, "event", None)
            msg = getattr(event, "message", None) if event else None
            if not msg:
                return
            chat_id = getattr(msg, "chat_id", "") or ""
            chat_type = getattr(msg, "chat_type", "") or ""
            msg_type = getattr(msg, "message_type", "") or ""
            content = getattr(msg, "content", "{}") or "{}"
            msg_id = getattr(msg, "message_id", "") or ""
            # 事件去重：WS 重连后飞书会重投
            if msg_id:
                if msg_id in self._recent_msg_ids:
                    return
                self._recent_msg_ids.add(msg_id)
                if len(self._recent_msg_ids) > 500:
                    self._recent_msg_ids.clear()
                    self._recent_msg_ids.add(msg_id)
            if msg_type != "text":
                return
            try:
                obj = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                return
            text = (obj.get("text") or "").strip()
            if not text or not chat_id:
                return
            sender = getattr(event, "sender", None)
            sid_obj = getattr(sender, "sender_id", None) if sender else None
            open_id = (getattr(sid_obj, "open_id", "") if sid_obj else "") or ""
            sender_type = getattr(sender, "sender_type", "") or ""
            log.info("[feishu] 收到消息：type=%s chat=%s sender=%s(%s) text=%s",
                     msg_type, chat_type, sender_type, open_id[-6:], text[:30])
            self._submit(self._route_message(text, chat_id, open_id, sender_type, chat_type))
        except Exception as e:  # noqa: BLE001
            log.warning("[feishu] 消息处理异常：%s", e)

    async def _route_message(self, text: str, chat_id: str, open_id: str,
                             sender_type: str, chat_type: str) -> None:
        admins = set(self._get_admin_users() or [])

        # 配对模式：无任何管理员时，私聊首条自动绑定（群消息不绑定，防误配）
        if not admins and chat_type == "p2p" and open_id:
            await self._pair_admin(open_id)
            await self.send_text(chat_id,
                                 "✅ 配对成功：你已成为 SysCenter 飞书 bot 的管理员。\n发送「帮助」查看可用指令。",
                                 "chat_id")
            return

        # 门禁：仅管理员或白名单机器人响应，其余一律不回（省 token）
        trusted = set(self._get_trusted_bots() or [])
        if open_id not in admins and open_id not in trusted:
            return

        # 指令路由
        if text in ("帮助", "help", "Help", "?"):
            await self.send_text(chat_id, self._help_text(), "chat_id")
            return
        if text in ("系统", "sys", "系统体检"):
            await self._cmd_system(chat_id)
            return
        if text in ("状态", "status"):
            await self._cmd_status(chat_id)
            return
        if text in ("待办列表", "todolist", "todos"):
            await self._cmd_todo_list(chat_id)
            return
        if text.startswith("待办 ") or text.startswith("todo "):
            content = text.split(" ", 1)[1].strip()
            if content:
                tid = await db.add_todo(content)
                await self.send_text(chat_id, f"📝 已记录待办 #{tid}：{content}", "chat_id")
            else:
                await self.send_text(chat_id, "用法：待办 <内容>", "chat_id")
            return
        if text.startswith("完成 ") or text.startswith("done "):
            arg = text.split(" ", 1)[1].strip()
            try:
                tid = int(arg)
            except ValueError:
                await self.send_text(chat_id, "用法：完成 <待办编号>", "chat_id")
                return
            ok = await db.done_todo(tid)
            await self.send_text(chat_id,
                                 f"✅ 待办 #{tid} 已标记完成" if ok else f"⚠️ 未找到待办 #{tid}",
                                 "chat_id")
            return

        # ===== 笔记 / API Key =====
        low = text.lower()
        for kw in ("存key", "存 key", "存api", "存 api", "savekey", "save key"):
            if low.startswith(kw):
                await self._cmd_save_key(chat_id, text[len(kw):].strip(" ：:　"))
                return
        for kw in ("记笔记", "存笔记"):
            if text.startswith(kw):
                await self._cmd_save_note(chat_id, text[len(kw):].strip(" ：:　"))
                return
        for kw in ("查笔记", "找笔记", "查key", "查 key", "找key"):
            if low.startswith(kw):
                await self._cmd_find_note(chat_id, text[len(kw):].strip(" ：:　"))
                return
        if text in ("笔记列表", "笔记", "notelist", "notes"):
            await self._cmd_note_list(chat_id)
            return

        # 明文查看：明文 / 明文显示 / 显示明文 / 显示 <编号>
        for kw in ("明文显示", "显示明文", "明文", "显示"):
            if text.startswith(kw):
                await self._cmd_show_plaintext(chat_id, text[len(kw):].strip(" ：:　#"))
                return

        # 其余任意文字 → 转发给 AI（DeepSeek）
        await self._cmd_ai(chat_id, text)

    # ---------------- 指令实现 ----------------
    async def _pair_admin(self, open_id: str) -> None:
        try:
            await db.upsert_setting("feishu_admin_users", json.dumps([open_id], ensure_ascii=False))
            settings.feishu_admin_users = [open_id]
            log.info("[feishu] 配对成功，管理员已写入：%s", open_id[-6:])
        except Exception as e:  # noqa: BLE001
            log.warning("[feishu] 写入管理员失败：%s", e)

    async def _cmd_system(self, chat_id: str) -> None:
        try:
            from . import modules
            h = modules.system_health.get_health()
        except Exception as e:  # noqa: BLE001
            await self.send_text(chat_id, f"⚠️ 读取系统体检失败：{type(e).__name__}", "chat_id")
            return
        up = h.get('uptime_seconds') or 0
        try:
            up = int(up)
            d_, r_ = divmod(up, 86400); h_, r_ = divmod(r_, 3600); m_ = r_ // 60
            uptime_str = f"{d_}天{h_}时{m_}分" if d_ else f"{h_}时{m_}分"
        except Exception:
            uptime_str = str(up)
        lines = [f"💻 **系统体检**",
                 f"CPU：{h.get('cpu_percent')}%",
                 f"内存：{h.get('ram_percent')}%",
                 f"开机时长：{uptime_str}"]
        for d in (h.get("disks") or []):
            lines.append(f"磁盘 {d.get('mount')}：{d.get('percent')}%")
        net = h.get("net_io")
        if net:
            sent_mb = (net.get('bytes_sent', 0) or 0) / 1048576
            recv_mb = (net.get('bytes_recv', 0) or 0) / 1048576
            lines.append(f"网卡流量：↑{sent_mb:.1f} / ↓{recv_mb:.1f} MB")
        await self.send_text(chat_id, "\n".join(lines), "chat_id")

    async def _cmd_status(self, chat_id: str) -> None:
        lines = ["🔧 **SysCenter 模块状态**"]
        # 数据库
        try:
            async with db.pool().acquire() as c:
                await c.execute("SELECT 1")
            lines.append("· 数据库 Postgres：✅")
        except Exception as e:  # noqa: BLE001
            lines.append(f"· 数据库 Postgres：❌ {type(e).__name__}")
        lines.append(f"· Redis：{settings.redis_url}")
        lines.append(f"· AI（DeepSeek）：{'✅ 已配置' if settings.ai_ready else '⚠️ 未配置'}")
        st = self.status()
        lines.append(f"· 飞书 bot：{'🟢 在线' if st['bot_online'] else '⚪ 离线'}"
                     f"（凭据{'已填' if st['cred_configured'] else '未填'}）")
        await self.send_text(chat_id, "\n".join(lines), "chat_id")

    async def _cmd_todo_list(self, chat_id: str) -> None:
        try:
            todos = await db.list_todos(only_open=True, limit=20)
        except Exception as e:  # noqa: BLE001
            await self.send_text(chat_id, f"⚠️ 读取待办失败：{type(e).__name__}", "chat_id")
            return
        if not todos:
            await self.send_text(chat_id, "📋 暂无未完成待办。", "chat_id")
            return
        lines = ["📋 **未完成待办**"]
        for t in todos:
            lines.append(f"#{t['id']} · {t['content']}")
        lines.append("\n完成某条：完成 <编号>")
        await self.send_text(chat_id, "\n".join(lines), "chat_id")

    async def _cmd_ai(self, chat_id: str, text: str) -> None:
        if not settings.ai_enabled:
            await self.send_text(chat_id,
                                 "🤖 AI 未启用（设置页开启 AI 并填写 API Key 后可用）。\n"
                                 "其它可用指令请发「帮助」。", "chat_id")
            return
        try:
            from . import ai_client
            system = (
                "你是 SysCenter 的系统管理助手，回答要简洁、用中文、面向个人服务器/运维场景。"
                "如果用户想让你【保存/记录】某条信息，不要口头答应，严格输出一个 JSON 对象"
                "（不要带任何多余文字、不要 markdown 围栏）：\n"
                '{"action":"save_note","title":"<简短标题>","category":"apikey|code|tech|other",'
                '"provider":"siliconflow|deepseek|openai|空","content":"<用户给出的完整原文，不得改动或补全>"}\n'
                "category 判断：\n"
                "· API Key/密钥/Token（用于调模型或接口的长期密钥）→ apikey；\n"
                "· 一次性验证码/授权码/登录链接/邀请码/connect code（如浏览器配对码、应用授权码）→ code；\n"
                "· 技术经验/排障步骤 → tech；其它 → other。\n"
                "provider 仅 apikey 时填服务商（siliconflow/deepseek/openai），不确定就留空字符串；code 类不要填 provider。\n"
                "如果用户想【查看某条记录的明文完整内容】（例如说“把第11条明文发我”“显示 #12 的完整内容”），"
                '输出：{"action":"show_plaintext","id":<记录编号>}\n'
                "如果用户既不是保存也不是查看明文，就正常直接回答（纯文本，不要输出 JSON）。"
            )
            # P2-08：发给 AI 前对用户消息脱敏（密钥/Token/密码等）
            safe_text = sensitive.redact(text)
            reply = await ai_client.chat(system, safe_text, max_tokens=1500, temperature=0.3, timeout=60.0)
        except Exception as e:  # noqa: BLE001
            reply = None
            log.warning("[feishu] AI 中转失败：%s", e)
        if not reply:
            await self.send_text(chat_id, "⚠️ AI 调用失败或未返回内容（检查 AI Key / 代理）。", "chat_id")
            return
        # 识别「存笔记」意图：AI 若回了 save_note JSON，则执行落库
        try:
            from . import ai_client as _ac
            intent = _ac._extract_json(reply)
        except Exception:  # noqa: BLE001
            intent = None
        if isinstance(intent, dict) and intent.get("action") == "save_note":
            await self._exec_save_note(chat_id, intent)
            return
        if isinstance(intent, dict) and intent.get("action") == "show_plaintext":
            nid = intent.get("id")
            if isinstance(nid, str) and str(nid).isdigit():
                nid = int(nid)
            if isinstance(nid, int):
                await self._cmd_show_plaintext(chat_id, str(nid))
            else:
                await self.send_text(chat_id, "用法：查看明文需指定记录编号，例如「显示 11 的明文」", "chat_id")
            return
        # 飞书单条文本上限保护
        if len(reply) > 3000:
            reply = reply[:3000] + "\n…（内容过长已截断）"
        await self.send_text(chat_id, f"🤖 {reply}", "chat_id")

    # ---------------- 笔记 / API Key 指令实现 ----------------
    @staticmethod
    def _mask_key(key: str) -> str:
        key = (key or "").strip()
        return (key[:8] + "…" + key[-4:]) if len(key) > 12 else "•••"

    async def _cmd_save_key(self, chat_id: str, arg: str) -> None:
        arg = (arg or "").strip().strip('"').strip("'").strip()
        if not arg:
            await self.send_text(chat_id,
                                 "用法：`存key <服务商> <key>`\n服务商可选 siliconflow/deepseek/openai（可省略，自动识别）",
                                 "chat_id")
            return
        provider, key = "", arg
        parts = arg.split(None, 1)
        _alias = {"siliconflow": "siliconflow", "deepseek": "deepseek", "openai": "openai",
                  "硅基流动": "siliconflow", "硅基": "siliconflow", "other": "other"}
        if len(parts) == 2 and parts[0].lower() in _alias:
            provider = _alias[parts[0].lower()]
            key = parts[1].strip().strip('"').strip("'").strip()
        if not key:
            await self.send_text(chat_id, "用法：`存key <服务商> <key>`", "chat_id")
            return
        try:
            from .routers import notes
            note = await notes.save_api_key_note(key, provider=provider, title="飞书存 API Key")
        except Exception as e:  # noqa: BLE001
            log.warning("[feishu] 存 key 失败：%s", e)
            await self.send_text(chat_id, f"⚠️ 保存失败：{type(e).__name__}", "chat_id")
            return
        if not note:
            await self.send_text(chat_id, "⚠️ 未识别到有效 Key", "chat_id")
            return
        state = ("✅ 有效" if note["tested"] == "ok"
                 else "❌ 无效" if note["tested"] == "fail" else "⚠️ 未验证")
        await self.send_text(chat_id,
                             f"🔑 已保存 API Key（#{note['id']}）\n服务商：{note['provider']}\n"
                             f"Key：{self._mask_key(key)}\n可用性：{state} — {note['test_result']}",
                             "chat_id")

    async def _cmd_save_note(self, chat_id: str, arg: str) -> None:
        content = (arg or "").strip()
        if not content:
            await self.send_text(chat_id, "用法：`记笔记 <内容>`", "chat_id")
            return
        title = content[:20] + ("…" if len(content) > 20 else "")
        try:
            nid = await db.add_note(title, "tech", "", content, [], tested="untested", test_result="")
        except Exception as e:  # noqa: BLE001
            await self.send_text(chat_id, f"⚠️ 保存失败：{type(e).__name__}", "chat_id")
            return
        await self.send_text(chat_id, f"📝 已保存笔记 #{nid}：{title}", "chat_id")

    async def _cmd_find_note(self, chat_id: str, arg: str) -> None:
        q = (arg or "").strip()
        if not q:
            await self.send_text(chat_id, "用法：`查笔记 <关键词>`", "chat_id")
            return
        try:
            notes = await db.list_notes(q=q, limit=10)
        except Exception as e:  # noqa: BLE001
            await self.send_text(chat_id, f"⚠️ 检索失败：{type(e).__name__}", "chat_id")
            return
        if not notes:
            await self.send_text(chat_id, f"🔍 没有找到与「{q}」相关的笔记。", "chat_id")
            return
        lines = [f"🔍 命中 {len(notes)} 条："]
        for n in notes:
            c = n["content"] or ""
            if n["category"] in ("apikey", "code"):
                c = self._mask_key(c)
            else:
                c = c[:60] + ("…" if len(c) > 60 else "")
            state = {"ok": "✅", "fail": "❌"}.get(n["tested"], "·")
            lines.append(f"#{n['id']} [{n['category']}] {n['title']} {state}\n    {c}")
        await self.send_text(chat_id, "\n".join(lines), "chat_id")

    async def _cmd_note_list(self, chat_id: str) -> None:
        try:
            notes = await db.list_notes(limit=20)
        except Exception as e:  # noqa: BLE001
            await self.send_text(chat_id, f"⚠️ 读取失败：{type(e).__name__}", "chat_id")
            return
        if not notes:
            await self.send_text(chat_id, "📝 暂无笔记。用「存key <key>」或「记笔记 <内容>」添加。", "chat_id")
            return
        lines = [f"📝 已存 {len(notes)} 条笔记（最新在前）："]
        for n in notes:
            lines.append(f"#{n['id']} [{n['category']}] {n['title']}")
        lines.append("\n查详情：`查笔记 <关键词>`")
        await self.send_text(chat_id, "\n".join(lines), "chat_id")

    async def _cmd_show_plaintext(self, chat_id: str, arg: str) -> None:
        """查看某条记录的完整明文（API Key / 验证码等），不做脱敏。"""
        arg = (arg or "").strip().lstrip("#")
        if not arg.isdigit():
            await self.send_text(chat_id,
                                 "用法：`明文 <编号>`（如 `明文 11`），或 `明文显示 11` 查看完整内容。",
                                 "chat_id")
            return
        nid = int(arg)
        try:
            note = await db.get_note(nid)
        except Exception as e:  # noqa: BLE001
            await self.send_text(chat_id, f"⚠️ 读取失败：{type(e).__name__}", "chat_id")
            return
        if not note:
            await self.send_text(chat_id, f"⚠️ 没有找到编号为 {nid} 的记录。", "chat_id")
            return
        content = note.get("content") or ""
        cat = note.get("category")
        label = {"apikey": "API Key", "code": "验证码", "tech": "技术", "other": "其他"}.get(cat, cat)
        await self.send_text(chat_id,
                             f"🔓 明文（#{nid} · {label}）\n标题：{note.get('title')}\n内容：\n{content}",
                             "chat_id")

    async def _exec_save_note(self, chat_id: str, intent: dict) -> None:
        title = (intent.get("title") or "").strip() or "笔记"
        category = intent.get("category") or "other"
        if category not in ("apikey", "code", "tech", "other"):
            category = "other"
        content = (intent.get("content") or "").strip()
        provider = (intent.get("provider") or "").strip()
        if not content:
            await self.send_text(chat_id, "⚠️ 想保存但没拿到内容，请把要保存的信息再发一次。", "chat_id")
            return
        if category == "apikey":
            try:
                from .routers import notes
                note = await notes.save_api_key_note(content, provider=provider, title=title)
            except Exception as e:  # noqa: BLE001
                await self.send_text(chat_id, f"⚠️ 保存失败：{type(e).__name__}", "chat_id")
                return
            if not note:
                await self.send_text(chat_id, "⚠️ 未识别到有效 Key", "chat_id")
                return
            state = ("✅ 有效" if note["tested"] == "ok"
                     else "❌ 无效" if note["tested"] == "fail" else "⚠️ 未验证")
            await self.send_text(chat_id,
                                 f"🔑 已保存 API Key（#{note['id']} · {note['provider']}）\n"
                                 f"Key：{self._mask_key(content)}\n可用性：{state} — {note['test_result']}",
                                 "chat_id")
            return
        if category == "code":
            try:
                nid = await db.add_note(title, "code", "", content, ["验证码"],
                                        tested="skipped", test_result="一次性验证码，无需验证可用性")
            except Exception as e:  # noqa: BLE001
                await self.send_text(chat_id, f"⚠️ 保存失败：{type(e).__name__}", "chat_id")
                return
            await self.send_text(chat_id,
                                 f"🔑 已保存验证码（#{nid}）：{title}\n"
                                 f"内容已加密保存；发「明文 {nid}」查看完整内容。",
                                 "chat_id")
            return
        try:
            nid = await db.add_note(title, category, provider, content, [],
                                    tested="untested", test_result="")
            await self.send_text(chat_id, f"📝 已保存笔记 #{nid}：{title}", "chat_id")
        except Exception as e:  # noqa: BLE001
            await self.send_text(chat_id, f"⚠️ 保存失败：{type(e).__name__}", "chat_id")

    # ---------------- 底层收发 ----------------
    async def _get_token(self) -> str | None:
        app_id, app_secret = self._get_cred()
        if not app_id or not app_secret:
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as cli:
                r = await cli.post(f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
                                   json={"app_id": app_id, "app_secret": app_secret})
                data = r.json()
            if data.get("code") != 0:
                log.error("[feishu] token 获取失败：%s", data)
                return None
            return data["tenant_access_token"]
        except Exception as e:  # noqa: BLE001
            log.error("[feishu] token 异常：%s", e)
            return None

    async def _do_send(self, payload: dict, id_type: str = "chat_id") -> bool:
        token = await self._get_token()
        if not token:
            return False
        try:
            async with httpx.AsyncClient(timeout=15.0) as cli:
                r = await cli.post(f"{FEISHU_BASE}/im/v1/messages",
                                   params={"receive_id_type": id_type},
                                   headers={"Authorization": f"Bearer {token}",
                                            "Content-Type": "application/json; charset=utf-8"},
                                   json=payload)
                data = r.json()
            if data.get("code") == 0:
                return True
            log.warning("[feishu] 发送失败：%s", str(data)[:200])
        except Exception as e:  # noqa: BLE001
            log.warning("[feishu] 发送异常：%s", e)
        return False

    async def send_text(self, receive_id: str, text: str, id_type: str = "chat_id") -> bool:
        """bot 主动发文本（回复用 id_type=chat_id；私发管理员用 open_id）。"""
        return await self._do_send({"receive_id": receive_id, "msg_type": "text",
                                    "content": json.dumps({"text": text}, ensure_ascii=False)},
                                   id_type)

    def _submit(self, coro) -> None:
        loop = self._loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)

    @staticmethod
    def _help_text() -> str:
        return (
            "📖 **SysCenter 飞书 bot · 帮助**\n\n"
            "个人服务器/运维管理中心。以下指令仅管理员可用，其它消息不回应。\n\n"
            "· `帮助` — 查看本说明\n"
            "· `系统` — 系统体检（CPU / 内存 / 磁盘 / 流量）\n"
            "· `状态` — 模块状态（数据库 / Redis / AI / 飞书）\n"
            "· `待办 <内容>` — 记一条待办\n"
            "· `待办列表` — 查看未完成待办\n"
            "· `完成 <编号>` — 标记某条待办完成\n"
            "· `存key <服务商> <key>` — 保存 API Key 并自动测可用性（服务商可省，自动识别）\n"
            "· `记笔记 <内容>` — 保存一条技术笔记\n"
            "· `查笔记 <关键词>` — 检索已存笔记\n"
            "· `笔记列表` — 查看已存笔记\n"
            "· `明文 <编号>` / `明文显示 <编号>` — 查看某条记录的完整明文（API Key / 验证码等）\n"
            "· 其它任意文字 — 转发给 AI（DeepSeek）问答，也可自然语言让它存笔记\n\n"
            "⚠️ 首次使用请**私聊**本 bot 完成管理员配对（自动绑定你的账号）。"
        )


# ==================== 模块级单例 + 启动包装 ====================
feishu_service = FeishuService(
    get_cred=lambda: (settings.feishu_app_id, settings.feishu_app_secret),
    enabled=lambda: settings.feishu_enabled,
    get_admin_users=lambda: list(settings.feishu_admin_users or []),
    get_trusted_bots=lambda: list(settings.feishu_trusted_bots or []),
)


def start_feishu_bot() -> None:
    """由 main.py 启动生命周期调用。仅当启用且凭据齐全才启动。"""
    if not settings.feishu_enabled:
        log.info("[feishu] 飞书未启用，bot 不启动")
        return
    if not (settings.feishu_app_id and settings.feishu_app_secret):
        log.warning("[feishu] 缺少飞书 App ID/Secret，bot 不启动（webhook 推送仍可用）")
        return
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    feishu_service.start(loop)


async def stop_feishu_bot() -> None:
    await feishu_service.stop()
