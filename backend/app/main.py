# -*- coding: utf-8 -*-
"""SysCenter FastAPI 主入口

后端以本机 Windows 进程运行（uvicorn），psutil 直读真实宿主机。
仅 /api 由本服务承载；前端静态资源与反代由 nginx（Docker）负责。
"""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import auth, db, feishu, scheduler
from .config import settings
from .routers import (ai, alerts, auth as auth_router, automation, feishu_bot,
                      modules, network, notify, settings as settings_router, system, todos, vps)

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
async def security_headers(request, call_next):
    """统一安全响应头（无 HTTPS 故不加 HSTS）。"""
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-XSS-Protection", "1; mode=block")
    return resp

# 路由注册
for r in (auth_router, system, network, vps, modules, ai, notify, settings_router, automation, alerts, feishu_bot, todos):
    app.include_router(r.router)


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
    await db.init_pool()
    await db.load_runtime_settings()
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

    uvicorn.run("app.main:app", host=settings.backend_host, port=settings.backend_port, reload=False)
