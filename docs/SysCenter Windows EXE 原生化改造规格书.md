# SysCenter Windows EXE 原生化改造规格书

**项目名称：** SysCenter  
**改造目标：** Windows 原生 EXE 化 + Windows Service 化  
**目标平台：** Windows 10 / Windows 11 x64  
**文档版本：** V1.0  
**文档日期：** 2026-08-20  
**适用对象：** Codex、Claude Code、Cursor、其他编程智能体及开发人员

---

# 1. 改造目标

将 SysCenter 当前依赖本机 Python 环境、虚拟环境及 `run.bat` 启动的后端运行模式，改造成：

```text
Windows
│
├── SysCenter.exe
│   └── FastAPI Backend
│
├── SysCenter Windows Service
│
├── Web Frontend
│
└── Docker
    ├── PostgreSQL
    └── Redis
```

最终用户不应需要手动安装：

- Python
- pip
- virtualenv
- uvicorn
- FastAPI
- Python 依赖包

生产环境中，SysCenter 后端必须能够脱离 Python 开发环境独立运行。

---

# 2. 核心架构

## 2.1 最终生产架构

```text
                         ┌──────────────────┐
                         │     Browser      │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │   Web Frontend   │
                         │ Vue/React/etc.   │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │  SysCenter.exe   │
                         │    FastAPI       │
                         └───────┬──────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
             ┌──────────────┐          ┌──────────────┐
             │ PostgreSQL   │          │    Redis     │
             │ Docker       │          │    Docker    │
             └──────────────┘          └──────────────┘
```

---

# 3. 核心设计原则

## 3.1 SysCenter 后端原生运行

生产环境禁止依赖：

```text
C:\Python\
C:\Python311\
C:\venv\
C:\Users\xxx\AppData\...
```

不得通过固定 Python 路径启动。

禁止生产启动方式：

```bat
python main.py
python -m uvicorn ...
venv\Scripts\python.exe ...
```

生产启动方式：

```text
SysCenter.exe
```

---

# 4. EXE 打包方案

## 4.1 首选方案

优先使用：

```text
Nuitka
```

进行 Windows x64 原生化编译。

建议目标：

```text
Python
   ↓
Nuitka
   ↓
SysCenter.exe
```

如果项目当前依赖 Nuitka 不兼容的第三方组件，允许使用：

```text
PyInstaller
```

作为兼容方案。

但是必须首先验证 Nuitka。

---

# 5. EXE 功能要求

SysCenter.exe 必须支持以下命令：

```text
SysCenter.exe
SysCenter.exe start
SysCenter.exe stop
SysCenter.exe restart
SysCenter.exe status
SysCenter.exe doctor
SysCenter.exe version
SysCenter.exe install
SysCenter.exe uninstall
SysCenter.exe migrate
SysCenter.exe config
```

其中：

## start

启动 SysCenter 后端。

## stop

停止后端。

## restart

重启后端。

## status

显示：

```text
SysCenter Status
----------------
Version:
Process:
PID:
Host:
Port:
Database:
Redis:
Uptime:
Health:
```

## doctor

执行完整诊断：

```text
EXE
配置
端口
数据库
Redis
Docker
文件权限
日志目录
数据库迁移
网络
```

并输出：

```text
PASS
WARN
FAIL
```

## version

输出：

```text
SysCenter x.x.x
Build:
Commit:
Build Time:
```

## migrate

执行数据库迁移。

禁止每次启动都无条件执行破坏性数据库操作。

---

# 6. Windows Service

生产环境必须支持 Windows Service。

服务名称建议：

```text
SysCenter
```

显示名称：

```text
SysCenter Service
```

描述：

```text
SysCenter Windows Management Platform
```

---

# 7. Windows Service 行为

服务必须支持：

```text
安装
启动
停止
重启
卸载
状态检测
自动恢复
```

Windows 服务恢复策略：

```text
第一次失败：重启服务
第二次失败：重启服务
后续失败：重启服务
```

建议设置恢复延迟：

```text
5000ms
```

---

# 8. 服务启动顺序

生产环境启动顺序：

```text
Windows
 ↓
Docker Desktop
 ↓
PostgreSQL
 ↓
Redis
 ↓
SysCenter Service
 ↓
SysCenter.exe
 ↓
Health Check
 ↓
Web UI
```

SysCenter 不应假设 PostgreSQL/Redis 一定已经立即可用。

必须实现：

```text
连接失败
 ↓
等待
 ↓
重试
 ↓
健康检查
 ↓
连接成功
```

禁止：

```text
数据库暂时没启动
 ↓
SysCenter 直接退出
```

---

# 9. Docker 职责

Docker 只负责基础设施。

默认：

```text
PostgreSQL
Redis
```

不要求 SysCenter 后端继续运行在 Docker 中。

生产架构：

```text
Windows Native
└── SysCenter.exe

Docker
├── PostgreSQL
└── Redis
```

---

# 10. Docker Compose

必须提供：

```text
docker-compose.yml
```

或：

```text
compose.yml
```

负责：

```text
PostgreSQL
Redis
```

要求：

- 固定数据卷
- 健康检查
- 自动重启
- 明确端口
- 明确用户名
- 明确数据库名称
- 明确密码来源
- 不允许密码硬编码在源码中

---

# 11. 数据持久化

禁止把数据库数据存放在容器临时层。

必须使用：

```text
Docker Volume
```

或宿主机持久化目录。

推荐：

```text
SysCenter/
├── data/
│   ├── postgres/
│   └── redis/
```

如果 Windows Docker Desktop 环境下存在权限或性能问题，可使用 Docker Named Volume。

---

# 12. Redis

Redis 主要承担：

```text
缓存
Session
任务状态
临时数据
限流
队列
```

必须允许：

```text
Redis 不可用
```

时进行明确错误处理。

不能导致：

```text
SysCenter.exe
```

直接崩溃。

---

# 13. PostgreSQL

PostgreSQL 作为主要业务数据库。

必须支持：

```text
初始化
迁移
备份
恢复
健康检查
连接池
异常重连
```

数据库连接配置不得写死。

---

# 14. 配置系统

生产配置统一放置：

```text
config/
```

或：

```text
.env
```

推荐最终：

```text
SysCenter/
├── SysCenter.exe
├── config/
│   └── config.yaml
├── data/
├── logs/
└── docker/
```

敏感信息：

```text
DATABASE_PASSWORD
REDIS_PASSWORD
JWT_SECRET
AI_API_KEY
```

禁止写入源码。

---

# 15. 配置优先级

建议：

```text
命令行参数
    ↓
环境变量
    ↓
config.yaml
    ↓
默认值
```

必须保证：

```text
开发环境
```

和：

```text
生产环境
```

可以使用不同配置。

---

# 16. 开发模式

EXE 化不能破坏开发体验。

开发环境仍然允许：

```text
Python
venv
uvicorn
hot reload
```

例如：

```text
开发：
Python + FastAPI + Vite

生产：
SysCenter.exe + Frontend
```

两者必须共享：

```text
业务代码
配置模型
数据库模型
API
测试
```

禁止为了 EXE 打包复制出一套完全不同的业务逻辑。

---

# 17. 前端

如果当前项目已经存在：

```text
Vue
React
其他 Web Frontend
```

保持现有技术栈。

生产环境执行：

```text
npm build
```

生成：

```text
dist/
```

如果 FastAPI 可以稳定托管静态资源，则允许：

```text
SysCenter.exe
 ├── FastAPI
 └── frontend/dist
```

直接提供 Web UI。

这样生产环境可以不依赖 Nginx。

---

# 18. Nginx

Nginx 不再作为 SysCenter 核心运行依赖。

允许：

```text
可选组件
```

用于：

- HTTPS
- 反向代理
- 多服务部署
- 外网访问
- 域名
- TLS

本机单机部署情况下：

```text
Browser
 ↓
SysCenter.exe
```

即可。

---

# 19. 推荐默认端口

最终端口必须集中配置。

示例：

```text
SysCenter:
8352

Frontend:
由 SysCenter 提供

PostgreSQL:
5432

Redis:
6379
```

如果原项目已经存在正式端口，不允许未经验证直接修改。

必须先扫描：

```text
前端
后端
配置
Docker
文档
脚本
测试
```

统一端口定义。

---

# 20. 健康检查

必须提供：

```text
/health
```

以及：

```text
/health/live
/health/ready
```

建议：

### live

只判断 SysCenter 进程是否正常。

### ready

判断：

```text
SysCenter
PostgreSQL
Redis
```

是否满足服务运行条件。

---

# 21. Windows 环境检测

SysCenter 启动时必须能够检测：

```text
Windows Version
Architecture
CPU
Memory
Disk
Docker
Docker Compose
PostgreSQL
Redis
Port
Network
```

不要因为某项检测失败就导致整个程序无法启动。

应该区分：

```text
必需条件
可选条件
警告条件
```

---

# 22. Docker 检测

SysCenter 必须能够判断：

```text
Docker 是否安装
Docker Desktop 是否运行
Docker Engine 是否可用
Compose 是否可用
PostgreSQL Container 是否运行
Redis Container 是否运行
```

如果 Docker 不可用：

```text
SysCenter
 ↓
doctor
 ↓
明确提示
```

不能输出难以理解的 Python traceback。

---

# 23. 数据库初始化

第一次运行：

```text
检测数据库
 ↓
数据库不存在
 ↓
创建数据库
 ↓
执行 migration
 ↓
初始化基础数据
 ↓
创建管理员
```

如果数据库已经存在：

```text
检测 migration
 ↓
执行必要 migration
```

禁止重复初始化。

---

# 24. 数据库迁移

必须使用项目现有迁移框架。

如果项目已经使用：

```text
Alembic
```

继续使用。

不得自行设计第二套迁移系统。

生产环境：

```text
SysCenter.exe migrate
```

执行迁移。

升级程序必须能够检测：

```text
当前数据库版本
目标数据库版本
```

并按顺序升级。

---

# 25. 日志

生产环境必须统一：

```text
logs/
```

建议：

```text
logs/
├── syscenter.log
├── error.log
├── access.log
├── service.log
└── startup.log
```

日志必须支持：

```text
INFO
WARNING
ERROR
CRITICAL
DEBUG
```

生产默认：

```text
INFO
```

---

# 26. 日志轮转

不能无限增长。

必须支持：

```text
最大文件大小
保留文件数量
自动压缩
自动删除
```

例如：

```text
20MB × 10
```

具体数值可配置。

---

# 27. 异常处理

生产环境禁止把：

```text
Python Traceback
内部路径
数据库密码
Token
API Key
```

直接返回浏览器。

用户看到：

```text
系统内部错误
Request ID: xxxxx
```

日志记录完整异常。

---

# 28. 崩溃恢复

SysCenter.exe 崩溃后：

```text
Windows Service
 ↓
检测进程退出
 ↓
自动重启
```

同时：

```text
记录 Crash
记录时间
记录原因
记录连续重启次数
```

如果短时间连续崩溃，应进入保护模式。

例如：

```text
5 分钟内连续启动失败 ≥ 5 次
```

则：

```text
停止无限重启
 ↓
写入错误日志
 ↓
等待人工处理
```

具体阈值可配置。

---

# 29. 单实例

默认禁止同一台机器启动多个 SysCenter 后端实例。

例如：

```text
SysCenter.exe
SysCenter.exe
```

第二个实例应该提示：

```text
SysCenter is already running.
```

避免：

```text
端口冲突
数据库竞争
任务重复执行
```

---

# 30. 文件目录规范

建议：

```text
C:\Program Files\SysCenter\
```

存放程序：

```text
SysCenter.exe
```

配置：

```text
C:\ProgramData\SysCenter\config\
```

数据：

```text
C:\ProgramData\SysCenter\data\
```

日志：

```text
C:\ProgramData\SysCenter\logs\
```

备份：

```text
C:\ProgramData\SysCenter\backup\
```

这样程序升级不会覆盖用户数据。

---

# 31. 程序与数据彻底分离

必须做到：

```text
Program Files
    ↓
程序

ProgramData
    ↓
配置
数据
日志
备份
```

禁止：

```text
SysCenter.exe
 └── 修改自身目录中的数据库
```

---

# 32. 权限设计

安装程序需要管理员权限。

正常运行时尽量使用：

```text
LocalSystem
```

或专门的 Windows Service Account。

必须根据 SysCenter 实际需要的 Windows 管理权限确定。

原则：

> 只授予 SysCenter 完成功能所需要的最小权限。

如果项目需要：

```text
Windows Service
Registry
网络配置
系统信息
进程管理
```

必须逐项验证权限。

---

# 33. 安全要求

禁止：

```text
硬编码密码
硬编码 API Key
硬编码 JWT Secret
硬编码数据库密码
```

必须检查源码：

```text
.env
config
Git history
Docker Compose
日志
异常
```

防止敏感信息泄露。

---

# 34. API 安全

必须检查：

```text
认证
授权
Session
JWT
CSRF
CORS
Rate Limit
密码策略
登录失败限制
```

EXE 化不是降低安全标准的理由。

---

# 35. Windows 防火墙

安装程序可以检测：

```text
8352
```

是否已经被防火墙阻止。

不要默认开放：

```text
0.0.0.0
```

如果 SysCenter 只允许本机访问，优先：

```text
127.0.0.1
```

如果需要局域网访问，再由用户明确启用。

---

# 36. 安装程序

最终应提供：

```text
SysCenter-Setup-x64.exe
```

安装程序负责：

```text
安装程序
 ↓
创建目录
 ↓
复制 SysCenter.exe
 ↓
创建配置目录
 ↓
检测 Docker
 ↓
准备 PostgreSQL/Redis
 ↓
安装 Windows Service
 ↓
启动服务
 ↓
健康检查
 ↓
打开 Web UI
```

---

# 37. 升级

必须支持：

```text
SysCenter v1
 ↓
安装 v2
 ↓
保留 config
 ↓
保留 data
 ↓
停止 Service
 ↓
升级 EXE
 ↓
数据库 migration
 ↓
启动 Service
 ↓
Health Check
```

禁止升级覆盖：

```text
数据库
用户配置
日志
备份
```

---

# 38. 回滚

升级失败必须至少提供：

```text
旧 EXE
旧配置
数据库备份
```

推荐升级前自动执行：

```text
Database Backup
Config Backup
```

如果升级失败：

```text
停止服务
 ↓
恢复 EXE
 ↓
必要时恢复数据库
 ↓
启动
 ↓
Health Check
```

---

# 39. 卸载

卸载程序必须明确区分：

```text
卸载程序
```

与：

```text
删除数据
```

默认：

```text
卸载 SysCenter
```

不删除：

```text
数据库
配置
日志
备份
```

必须提供：

```text
彻底删除所有数据
```

的明确选项。

避免用户误删业务数据。

---

# 40. 备份

必须提供 SysCenter 数据备份机制。

至少包括：

```text
PostgreSQL
配置
重要系统数据
```

建议支持：

```text
SysCenter.exe backup
```

生成：

```text
backup/
└── SysCenter-YYYYMMDD-HHMMSS.zip
```

---

# 41. 恢复

必须支持：

```text
SysCenter.exe restore
```

恢复过程：

```text
检查备份
 ↓
停止服务
 ↓
停止依赖服务
 ↓
恢复数据库
 ↓
恢复配置
 ↓
启动 Docker
 ↓
启动 SysCenter
 ↓
Health Check
```

---

# 42. AI 模块

如果 SysCenter 当前存在 AI 功能：

```text
DeepSeek
NVIDIA
OpenAI-compatible API
其他模型
```

必须继续保持。

AI 配置：

```text
Provider
Base URL
API Key
Model
Timeout
Temperature
Max Tokens
```

全部配置化。

---

# 43. AI 故障隔离

AI 服务不可用：

```text
AI API 超时
 ↓
不能导致 SysCenter 崩溃
```

必须：

```text
Timeout
Retry
Fallback
Error Message
```

AI 是增强功能，不得成为整个管理面板的单点故障。

---

# 44. 后台任务

如果 SysCenter 有：

```text
Scheduler
Background Task
定时任务
监控任务
AI Task
```

必须检查 EXE 化后的行为。

尤其要避免：

```text
Windows Service 重启
 ↓
任务重复执行
```

需要：

```text
Task ID
Lock
State
Retry
```

等机制。

---

# 45. WebSocket / SSE

如果项目存在：

```text
WebSocket
SSE
Streaming
实时日志
AI Streaming
```

必须在 EXE 模式下进行专项测试。

验证：

```text
连接
断线
重连
超时
服务重启
浏览器刷新
```

---

# 46. 静态资源

生产构建必须确认：

```text
JS
CSS
Images
Fonts
favicon
```

全部正确加载。

不能出现：

```text
开发环境正常
EXE 后 404
```

---

# 47. 路径处理

严禁：

```python
"C:\\xxx\\SysCenter\\..."
```

这种固定路径。

必须使用：

```text
Path(__file__)
```

或经过统一封装的：

```text
APP_DIR
CONFIG_DIR
DATA_DIR
LOG_DIR
```

处理。

必须兼容：

```text
开发环境
EXE 环境
Windows Service 环境
```

---

# 48. EXE 运行目录

不能依赖：

```text
Current Working Directory
```

因为 Windows Service 的工作目录可能不同。

所有资源路径必须通过统一路径管理器计算。

---

# 49. 子进程

如果 SysCenter 会执行：

```text
docker
docker compose
sc.exe
netsh
powershell
cmd
其他 Windows 工具
```

必须统一封装。

禁止业务代码大量散落：

```python
subprocess.run(...)
```

应建立：

```text
SystemCommandService
```

统一：

```text
命令
参数
超时
退出码
stdout
stderr
日志
异常
```

---

# 50. 命令执行安全

任何来自：

```text
HTTP
AI
用户输入
数据库
```

的数据，都不能直接拼接成 Shell 命令。

必须使用：

```text
参数数组
白名单
命令模板
权限控制
```

防止命令注入。

---

# 51. AI 执行权限

如果 SysCenter AI 具有：

```text
系统管理权限
```

必须建立明确的工具层。

推荐：

```text
AI
 ↓
Tool Router
 ↓
Permission Check
 ↓
Command Executor
 ↓
Windows
```

禁止：

```text
AI
 ↓
直接执行任意 CMD
```

---

# 52. AI 操作日志

AI 执行任何系统操作必须记录：

```text
时间
用户
AI
工具
参数
目标
执行结果
耗时
错误
```

例如：

```text
2026-08-20 05:20
User: admin
Tool: restart_service
Target: nginx
Result: SUCCESS
```

---

# 53. 不允许 AI 删除关键数据

必须保留用户最终控制权。

高风险操作：

```text
删除数据库
删除 Docker Volume
删除系统文件
卸载服务
删除用户
清空日志
```

必须进行：

```text
用户确认
```

不得因为 AI 拥有系统权限就自动执行。

---

# 54. Docker 管理模块

SysCenter 如果管理 Docker，至少应能够展示：

```text
Containers
Images
Volumes
Networks
Compose Projects
```

并支持现有项目已有功能。

EXE 化不能造成 Docker 管理功能退化。

---

# 55. Docker 操作失败处理

例如：

```text
docker restart xxx
```

失败时必须展示：

```text
命令
退出码
错误原因
```

不能只显示：

```text
操作失败
```

---

# 56. 数据库连接池

FastAPI 数据库层必须使用合理连接池。

必须检查：

```text
连接泄漏
连接超时
断线重连
最大连接数
空闲连接
```

Windows EXE 长时间运行时：

```text
24小时
7天
30天
```

都不能出现明显连接泄漏。

---

# 57. 长时间运行稳定性

必须进行：

```text
24h
72h
```

稳定性测试。

重点观察：

```text
Memory
CPU
Thread
Handle
Database Connections
Redis Connections
Log Size
Task Count
```

---

# 58. 内存泄漏测试

SysCenter.exe 连续运行后：

```text
内存不能持续无限增长。
```

重点检查：

```text
FastAPI
WebSocket
SSE
Scheduler
AI Streaming
Docker Monitor
Windows Monitor
```

---

# 59. 安装环境测试

至少测试：

```text
Windows 10 x64
Windows 11 x64
```

分别测试：

```text
全新系统
已有 Docker
无 Docker
Docker 未启动
已有 PostgreSQL
已有 Redis
端口被占用
普通用户
管理员
```

---

# 60. 端口冲突

如果：

```text
8352
```

已经被占用。

安装程序必须明确提示：

```text
Port 8352 is already in use.
```

并提供：

```text
查看占用进程
修改端口
```

而不是直接启动失败。

---

# 61. Docker 未安装

如果用户安装 SysCenter 时没有 Docker：

必须明确提示：

```text
SysCenter Backend can run,
but PostgreSQL/Redis dependencies require Docker.
```

不得出现无法理解的错误。

---

# 62. Docker 未启动

必须：

```text
检测
 ↓
提示
 ↓
允许启动 Docker Desktop
 ↓
重新检测
```

如果无法启动：

```text
进入 doctor
```

提供明确故障信息。

---

# 63. 服务启动失败

Windows Service 启动失败时必须能够通过：

```text
SysCenter.exe doctor
```

定位原因。

至少检查：

```text
EXE
配置
端口
权限
数据库
Redis
Docker
日志
```

---

# 64. 前端启动检查

健康检查不能只检查：

```text
HTTP 200
```

还应该检查：

```text
API
Database
Redis
关键静态资源
```

---

# 65. 开发与生产文件结构

建议最终：

```text
SysCenter/
│
├── backend/
│
├── frontend/
│
├── packaging/
│   ├── windows/
│   │   ├── build.ps1
│   │   ├── installer/
│   │   └── service/
│
├── docker/
│   └── compose.yml
│
├── scripts/
│
├── tests/
│
├── docs/
│
└── README.md
```

具体目录必须根据原项目实际结构调整。

禁止为了“看起来规范”而无意义大规模移动源码。

---

# 66. 构建流程

必须提供：

```text
build-windows.ps1
```

实现：

```text
清理
 ↓
安装依赖
 ↓
前端 Build
 ↓
后端检查
 ↓
测试
 ↓
Nuitka Build
 ↓
复制资源
 ↓
生成版本信息
 ↓
生成安装包
```

---

# 67. CI/CD

如果项目使用 GitHub Actions，应增加 Windows Build。

建议：

```text
push
 ↓
Test
 ↓
Build Windows EXE
 ↓
Smoke Test
 ↓
Artifact
```

Release：

```text
Git Tag
 ↓
Build
 ↓
Installer
 ↓
Release
```

---

# 68. 版本管理

EXE 版本必须来自统一版本号：

```text
MAJOR.MINOR.PATCH
```

例如：

```text
1.0.0
```

版本信息必须写入：

```text
EXE
API
Web UI
日志
```

---

# 69. Git Commit 信息

生产 EXE 应记录：

```text
Version
Git Commit
Build Time
Build Environment
```

方便定位：

```text
某个 EXE 到底来自哪次代码提交。
```

---

# 70. 单元测试

EXE 改造不能只测试：

```text
能不能启动。
```

必须测试：

```text
数据库
Redis
API
认证
权限
Docker
Windows
AI
任务
配置
```

---

# 71. Smoke Test

每次生成 EXE 后自动执行：

```text
启动 EXE
 ↓
检测端口
 ↓
GET /health
 ↓
登录
 ↓
访问核心 API
 ↓
访问 Web
 ↓
停止
```

全部通过才能发布。

---

# 72. 安装验收

安装包必须验证：

```text
[ ] 安装成功
[ ] 创建 Windows Service
[ ] Service 自动启动
[ ] EXE 正常启动
[ ] Web 正常访问
[ ] PostgreSQL 正常
[ ] Redis 正常
[ ] 数据库 migration 正常
[ ] 登录正常
[ ] 核心功能正常
```

---

# 73. 重启验收

执行：

```text
Windows Restart
```

之后验证：

```text
[ ] Docker 自动恢复
[ ] PostgreSQL 恢复
[ ] Redis 恢复
[ ] SysCenter Service 自动启动
[ ] Web 可以访问
[ ] 数据没有丢失
[ ] 定时任务没有重复执行
```

---

# 74. 异常验收

模拟：

```text
杀死 SysCenter.exe
```

要求：

```text
Service 自动恢复
```

模拟：

```text
停止 Redis
```

要求：

```text
SysCenter 不崩溃
```

模拟：

```text
停止 PostgreSQL
```

要求：

```text
SysCenter 不崩溃
```

数据库恢复后：

```text
SysCenter 自动恢复数据库连接。
```

---

# 75. 升级验收

测试：

```text
V1
 ↓
V2
```

要求：

```text
[ ] 用户数据保留
[ ] 配置保留
[ ] 数据库 migration 成功
[ ] Service 保留
[ ] EXE 更新
[ ] Web 正常
```

---

# 76. 卸载验收

测试：

```text
卸载
```

要求：

```text
[ ] Service 删除
[ ] EXE 删除
[ ] 程序目录删除
[ ] 用户数据默认保留
```

选择：

```text
彻底删除
```

后才删除：

```text
Data
Config
Backup
```

---

# 77. 原有功能零回归

这是本次改造的最高优先级之一。

EXE 化属于：

```text
运行方式重构
```

不是：

```text
业务功能重写
```

禁止在没有明确需求的情况下修改：

```text
业务逻辑
数据库结构
API 行为
权限模型
UI
用户数据
```

---

# 78. Codex 执行原则

Codex 开始改造之前必须：

```text
1. 完整扫描仓库
2. 识别后端入口
3. 识别 FastAPI App
4. 识别数据库
5. 识别 Redis
6. 识别 Docker
7. 识别前端
8. 识别现有启动脚本
9. 识别配置系统
10. 识别后台任务
11. 识别 Windows API
12. 识别 AI 模块
```

不得直接开始重构。

---

# 79. 改造前必须生成分析报告

Codex 必须先输出：

```text
ARCHITECTURE_ANALYSIS.md
```

至少包含：

```text
当前架构
后端入口
启动方式
数据库
Redis
Docker
前端
配置
Windows 功能
AI
任务系统
风险点
EXE 打包风险
```

然后才能开始编码。

---

# 80. 不允许盲目替换

不得直接：

```text
删除 run.bat
```

必须先建立：

```text
EXE
```

并确认：

```text
EXE 可以正常启动
```

然后再逐步淘汰旧启动方式。

---

# 81. 兼容旧开发方式

至少在开发阶段保留：

```text
run.bat
```

但必须修改为：

```text
开发启动脚本
```

不能继续使用：

```text
固定 Python 路径
```

应该自动检测：

```text
venv
uv
python
```

---

# 82. 生产环境禁止旧启动方式

最终 Release 中：

```text
run.bat
```

不能作为生产启动入口。

生产唯一标准入口：

```text
Windows Service
```

或者：

```text
SysCenter.exe
```

---

# 83. 不允许把所有依赖塞入 EXE

EXE 内部允许：

```text
Python Runtime
FastAPI
业务依赖
```

但不应该塞入：

```text
PostgreSQL Server
Redis Server
Docker Engine
Docker Desktop
```

---

# 84. 安装包边界

安装包负责：

```text
SysCenter
Windows Service
配置
启动器
```

Docker 负责：

```text
PostgreSQL
Redis
```

Windows 本身负责：

```text
系统服务
网络
系统资源
```

---

# 85. 最终用户体验

目标体验：

```text
双击 SysCenter-Setup.exe
        ↓
下一步
        ↓
安装
        ↓
完成
        ↓
SysCenter 自动启动
        ↓
浏览器打开
        ↓
登录
```

用户不应该需要打开：

```text
CMD
PowerShell
Python
Docker Compose
```

进行日常启动。

---

# 86. 最终部署目录

推荐：

```text
C:\Program Files\SysCenter\
    └── SysCenter.exe

C:\ProgramData\SysCenter\
    ├── config\
    ├── data\
    ├── logs\
    ├── backup\
    └── docker\
```

---

# 87. 最终启动链

```text
Windows Boot
     │
     ▼
Docker Desktop
     │
     ▼
PostgreSQL / Redis
     │
     ▼
SysCenter Windows Service
     │
     ▼
SysCenter.exe
     │
     ▼
FastAPI
     │
     ├── PostgreSQL
     ├── Redis
     ├── Docker
     ├── Windows API
     ├── AI
     └── Scheduler
     │
     ▼
Web UI
```

---

# 88. 验收标准

本项目只有在以下条件全部满足后，才允许宣布 EXE 原生化完成：

## A. 构建

```text
[ ] Windows x64 EXE 可以生成
[ ] 不依赖本机 Python
[ ] 不依赖 venv
[ ] EXE 可以独立启动
```

## B. 服务

```text
[ ] Windows Service 安装成功
[ ] 自动启动
[ ] 自动恢复
[ ] 停止正常
[ ] 卸载正常
```

## C. Docker

```text
[ ] PostgreSQL 正常
[ ] Redis 正常
[ ] Docker 重启后恢复
```

## D. 数据

```text
[ ] 数据库初始化正常
[ ] Migration 正常
[ ] 数据持久化
[ ] 备份正常
[ ] 恢复正常
```

## E. Web

```text
[ ] Web 正常
[ ] API 正常
[ ] 登录正常
[ ] 静态资源正常
[ ] WebSocket/SSE 正常
```

## F. AI

```text
[ ] AI 正常
[ ] AI 超时不导致系统崩溃
[ ] AI 操作有日志
[ ] 高风险操作有确认
```

## G. 稳定性

```text
[ ] 24小时运行
[ ] 72小时运行
[ ] 无明显内存泄漏
[ ] 无连接泄漏
[ ] 日志正常轮转
```

## H. 升级

```text
[ ] 升级成功
[ ] 数据不丢失
[ ] 配置不丢失
[ ] Migration 正常
[ ] 回滚可执行
```

---

# 89. 最终交付物

Codex 必须最终提交：

```text
SysCenter.exe
SysCenter-Setup-x64.exe
```

以及：

```text
docs/
├── WINDOWS_EXE_ARCHITECTURE.md
├── WINDOWS_INSTALL.md
├── WINDOWS_SERVICE.md
├── WINDOWS_UPGRADE.md
├── WINDOWS_BACKUP_RESTORE.md
├── WINDOWS_TROUBLESHOOTING.md
└── WINDOWS_EXE_ACCEPTANCE.md
```

构建文件：

```text
packaging/
├── windows/
│   ├── build.ps1
│   ├── installer/
│   └── service/
```

---

# 90. Codex 最终执行指令

> **不要把本任务理解成“把 Python 打包成 EXE”。**

本任务的真实目标是：

```text
将 SysCenter 从
“依赖 Python 环境运行的 Web 项目”

升级为

“Windows 原生后台服务 + Docker 基础设施 + Web 管理界面”的完整 Windows 应用。
```

必须遵循：

```text
先分析
 ↓
再设计
 ↓
再实现
 ↓
再测试
 ↓
再打包
 ↓
再安装测试
 ↓
再重启测试
 ↓
再升级测试
 ↓
再卸载测试
 ↓
最后提交
```

严禁：

```text
为了生成 EXE 而破坏现有功能。
```

最终目标不是：

```text
“SysCenter 能生成一个 EXE”
```

而是：

```text
“普通 Windows 用户安装一次，
以后无需理解 Python、pip、venv、uvicorn，
SysCenter 就能够像一个正规 Windows 服务一样稳定运行。”
```

**验收结论必须以实际运行测试为准，不得仅以“代码已经修改完成”作为通过依据。**