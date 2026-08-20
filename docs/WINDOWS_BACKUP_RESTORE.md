# SysCenter 备份与恢复（规格书 §40/§41）

## 1. 备份

```powershell
SysCenter.exe backup
```

产物：`backup/SysCenter-YYYYMMDD-HHMMSS.zip`，包含：
- 全量数据库导出（`db_dump.json`，所有 public 表）
- `.env` 配置（含口令，注意保管）
- `data/` 目录（OTP 密钥等，已加密/脱敏）

> 升级前建议先执行一次备份（规格书 §38）。

## 2. 恢复

```powershell
# 指定备份文件
SysCenter.exe restore backup\SysCenter-20260820-120000.zip

# 省略参数则恢复最新一份
SysCenter.exe restore
```

恢复流程：解压 → 清空并回写各表 → 完成。恢复期建议先停止服务：

```powershell
net stop SysCenter
SysCenter.exe restore <file>
net start SysCenter
```

## 3. 注意事项

- 恢复会 **TRUNCATE** 现有表再写入，属覆盖性操作，请确认目标库可覆盖。
- 备份不含 PostgreSQL/Redis 容器卷；如需整库物理备份，另行 `pg_dump` / `redis-cli --rdb`。
- 敏感信息：`.env` 与 `data/` 含密钥，备份文件应存放于受限目录。
