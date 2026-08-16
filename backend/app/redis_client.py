# -*- coding: utf-8 -*-
"""Redis 客户端（同步）：承载会话令牌存储，复用项目已有的 redis 依赖。

后端为 Windows 宿主进程，会话写操作为低频（登录/校验/登出），用同步客户端即可。
redis-py 客户端线程安全（命令级从连接池取连接），可安全在多 worker/线程间共享。
Redis 不可达时，调用方需自行回退（见 auth.py 的会话函数）。
"""
import logging

import redis

from .config import settings

log = logging.getLogger("redis")

_client = None


def get_redis_sync() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=3, socket_timeout=3)
    return _client


def clear_sessions():
    """清空所有会话键（换绑 OTP / 强制全部登出时用）。"""
    try:
        r = get_redis_sync()
        for k in r.scan_iter("session:*"):
            r.delete(k)
    except Exception as e:  # noqa: BLE001
        log.warning("clear_sessions 失败(忽略): %s", str(e)[:120])
