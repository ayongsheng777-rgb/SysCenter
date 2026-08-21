# -*- coding: utf-8 -*-
"""技能安装引擎（A 路：遥控安装 SkillHub 技能）。

能力：
- 解析「装技能」指令（提取 URL、技能名）
- 生成待确认清单（不直接执行）
- 管理员确认后执行并回报

执行方式：纯 Python 直装（不依赖 Git Bash / 系统 python3，适配 EXE 独立运行态）。
  · 装 CLI：下载 kit tarball → 解压 → 复制 skills_store_cli.py 等到 ~/.skillhub/
  · 装技能：用本进程 python（sys.executable）跑 skills_store_cli.py install <ref> --dir <skills 目录>

安全设计（对齐用户选择「先列再确认」）：
- 只生成清单、不立即执行；飞书回执列清单 + 确认编号
- 管理员回「确认 <编号>」才执行；10 分钟不确认自动作废
- 执行带超时；失败即停并回显输出
"""
import asyncio
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import uuid
import logging

import httpx

log = logging.getLogger("syscenter.skill_installer")

# skillhub 官方 kit 与配置（来源见 skillhub.cn/install/skillhub.md）
SKILLHUB_KIT_URL = "https://skillhub-1388575217.cos.ap-guangzhou.myqcloud.com/install/latest.tar.gz"
SKILLHUB_SELF_UPDATE_URL = "https://skillhub-1388575217.cos.ap-guangzhou.myqcloud.com/version.json"

HOME = os.path.expanduser("~")
SKILLHUB_HOME = os.path.join(HOME, ".skillhub")
SKILLHUB_CLI = os.path.join(SKILLHUB_HOME, "skills_store_cli.py")
# workbuddy 的 skills 目录（SkillHub 技能装到这里给 WorkBuddy 用）
WORKBUDDY_SKILLS_DIR = os.path.join(HOME, ".workbuddy", "skills")

_CLI_FILES = ("skills_store_cli.py", "skills_upgrade.py", "version.json", "metadata.json")

_SKILL_REF = re.compile(r"@([\w.-]+)/([\w.-]+)")
_URL_RE = re.compile(r"https?://[^\s，。；;、]+")

# 待确认队列（内存态，重启即丢，设计内取舍）
_pending: dict[str, dict] = {}
_pending_lock = threading.Lock()
_PENDING_TTL = 600  # 10 分钟


# ==================== 指令解析 ====================
def parse_install_request(text: str) -> dict:
    """从消息里提取 URL 与技能引用（@ns/slug 或纯名）。"""
    urls = [u.rstrip(".,)") for u in _URL_RE.findall(text or "")]
    refs = _SKILL_REF.findall(text or "")  # [(ns, slug), ...]
    skills = [f"@{ns}/{slug}" for ns, slug in refs]
    plain = []
    m = re.search(r"(?:安装|装)\s*(?:技能|skill)?\s*([A-Za-z0-9][A-Za-z0-9._-]{2,})", text or "", re.I)
    if m and not m.group(1).startswith("http"):
        plain.append(m.group(1))
    return {"urls": urls, "skills": skills + plain}


def is_install_request(text: str) -> bool:
    """判断消息是否属于「装技能」意图。"""
    t = text or ""
    if re.search(r"装技能|安装技能|装\s*skill|安装\s*skill|install\s+skill", t, re.I):
        return True
    if "安装" in t and ("http" in t or _SKILL_REF.search(t)):
        return True
    return False


# ==================== 清单生成 ====================
def build_plan(text: str) -> dict | None:
    """生成待确认清单。返回 None 表示无法识别（应由调用方提示）。"""
    parsed = parse_install_request(text)
    skills = parsed["skills"]
    urls = parsed["urls"]
    is_skillhub = any("skillhub" in u for u in urls)

    steps: list[dict] = []
    warnings: list[str] = []

    if not skills and not urls:
        return None

    need_cli = is_skillhub or any("@" in s for s in skills)
    if need_cli:
        steps.append({
            "title": "确保 skillhub CLI 就绪（未装则自动下载安装）",
            "desc": f"下载 {SKILLHUB_KIT_URL} 并解压到 ~/.skillhub/",
            "action": "ensure_cli",
        })

    for s in skills:
        steps.append({
            "title": f"安装技能 {s}",
            "desc": f"skillhub install {s} --dir ~/.workbuddy/skills",
            "action": "install_skill",
            "skill": s,
        })

    if urls and not skills and not is_skillhub:
        warnings.append("链接非 skillhub，暂不支持自动解析安装步骤")

    if not steps:
        return None
    return {"kind": "skillhub" if (need_cli or skills) else "url",
            "steps": steps, "warnings": warnings, "urls": urls, "skills": skills}


def format_plan(plan: dict, confirm_id: str) -> str:
    """把清单渲染成飞书文本。"""
    lines = ["🛠 **待确认安装清单**", f"编号：`{confirm_id}`"]
    for i, st in enumerate(plan["steps"], 1):
        lines.append(f"\n步骤 {i}　{st['title']}")
        if st.get("desc"):
            lines.append(f"　　{st['desc']}")
    for w in plan.get("warnings", []):
        lines.append(f"\n⚠️ {w}")
    lines.append(f"\n回复「确认 {confirm_id}」执行；不回复或回复其它内容则放弃。")
    return "\n".join(lines)


# ==================== 待确认队列 ====================
def add_pending(chat_id: str, plan: dict) -> str:
    cid = uuid.uuid4().hex[:6]
    with _pending_lock:
        _pending[cid] = {"chat_id": chat_id, "steps": plan["steps"], "created": time.time()}
    return cid


def _get_pending(cid: str) -> dict | None:
    with _pending_lock:
        p = _pending.get(cid)
        if not p:
            return None
        if time.time() - p["created"] > _PENDING_TTL:
            _pending.pop(cid, None)
            return None
        return p


# ==================== 执行（纯 Python 直装） ====================
def _cli_installed() -> bool:
    return os.path.isfile(SKILLHUB_CLI)


def _ensure_client_id(cfg_path: str) -> None:
    """补 client_id（uuid，符合 [A-Za-z0-9._-]+），供 CLI 匿名统计/去重用。"""
    try:
        raw = {}
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw = loaded
        cid = str(raw.get("client_id") or "").strip()
        if cid and len(cid) <= 128 and re.fullmatch(r"[A-Za-z0-9._-]+", cid):
            return
        raw["client_id"] = str(uuid.uuid4())
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        log.warning("[skill_installer] 写 client_id 失败：%s", e)


async def _install_cli() -> tuple[bool, str]:
    """下载 kit 并安装 skillhub CLI（纯 Python，复刻官方 install.sh 核心步骤）。"""
    tmp = tempfile.mkdtemp(prefix="skillhub_")
    try:
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
                r = await c.get(SKILLHUB_KIT_URL)
            if r.status_code != 200:
                return False, f"下载失败 HTTP {r.status_code}"
            archive = r.content
        except Exception as e:  # noqa: BLE001
            return False, f"下载异常：{type(e).__name__}: {e}"

        arc_path = os.path.join(tmp, "kit.tar.gz")
        with open(arc_path, "wb") as f:
            f.write(archive)
        extract = os.path.join(tmp, "extract")
        os.makedirs(extract, exist_ok=True)
        with tarfile.open(arc_path, "r:gz") as tf:
            tf.extractall(extract)

        cli_dir = None
        for root, _dirs, files in os.walk(extract):
            if "skills_store_cli.py" in files:
                cli_dir = root
                break
        if not cli_dir:
            return False, "安装包内未找到 skills_store_cli.py"

        os.makedirs(SKILLHUB_HOME, exist_ok=True)
        for fn in _CLI_FILES:
            src = os.path.join(cli_dir, fn)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(SKILLHUB_HOME, fn))
        idx = os.path.join(cli_dir, "skills_index.local.json")
        if os.path.isfile(idx):
            shutil.copy2(idx, os.path.join(SKILLHUB_HOME, "skills_index.local.json"))

        cfg_path = os.path.join(SKILLHUB_HOME, "config.json")
        if not os.path.isfile(cfg_path):
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({"self_update_url": SKILLHUB_SELF_UPDATE_URL}, f, ensure_ascii=False, indent=2)
        _ensure_client_id(cfg_path)
        return True, f"CLI 已安装到 ~/.skillhub/"
    except Exception as e:  # noqa: BLE001
        return False, f"安装异常：{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _run_skillhub(args: list[str], timeout: int = 180) -> tuple[bool, str]:
    """用本进程 python 跑 skillhub CLI（skills_store_cli.py 仅依赖标准库）。"""
    if not _cli_installed():
        return False, "skillhub CLI 未安装"
    cmd = [sys.executable, SKILLHUB_CLI] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=SKILLHUB_HOME,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode == 0, out.decode("utf-8", "replace")
    except asyncio.TimeoutError:
        return False, f"执行超时（>{timeout}s）"
    except Exception as e:  # noqa: BLE001
        return False, f"执行异常：{type(e).__name__}: {e}"


def _check_installed(ref: str) -> str | None:
    """查 lock 文件：返回已装版本号，未装返回 None。"""
    lock_path = os.path.join(WORKBUDDY_SKILLS_DIR, ".skills_store_lock.json")
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            lock = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    entry = (lock.get("skills") or {}).get(ref)
    if not entry:
        return None
    return str(entry.get("version") or "").strip() or "?"


async def _install_skill(ref: str) -> tuple[bool, str]:
    installed = _check_installed(ref)
    if installed:
        return True, f"已安装（版本 {installed}），跳过"
    return await _run_skillhub(["install", ref, "--dir", WORKBUDDY_SKILLS_DIR])


async def confirm_and_run(cid: str) -> str:
    """确认并执行待确认清单。"""
    p = _get_pending(cid)
    if not p:
        return "⚠️ 该确认编号不存在或已过期（10 分钟内有效）。"
    with _pending_lock:
        _pending.pop(cid, None)

    lines = ["⚙️ **开始执行**"]
    for st in p["steps"]:
        action = st.get("action")
        lines.append(f"\n▶ {st['title']}")
        try:
            if action == "ensure_cli":
                if _cli_installed():
                    ok, out = True, "已安装，跳过"
                else:
                    ok, out = await _install_cli()
            elif action == "install_skill":
                ok, out = await _install_skill(st["skill"])
            else:
                ok, out = False, f"未知动作：{action}"
        except Exception as e:  # noqa: BLE001
            ok, out = False, f"{type(e).__name__}: {e}"
        lines.append("✅ 完成" if ok else "❌ 失败")
        tail = (out or "").strip()
        if tail:
            lines.append("```\n%s\n```" % tail[-800:])
        if not ok:
            lines.append("⛔ 后续步骤已取消。")
            break
    return "\n".join(lines)
