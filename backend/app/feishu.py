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
    """统一入口：推送飞书 + 落库告警日志（被健康检查等内部调用）。"""
    await db.save_alert(level, source, message, payload)
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
            system = ("你是 SysCenter 的系统管理助手，回答要简洁、用中文、面向个人服务器/运维场景。"
                      "如果用户问的是操作类问题，给出可执行的步骤。")
            reply = await ai_client.chat(system, text, max_tokens=1500, temperature=0.6, timeout=60.0)
        except Exception as e:  # noqa: BLE001
            reply = None
            log.warning("[feishu] AI 中转失败：%s", e)
        if not reply:
            await self.send_text(chat_id, "⚠️ AI 调用失败或未返回内容（检查 AI Key / 代理）。", "chat_id")
            return
        # 飞书单条文本上限保护
        if len(reply) > 3000:
            reply = reply[:3000] + "\n…（内容过长已截断）"
        await self.send_text(chat_id, f"🤖 {reply}", "chat_id")

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
            "· 其它任意文字 — 转发给 AI（DeepSeek）问答\n\n"
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
