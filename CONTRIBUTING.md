# 贡献指南

欢迎参与 SysCenter。请遵循以下约定，让协作顺畅。

## 开发流程

1. 从 `main` 拉出功能分支（如 `feat/redis-session`、`fix/xxx`）。
2. 改动前先读相关源码，理解现有约定（本项目强调「改前必读源码」）。
3. 后端改动后跑 `py_compile` 与 pytest；前端改动后 `npm run build` 确认可构建。
4. 提交信息用清晰的中文描述「为什么 + 改了什么」。
5. 推分支、开 PR，等待 CI 绿后合并。

## 代码约定

- **后端**：FastAPI + asyncpg；数据访问集中在 `app/db.py`，路由只做编排。
- **鉴权**：读类接口用 `require_auth`，高危写操作用 `require_role("admin")` 并 `await db.add_audit(...)` 留痕。
- **数据库变更**：新增表/列走 Alembic 迁移（`backend/migrations/versions/`），迁移用 `IF NOT EXISTS` 幂等；同时在 `db.py::SCHEMA` 兜底建表里同步，保证回退路径一致。
- **错误处理**：抛 `HTTPException`，由全局异常处理器统一转成 `{success, code, message, request_id}`。
- **前端**：组件放 `frontend/src/components/`，在 `App.vue` 的 `tabs`/`map` 注册；错误提示优先读 `e.response.data.message`（`api.js` 已做 `detail` 别名兼容）。

## 测试

- 后端测试在 `tests/`，用 pytest；涉及登录的用例通过 `helpers.make_otp()` 用共享 `DATA_DIR` 生成动态码。
- CI 在 PR / 推 main 时自动拉起 PG + Redis 跑 pytest。

## 提交信息模板

```
feat: 一句话概括

- 具体改动点 1
- 具体改动点 2
```

## 联系

有问题或想讨论设计，直接提 issue。
