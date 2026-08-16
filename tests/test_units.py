# -*- coding: utf-8 -*-
"""纯函数单元测试（无需运行中的服务 / 数据库）。"""
import os
import sys
import time

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app import auth, config          # noqa: E402
from app.modules import net_probe     # noqa: E402
from app import ai_client              # noqa: E402


def test_totp_roundtrip():
    secret = auth.get_secret()
    code = auth._totp_at(secret, int(time.time()))
    assert auth.verify_otp(code)


def test_mask_secret():
    assert config.mask_secret("") == ""
    masked = config.mask_secret("abcdef1234567890")
    assert masked != "abcdef1234567890"
    assert "*" in masked


def test_is_ipv4():
    assert net_probe._is_ipv4("192.168.1.1")
    assert not net_probe._is_ipv4("256.1.1.1")
    assert not net_probe._is_ipv4("not.an.ip")
    assert not net_probe._is_ipv4("")


def test_ping_rejects_metachars():
    # 含空白 / Shell 元字符的主机串必须被拒绝（返回 None，不执行）
    assert net_probe.ping("") is None
    assert net_probe.ping("8.8.8.8; rm -rf /") is None
    assert net_probe.ping("8.8.8.8 && calc") is None


def test_placeholder_keys_defined():
    assert isinstance(ai_client._PLACEHOLDERS, tuple)
    assert "sk-xxx" in ai_client._PLACEHOLDERS
    assert "changeme" in ai_client._PLACEHOLDERS
