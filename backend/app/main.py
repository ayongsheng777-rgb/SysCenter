# -*- coding: utf-8 -*-
"""SysCenter FastAPI 主入口

后端以本机 Windows 进程运行（uvicorn），psutil 直读真实宿主机。
仅 /api 由本服务承载；前端静态资源与反代由 nginx（Docker）负责。
"""
import logging
import os
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, db, feishu, scheduler
from .config import settings
from .request_ctx import get_request_id, set_request_context
from .routers import (ai, alerts, audit, auth as auth_router, automation, backup as backup_router,
                      feishu_bot, modules, network, notify, notes, settings as settings_router,
                      skills, system, todos, vps)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("main")

# 公网入口（无 HTTPS，参考本机约定的非标端口 HTTP）
_ALLOW_ORIGINS = [
    "http://syscenter.yshost.de5.net",
    "http://localhost:8372",
    "http://127.0.0.1:8372",
    "http://localhost:5173",   # 开发态 vite
]

app = FastAPI(title="SysCenter API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """生成/透传 X-Request-ID，并写入请求上下文（供审计与日志使用）。"""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    client_ip = request.client.host if request.client else ""
    set_request_context(rid, client_ip)
    resp = await call_next(request)
    resp.headers["X-Request-ID"] = rid
    return resp


@app.middleware("http")
async def security_headers(request, call_next):
    """统一安全响应头（无 HTTPS 故不加 HSTS）。"""
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-XSS-Protection", "1; mode=block")
    return resp

# 路由注册
for r in (auth_router, system, network, vps, modules, ai, notify, settings_router, automation, alerts, feishu_bot, todos, audit, notes, skills, backup_router):
    app.include_router(r.router)


# ============== 健康检查（规格书 §20：/health /health/live /health/ready） ==============
async def _check_pg() -> bool:
    try:
        async with db.pool().acquire() as c:
            await c.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


async def _check_redis() -> bool:
    try:
        r = db._pool  # 仅探测，不强制
        from . import redis_client
        rc = redis_client.get_redis_sync()
        return bool(rc and rc.ping())
    except Exception:  # noqa: BLE001
        return False


@app.get("/health")
async def health():
    """综合健康：SysCenter + PostgreSQL + Redis。无需鉴权，供监控系统/doctor 使用。"""
    pg = await _check_pg()
    redis_ok = await _check_redis()
    return {
        "status": "ok" if (pg and redis_ok) else "degraded",
        "service": "SysCenter",
        "components": {"postgres": "up" if pg else "down", "redis": "up" if redis_ok else "down"},
        "otp_setup_open": auth.is_setup_open(),
    }


@app.get("/health/live")
async def health_live():
    """存活探针：仅判断进程是否正常。"""
    return {"status": "up"}


@app.get("/health/ready")
async def health_ready():
    """就绪探针：判断依赖是否满足服务运行条件。"""
    pg = await _check_pg()
    redis_ok = await _check_redis()
    if pg and redis_ok:
        return {"status": "ready", "postgres": "up", "redis": "up"}
    return JSONResponse(status_code=503, content={
        "status": "not_ready", "postgres": "up" if pg else "down", "redis": "up" if redis_ok else "down"})


# ============== 前端静态资源托管（EXE 原生化：SysCenter.exe 直接提供 Web UI，规格书 §17） ==============
def _find_frontend_dist() -> str | None:
    """多候选定位 frontend/dist（开发态 / EXE 冻结态 / 安装布局均可）。"""
    candidates: list[str] = []
    if os.environ.get("FRONTEND_DIST"):
        candidates.append(os.environ["FRONTEND_DIST"])
    # 开发态：backend/app -> ../../frontend/dist
    candidates.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")))
    # EXE onefile 解压目录
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "frontend", "dist"))
    # EXE / 安装目录：<exe_dir>/frontend/dist 或 <exe_dir>/../frontend/dist
    if getattr(sys, "frozen", False):
        exedir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exedir, "frontend", "dist"))
        candidates.append(os.path.join(exedir, "..", "frontend", "dist"))
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return None


_DIST = _find_frontend_dist()
if _DIST:
    _assets_dir = os.path.join(_DIST, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def _spa(full_path: str):
        # /api 由业务路由处理；此处只兜底前端 SPA 路由与静态文件
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"success": False, "code": "NOT_FOUND", "message": "接口不存在"})
        candidate = os.path.join(_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_DIST, "index.html"))
else:
    log.info("未检测到 frontend/dist，跳过静态资源托管（开发态请由 Vite 提供前端）")


# ============== 统一异常处理：错误统一返回 {success,code,message,request_id} ==============
_ERR_CODE_MAP = {
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}


@app.exception_handler(StarletteHTTPException)
async def _http_exc_handler(request: Request, exc: StarletteHTTPException):
    code = _ERR_CODE_MAP.get(exc.status_code, f"HTTP_{exc.status_code}")
    return JSONResponse(status_code=exc.status_code, content={
        "success": False, "code": code, "message": str(exc.detail),
        "request_id": get_request_id()})


@app.exception_handler(RequestValidationError)
async def _validation_exc_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "success": False, "code": "VALIDATION_ERROR",
        "message": "请求参数校验失败",
        "request_id": get_request_id(),
        "errors": exc.errors()})


@app.exception_handler(Exception)
async def _unhandled_exc_handler(request: Request, exc: Exception):
    log.exception("未处理的异常: %s", exc)
    return JSONResponse(status_code=500, content={
        "success": False, "code": "INTERNAL_ERROR",
        "message": "服务器内部错误",
        "request_id": get_request_id()})


@app.get("/api/ping")
async def ping():
    return {"ok": True, "service": "SysCenter", "otp_setup_open": auth.is_setup_open()}


@app.get("/api/healthz")
async def healthz():
    """存活探针（无需鉴权，供 nginx/liveness 使用）。"""
    return {"status": "up"}


@app.on_event("startup")
async def on_startup():
    # 安全提醒：若仍在使用弱默认/占位密码，记录告警（生产应在 .env 设置强密码）
    if settings.pg_password in ("syscenter_pass_2026", "ChangeMe_StrongPassw0rd!2026", ""):
        log.warning("PG_PASSWORD 使用了默认值/弱口令或占位符，存在安全风险，"
                    "请在生产环境通过 .env 设置强密码")
    # 首次绑定 Bootstrap Code（P1-01）：未绑定时生成并打印到日志，/auth/setup 必须携带
    bootstrap = auth.init_bootstrap()
    if bootstrap:
        log.warning("=" * 60)
        log.warning("首次 OTP 绑定 Bootstrap Code: %s", bootstrap)
        log.warning("请访问 /api/auth/setup?code=%s 完成绑定（该 Code 仅显示一次，绑定后作废）", bootstrap)
        log.warning("=" * 60)
    await db.init_pool()
    await db.load_runtime_settings()
    # 技能运行时初始化（B 路：可执行技能，内置技能首次写入可写技能目录）
    try:
        from .skills import init_skills
        n = init_skills()
        log.info("技能运行时已初始化，加载 %d 个技能", n)
    except Exception as e:  # noqa: BLE001
        log.warning("技能运行时初始化失败（不影响主流程）：%s", e)
    scheduler.start()
    feishu.start_feishu_bot()
    log.info("SysCenter 启动完成，监听 %s:%s", settings.backend_host, settings.backend_port)


@app.on_event("shutdown")
async def on_shutdown():
    scheduler.stop()
    await feishu.stop_feishu_bot()
    await db.close_pool()


if __name__ == "__main__":
    import uvicorn

    # P2-06：启用代理头，使 request.client / X-Forwarded-* 反映真实客户端 IP
    # （Cloudflare Tunnel / Nginx 反代场景下的登录限速、审计 IP、安全分析依赖此）
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
