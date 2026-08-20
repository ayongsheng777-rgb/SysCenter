# -*- coding: utf-8 -*-
"""Secrets Vault：敏感字段（API Key 等）入库前加密、读取时解密（P1-02）

设计（契合 EXE 原生化，Windows 原生优先）：
- Windows 平台：优先使用系统 DPAPI（CryptProtectData），密钥与当前登录用户/系统绑定，
  无需自管主密钥，重启后仍可解密。
- 非 Windows（如 CI / Ubuntu、本地开发）：回退 AES-256-GCM，主密钥来自环境变量
  MASTER_KEY，缺失时自动在 DATA_DIR 生成并持久化 vault_key（仅本机可用）。
- 加密结果带前缀标记（dpapi:v1: / enc:v1:），读取时自动识别；旧明文（无前缀）原样返回，
  保证存量数据向后兼容、平滑迁移。

对外只暴露 encrypt_str / decrypt_str。
"""
import base64
import os
import threading

# AES-GCM 需要 cryptography；Windows DPAPI 走 ctypes 无需额外依赖
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_CRYPTO = True
except Exception:  # noqa: BLE001
    _HAS_CRYPTO = False

import logging

log = logging.getLogger("secret_vault")

_DATA_DIR_DEFAULT = os.path.join(os.path.dirname(__file__), "..", "data")
DATA_DIR = os.environ.get("DATA_DIR", _DATA_DIR_DEFAULT)
_MASTER_KEY_ENV = "MASTER_KEY"
_KEY_FILE = os.path.join(DATA_DIR, "vault_key")

_DPAPI_PREFIX = "dpapi:v1:"
_AES_PREFIX = "enc:v1:"

_lock = threading.Lock()
_master_key_cache = None

_IS_WINDOWS = os.name == "nt"


# ==================== Windows DPAPI（ctypes） ====================
def _dpapi_available() -> bool:
    return _IS_WINDOWS


def _dpapi_protect(plain: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes, byref, c_buffer

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    CRYPTPROTECT_UI_FORBIDDEN = 0x40

    data_in = c_buffer(plain, len(plain))
    out = wintypes.DATA_BLOB()
    res = crypt32.CryptProtectData(
        byref(wintypes.DATA_BLOB(ctypes.sizeof(data_in), ctypes.cast(data_in, ctypes.POINTER(wintypes.c_char)))),
        None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, byref(out))
    if not res:
        raise OSError("CryptProtectData 失败")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)  # type: ignore[attr-defined]


def _dpapi_unprotect(blob: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes, byref, c_buffer

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    CRYPTPROTECT_UI_FORBIDDEN = 0x40

    data_in = c_buffer(blob, len(blob))
    out = wintypes.DATA_BLOB()
    res = crypt32.CryptUnprotectData(
        byref(wintypes.DATA_BLOB(ctypes.sizeof(data_in), ctypes.cast(data_in, ctypes.POINTER(wintypes.c_char)))),
        None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, byref(out))
    if not res:
        raise OSError("CryptUnprotectData 失败")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)  # type: ignore[attr-defined]


# ==================== AES-256-GCM 回退 ====================
def _get_master_key() -> bytes:
    """返回 32 字节主密钥；优先 MASTER_KEY 环境变量，否则本机 vault_key 文件。"""
    global _master_key_cache
    if _master_key_cache:
        return _master_key_cache
    with _lock:
        if _master_key_cache:
            return _master_key_cache
        env = os.environ.get(_MASTER_KEY_ENV, "").strip()
        if env:
            key = env.encode("utf-8")
            # 允许十六进制或原始字符串，统一哈希到 32 字节
            if len(key) == 64:
                try:
                    key = bytes.fromhex(env)
                except ValueError:
                    key = key[:32] if len(key) >= 32 else key.ljust(32, b"0")
            else:
                import hashlib
                key = hashlib.sha256(key).digest()
            _master_key_cache = key
            return key
        # 生成本机随机密钥并持久化
        import secrets
        os.makedirs(DATA_DIR, exist_ok=True)
        key = secrets.token_bytes(32)
        with open(_KEY_FILE, "wb") as f:
            f.write(key)
        try:
            os.chmod(_KEY_FILE, 0o600)
        except Exception:  # noqa: BLE001
            pass
        _master_key_cache = key
        log.warning("已生成本机 Secrets Vault 主密钥：%s（请妥善保管，丢失将无法解密已存密钥）", _KEY_FILE)
        return key


def _aes_encrypt(plain: bytes) -> bytes:
    if not _HAS_CRYPTO:
        raise RuntimeError("缺少 cryptography 依赖，无法使用 AES 加密（请 pip install cryptography）")
    import os as _os
    nonce = _os.urandom(12)
    ct = AESGCM(_get_master_key()).encrypt(nonce, plain, None)
    return nonce + ct


def _aes_decrypt(blob: bytes) -> bytes:
    if not _HAS_CRYPTO:
        raise RuntimeError("缺少 cryptography 依赖")
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(_get_master_key()).decrypt(nonce, ct, None)


# ==================== 对外 API ====================
def encrypt_str(plain: str | None) -> str:
    """加密字符串；空值直接返回空串。结果带可识别前缀。"""
    if plain is None:
        return ""
    data = plain.encode("utf-8")
    if _dpapi_available():
        try:
            return _DPAPI_PREFIX + base64.b64encode(_dpapi_protect(data)).decode("ascii")
        except Exception as e:  # noqa: BLE001
            log.warning("DPAPI 加密失败，回退 AES：%s", e)
    return _AES_PREFIX + base64.b64encode(_aes_encrypt(data)).decode("ascii")


def decrypt_str(blob: str | None) -> str:
    """解密字符串；无前缀（旧明文）原样返回；解密失败回退原文并告警。"""
    if not blob:
        return ""
    if blob.startswith(_DPAPI_PREFIX):
        try:
            raw = base64.b64decode(blob[len(_DPAPI_PREFIX):])
            return _dpapi_unprotect(raw).decode("utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("DPAPI 解密失败，返回原文：%s", e)
            return blob
    if blob.startswith(_AES_PREFIX):
        try:
            raw = base64.b64decode(blob[len(_AES_PREFIX):])
            return _aes_decrypt(raw).decode("utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("AES 解密失败，返回原文：%s", e)
            return blob
    # 旧明文（迁移前数据）原样返回
    return blob
