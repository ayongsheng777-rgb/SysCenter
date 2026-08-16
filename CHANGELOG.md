# Changelog

本文件记录 SysCenter 的功能与工程演进。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，版本号遵循语义化版本。

## [Unreleased]

### 新增
- **Redis 会话**：登录令牌由内存 `VALID_TOKENS` 迁移到 Redis（`session:<token>` + TTL），后端重启登录态不再丢失，为多 worker/横向扩展铺路；Redis 不可用自动回退内存态。
- **RBAC 角色护栏**：`require_role(*roles)` 依赖；令牌携带 `role`（默认 admin），高危路由（改设置/启停服务/删 VPS/执行自动化/重置 OTP 等）仅 admin 可访问。单用户场景行为不变。
- **操作审计日志**：新增 `audit_log` 表（Alembic 0002）与 `GET /api/audit`；登录/登出/改设置/启停服务/删 VPS/执行自动化/删告警/飞书配置等高风险动作落库（含 actor/action/target/IP/request_id）。
- **统一错误格式**：所有错误统一返回 `{success, code, message, request_id}`，覆盖 401/403/404/422/429/500。
- **请求 ID 全链路**：中间件生成/透传 `X-Request-ID`，审计与排错可关联。
- **VPS 探测并发化**：`asyncio.gather` + 信号量（上限 20），替代串行逐个探测。
- **前端审计页**：新增「审计」标签页，支持按动作筛选。

## [0.1.0] - 2026-08-16

### 新增
- 初始版本：FastAPI + Vue3 + PostgreSQL + Redis + Nginx。
- OTP/TOTP 双因素认证 + Bearer 会话令牌。
- 系统健康监控、Windows 服务管理、VPS/代理矩阵、网络资产探测。
- AI 诊断（多模型 + 场景轮循 + fallback）。
- 飞书告警推送 + 双向 Bot + 扫码授权配置。
- n8n 自动化剧本预设与触发。
- 待办/经验沉淀、AI 诊断历史。
- Alembic 版本化数据库迁移（0001_initial）。
- pytest 测试套件 + GitHub Actions CI。
- 弱口令启动告警、登录限速、登出吊销令牌。
