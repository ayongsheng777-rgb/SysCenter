# -*- coding: utf-8 -*-
"""自动灾变备份：每月全量 + 每周增量，备份到 F:/SysCenterBAK

设计（核心数据，异盘灾备）：
- 全量（full）：数据库完整 dump + 全部核心文件（.env / config.yaml / data 目录）→ zip
- 增量（incr）：数据库完整 dump + 仅变化的文件（对比 manifest.json 里记录的 hash）
- 归档目录：F:/SysCenterBAK/full/YYYYMM 与 incr/YYYYWW，可用环境变量 BACKUP_DIR 覆盖
- 保留策略：全量 90 天、增量 28 天，每次备份后清理过期
- 调度：check_and_backup() 由 scheduler 周期调用，内部 1 小时节流；
  距上次全量 >=30 天做全量，距上次增量 >=7 天做增量
- 落库 backup_log，供周期判断与前端状态查询
"""
import asyncio
import hashlib
import json
import logging
import os
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import db

log = logging.getLogger("backup")

# ===== 配置（可环境变量覆盖） =====
BACKUP_ROOT = Path(os.environ.get("BACKUP_DIR", "F:/SysCenterBAK"))
FULL_INTERVAL_DAYS = int(os.environ.get("BACKUP_FULL_INTERVAL_DAYS", "30"))
INCR_INTERVAL_DAYS = int(os.environ.get("BACKUP_INCR_INTERVAL_DAYS", "7"))
FULL_RETENTION_DAYS = int(os.environ.get("BACKUP_FULL_RETENTION_DAYS", "90"))
INCR_RETENTION_DAYS = int(os.environ.get("BACKUP_INCR_RETENTION_DAYS", "28"))
CHECK_THROTTLE = 3600  # 调度节流：1 小时内最多检查一次

# 数据目录（syscenter_app.py 启动时已固化到环境变量 DATA_DIR）
DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
APP_HOME = DATA_DIR.parent

# manifest：记录上次备份时每个文件的 hash，供增量对比
_MANIFEST = BACKUP_ROOT / "manifest.json"

# 调度节流状态
_last_check = 0.0


# ==================== 底层：数据库 dump / 文件收集 / hash ====================
async def _dump_db() -> dict:
    """dump 所有用户表（库小，全量快照即可，与 EXE cmd_backup 同构）。"""
    async with db.pool().acquire() as conn:
        tables = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        dump: dict = {}
        for r in tables:
            t = r["table_name"]
            try:
                rows = await conn.fetch(f'SELECT * FROM "{t}"')
                dump[t] = [dict(x) for x in rows]
            except Exception as e:  # noqa: BLE001
                log.warning("dump 表 %s 失败(忽略): %s", t, e)
        return dump


def _collect_files() -> dict[str, Path]:
    """收集核心文件：.env、config/config.yaml、data 目录。返回 {相对路径: 绝对路径}。"""
    files: dict[str, Path] = {}
    envf = APP_HOME / ".env"
    if envf.exists():
        files[".env"] = envf
    cfgf = APP_HOME / "config" / "config.yaml"
    if cfgf.exists():
        files["config/config.yaml"] = cfgf
    if DATA_DIR.exists():
        for p in DATA_DIR.rglob("*"):
            if p.is_file():
                files[f"data/{p.relative_to(DATA_DIR)}"] = p
    return files


def _hash_file(path: Path) -> str:
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except Exception:  # noqa: BLE001
        return ""


def _load_manifest() -> dict:
    try:
        return json.loads(_MANIFEST.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_manifest(m: dict):
    try:
        _MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        _MANIFEST.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("写 manifest 失败(忽略): %s", e)


def _changed_files(files: dict[str, Path], manifest: dict) -> dict[str, Path]:
    """返回自上次备份以来变化的文件（hash 不同或新增），并原地更新 manifest。"""
    changed: dict[str, Path] = {}
    for rel, p in files.items():
        h = _hash_file(p)
        if manifest.get(rel) != h:
            changed[rel] = p
            manifest[rel] = h
    # 移除已删除的文件
    for rel in list(manifest.keys()):
        if rel not in files:
            manifest.pop(rel, None)
    return changed


def _write_zip(zip_path: Path, db_dump: dict, files: dict[str, Path]):
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("db_dump.json", json.dumps(db_dump, default=str, ensure_ascii=False))
        for rel, p in files.items():
            z.write(p, arcname=rel)


# ==================== 落库 ====================
async def _log_backup(btype: str, file_path, file_size: int, status: str, message: str = ""):
    try:
        async with db.pool().acquire() as conn:
            await conn.execute(
                "INSERT INTO backup_log (backup_type, file_path, file_size, status, message) "
                "VALUES ($1,$2,$3,$4,$5)",
                btype, str(file_path) if file_path else None, file_size, status, message)
    except Exception as e:  # noqa: BLE001
        log.warning("写 backup_log 失败(忽略): %s", e)


async def _last_backup_time(btype: str) -> Optional[float]:
    """上次成功备份的 epoch 秒（无记录返回 None）。"""
    try:
        async with db.pool().acquire() as conn:
            r = await conn.fetchrow(
                "SELECT EXTRACT(EPOCH FROM created_at) AS e FROM backup_log "
                "WHERE backup_type=$1 AND status='success' "
                "ORDER BY created_at DESC LIMIT 1", btype)
            return float(r["e"]) if r else None
    except Exception as e:  # noqa: BLE001
        log.warning("查上次备份时间失败(忽略): %s", e)
        return None


# ==================== 全量 / 增量 ====================
async def do_full_backup() -> dict:
    """全量备份：数据库完整 dump + 全部核心文件，并重置增量基线。"""
    stamp = datetime.now()
    db_dump = await _dump_db()
    files = _collect_files()
    manifest = {rel: _hash_file(p) for rel, p in files.items()}
    _save_manifest(manifest)

    zip_path = (BACKUP_ROOT / "full" / stamp.strftime("%Y%m")
                / f"full-{stamp.strftime('%Y%m%d-%H%M%S')}.zip")
    await asyncio.to_thread(_write_zip, zip_path, db_dump, files)
    size = zip_path.stat().st_size
    await _log_backup("full", zip_path, size, "success", f"全量备份完成，{len(files)} 个文件")
    log.info("全量备份完成: %s (%d bytes, %d 个文件)", zip_path, size, len(files))
    return {"type": "full", "path": str(zip_path), "size": size, "files": len(files)}


async def do_incremental_backup() -> dict:
    """增量备份：数据库完整 dump + 仅变化的文件。"""
    stamp = datetime.now()
    db_dump = await _dump_db()
    files = _collect_files()
    manifest = _load_manifest()
    changed = _changed_files(files, manifest)
    _save_manifest(manifest)

    week = f"{stamp.isocalendar()[0]}W{stamp.isocalendar()[1]:02d}"
    zip_path = (BACKUP_ROOT / "incr" / week
                / f"incr-{stamp.strftime('%Y%m%d-%H%M%S')}.zip")
    await asyncio.to_thread(_write_zip, zip_path, db_dump, changed)
    size = zip_path.stat().st_size
    await _log_backup("incr", zip_path, size, "success", f"增量备份完成，{len(changed)} 个变化文件")
    log.info("增量备份完成: %s (%d bytes, %d 个变化文件)", zip_path, size, len(changed))
    return {"type": "incr", "path": str(zip_path), "size": size, "files": len(changed)}


# ==================== 清理过期 ====================
def _cleanup() -> int:
    """清理过期备份（full 90 天、incr 28 天）。返回删除数量。"""
    now = time.time()
    rules = [
        (BACKUP_ROOT / "full", FULL_RETENTION_DAYS),
        (BACKUP_ROOT / "incr", INCR_RETENTION_DAYS),
    ]
    removed = 0
    for base, days in rules:
        if not base.exists():
            continue
        cutoff = now - days * 86400
        for p in base.rglob("*.zip"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except Exception as e:  # noqa: BLE001
                log.warning("清理 %s 失败(忽略): %s", p, e)
    if removed:
        log.info("清理过期备份 %d 个", removed)
    return removed


# ==================== 调度 & 手动触发 & 状态 ====================
async def check_and_backup():
    """周期检查（scheduler 调用），内部 1 小时节流。"""
    global _last_check
    now = time.time()
    if now - _last_check < CHECK_THROTTLE:
        return
    _last_check = now
    btype: Optional[str] = None
    try:
        last_full = await _last_backup_time("full")
        last_incr = await _last_backup_time("incr")
        now_t = time.time()
        if last_full is None or (now_t - last_full) >= FULL_INTERVAL_DAYS * 86400:
            btype = "full"
            await do_full_backup()
        elif last_incr is None or (now_t - last_incr) >= INCR_INTERVAL_DAYS * 86400:
            btype = "incr"
            await do_incremental_backup()
    except Exception as e:  # noqa: BLE001
        log.warning("备份失败: %s", e)
        await _log_backup(btype or "full", None, 0, "failed", str(e)[:200])
    finally:
        try:
            _cleanup()
        except Exception as e:  # noqa: BLE001
            log.warning("清理过期备份失败: %s", e)


async def run_backup(btype: str) -> dict:
    """手动触发备份（API 用）。btype: full|incr"""
    btype = (btype or "").strip().lower()
    if btype == "full":
        return await do_full_backup()
    if btype == "incr":
        return await do_incremental_backup()
    raise ValueError("backup_type 必须是 full 或 incr")


async def backup_status() -> dict:
    """备份状态（API 用）：最近记录 + 上次成功时间 + 周期配置。"""
    async with db.pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT backup_type, file_path, file_size, status, message, created_at "
            "FROM backup_log ORDER BY created_at DESC LIMIT 20")
    recent = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        recent.append(d)
    last_full = await _last_backup_time("full")
    last_incr = await _last_backup_time("incr")
    return {
        "root": str(BACKUP_ROOT),
        "last_full": datetime.fromtimestamp(last_full).isoformat() if last_full else None,
        "last_incr": datetime.fromtimestamp(last_incr).isoformat() if last_incr else None,
        "full_interval_days": FULL_INTERVAL_DAYS,
        "incr_interval_days": INCR_INTERVAL_DAYS,
        "full_retention_days": FULL_RETENTION_DAYS,
        "incr_retention_days": INCR_RETENTION_DAYS,
        "recent": recent,
    }
