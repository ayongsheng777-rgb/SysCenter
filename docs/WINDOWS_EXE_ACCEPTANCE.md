# SysCenter EXE 原生化验收（规格书 §88/§89）

> 验收结论以**实际运行测试**为准，不仅凭代码修改。

## A. 构建（必须由本机产出）
- [x] `SysCenter.exe` 可生成（PyInstaller onefile，规格书 §4.1 允许的兼容方案）
- [x] 不依赖本机 Python / venv
- [x] `SysCenter.exe` 可独立启动

## B. 服务
- [x] `SysCenter.exe install` 安装成功
- [x] 自动启动（SCM 自动）
- [x] 自动恢复（三次失败均重启，延迟 5000ms）
- [x] 停止/卸载正常

## C. Docker（基础设施）
- [x] PostgreSQL 正常（端口 5442，固定卷，健康检查）
- [x] Redis 正常（端口 6387，固定卷，健康检查）
- [x] Docker 重启后由 restart 策略恢复

## D. 数据
- [x] 数据库初始化 / Migration 正常（Alembic）
- [x] 数据持久化（Docker 卷）
- [x] 备份 / 恢复正常（`backup` / `restore`）

## E. Web
- [x] Web 正常（EXE 直接托管 frontend/dist）
- [x] API 正常（/api 相对路径）
- [x] 登录正常（OTP Bootstrap + TOTP 会话）
- [x] 静态资源正常（JS/CSS/ assets）
- [x] 健康检查端点 `/health` `/health/live` `/health/ready`

## F. AI
- [x] AI 配置化（Provider/BaseURL/Key/Model）
- [x] 超时/重试/降级，不导致系统崩溃（规格书 §43）
- [x] AI 操作有日志（规格书 §52）

## G. 稳定性
- [ ] 24h / 72h 长时间运行（需实机长跑，见 §57/§58）
- [x] 日志正常轮转（20MB×10）
- [x] 单实例保护（规格书 §29）

## H. 升级
- [x] 升级脚本化（`backup` → 覆盖 → `migrate` → 启动）
- [x] 数据/配置不丢失
- [x] 回滚可执行（备份 + `restore`）

## 备注：Nuitka 评估
- 本机构建环境**缺少 MSVC `cl.exe`**；Nuitka 需 MinGW 且对本项目大量 C 扩展
  （asyncpg / cryptography / psutil）+ lark-oapi 兼容不稳定。
- 按规格书 §4.1「允许使用 PyInstaller 作为兼容方案」，实际交付采用 PyInstaller。
- `packaging/windows/build.ps1` 保留 `USE_NUITKA=1` 切换项，待具备 MSVC 工具链时可改回 Nuitka。
