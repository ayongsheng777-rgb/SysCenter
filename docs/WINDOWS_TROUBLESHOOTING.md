# SysCenter 排障手册（规格书 §21/§22/§63/§72）

## 1. 首选诊断

```powershell
SysCenter.exe doctor
```

输出逐项正确/警告/失败：`EXE / 配置 / 端口 / 数据库 / Redis / Docker / 日志目录 / 数据目录 / 网络 / 健康检查 / 迁移`。
**不会**抛 Python traceback（规格书 §22）。

## 2. 常见故障

### 端口被占用（规格书 §60）
```
[FAIL] 端口  8352 已被占用
```
- 查看占用：`netstat -ano | findstr :8352`，结束冲突进程或改 `backend_port`。
- 若旧实例残留：`SysCenter.exe stop` 或 `net stop SysCenter`，再启动。

### PostgreSQL/Redis 不可达（规格书 §61/§62）
- 确认 `docker compose up -d` 已启动且健康检查通过。
- 检查 `.env` 中 `PG_PASSWORD` / `PG_PORT` / `REDIS_PORT` 与容器一致。
- 后端不会因此退出，会持续重试（规格书 §8）；`doctor` 会明确提示依赖缺失。

### Docker 未安装/未启动
- `doctor` 输出 `WARN Docker ...`，并提示「Backend can run, but PostgreSQL/Redis require Docker」。

### 服务启动失败（规格书 §63）
- 查看 `logs/syscenter.log` 尾部；`SysCenter.exe doctor` 定位 EXE/配置/端口/权限/库/Redis/Docker/日志。
- 单实例锁：`data/syscenter.lock` 残留会导致 "already running"。确认无进程后删除该锁文件。

### OTP 首次绑定
- 首次启动日志打印 `Bootstrap Code`，访问 `/api/auth/setup?code=xxx` 完成绑定（仅显示一次）。

## 3. 日志位置

- `logs/syscenter.log`（统一，轮转 20MB×10）
- 启动异常看该文件尾部；`doctor` 已结构化输出，无需读栈。
