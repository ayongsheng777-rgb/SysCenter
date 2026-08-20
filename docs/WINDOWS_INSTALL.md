# SysCenter Windows 安装指南

## 1. 前置条件

- Windows 10 / 11 x64
- Docker Desktop（提供 PostgreSQL + Redis；未安装时 `doctor` 会明确提示）
- 管理员权限（安装 Windows Service / 写 `C:\Program Files`）

## 2. 获取 SysCenter.exe

两种来源：

1. **Release 包**：`SysCenter-Setup-x64.exe`（安装向导，下一步式）。
2. **便携包**：`dist_exe/SysCenter/` 目录（含 `SysCenter.exe` + `config/` + `frontend/dist` + `alembic.ini` + `migrations/`）。

> 本仓提供便携包构建：`packaging/windows/build.ps1`（详见 ARCHITECTURE）。

## 3. 安装步骤（便携包）

```powershell
# 1) 放置程序（建议）
New-Item -ItemType Directory -Force -Path "C:\Program Files\SysCenter" | Out-Null
Copy-Item dist_exe\SysCenter\* "C:\Program Files\SysCenter\" -Recurse -Force

# 2) 准备依赖（PostgreSQL + Redis）
#    编辑 SysCenter 目录下的 .env，设置强口令 PG_PASSWORD
docker compose up -d        # 启动 postgres / redis

# 3) 初始化数据库（首次）
& "C:\Program Files\SysCenter\SysCenter.exe" migrate

# 4) 安装为 Windows Service（自动启动 + 自动恢复）
#    需管理员 PowerShell
& "C:\Program Files\SysCenter\SysCenter.exe" install
#    安装后到“服务”中把恢复策略确认为：第一次/第二次/后续失败均“重新启动服务”，延迟 5000ms

# 5) 启动
net start SysCenter
# 或前台调试：SysCenter.exe start
```

## 4. 验证

```powershell
SysCenter.exe status      # 进程/端口/库/健康检查
SysCenter.exe doctor     # 全量诊断（应全 PASS/WARN）
# 浏览器打开 http://localhost:8352  （或经 nginx 8372）
```

## 5. 防火墙（规格书 §35）

默认后端监听 `0.0.0.0:8352`。若仅本机访问，将 `backend_host` 设为 `127.0.0.1`；
如需局域网，请在 Windows 防火墙放行 **8352**（不要默认开放 `0.0.0.0`）。
