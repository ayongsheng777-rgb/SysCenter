# -*- coding: utf-8 -*-
"""本地二维码生成（纯 Python，segno）——不外发任何密钥/内容到在线服务。

统一产出 data:image/png;base64 的 data URL，前端直接 <img :src> 渲染。
"""
import base64
import io

import segno


def qr_data_url(text: str, scale: int = 6, border: int = 2) -> str:
    """把任意文本（otpauth URI 或飞书授权 URL）渲染成 PNG data URL。"""
    if not text:
        return ""
    buf = io.BytesIO()
    # error='m' 中等纠错；深色前景 + 白底，保证各验证器可读
    segno.make(text, error="m").save(
        buf, kind="png", scale=scale, border=border,
        dark="#000000", light="#ffffff",
    )
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"
