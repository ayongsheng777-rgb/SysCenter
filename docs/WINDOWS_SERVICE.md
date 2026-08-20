# SysCenter Windows Service 说明（规格书 §6/§7/§28）

## 1. 服务身份

| 项 | 值 |
| --- | --- |
| 服务名 | `SysCenter` |
| 显示名 | `SysCenter Service` |
| 描述 | `SysCenter Windows Management Platform` |
| 启动类型 | 自动（延迟） |
| 恢复策略 | 第一次/第二次/后续失败均「重新启动服务」，延迟 5000ms |

## 2. 安装 / 卸载（需管理员）

```powershell
SysCenter.exe install      # 安装并设为自动启动 + 自动恢复
SysCenter.exe uninstall    # 卸载服务
net start SysCenter        # 启动
net stop  SysCenter        # 停止
```

## 3. 实现机制

- `service.py` 定义 `SysCenterService`（继承 `win32serviceutil.ServiceFramework`）。
- `SvcDoRun`：启动 uvicorn（后台线程）并阻塞等待 SCM 停止事件。
- `SvcStop`：上报 `SERVICE_STOP_PENDING` 并触发停止事件 → `syscenter_app.stop_server()` 优雅退出。
- 单实例保护：`_is_running()` 端口/锁文件检测，避免重复实例争抢资源（规格书 §29）。

## 4. 崩溃恢复（规格书 §28）

- 进程被杀死 → SCM 按恢复策略自动重启。
- 数据库/Redis 短暂不可用时，后端**不退出**，持续重试连接（规格书 §8）。
- 连续失败保护：SCM 恢复策略上限由 Windows 控制；建议配合日志（`logs/syscenter.log`）排查根因。

## 5. 与工作目录

Service 工作目录可能为 `C:\Windows\system32`，故所有路径均由 `sys.executable` 目录派生（规格书 §48），不依赖 CWD。
