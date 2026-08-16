# SysCenter 系统综合管理中心

一个面向**个人/小团队运维**的轻量智能运维中枢：把 Windows 宿主机、VPS/代理矩阵、网络资产、飞书机器人、AI 诊断与 n8n 自动化收拢到一个面板里。

> 定位：已从「个人运维工具」进入「小型智能运维平台」阶段，可内部生产使用；公网对外请务必配合 HTTPS（Cloudflare Tunnel 等）使用。

## 技术栈

| 层 | 技术 | 说明 |
| --- | --- | --- |
| 前端 | Vue 3 + Vite | 组件式 hash 路由，轻依赖 |
| 后端 | FastAPI (Python 3.13) | 宿主 Windows 进程，端口 8352 |
| 数据库 | PostgreSQL | 端口 5442，Alembic 版本化迁移 |
| 缓存 | Redis | 端口 6387，承载会话令牌 |
| 网关 | Nginx (Docker) | 端口 8372，反代 `/api` |
| 认证 | TOTP (RFC 6238) + Bearer Session | 双层认证 + RBAC 角色护栏 |
| CI | GitHub Actions | 拉 PG+Redis 跑 pytest |

## 核心能力

- **OTP/TOTP 双因素认证**：Google Authenticator 类验证器；登录换取会话令牌（存 Redis，带 TTL，重启保活）。
- **系统监控**：CPU/内存/磁盘/网络/进程，Windows 服务启停、开机自启管理。
- **VPS / 代理矩阵**：实例管理 + 并发存活延迟探测（`asyncio.gather` + 信号量）。
- **网络资产**：网卡、局域网扫描、NAS / TV 盒子在线状态。
- **AI 诊断**：多模型、场景轮循 + fallback 链，日志交给大模型出排障建议。
- **飞书**：告警推送（webhook 签名）+ 双向 Bot（WebSocket）+ 扫码授权配置。
- **自动化**：n8n webhook 剧本预设与一键触发。
- **审计日志**：登录/登出/改设置/启停服务/删 VPS 等高风险动作留痕（含 IP、请求 ID）。
- **统一错误格式**：`{success, code, message, request_id}`，全链路 `X-Request-ID` 透传。

## 目录结构

```text
SysCenter
├── backend/               FastAPI 后端（宿主进程）
│   ├── app/
│   │   ├── main.py        入口 + 中间件 + 统一异常
│   │   ├── auth.py        OTP/TOTP + 会话令牌（Redis）
│   │   ├── security.py    鉴权依赖 require_auth / require_role
│   │   ├── db.py          asyncpg 连接池 + 业务数据访问
│   │   └── routers/       各业务路由
│   ├── migrations/        Alembic 迁移
│   ├── alembic.ini
│   └── requirements.txt
├── frontend/              Vue 3 前端
├── tests/                 pytest 测试套件
├── .github/workflows/     CI
└── docs/                  设计与验收文档
```

## 快速开始

### 1. 起依赖（PostgreSQL + Redis + Nginx）

```bash
docker compose up -d
```

### 2. 后端（宿主 Windows 进程）

```bash
cd backend
# 建虚拟环境并装依赖（若尚未）
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt

# 配置环境变量（复制 .env.example 为 .env 并填写强密码）
# 启动
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8352
```

### 3. 前端

```bash
cd frontend
npm install
npm run build   # 产物由 nginx 提供；开发态 npm run dev
```

### 4. 首次绑定 OTP

访问面板 → 登录页会展示二维码，用 Authenticator 扫码绑定，之后用 6 位动态码登录。

## 环境变量（节选）

完整清单见 `backend/.env.example`。关键项：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PG_HOST/PORT/USER/PASSWORD/DATABASE` | 127.0.0.1/5442/syscenter | PostgreSQL 连接 |
| `REDIS_HOST/PORT/DB` | 127.0.0.1/6387/0 | Redis（会话） |
| `DATA_DIR` | backend/data | OTP 密钥等落盘处 |
| `SESSION_TTL` | 43200 | 会话有效期（秒） |
| `OTP_SECRET` | （自动生成） | 覆盖 TOTP 密钥（留空则落盘 data/otp_secret） |
| `AI_ENABLED / AI_API_KEY / AI_BASE_URL / AI_MODEL` | - | AI 诊断 |
| `FEISHU_ENABLED / FEISHU_WEBHOOK / FEISHU_SECRET` | - | 飞书告警 |
| `FEISHU_APP_ID / FEISHU_APP_SECRET` | - | 飞书双向 Bot |
| `AUTOMATION_ENABLED / N8N_WEBHOOK_BASE` | - | n8n 自动化 |

## 测试

```bash
cd backend
.venv/Scripts/python.exe -m pytest
```

## 数据库迁移

启动时后端会自动执行 `alembic upgrade head`（失败则回退内联建表，保证可启动）。手动迁移：

```bash
cd backend
.venv/Scripts/alembic.exe upgrade head
```

## 安全

- 公网使用请用 **HTTPS**（推荐 Cloudflare Tunnel / Access 双层门禁）。
- 生产环境务必在 `.env` 设置强 `PG_PASSWORD`，勿用默认弱口令。
- 高风险操作（改设置/启停服务/删 VPS/重置 OTP）需 admin 角色，且全部写入审计日志。
- 报告漏洞见 `SECURITY.md`。

## 许可证

MIT，见 `LICENSE`。
