# SysCenter Windows EXE 原生化架构

> 配套《SysCenter Windows EXE 原生化改造规格书 V1.0》与《综合专业验收报告 V2.0》。

## 1. 目标形态

```
Windows
├── SysCenter.exe            # FastAPI 后端（原生，脱离 Python 环境运行）
│   ├── 直接托管 frontend/dist（Web UI，规格书 §17）
│   ├── 命令中枢：start/stop/restart/status/doctor/version/install/uninstall/migrate/config/backup/restore
│   └── 可选注册为 Windows Service（SysCenter Service，自动启动+自动恢复）
├── C:\ProgramData\SysCenter\   # 程序/数据分离（可经 DATA_DIR 重定向，规格书 §31）
│   ├── config\  config.yaml
│   ├── data\    OTP 密钥等落盘（已加密/脱敏）
│   ├── logs\    syscenter.log（轮转 20MB×10）
│   └── backup\  SysCenter-YYYYMMDD-HHMMSS.zip
└── Docker（仅基础设施）
    ├── PostgreSQL（端口 5442）
    └── Redis（端口 6387）
```

## 2. 运行入口

| 场景 | 入口 |
| --- | --- |
| 生产标准 | Windows Service（`SysCenter.exe install` → SCM 管理） |
| 开发/调试 | `python backend/syscenter_app.py start` 或 `uvicorn app.main:app` |
| 公网访问 | 由 nginx（docker-compose frontend 服务）反代 8352 → 对外 8372；或 EXE 直连 |

## 3. 关键设计点（对照规格书）

- **§4 脱离 Python**：最终交付 `SysCenter.exe`，无需本机 Python/venv/uvicorn。
- **§6/§7 Windows Service**：`service.py` 封装 `SysCenterService`，安装时设自动启动 + 三次失败均重启（延迟 5000ms）。
- **§14/§15 集中配置**：`config/config.yaml` 作为环境变量默认值（env/.env 优先级更高）；敏感信息仅由 .env 提供。
- **§20/§21 健康检查**：`/health`、`/health/live`、`/health/ready` 三端点；`doctor` 全量诊断（EXE/配置/端口/DB/Redis/Docker/迁移/网络）。
- **§25/§26 日志**：统一 `logs/syscenter.log`，`RotatingFileHandler` 20MB×10。
- **§29 单实例**：锁文件 + 端口探测，重复启动提示 "SysCenter is already running."
- **§47/§48 路径**：全部由 `Path(__file__)/sys.executable` 派生，兼容 开发 / EXE / Service 三种工作目录。
- **§77 零回归**：仅改造运行方式，**未改动** 业务逻辑、数据库结构、API 行为、权限模型、UI。

## 4. 与原 Python 启动的关系

- `backend/run.bat` 保留为开发启动脚本（已去除固定 Python 路径，规格书 §81）。
- 生产禁止用 `run.bat` 作为启动入口（规格书 §82）；统一走 `SysCenter.exe` / Service。
