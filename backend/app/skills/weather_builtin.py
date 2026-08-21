# -*- coding: utf-8 -*-
"""内置技能：天气查询（代码内嵌注册，不依赖磁盘文件，EXE 打包无歧义）。

Open-Meteo 免费公开数据，无需 API Key。作为 B 路（可执行技能）的示例，
验证「飞书消息 → 触发词匹配 → 技能执行」整条链路。
"""
import re

import httpx

_GEO = "https://geocoding-api.open-meteo.com/v1/search"
_FC = "https://api.open-meteo.com/v1/forecast"
_HTTP = dict(trust_env=False, timeout=httpx.Timeout(15))

_WMO = {
    0: "晴", 1: "大致晴朗", 2: "局部多云", 3: "阴",
    45: "雾", 48: "雾凇", 51: "毛毛雨(弱)", 53: "毛毛雨(中)", 55: "毛毛雨(强)",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨(弱)", 67: "冻雨(强)",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨(弱)", 81: "阵雨(中)", 82: "阵雨(强)", 85: "阵雪(弱)", 86: "阵雪(强)",
    95: "雷阵雨", 96: "雷阵雨伴小冰雹", 99: "雷阵雨伴大冰雹",
}

_STOPWORDS = [
    "天气", "气温", "温度", "多少度", "下雨", "降雨", "下雪", "晴天", "多云", "阴天",
    "预报", "预测", "查询", "查一下", "查查", "看看", "今天", "明天", "后天", "现在",
    "当前", "实时", "怎么样", "怎样", "如何", "帮我", "我想知道", "会", "吗", "呢",
    "啊", "的", "了", "请", "？", "?", "。", ".", "！", "!", "，", ",", " ",
]


class SkillHandler:
    def __init__(self, metadata: dict):
        self.metadata = metadata

    async def execute(self, message: str, context: list = None, user_id: str = None) -> str:
        city = self._extract_city(message) or "北京"
        geo = await self._geocode(city)
        if not geo:
            return f"抱歉，没查到「{city}」这个城市，换个写法试试（如「天气 深圳」）。"
        try:
            async with httpx.AsyncClient(**_HTTP) as c:
                r = await c.get(_FC, params={
                    "latitude": geo["lat"], "longitude": geo["lon"],
                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                    "timezone": "auto", "forecast_days": 4,
                })
                r.raise_for_status()
                data = r.json()
        except Exception as e:  # noqa: BLE001
            return f"天气数据获取失败：{type(e).__name__}"

        cur = data.get("current", {})
        daily = data.get("daily", {})
        lines = [f"🌤 **{geo['name']} 天气**"]
        lines.append(
            f"当前：{_WMO.get(cur.get('weather_code', 0), '未知')}，"
            f"气温 {cur.get('temperature_2m', '?')}°C，"
            f"湿度 {cur.get('relative_humidity_2m', '?')}%，"
            f"风速 {cur.get('wind_speed_10m', '?')} km/h")
        days = daily.get("time", [])[:3]
        codes = daily.get("weather_code", [])[:3]
        highs = daily.get("temperature_2m_max", [])[:3]
        lows = daily.get("temperature_2m_min", [])[:3]
        if days:
            lines.append("未来三天：")
            for d, code, hi, lo in zip(days, codes, highs, lows):
                lines.append(f"· {d}：{_WMO.get(code, '未知')}，{lo}~{hi}°C")
        return "\n".join(lines)

    @staticmethod
    def _extract_city(message: str) -> str:
        text = message or ""
        for kw in _STOPWORDS:
            text = text.replace(kw, "")
        text = re.sub(r"weather", "", text, flags=re.I)
        text = text.strip()
        m = re.search(r"[\u4e00-\u9fa5]{2,4}", text)
        if m:
            return m.group(0)
        return ""

    async def _geocode(self, city: str):
        try:
            async with httpx.AsyncClient(**_HTTP) as c:
                r = await c.get(_GEO, params={"name": city, "count": 1, "language": "zh", "format": "json"})
                r.raise_for_status()
                res = r.json().get("results") or []
        except Exception:  # noqa: BLE001
            return None
        if not res:
            return None
        return {"name": res[0].get("name", city), "lat": res[0]["latitude"], "lon": res[0]["longitude"]}


# 内置技能元数据（供 registry 注册）
BUILTIN_META = {
    "key": "weather",
    "name": "天气查询",
    "description": "天气查询（内置技能，Open-Meteo 免费公开数据，无需 Key）：实时天气 / 未来 3 天预报 / 气温湿度风力。",
    "trigger_keywords": ["天气", "气温", "温度", "多少度", "下雨", "降雨", "下雪", "预报", "weather"],
}
