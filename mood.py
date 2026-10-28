# -*- coding: utf-8 -*-
"""情緒判斷與貼圖挑選。

設計原則
    1. **不改動模型輸出格式**（不要求 LLM 吐情緒標籤），避免標記洩漏給使用者、
       或模型不遵守時整段回覆變怪。情緒用文字規則推斷。
    2. 貼圖清單**執行時才抓**（guild stickers），不把 ID 硬編碼在程式裡，
       因為貼圖隨時會被新增／刪除。
    3. 貼圖與情緒的對應**由使用者自行在設定檔定義**（`mood.sticker_map`），
       程式不預設任何貼圖名稱——空白範本不該假設別人伺服器有哪些貼圖。

設定格式（config.json）
    "mood": {
      "sticker_map": {"貼圖名稱": "love", "另一個名稱": "angry"},
      "exclude": ["不想被自動發出的貼圖名稱"]
    }

用法
    from mood import guess_emotion, pick_sticker
    emo = guess_emotion("你怎麼都不回我啦")
    sticker = pick_sticker(stickers, emo, mapping=sticker_map(cfg))
"""
from __future__ import annotations

import re
import unicodedata

# ---- 情緒代號 -------------------------------------------------------------
# love 愛／親密 / shy 害羞 / happy 開心 / tease 吐槽嫌棄 / angry 生氣
# sad 難過 / confused 困惑 / surprise 驚訝 / smug 得意 / speechless 無語
# curious 好奇 / selfmock 自嘲 / sleepy 想睡 / comfort 安慰
EMOTIONS = (
    "love", "shy", "happy", "tease", "angry", "sad",
    "confused", "surprise", "smug", "speechless", "curious", "selfmock",
    "sleepy", "comfort",
)

# 關鍵詞 → 情緒。順序即優先序（越前面越優先）。
RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("love", ("想你", "想我", "愛你", "喜歡你", "抱抱", "抱一下", "貼貼", "黏",
              "陪我", "親一個", "心動", "好甜", "最喜歡")),
    ("shy", ("害羞", "臉紅", "不好意思", "討厭啦", "別說", "哪有", "才沒有")),
    # smug 必須排在 angry 之前：否則「哼哼」（得意）會被 angry 的「哼」吃掉
    ("smug", ("早就說", "看我", "厲害吧", "當然", "哼哼", "我可是", "就說吧")),
    ("angry", ("生氣", "討厭", "過分", "不理我", "不理你", "壞欸", "可惡", "氣死", "哼")),
    ("sad", ("難過", "想哭", "委屈", "傷心", "孤單", "一個人也", "算了")),
    ("happy", ("開心", "太好了", "讚", "爽", "耶", "笑死", "哈哈", "好耶", "棒")),
    ("surprise", ("真的假的", "怎麼可能", "居然", "竟然", "天啊", "哇", "嚇到")),
    ("confused", ("不懂", "什麼意思", "為什麼", "怎麼辦", "搞不清", "疑惑", "？")),
    ("tease", ("才怪", "最好是", "嘴硬", "少來", "齁", "嫌棄", "傻眼", "無言")),
    ("speechless", ("點點點", "無語", "傻眼貓咪", "不知道該說", "嗯嗯")),
    ("curious", ("我看看", "瞧瞧", "是什麼", "讓我看看", "有興趣")),
    ("selfmock", ("我好笨", "我蠢", "丟臉", "笑自己", "小丑", "又失敗")),
    ("sleepy", ("好想睡", "想睡了", "睏", "困了", "打哈欠", "熬夜")),
    ("comfort", ("別難過", "我在這裡", "慢慢來", "陪你", "沒事的", "辛苦了")),
)


def _norm(text: str) -> str:
    """全形轉半形、去掉空白，避免「？」與「?」判斷不一致。"""
    t = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", "", t)


def guess_emotion(text: str) -> str | None:
    """依關鍵詞推斷情緒；判斷不出來回 None（呼叫端就不要發貼圖）。"""
    t = _norm(text)
    if not t:
        return None
    for emo, words in RULES:
        if any(w in t for w in words):
            return emo
    return None


def sticker_map(cfg: dict) -> dict[str, str]:
    """讀取使用者自訂的「貼圖名稱 → 情緒」對應；格式錯誤的項目直接忽略。"""
    raw = ((cfg or {}).get("mood") or {}).get("sticker_map") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(name): str(emo) for name, emo in raw.items()
            if isinstance(name, str) and name and str(emo) in EMOTIONS}


def excluded(cfg: dict) -> set[str]:
    raw = ((cfg or {}).get("mood") or {}).get("exclude") or []
    if not isinstance(raw, list):
        return set()
    return {str(x) for x in raw if isinstance(x, str) and x}


def pick_sticker(stickers: list[dict], emotion: str | None, *,
                 mapping: dict[str, str] | None = None,
                 exclude: set[str] | None = None) -> dict | None:
    """從 guild 貼圖清單挑一個符合情緒的。挑不到回 None。

    stickers: Discord API 的 sticker 物件（需含 name / id）
    mapping: 貼圖名稱 → 情緒；空的話一律不挑（安全預設）
    """
    if not emotion or not mapping:
        return None
    banned = set(exclude or ())
    for s in stickers:
        name = s.get("name") or ""
        if not name or name in banned:
            continue
        if mapping.get(name) == emotion:
            return s
    return None


def trim(text: str, limit: int = 360) -> str:
    """只看回覆開頭：情緒通常在最前面幾句，避免長段落尾巴誤判。"""
    t = (text or "").strip()
    return t[:limit]
