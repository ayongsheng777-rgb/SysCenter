# -*- coding: utf-8 -*-
"""SysCenter 统一入口（EXE 原生化核心，规格书 §5/§21/§40/§41）

以 SysCenter.exe 运行时的命令中枢：
    SysCenter.exe                # 等同 start
    SysCenter.exe start         # 前台启动后端（Ctrl+C 停止）
    SysCenter.exe stop          # 停止（Service 模式走 SCM；否则提示）
    SysCenter.exe restart       # 重启
    SysCenter.exe status        # 进程/PID/端口/库/健康检查
    SysCenter.exe doctor        # 全量诊断（EXE/配置/端口/DB/Redis/Docker/日志/迁移/网络）
    SysCenter.exe version       # 版本/构建/Commit/构建时间
    SysCenter.exe tray          # 托盘 GUI 模式（EXE 默认启动方式，无终端窗口）
    SysCenter.exe install       # 安装开机自启（登录时启动托盘，无需管理员）
    SysCenter.exe uninstall     # 取消开机自启
    SysCenter.exe migrate       # 执行数据库迁移（Alembic upgrade head）
    SysCenter.exe config        # 打印生效配置（密钥脱敏）
    SysCenter.exe backup        # 备份 PostgreSQL + 配置 + 数据 -> backup/SysCenter-YYYYMMDD-HHMMSS.zip
    SysCenter.exe restore       # 从备份 zip 恢复

设计原则（与规格书一致）：
- 复用现有业务代码（app.main:app / db / config），不另搞一套逻辑。
- 路径全部经统一封装（Path(__file__) 派生），兼容 开发 / EXE / Windows Service 三种工作目录。
- 不依赖 CWD；资源路径由本模块统一计算。
"""
import argparse
import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

# ===== 统一路径（规格书 §47/§48：不依赖 CWD） =====
# 开发态：__file__ 在 backend/syscenter_app.py，BACKEND_DIR=backend/
# EXE 冻结态（onefile）：__file__ 指向临时解压目录，资源应以 exe 所在目录为准
BACKEND_DIR = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    # SysCenter.exe 所在目录（生产布局：<安装目录>/SysCenter.exe）
    APP_HOME = Path(sys.executable).resolve().parent
else:
    APP_HOME = BACKEND_DIR
PROJECT_DIR = APP_HOME
# 数据/日志/备份默认随安装目录（可用 DATA_DIR 环境变量重定向到 C:\ProgramData\SysCenter\...）
# 必须在 import app.* 之前把 DATA_DIR 固化到环境变量，确保 auth.py / config.py / db.py
# 读取同一目录（冻结态 exe 目录即数据目录；开发态为 backend/data）。
os.environ.setdefault("DATA_DIR", str(APP_HOME / "data"))
DATA_DIR = Path(os.environ["DATA_DIR"])
LOG_DIR = APP_HOME / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOCK_FILE = DATA_DIR / "syscenter.lock"
BACKUP_DIR = APP_HOME / "backup"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# 把 backend 加入 sys.path，确保 `app.main:app` 可被 uvicorn 解析（EXE 冻结后同样适用）
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.config as _cfg  # noqa: E402
from app import __version__, __build__, __commit__, __build_time__  # noqa: E402

settings = _cfg.settings

# ===== 日志（规格书 §25/§26：统一 logs/ + 轮转 20MB×10） =====
log = logging.getLogger("syscenter")


def _setup_logging(level: int = logging.INFO):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    # 避免重复 handler
    for h in list(root.handlers):
        root.removeHandler(h)
    rf = logging.handlers.RotatingFileHandler(
        LOG_DIR / "syscenter.log", maxBytes=20 * 1024 * 1024, backupCount=10, encoding="utf-8")
    rf.setFormatter(fmt)
    root.addHandler(rf)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)


try:
    import logging.handlers  # noqa: F401
except Exception:  # noqa: BLE001
    pass


# ===== 单实例（规格书 §29） =====
def _port_in_use(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _read_lock() -> dict | None:
    try:
        return json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _write_lock(pid: int):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps({"pid": pid, "ts": datetime.now().isoformat()}), encoding="utf-8")


def _is_running() -> bool:
    lock = _read_lock()
    if lock and lock.get("pid"):
        # 进程是否存活
        try:
            import psutil
            if psutil.pid_exists(lock["pid"]):
                return True
        except Exception:  # noqa: BLE001
            pass
        # 端口占用也可作为存活信号
    return _port_in_use(settings.backend_host or "127.0.0.1", settings.backend_port)


# ===== uvicorn 服务器管理 =====
_server = None
_stop_event = threading.Event()


def _make_server():
    import uvicorn
    # 静态导入 app.main：uvicorn 以字符串 "app.main:app" 加载 ASGI 应用，
    # PyInstaller 的静态分析看不到字符串导入，会导致整个 app 子包（main/db/routers）
    # 不被打包。此处显式静态导入，确保冻结态一并收集。
    import app.main  # noqa: F401
    # log_config=None：不接管 logging，让 uvicorn 的日志向上传播到根 logger
    # （由 _setup_logging 统一写入 logs/syscenter.log），避免后端启动失败无日志可查。
    cfg = uvicorn.Config(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        proxy_headers=True,            # P2-06：启用代理头
        forwarded_allow_ips="*",
        log_level="info",
        log_config=None,
    )
    return uvicorn.Server(cfg)


def start_server_thread() -> threading.Thread:
    """启动 uvicorn（后台线程）。返回线程，便于 Service 模式阻塞等待。"""
    global _server
    _server = _make_server()

    def _run():
        try:
            _server.run()
        except Exception:  # noqa: BLE001
            log.exception("后端服务启动失败（请检查依赖导入 / 端口占用 / 数据库连接）")

    t = threading.Thread(target=_run, name="syscenter-uvicorn", daemon=True)
    t.start()
    return t


def stop_server():
    global _server
    if _server:
        _server.should_exit = True
    _stop_event.set()


# ===== 命令实现 =====
def cmd_start(args):
    if _is_running():
        print("SysCenter is already running.")
        return 1
    _setup_logging()
    log.info("启动 SysCenter %s (host=%s port=%s)", __version__, settings.backend_host, settings.backend_port)
    _write_lock(os.getpid())
    t = start_server_thread()
    try:
        while t.is_alive() and not _stop_event.is_set():
            t.join(1.0)
    except KeyboardInterrupt:
        log.info("收到中断信号，停止 SysCenter ...")
        stop_server()
        t.join(timeout=10)
    finally:
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass
    return 0


def cmd_stop(args):
    if _cfg_is_windows_service_installed():
        _win_service_control("stop")
        return 0
    print("SysCenter 以前台模式运行（Ctrl+C 停止），或非 Service 模式。")
    print("若以 Service 安装，请使用 `SysCenter.exe stop`（需管理员）。")
    return 0


def cmd_restart(args):
    if _cfg_is_windows_service_installed():
        _win_service_control("restart")
        return 0
    print("非 Service 模式：请 Ctrl+C 停止后重新 start。")
    return 0


def cmd_status(args):
    lock = _read_lock()
    running = _is_running()
    port = _port_in_use(settings.backend_host or "127.0.0.1", settings.backend_port)
    # 尝试健康检查
    health = _probe_health()
    print("SysCenter Status")
    print("----------------")
    print(f"Version : {__version__}")
    print(f"Process : {'running' if running else 'stopped'}")
    print(f"PID     : {lock.get('pid') if lock else '-'}")
    print(f"Host    : {settings.backend_host}")
    print(f"Port    : {settings.backend_port}")
    print(f"Database: {settings.pg_host}:{settings.pg_port}/{settings.pg_database}")
    print(f"Redis   : {settings.redis_host}:{settings.redis_port}")
    print(f"Uptime  : -")
    print(f"Health  : {health}")
    return 0


def cmd_version(args):
    print(f"SysCenter {__version__}")
    print(f"Build   : {__build__}")
    print(f"Commit  : {__commit__}")
    print(f"BuildAt : {__build_time__ or '-'}")
    return 0


def cmd_config(args):
    import app.config as cfg
    print("SysCenter 生效配置（密钥已脱敏）：")
    print("-------------------------------")
    for k in sorted(cfg.RUNTIME_KEYS):
        v = getattr(settings, k, None)
        if k in cfg.SECRET_KEYS:
            v = cfg.mask_secret(v) if v else ""
        print(f"{k} = {v}")
    print("-------------------------------")
    print(f"backend_host = {settings.backend_host}")
    print(f"backend_port = {settings.backend_port}")
    print(f"pg_dsn       = {settings.pg_dsn}")
    print(f"redis_url    = {settings.redis_url}")
    return 0


def cmd_migrate(args):
    _setup_logging()
    print("执行数据库迁移（Alembic upgrade head）...")
    try:
        from alembic import command
        from alembic.config import Config
        ini = APP_HOME / "alembic.ini"
        cfg = Config(str(ini))
        cfg.set_main_option("script_location", str(APP_HOME / "migrations"))
        if str(BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(BACKEND_DIR))
        command.upgrade(cfg, "head")
        print("迁移完成。")
        return 0
    except Exception as e:  # noqa: BLE001
        log.exception("迁移失败")
        print(f"迁移失败：{e}")
        return 1


# ===== doctor（规格书 §21/§22） =====
def _probe_health() -> str:
    import urllib.request
    for ep in ("/health", "/health/ready"):
        try:
            with urllib.request.urlopen(
                f"http://{settings.backend_host or '127.0.0.1'}:{settings.backend_port}{ep}",
                timeout=2) as r:
                if r.status == 200:
                    return "ok"
        except Exception:  # noqa: BLE001
            continue
    return "down"


def _check_docker() -> tuple[str, str]:
    try:
        out = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0:
            return "PASS", f"Docker {out.stdout.strip()}"
        return "WARN", "Docker 已安装但引擎未运行"
    except FileNotFoundError:
        return "WARN", "Docker 未安装（PG/Redis 需 Docker 或自备）"
    except Exception as e:  # noqa: BLE001
        return "WARN", f"Docker 检测异常：{e}"


async def _check_db() -> tuple[str, str]:
    try:
        import asyncpg
        conn = await asyncpg.connect(settings.pg_dsn, timeout=5)
        try:
            await conn.execute("SELECT 1")
            return "PASS", f"PostgreSQL 可达 {settings.pg_host}:{settings.pg_port}"
        finally:
            await conn.close()
    except Exception as e:  # noqa: BLE001
        return "FAIL" if "password" not in str(e).lower() else "FAIL", f"PostgreSQL 不可达：{str(e)[:120]}"


async def _check_redis() -> tuple[str, str]:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=5)
        try:
            await r.ping()
            return "PASS", f"Redis 可达 {settings.redis_host}:{settings.redis_port}"
        finally:
            await r.aclose()
    except Exception as e:  # noqa: BLE001
        return "WARN", f"Redis 不可达：{str(e)[:120]}"


async def _check_migration() -> tuple[str, str]:
    """直接查 alembic_version 表，报告当前迁移版本（绕过冻结态 alembic 模板渲染）。"""
    try:
        import asyncpg
        conn = await asyncpg.connect(settings.pg_dsn, timeout=5)
        try:
            cur = await conn.fetch("SELECT version_num FROM alembic_version")
            revs = ", ".join(r["version_num"] for r in cur) or "（未初始化）"
            return "PASS", f"当前版本：{revs}"
        finally:
            await conn.close()
    except Exception as e:  # noqa: BLE001
        return "WARN", f"无法查询：{str(e)[:120]}"


def cmd_doctor(args):
    print("SysCenter Doctor")
    print("================")
    rows = []

    # EXE / 解释器
    frozen = getattr(sys, "frozen", False)
    rows.append(("EXE", "PASS" if frozen else "INFO",
                 "SysCenter.exe 原生运行" if frozen else f"Python 解释器运行：{sys.executable}"))

    # 配置
    rows.append(("配置", "PASS", f"backend {settings.backend_host}:{settings.backend_port}"))

    # 端口
    if _port_in_use(settings.backend_host or "127.0.0.1", settings.backend_port):
        rows.append(("端口", "INFO", f"{settings.backend_port} 已被占用（可能已在运行）"))
    else:
        rows.append(("端口", "PASS", f"{settings.backend_port} 空闲"))

    # 数据库 / Redis
    db_st, db_msg = asyncio.run(_check_db())
    rows.append(("数据库", db_st, db_msg))
    rd_st, rd_msg = asyncio.run(_check_redis())
    rows.append(("Redis", rd_st, rd_msg))

    # Docker
    dk_st, dk_msg = _check_docker()
    rows.append(("Docker", dk_st, dk_msg))

    # 文件权限 / 日志目录
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        (LOG_DIR / ".writetest").write_text("ok"); (LOG_DIR / ".writetest").unlink()
        rows.append(("日志目录", "PASS", str(LOG_DIR)))
    except Exception as e:  # noqa: BLE001
        rows.append(("日志目录", "FAIL", f"无写权限：{e}"))

    # 数据目录
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        rows.append(("数据目录", "PASS", str(DATA_DIR)))
    except Exception as e:  # noqa: BLE001
        rows.append(("数据目录", "FAIL", f"{e}"))

    # 网络
    try:
        socket.gethostbyname("api.deepseek.com")
        rows.append(("网络", "PASS", "DNS 解析正常"))
    except Exception as e:  # noqa: BLE001
        rows.append(("网络", "WARN", f"DNS 解析失败：{e}"))

    # 健康检查
    h = _probe_health()
    rows.append(("健康检查", "PASS" if h == "ok" else "WARN", f"/health = {h}"))

    # 迁移版本（直接查库，避免冻结态 alembic 模板渲染的 buffer 参数问题）
    mg_st, mg_msg = asyncio.run(_check_migration())
    rows.append(("迁移", mg_st, mg_msg))

    for name, st, msg in rows:
        print(f"[{st:4}] {name:8} {msg}")
    return 0


# ===== 备份 / 恢复（规格书 §40/§41） =====
async def _dump_all() -> dict:
    import asyncpg
    conn = await asyncpg.connect(settings.pg_dsn, timeout=10)
    try:
        tables = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        dump = {}
        for r in tables:
            t = r["table_name"]
            rows = await conn.fetch(f'SELECT * FROM "{t}"')
            dump[t] = [dict(x) for x in rows]
        return dump
    finally:
        await conn.close()


async def _restore_all(dump: dict):
    import asyncpg
    conn = await asyncpg.connect(settings.pg_dsn, timeout=10)
    try:
        for t, rows in dump.items():
            if not rows:
                continue
            cols = list(rows[0].keys())
            await conn.execute(f'TRUNCATE TABLE "{t}" CASCADE')
            for row in rows:
                placeholders = [f"${i+1}" for i in range(len(cols))]
                await conn.execute(
                    f'INSERT INTO "{t}" ({", ".join(cols)}) VALUES ({", ".join(placeholders)})',
                    *[row[c] for c in cols])
    finally:
        await conn.close()


def cmd_backup(args):
    _setup_logging()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_zip = BACKUP_DIR / f"SysCenter-{stamp}.zip"
    print(f"备份中 -> {out_zip}")
    try:
        data = asyncio.run(_dump_all())
    except Exception as e:  # noqa: BLE001
        log.exception("备份导出失败")
        print(f"数据库导出失败：{e}")
        return 1
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("db_dump.json", json.dumps(data, default=str, ensure_ascii=False))
        # 配置（.env）如果存在
        envf = PROJECT_DIR / ".env"
        if envf.exists():
            z.write(envf, "config/.env")
        # 数据目录（OTP 密钥等，已加密/脱敏）
        if DATA_DIR.exists():
            for p in DATA_DIR.rglob("*"):
                if p.is_file():
                    z.write(p, f"data/{p.relative_to(DATA_DIR)}")
    print(f"备份完成：{out_zip}（{(out_zip.stat().st_size)//1024} KB）")
    return 0


def cmd_restore(args):
    _setup_logging()
    target = Path(args.file) if args.file else None
    if not target or not target.exists():
        # 取最新
        files = sorted(BACKUP_DIR.glob("SysCenter-*.zip"), reverse=True)
        if not files:
            print("未找到任何备份文件。")
            return 1
        target = files[0]
    print(f"从 {target} 恢复...")
    with zipfile.ZipFile(target) as z:
        data = json.loads(z.read("db_dump.json"))
    try:
        asyncio.run(_restore_all(data))
    except Exception as e:  # noqa: BLE001
        log.exception("恢复失败")
        print(f"恢复失败：{e}")
        return 1
    print("恢复完成。")
    return 0


# ===== Windows Service 集成（规格书 §6/§7） =====
SERVICE_NAME = "SysCenter"
SERVICE_DISPLAY = "SysCenter Service"
SERVICE_DESC = "SysCenter Windows Management Platform"


def _cfg_is_windows_service_installed() -> bool:
    try:
        import win32serviceutil
        return win32serviceutil.ExistsService(SERVICE_NAME)
    except Exception:  # noqa: BLE001
        return False


def _win_service_control(action: str):
    import win32serviceutil
    if action == "stop":
        win32serviceutil.StopService(SERVICE_NAME)
    elif action == "restart":
        win32serviceutil.RestartService(SERVICE_NAME)
    elif action == "start":
        win32serviceutil.StartService(SERVICE_NAME)


# ===== 系统托盘（GUI 模式） & 开机自启 & OTP 退出 =====
def _messagebox(title: str, message: str, error: bool = False):
    """窗口化提示：在独立线程中延迟弹出 Windows 原生 MessageBox。

    pystray 的菜单回调是在 TrackPopupMenuEx 返回后同步执行的，此刻菜单的鼠标捕获/
    焦点尚未完全释放，若在此刻同步弹任何模态框（tkinter 或 MessageBoxW 都一样），
    对话框会显示但点击“确定”无响应、无法关闭。故把弹窗放到独立线程并延迟 150ms，
    等菜单清理完成后再弹，即可正常交互。
    """
    def _show():
        time.sleep(0.15)
        try:
            import ctypes
            MB_OK = 0x0
            MB_ICONERROR = 0x10
            MB_ICONINFORMATION = 0x40
            MB_SETFOREGROUND = 0x10000
            flags = MB_OK | MB_SETFOREGROUND | (MB_ICONERROR if error else MB_ICONINFORMATION)
            ctypes.windll.user32.MessageBoxW(0, message, title, flags)
        except Exception:  # noqa: BLE001
            log.info("[%s] %s", title, message)
    threading.Thread(target=_show, daemon=True).start()


def _build_tray_icon():
    """用 PIL 现画一个 SysCenter 托盘图标（无需外部资源文件）。"""
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, size - 6, size - 6], radius=16,
                        fill=(37, 99, 235, 255), outline=(255, 255, 255, 220))
    try:
        from PIL import ImageFont
        try:
            f = ImageFont.truetype("arial.ttf", 34)
        except Exception:  # noqa: BLE001
            f = ImageFont.load_default()
        d.text((size // 2 - 11, size // 2 - 18), "S", fill=(255, 255, 255, 255), font=f)
    except Exception:  # noqa: BLE701
        d.text((size // 2 - 7, size // 2 - 9), "S", fill=(255, 255, 255, 255))
    return img


def _prompt_otp() -> str | None:
    """弹出 OTP 输入框：使用 PowerShell + Microsoft.VisualBasic.InputBox（独立进程）。

    不能用 tkinter simpledialog：pystray 的菜单回调在 Win32 消息循环线程中同步执行，
    在其中同步弹出 Tk 模态对话框会导致事件循环冲突，输入后无响应、无法退出。
    InputBox 在独立 powershell 进程中运行，互不干扰。
    """
    import base64
    ps = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "$r = [Microsoft.VisualBasic.Interaction]::InputBox("
        "'SysCenter 正在运行。请输入身份验证器(OTP)动态码以安全退出：', "
        "'退出认证', ''); "
        "if ($null -ne $r) { [Console]::Write($r) }"
    )
    try:
        # -EncodedCommand 用 UTF-16LE 传脚本，规避中文命令行/引号转义问题
        encoded = base64.b64encode(ps.encode("utf-16le")).decode("ascii")
        r = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-WindowStyle", "Hidden",
             "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip()
        return out or None
    except Exception:  # noqa: BLE001
        return None


def _run_tray(server_thread):
    """创建系统托盘并阻塞运行；『退出』菜单经 OTP 校验后停止。"""
    try:
        import pystray
        from pystray import Menu, MenuItem
    except Exception as e:  # noqa: BLE001
        log.warning("pystray 不可用（可能无图形界面），降级为无托盘后台运行：%s", e)
        try:
            while server_thread.is_alive() and not _stop_event.is_set():
                server_thread.join(1.0)
        except KeyboardInterrupt:
            pass
        return

    # 浏览器访问地址：backend_host 是监听地址（0.0.0.0/:: 表示绑定所有网卡），
    # 浏览器打不开 0.0.0.0，须转成回环地址 127.0.0.1 才能访问。
    _web_host = settings.backend_host or "127.0.0.1"
    if _web_host in ("0.0.0.0", "::", "[::]"):
        _web_host = "127.0.0.1"
    url = f"http://{_web_host}:{settings.backend_port}"

    def on_open(icon, item):
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    def on_status(icon, item):
        h = _probe_health()
        _messagebox("SysCenter 状态",
                    f"版本：{__version__}\n地址：{url}\n健康检查：{h}\n数据目录：{DATA_DIR}")

    def on_exit(icon, item):
        from app import auth
        for _ in range(3):
            code = _prompt_otp()
            if code is None:          # 用户取消
                return
            try:
                if auth.verify_otp(code):
                    icon.stop()
                    return
            except Exception:  # noqa: BLE001
                pass
            _messagebox("OTP 错误", "动态码不正确或已过期，请重试。", error=True)
        _messagebox("已取消退出", "连续 3 次校验失败，已取消退出。", error=True)

    icon = pystray.Icon(
        "SysCenter", _build_tray_icon(), f"SysCenter {__version__}",
        menu=Menu(
            MenuItem("打开管理页面", on_open),
            MenuItem("状态", on_status),
            Menu.SEPARATOR,
            MenuItem("退出（需 OTP 认证）", on_exit),
        ),
    )
    try:
        icon.run()
    except Exception as e:  # noqa: BLE001
        log.warning("托盘运行异常，降级为后台运行：%s", e)
        try:
            while server_thread.is_alive() and not _stop_event.is_set():
                server_thread.join(1.0)
        except KeyboardInterrupt:
            pass


def cmd_tray(args):
    """托盘 GUI 模式（EXE 默认启动方式）：启动后端 + 系统托盘，无终端窗口。"""
    _setup_logging()
    if _is_running():
        _messagebox("SysCenter 已在运行", "SysCenter 已经在运行中，无需重复启动。")
        return 0
    log.info("启动 SysCenter 托盘模式 %s (host=%s port=%s)",
             __version__, settings.backend_host, settings.backend_port)
    _write_lock(os.getpid())
    t = start_server_thread()
    try:
        _run_tray(t)
    finally:
        stop_server()
        t.join(timeout=15)
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass
    return 0


# ===== 开机自启（HKCU Run 键，用户登录时启动托盘；无需管理员） =====
def _autostart_set(enable: bool) -> bool:
    try:
        import winreg
        exe = sys.executable  # 冻结态即 SysCenter.exe 绝对路径
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        if enable:
            winreg.SetValueEx(key, "SysCenter", 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, "SysCenter")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("设置开机自启失败：%s", e)
        return False


def cmd_install(args):
    """安装开机自启（用户登录时启动 SysCenter 托盘，无终端窗口）。"""
    if _autostart_set(True):
        msg = (f"已设置开机自启（用户登录时自动启动托盘）。\n"
               f"可执行文件：{sys.executable}\n\n"
               f"如需立即运行，请双击 SysCenter.exe。")
        print(msg)
        _messagebox("SysCenter", msg)
        return 0
    print("设置开机自启失败，请检查权限或手动将 SysCenter.exe 加入启动项。")
    return 1


def cmd_uninstall(args):
    """取消开机自启（仅移除自启项；不卸载程序）。"""
    if _autostart_set(False):
        msg = "已取消开机自启。"
        print(msg)
        _messagebox("SysCenter", msg)
        return 0
    print("取消开机自启失败。")
    return 1


# ===== CLI 入口 =====
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="SysCenter", description="SysCenter 运维中枢（Windows EXE 原生版）")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("start", help="启动后端（前台）")
    sub.add_parser("stop", help="停止")
    sub.add_parser("restart", help="重启")
    sub.add_parser("status", help="状态")
    sub.add_parser("doctor", help="诊断")
    sub.add_parser("version", help="版本")
    sub.add_parser("install", help="安装开机自启（登录启动托盘）")
    sub.add_parser("uninstall", help="取消开机自启")
    sub.add_parser("tray", help="托盘 GUI 模式（EXE 默认）")
    sub.add_parser("migrate", help="数据库迁移")
    sub.add_parser("config", help="打印配置")
    sub.add_parser("backup", help="备份")
    rp = sub.add_parser("restore", help="恢复")
    rp.add_argument("file", nargs="?", default=None, help="备份 zip 路径（缺省取最新）")
    sub.add_parser("service", help="以 Windows Service 方式运行（内部使用）")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    cmd = args.command or "start"
    handlers = {
        "start": cmd_start, "stop": cmd_stop, "restart": cmd_restart,
        "status": cmd_status, "doctor": cmd_doctor, "version": cmd_version,
        "install": cmd_install, "uninstall": cmd_uninstall, "migrate": cmd_migrate,
        "config": cmd_config, "backup": cmd_backup, "restore": cmd_restore,
        "tray": cmd_tray,
    }
    if cmd == "service":
        # Windows Service 宿主模式：交给 pywin32 框架（SCM 启动/调试均走此分支）。
        # 安装时 exeArgs="service"，SCM 启动 SysCenter.exe 即进入本分支并触发 SvcDoRun。
        import win32serviceutil
        from service import SysCenterService
        win32serviceutil.HandleCommandLine(SysCenterService)
        return 0
    # EXE 冻结态：start / 无参数 进入托盘 GUI 模式（无终端窗口）；开发态保持前台控制台。
    if getattr(sys, "frozen", False) and cmd == "start":
        return cmd_tray(args)
    return handlers.get(cmd, cmd_start)(args)


if __name__ == "__main__":
    sys.exit(main())
