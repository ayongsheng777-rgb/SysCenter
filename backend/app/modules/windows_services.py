# -*- coding: utf-8 -*-
"""Windows 系统级调度：服务可视化启停 + 注册表/启动文件夹扫描桌面应用

后端以本机进程运行，故 sc / winreg 操作的是真实 Windows 宿主机。
核心系统服务禁止在面板直接停止（避免系统崩溃，对应指南 modules/info 的 core_service 警告）。
"""
import locale
import logging
import os
import subprocess
from typing import Optional

try:
    import winreg  # Windows 专用；非 Windows 平台（如 CI Linux runner）降级为空实现
except ImportError:
    winreg = None

log = logging.getLogger("win_services")

# 受保护的核心服务（禁止面板停止）
PROTECTED_SERVICES = {
    "Winmgmt", "RpcSs", "DcomLaunch", "LanmanServer", "LanmanWorkstation",
    "Schedule", "EventLog", "PlugPlay", "Power", "Spooler", "Dnscache",
    "System", "Registry", "SamSS", "wersvc",
}


def _run(args: list[str], timeout: int = 15) -> tuple[int, str]:
    # 按字节读取，避免中文 Windows 下 sc/reg 输出 GBK(CP936) 导致 UTF-8 解码崩溃(500)。
    enc = locale.getpreferredencoding() or "cp936"
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, shell=False)
        out = (r.stdout or b"").decode(enc, errors="replace")
        out += (r.stderr or b"").decode(enc, errors="replace")
        return r.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, "命令超时"
    except Exception as e:
        return -2, str(e)


def list_services() -> list[dict]:
    """列出本机 Windows 服务（名称/显示名/状态/启动类型）。"""
    code, out = _run(["sc", "query", "type=", "service", "state=", "all"])
    if code != 0:
        return []
    services = []
    cur = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("SERVICE_NAME:"):
            if cur:
                services.append(cur)
            cur = {"name": line.split(":", 1)[1].strip(), "display": "", "state": "", "start_type": ""}
        elif line.startswith("DISPLAY_NAME:"):
            if cur is not None:
                cur["display"] = line.split(":", 1)[1].strip()
        elif line.startswith("STATE"):
            # STATE              : 4  RUNNING
            parts = line.split(":", 1)[1].strip().split(None, 1)
            if len(parts) == 2:
                cur["state"] = parts[1]
        elif line.startswith("WIN32_EXIT_CODE") or line.startswith("SERVICE_EXIT_CODE"):
            continue
    if cur:
        services.append(cur)
    # 补启动类型（并行 sc qc，避免数百个服务串行过慢导致接口超时/页面卡死）
    def _start_type(name: str) -> str:
        c2, o2 = _run(["sc", "qc", name])
        if c2 == 0:
            for ln in o2.splitlines():
                if "START_TYPE" in ln:
                    return ln.split(":", 1)[1].strip().split(None, 1)[-1]
        return ""
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=16) as ex:
            types = list(ex.map(_start_type, [s["name"] for s in services]))
        for s, t in zip(services, types):
            s["start_type"] = t
    except Exception:
        # 并行失败时回退串行，保证接口可用
        for s in services:
            s["start_type"] = _start_type(s["name"])
    return services


def service_action(name: str, action: str) -> tuple[bool, str]:
    """启动/停止服务。action in {start, stop}。核心服务拒绝。"""
    if name in PROTECTED_SERVICES:
        return False, f"服务 {name} 为核心系统服务，已被面板禁止操作以免系统崩溃"
    if action not in ("start", "stop"):
        return False, "动作仅支持 start/stop"
    code, out = _run(["sc", action, name])
    if code == 0:
        return True, out or f"{action} 成功"
    return False, out or f"{action} 失败"


def registry_startup_apps() -> list[dict]:
    """扫描注册表 Run 键 + 启动文件夹，列出开机自启应用。"""
    if winreg is None:
        return []  # 非 Windows 平台不支持注册表扫描，安全降级为空
    items = []
    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
    ]
    for hkey, sub in keys:
        try:
            with winreg.OpenKey(hkey, sub) as k:
                n = winreg.QueryInfoKey(k)[1]
                for i in range(n):
                    name, val, _ = winreg.EnumValue(k, i)
                    items.append({"scope": ("HKCU" if hkey == winreg.HKEY_CURRENT_USER else "HKLM"),
                                  "key": sub, "name": name, "command": val})
        except Exception:
            continue
    # 启动文件夹（当前用户）
    startup_dir = os.path.join(os.environ.get("APPDATA", ""),
                               r"Microsoft\Windows\Start Menu\Programs\Startup")
    if os.path.isdir(startup_dir):
        for f in os.listdir(startup_dir):
            items.append({"scope": "StartupFolder", "key": startup_dir,
                          "name": f, "command": os.path.join(startup_dir, f)})
    return items
