# -*- coding: utf-8 -*-
"""鉴权后 API 冒烟 + todos 增删改查（经接口，自动清理）。"""
from helpers import req


def test_ping():
    s, d = req("GET", "/api/ping")
    assert s == 200 and d.get("ok") is True


def test_alerts(auth_headers):
    s, d = req("GET", "/api/alerts?limit=50", headers=auth_headers)
    assert s == 200 and isinstance(d, list)


def test_services(auth_headers):
    s, d = req("GET", "/api/system/services", headers=auth_headers)
    assert s == 200


def test_ai_history(auth_headers):
    s, d = req("GET", "/api/ai/history", headers=auth_headers)
    assert s == 200


def test_presets(auth_headers):
    s, d = req("GET", "/api/automation/presets", headers=auth_headers)
    assert s == 200


def test_todos_crud(auth_headers):
    s1, d1 = req("POST", "/api/todos", {"content": "__pytest_tmp__"}, headers=auth_headers)
    assert s1 == 200
    tid = d1.get("id")
    if tid is None and isinstance(d1.get("data"), dict):
        tid = d1["data"].get("id")
    assert tid, f"创建待办未返回 id: {d1}"
    try:
        s2, _ = req("GET", "/api/todos?all=1", headers=auth_headers)
        assert s2 == 200
        s3, _ = req("PUT", f"/api/todos/{tid}/status", {"status": "已完成"}, headers=auth_headers)
        assert s3 == 200
    finally:
        s4, _ = req("DELETE", f"/api/todos/{tid}", headers=auth_headers)
        assert s4 == 200
