# -*- coding: utf-8 -*-
"""请求级上下文：在中间件中设置，供审计日志与业务日志读取，避免逐层传参。"""
import contextvars

REQUEST_ID = contextvars.ContextVar("syscenter_request_id", default="")
CLIENT_IP = contextvars.ContextVar("syscenter_client_ip", default="")


def get_request_id() -> str:
    return REQUEST_ID.get()


def get_client_ip() -> str:
    return CLIENT_IP.get()


def set_request_context(request_id: str, client_ip: str):
    """在请求中间件中调用，绑定当前请求的 request_id 与客户端 IP。"""
    REQUEST_ID.set(request_id)
    CLIENT_IP.set(client_ip)
