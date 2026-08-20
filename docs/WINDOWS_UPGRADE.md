# SysCenter 升级与回滚（规格书 §37/§38）

## 1. 升级流程（保留数据与配置）

```powershell
net stop SysCenter
# 1) 自动备份（强烈建议）
SysCenter.exe backup
# 2) 替换程序：用新 SysCenter.exe + 配套资源覆盖安装目录
#    （保留 config/ .env data/ logs/ backup/ 不被覆盖）
# 3) 执行数据库迁移
SysCenter.exe migrate
# 4) 启动
net start SysCenter
SysCenter.exe doctor
```

- **禁止**覆盖：数据库、用户配置（`.env`）、日志、备份（规格书 §37）。
- `migrate` 仅执行必要的 Alembic 升级，不会无条件做破坏性操作（规格书 §23/§24）。

## 2. 回滚

若升级失败：

```powershell
net stop SysCenter
# 恢复旧 EXE（保留备份）
# 必要时：
SysCenter.exe restore <升级前备份 zip>   # 仅当需要回退数据
net start SysCenter
```

- 升级前自动执行的「数据库 + 配置备份」是回滚的安全网（规格书 §38）。

## 3. 兼容性

- EXE 原生化仅改变运行方式，不改动 API/数据库结构/权限模型（规格书 §77），因此跨小版本升级通常只需覆盖 EXE + 跑 `migrate`。
