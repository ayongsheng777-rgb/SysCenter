# -*- coding: utf-8 -*-
"""OTP(TOTP) 登录鉴权 —— 纯标准库实现，无额外依赖

方案参考本机 dragons-breath 项目：
- 动态码：RFC 6238 TOTP（与 Google Authenticator / 1Password / Authy 兼容）
- 会话令牌：HMAC-SHA256 签名的无状态令牌，签发后放入内存有效集（重启即失效）
- 密钥来源：优先读环境变量 OTP_SECRET；否则自动生成并落盘到 ./data/otp_secret
- 绑定（enrollment）：首次登录成功后写 ./data/otp_enrolled，此后不再暴露密钥
- 重置：删除 ./data/otp_secret 与 ./data/otp_enrolled 并重启即可重新绑定
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from datetime import datetime, timezone
from urllib.parse import quote

# 默认落盘到后端 data 目录（本机运行）
_DATA_DIR_DEFAULT = os.path.join(os.path.dirname(__file__), "..", "data")
DATA_DIR = os.environ.get("DATA_DIR", _DATA_DIR_DEFAULT)
OTP_ISSUER = os.environ.get("OTP_ISSUER", "SysCenter")
OTP_ACCOUNT = os.environ.get("OTP_ACCOUNT", "admin@syscenter")
SESSION_TTL = int(os.environ.get("SESSION_TTL", "43200"))  # 默认 12 小时

_SECRET_FILE = os.path.join(DATA_DIR, "otp_secret")
_ENROLLED_FILE = os.path.join(DATA_DIR, "otp_enrolled")
_SESSION_FILE = os.path.join(DATA_DIR, "session_secret")

VALID_TOKENS = set()          # 内存中的有效会话（重启即清空）
_session_secret = None


# ==================== 底层 IO ====================
def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def _write(path: str, text: str):
    _ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ==================== TOTP 密钥 ====================
def get_secret() -> str:
    env = os.environ.get("OTP_SECRET")
    if env and env.strip():
        return env.strip().upper()
    s = _read(_SECRET_FILE)
    if s:
        return s
    raw = secrets.token_bytes(20)
    s = base64.b32encode(raw).decode("ascii").rstrip("=")
    _write(_SECRET_FILE, s)
    return s


def is_setup_open() -> bool:
    if os.environ.get("OTP_SECRET"):
        return False
    if _read(_ENROLLED_FILE):
        return False
    return True


def mark_enrolled():
    _write(_ENROLLED_FILE, datetime.now(timezone.utc).isoformat())


def _encode_label(text: str) -> str:
    return quote(text, safe="")


def otpauth_uri() -> str:
    secret = get_secret()
    label = _encode_label(OTP_ISSUER)
    issuer = _encode_label(OTP_ISSUER)
    return (f"otpauth://totp/{label}?secret={secret}"
            f"&issuer={issuer}&algorithm=SHA1&digits=6&period=30")


# ==================== HOTP / TOTP ====================
def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % 10 ** 6).zfill(6)


def _totp_at(secret: str, t: int, step: int = 30) -> str:
    return _hotp(secret, t // step)


def verify_otp(code: str, window: int = 1) -> bool:
    """校验动态码，允许 ±window 个时间步长（默认 ±30s）以容忍时钟漂移。"""
    code = (code or "").strip()
    if len(code) != 6 or not code.isdigit():
        return False
    secret = get_secret()
    now = int(time.time())
    for w in range(-window, window + 1):
        if _totp_at(secret, now + w * 30) == code:
            return True
    return False


# ==================== 会话令牌（HMAC 签名，无依赖） ====================
def _session_secret_get() -> str:
    global _session_secret
    if _session_secret:
        return _session_secret
    env = os.environ.get("SESSION_SECRET")
    if env and env.strip():
        _session_secret = env.strip()
    else:
        s = _read(_SESSION_FILE)
        if not s:
            s = secrets.token_hex(32)
            _write(_SESSION_FILE, s)
        _session_secret = s
    return _session_secret


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def generate_token() -> dict:
    issued = int(time.time())
    expiry = issued + SESSION_TTL
    body = _b64u(f"{issued}.{expiry}".encode("ascii"))
    sig = hmac.new(_session_secret_get().encode(), body.encode(), hashlib.sha256).hexdigest()
    token = f"{body}.{sig}"
    VALID_TOKENS.add(token)
    return {"token": token, "issued": issued, "expires": expiry, "ttl": SESSION_TTL}


def verify_token(token: str | None) -> bool:
    if not token or token not in VALID_TOKENS:
        return False
    try:
        body, sig = token.rsplit(".", 1)
        issued, expiry = _b64d(body).decode("ascii").split(".")
        int(issued); expiry = int(expiry)
    except Exception:
        return False
    exp_sig = hmac.new(_session_secret_get().encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(exp_sig, sig):
        return False
    if int(time.time()) > expiry:
        VALID_TOKENS.discard(token)
        return False
    return True


def revoke_token(token: str | None):
    if token:
        VALID_TOKENS.discard(token)


# ==================== OTP 重置（更换验证器） ====================
def reset_otp() -> dict | None:
    if os.environ.get("OTP_SECRET"):
        return None
    for f in (_SECRET_FILE, _ENROLLED_FILE):
        try:
            if os.path.exists(f):
                os.remove(f)
        except OSError:
            pass
    VALID_TOKENS.clear()
    raw = secrets.token_bytes(20)
    new_secret = base64.b32encode(raw).decode("ascii").rstrip("=")
    _write(_SECRET_FILE, new_secret)
    label = _encode_label(f"{OTP_ISSUER}:{OTP_ACCOUNT}")
    issuer = _encode_label(OTP_ISSUER)
    uri = (f"otpauth://totp/{label}?secret={new_secret}"
           f"&issuer={issuer}&algorithm=SHA1&digits=6&period=30")
    from .qrutil import qr_data_url
    return {"secret": new_secret, "otpauth_uri": uri, "qr": qr_data_url(uri)}
