# -*- coding: utf-8 -*-
"""定时健康检查：越阈值时推送飞书告警 + 落库（带冷却，避免刷屏）"""
import asyncio
import logging
import time

from . import backup, db, feishu, modules
from .config import settings

log = logging.getLogger("scheduler")

_running = False
_task = None
_last_alert: dict[str, float] = {}
_COOLDOWN = 600  # 同一指标 10 分钟内只告警一次


async def _check_once():
    try:
        h = modules.system_health.get_health()
    except Exception as e:
        log.warning("健康检查读取失败: %s", e)
        return
    now = time.time()
    alerts = []

    def _should(metric: str) -> bool:
        t = _last_alert.get(metric, 0)
        if now - t < _COOLDOWN:
            return False
        _last_alert[metric] = now
        return True

    if h["cpu_percent"] >= settings.alert_cpu_threshold and _should("cpu"):
        alerts.append(("critical", "system", f"CPU 使用率 {h['cpu_percent']}% 超过阈值 {settings.alert_cpu_threshold}%"))
    if h["ram_percent"] >= settings.alert_ram_threshold and _should("ram"):
        alerts.append(("critical", "system", f"内存使用率 {h['ram_percent']}% 超过阈值 {settings.alert_ram_threshold}%"))
    for d in h.get("disks", []):
        if d["percent"] >= settings.alert_disk_threshold and _should(f"disk:{d['mount']}"):
            alerts.append(("warning", "system",
                           f"磁盘 {d['mount']} 使用率 {d['percent']}% 超过阈值 {settings.alert_disk_threshold}%"))

    for level, source, msg in alerts:
        try:
            # 去重落库（同 level+source+message 未确认则跳过），随后仅推送飞书（不重复落库，P2-02）
            if not await db.open_alert_exists(level, source, msg):
                await db.save_alert(level, source, msg)
                await feishu.send(level, source, msg)
        except Exception as e:
            log.warning("健康检查告警处理失败: %s", e)


async def _loop():
    while _running:
        if settings.health_check_enabled:
            await _check_once()
        # 自动灾变备份周期检查（backup.check_and_backup 内部 1 小时节流 + 周期判断）
        try:
            await backup.check_and_backup()
        except Exception as e:  # noqa: BLE001
            log.warning("备份周期检查失败(忽略): %s", e)
        try:
            await asyncio.sleep(max(30, settings.health_check_interval))
        except asyncio.CancelledError:
            break


def start():
    global _running, _task
    if _running:
        return
    _running = True
    _task = asyncio.create_task(_loop())
    log.info("健康检查调度已启动")


def stop():
    global _running, _task
    _running = False
    if _task:
        _task.cancel()
        _task = None
