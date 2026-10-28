# -*- coding: utf-8 -*-
"""依情緒搜尋 GIF（目前支援 Giphy）。

設計重點
    1. **只回傳網址**，不下載、不存檔。貼進聊天由 Discord 自己展開。
    2. **每個情緒快取數條**，避免每次都打 API（免費額度有限）。
    3. **任何失敗都回 None**，不拋例外、不影響文字回覆。
    4. 關鍵字由使用者在設定檔定義；可選擇強制附加主題字（例如 cat）。

設定格式（config.json）
    "gif": {
      "enabled": false,
      "provider": "giphy",
      "api_key": "",
      "rating": "pg-13",
      "require_theme": true,
      "theme": "cat",
      "queries": {"love": "cute cuddle", "happy": "happy dance"}
    }

注意
    API key 屬於憑證，只放在本機 config.json（已被 .gitignore 排除），
    不可寫進版本控制、記憶檔或任何交付報告。
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.giphy.com/v1/gifs/search"
CACHE_TTL = 3600          # 同一情緒的快取存活秒數
CACHE_SIZE = 8            # 每個情緒預抓幾條

_cache: dict[str, dict] = {}


def _fetch(api_key: str, query: str, rating: str, limit: int, lang: str) -> list[str]:
    url = (f"{API}?api_key={urllib.parse.quote(api_key)}"
           f"&q={urllib.parse.quote(query)}&limit={limit}"
           f"&rating={urllib.parse.quote(rating)}"
           f"&lang={urllib.parse.quote(lang)}")
    req = urllib.request.Request(url, headers={"User-Agent": "CompanionBot/1.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=12) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for g in data.get("data", []):
        link = (g.get("url") or "").strip()
        # 只收 giphy.com 的頁面網址，避免貼到奇怪的轉址
        if link.startswith("https://giphy.com/") or link.startswith("https://www.giphy.com/"):
            out.append(link)
    return out


def ready(cfg: dict) -> bool:
    gif = (cfg or {}).get("gif") or {}
    return bool(gif.get("enabled") and str(gif.get("api_key") or "").strip())


def pick(cfg: dict, emotion: str | None, *, rng: random.Random | None = None) -> str | None:
    """回傳一條符合情緒的 GIF 網址；沒有／失敗回 None。"""
    if not emotion:
        return None
    gif = (cfg or {}).get("gif") or {}
    if not gif.get("enabled"):
        return None
    key = str(gif.get("api_key") or "").strip()
    query = str((gif.get("queries") or {}).get(emotion) or "").strip()
    if not key or not query:
        return None
    theme = str(gif.get("theme") or "").strip()
    if gif.get("require_theme", True) and theme and theme.lower() not in query.lower():
        query = f"{query} {theme}"
    rating = str(gif.get("rating") or "pg-13")
    lang = str(gif.get("lang") or "zh-TW")

    now = time.time()
    slot = _cache.get(emotion)
    if not slot or now - slot["at"] > CACHE_TTL or not slot["urls"]:
        try:
            urls = _fetch(key, query, rating, CACHE_SIZE, lang)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
            urls = []
        slot = _cache[emotion] = {"at": now, "urls": urls}
    if not slot["urls"]:
        return None
    return (rng or random).choice(slot["urls"])


def clear_cache() -> None:
    _cache.clear()
