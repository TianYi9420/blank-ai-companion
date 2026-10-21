# -*- coding: utf-8 -*-
"""B站公开视频候选元数据；不下载视频、不读取字幕、不调用模型。"""
from __future__ import annotations

import html
import http.client
import ipaddress
import json
import math
import queue
import re
import socket
import ssl
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

HOST = "api.bilibili.com"
PATH = "/x/web-interface/search/type"
TIMEOUT = 8.0
MAX_BYTES = 1024 * 1024
COOLDOWN_SECONDS = 30 * 60
MAX_CHECKED = 20
MAX_RESULTS = 3
MAX_QUERY = 120
_UNKNOWN_LABELS = {"game": "游戏", "versions": "版本", "platforms": "端游/手游", "regions": "服务器", "modes": "PVE/PVP", "builds": "流派", "purposes": "用途"}
_BUILDS = ("攻克", "元素")
_PURPOSES = {"配装": ("配装", "装备搭配", "装备选择"), "输出手法": ("输出手法", "输出循环", "手法", "连招"),
             "技能搭配": ("技能搭配", "技能选择", "技能加点", "加点"), "副本": ("副本", "团本", "打本"),
             "木桩": ("木桩", "打桩")}
USER_AGENT = "BlankCompanion/1.0 (public video metadata search)"
_BVID = re.compile(r"BV[0-9A-Za-z]{10}\Z")
_VERSION = re.compile(r"(?<![\d.])\d+(?:\.\d+){2,}(?![\d.])")
_SCHOOLS = ("潮光", "碎梦", "铁衣", "神相", "血河", "素问", "九灵", "龙吟", "玄机", "鸿音", "荒羽", "沧澜")
_OTHER_GAMES = ("鸣潮", "剑网三", "剑网3", "剑侠情缘", "原神", "崩坏", "天涯明月刀", "魔兽世界", "最终幻想14")
_ALIASES = {"逆水寒": "逆水寒", "潮光": "潮光", "碎夢": "碎梦", "鐵衣": "铁衣", "素問": "素问", "九靈": "九灵", "龍吟": "龙吟", "玄機": "玄机", "鴻音": "鸿音", "滄瀾": "沧澜", "鳴潮": "鸣潮", "劍網": "剑网", "劍俠情緣": "剑侠情缘", "崩壞": "崩坏", "天涯明月刀": "天涯明月刀", "魔獸世界": "魔兽世界", "最終幻想": "最终幻想", "端遊": "端游", "手遊": "手游", "國服": "国服", "國際服": "国际服", "臺服": "台服", "台灣服": "台服", "台湾服": "台服", "陸服": "国服", "陆服": "国服", "配裝": "配装", "裝備": "装备", "選擇": "选择", "輸出": "输出", "循環": "循环", "連招": "连招", "點": "点", "團本": "团本", "木樁": "木桩", "打樁": "打桩"}
_lock = threading.Lock()
_cooldown_until = 0.0


class SearchUnavailable(Exception):
    """不含响应正文、URL、凭证或上游异常的归一化错误。"""


class SearchBlocked(SearchUnavailable):
    """上游风控或限流；调用者必须熔断而非重试。"""


def _normalize(text: str) -> str:
    for old, new in _ALIASES.items():
        text = text.replace(old, new)
    return text.casefold()


def _plain(value, limit: int = 200) -> str:
    if not isinstance(value, str):
        return ""
    value = html.unescape(value[:4000])
    value = re.sub(r"<[^>]*>", " ", value)
    value = re.sub(r"https?://\S+|www\.\S+", " ", value, flags=re.I)
    value = "".join(" " if unicodedata.category(char).startswith("C") else char for char in value)
    value = re.sub(r"[`*_{}\[\]()<>#|~!\\]", " ", value).replace("@", "＠")
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _query(query) -> str | None:
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= MAX_QUERY:
        return None
    if re.search(r"https?://|api[_ -]?(?:key|token)|bearer\s|password|passwd|secret|sk-[a-z0-9]{8,}|密[钥鑰码碼]|令牌|私[聊信]|聊天[记录記錄]|身[份分][证證]|信用卡|cookie|sessdata|bili_jct|[验驗][证證][码碼]|verification[ _-]?code", query, re.I):
        return None
    if any(unicodedata.category(char).startswith("C") and char not in "\t\n\r" for char in query):
        return None
    query = re.sub(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|<[@#][!&]?\d+>|(?<![\d.])\+?\d[\d -]{8,}\d(?![\d.])", " ", query, flags=re.I)
    query = re.sub(r"\s+", " ", query).strip()
    return query if len(query) >= 2 else None


def constraints(query: str) -> dict:
    """只提取明确条件；门派仅作游戏路由，不代表已核验游戏。"""
    text = _normalize(query) if isinstance(query, str) else ""
    schools = [school for school in _SCHOOLS if school in text]
    games = [game for game in _OTHER_GAMES if game in text]
    if "逆水寒" in text:
        games.insert(0, "逆水寒")
    if not games and schools:
        game, inferred = "逆水寒", True
    else:
        game, inferred = (games[0] if len(games) == 1 else None), False
    return {"game": game, "game_inferred": inferred, "schools": schools,
            "versions": list(dict.fromkeys(_VERSION.findall(text))),
            "modes": [mode for mode in ("pve", "pvp") if re.search(r"(?<![a-z])" + mode + r"(?![a-z])", text)],
            "platforms": [name for name in ("端游", "手游") if name in text],
            "regions": [name for name in ("国服", "国际服", "台服", "日服", "韩服", "美服", "欧服") if name in text],
            "builds": [name for name in _BUILDS if name in text],
            "purposes": [name for name, aliases in _PURPOSES.items() if any(alias in text for alias in aliases)]}


def _play(value) -> tuple[int | None, str | None]:
    if isinstance(value, bool):
        return None, None
    if isinstance(value, int):
        return (value, str(value)) if 0 <= value <= 10**15 else (None, None)
    if not isinstance(value, str) or len(value) > 32:
        return None, None
    normalized = value.strip().replace("萬", "万").replace("億", "亿")
    match = re.fullmatch(r"(\d+)(?:\.(\d+))?([万亿]?)", normalized)
    if not match or (match.group(2) and not match.group(3)):
        return None, None
    try:
        number = Decimal(match.group(1) + ("." + match.group(2) if match.group(2) else ""))
        number *= {"": 1, "万": 10000, "亿": 100000000}[match.group(3)]
        if not number.is_finite() or not 0 <= number <= 10**15:
            return None, None
        return int(number), value.strip()
    except (InvalidOperation, OverflowError):
        return None, None


def _published(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value) or value < 0:
            return None
        return datetime.fromtimestamp(value, timezone(timedelta(hours=8))).date().isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _duration(value) -> str | None:
    if not isinstance(value, str) or len(value) > 24:
        return None
    value = value.strip()
    return value if re.fullmatch(r"(?:\d+:[0-5]\d:[0-5]\d|\d+:[0-5]\d)", value) else None


def rank_candidates(raw_rows: list, query: str) -> list[dict]:
    """首20条内先按标题适用性分层，同层按公开播放量排序，最多3条。"""
    if not isinstance(raw_rows, list):
        return []
    wanted = constraints(query)
    ranked, seen = [], set()
    for row in raw_rows[:MAX_CHECKED]:
        if not isinstance(row, dict) or row.get("type") != "video":
            continue
        bvid = row.get("bvid")
        if not isinstance(bvid, str) or not _BVID.fullmatch(bvid) or bvid in seen:
            continue
        if not isinstance(row.get("title"), str) or len(row["title"]) > 4000:
            continue
        title = _plain(row["title"], 4000)
        if not title:
            continue
        text = _normalize(title)
        actual = constraints(text)
        if wanted["schools"] and not all(school in text for school in wanted["schools"]):
            continue
        named_games = {game for game in ("逆水寒",) + _OTHER_GAMES if game in text}
        if wanted["game"] and named_games - {wanted["game"]}:
            continue
        unknown = []
        if wanted["game"] and wanted["game"] not in named_games:
            unknown.append("game")
        wrong = False
        for key in ("versions", "platforms", "regions"):
            if wanted[key]:
                if actual[key] and not set(actual[key]).issubset(wanted[key]):
                    wrong = True
                    break
                if not set(wanted[key]).issubset(actual[key]):
                    unknown.append(key)
        if wrong:
            continue
        mixed = len(actual["modes"]) > 1
        if wanted["modes"]:
            if actual["modes"] and not set(actual["modes"]) & set(wanted["modes"]):
                continue
            if not set(wanted["modes"]).issubset(actual["modes"]):
                unknown.append("modes")
        if wanted["builds"]:
            if actual["builds"] and not set(actual["builds"]) & set(wanted["builds"]):
                continue
            if not set(wanted["builds"]).issubset(actual["builds"]):
                unknown.append("builds")
        missing_purposes = len(set(wanted["purposes"]) - set(actual["purposes"]))
        if missing_purposes:
            unknown.append("purposes")
        # 无明确游戏/门派/版本时仍要求标题与检索词相关，不以播放量顶替相关性。
        query_terms = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-z][a-z0-9]{2,}", _normalize(query)))
        stop = {"搜索", "搜一下", "查一下", "找一下", "攻略", "视频", "影片", "最新", "search", "video", "guide"}
        terms = query_terms - stop
        if not any((wanted["game"], wanted["schools"], wanted["versions"])) and terms and not any(term in text for term in terms):
            continue
        play, play_source = _play(row.get("play"))
        candidate = {"bvid": bvid, "url": "https://www.bilibili.com/video/" + bvid + "/",
                     "title": title[:200], "author": _plain(row.get("author"), 100) or None,
                     "play_count": play, "play_display": ("约" + play_source + "次播放（B站来源值）") if play is not None else None,
                     "play_source": play_source, "published_date": _published(row.get("pubdate")),
                     "duration": _duration(row.get("duration")), "applicability": actual,
                     "unknown_conditions": [_UNKNOWN_LABELS[key] for key in unknown], "mixed_mode": mixed, "game_verified": False,
                     "metadata_only": True}
        tier = ("versions" in unknown, len(unknown), bool(wanted["modes"] and mixed),
                bool(wanted["builds"] and set(actual["builds"]) - set(wanted["builds"])),
                missing_purposes, len(set(actual["schools"]) - set(wanted["schools"])))
        ranked.append((tier, play is None, -(play or 0), candidate))
        seen.add(bvid)
    ranked.sort(key=lambda item: item[:3])
    return [item[3] for item in ranked[:MAX_RESULTS]]


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SearchUnavailable("deadline")
    return remaining


def _fetch(query: str) -> bytes:
    """唯一网络出口：固定HTTPS主机与路径、公网DNS后固定IP、无代理/跳转/重试。"""
    deadline = time.monotonic() + TIMEOUT
    resolved = queue.Queue(maxsize=1)

    def resolve():
        try:
            resolved.put(socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM))
        except Exception:
            resolved.put(None)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses = resolved.get(timeout=_remaining(deadline))
    except queue.Empty:
        raise SearchUnavailable("deadline") from None
    if not addresses:
        raise SearchUnavailable("dns")
    try:
        for _, _, _, _, sockaddr in addresses:
            address = ipaddress.ip_address(sockaddr[0])
            if not address.is_global or address.is_multicast or address.is_reserved or (address.version == 6 and address.ipv4_mapped is not None):
                raise SearchUnavailable("dns")
        family, socktype, proto, _, sockaddr = addresses[0]
        remaining = _remaining(deadline)
        raw = socket.socket(family, socktype, proto)
    except (ValueError, TypeError, IndexError, OSError):
        raise SearchUnavailable("dns") from None
    connection, guard, watchdog = None, None, None
    expired = threading.Event()

    def abort():
        expired.set()
        if guard is not None:
            try:
                guard.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if connection is not None:
            connection.close()

    try:
        connection = http.client.HTTPSConnection(HOST, timeout=remaining, context=ssl.create_default_context())
        # 看门狗关闭socket后禁止HTTPConnection隐式重连，避免重新DNS解析或第二次请求。
        connection.auto_open = 0
        raw.settimeout(_remaining(deadline))
        raw.connect(sockaddr)
        guard = raw.dup()
        watchdog = threading.Timer(_remaining(deadline), abort)
        watchdog.daemon = True
        watchdog.start()
        raw.settimeout(_remaining(deadline))
        tls = connection._context.wrap_socket(raw, server_hostname=HOST)
        connection.sock = tls
        tls.settimeout(_remaining(deadline))
        connection.request("GET", PATH + "?search_type=video&keyword=" + quote(query, safe="") + "&order=totalrank&page=1",
                           headers={"Host": HOST, "Accept": "application/json", "Accept-Encoding": "identity",
                                    "Connection": "close", "User-Agent": USER_AGENT})
        response = connection.getresponse()
        _remaining(deadline)
        if response.status in (412, 429):
            raise SearchBlocked("blocked")
        if response.status != 200:
            raise SearchUnavailable("status")
        encoding = response.getheader("Content-Encoding", "identity")
        if not isinstance(encoding, str) or encoding.strip().lower() not in ("", "identity"):
            raise SearchUnavailable("encoding")
        length = response.getheader("Content-Length")
        if length is not None and (not re.fullmatch(r"\d{1,10}", length) or int(length) > MAX_BYTES):
            raise SearchUnavailable("size")
        chunks, size = [], 0
        while True:
            _remaining(deadline)
            chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
            _remaining(deadline)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise SearchUnavailable("size")
            chunks.append(chunk)
        if expired.is_set():
            raise SearchUnavailable("deadline")
        return b"".join(chunks)
    except SearchUnavailable:
        raise
    except Exception:
        raise SearchUnavailable("transport") from None
    finally:
        if watchdog is not None:
            watchdog.cancel()
            watchdog.join()
        if guard is not None:
            guard.close()
        if connection is not None:
            connection.close()
        raw.close()


def _decode(payload: bytes) -> list:
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
        raise SearchUnavailable("payload")
    try:
        body = json.loads(payload.decode("utf-8-sig"), parse_constant=lambda _: None)
    except (ValueError, UnicodeError, RecursionError):
        raise SearchUnavailable("payload") from None
    if not isinstance(body, dict) or type(body.get("code")) is not int:
        raise SearchUnavailable("payload")
    # 只识别公开常见的限流/风控/验证码业务码；不展示上游信息或尝试解决验证码。
    message = body.get("message")
    if body["code"] in (-352, -412, -429, -509, -799, 412, 429) or (
            body["code"] != 0 and isinstance(message, str) and re.search(r"验证码|驗證碼|captcha|risk|风控|風控|请求过于频繁|請求過於頻繁", message, re.I)):
        raise SearchBlocked("blocked")
    if body["code"] != 0 or not isinstance(body.get("data"), dict):
        raise SearchUnavailable("payload")
    rows = body["data"].get("result")
    if not isinstance(rows, list):
        raise SearchUnavailable("payload")
    return rows[:MAX_CHECKED]


def search(query: str) -> dict:
    """单次受限检索；风控后进程内至少30分钟无网络请求，无网络后备来源。"""
    global _cooldown_until
    query = _query(query)
    result = {"status": "unavailable", "candidates": [], "search_url": "", "checked_count": 0}
    if query is None:
        return result
    result["search_url"] = "https://search.bilibili.com/all?keyword=" + quote(query, safe="")
    with _lock:
        if time.monotonic() < _cooldown_until:
            result["status"] = "cooldown"
            return result
        try:
            rows = _decode(_fetch(query))
            result["checked_count"] = len(rows)
            result["candidates"] = rank_candidates(rows, query)
            result["status"] = "ok"
        except SearchBlocked:
            _cooldown_until = time.monotonic() + COOLDOWN_SECONDS
            result["status"] = "blocked"
        except SearchUnavailable:
            pass
    return result
