# -*- coding: utf-8 -*-
"""電子伴侶的形象照生成 —— 用阿里雲百煉（DashScope）的 Qwen-Image。

★ 角色一致性做法：以**形象錨點**當參考圖（image-to-image），
  這樣每張畫出來的都還是同一個電子伴侶，不會越畫越走鐘。

★ 依 2026-10-13 官方文檔：
  - 端點（新加坡／國際站）：https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
    北京地域為獨立端點與獨立 API Key，**不可混用**；台灣請用新加坡。
  - 認證：`Authorization: Bearer sk-xxxx`
  - 文生圖：content 只放 {"text": ...}
  - 圖生圖／編輯：content 放 1-3 張 {"image": URL 或 base64} ＋ 一個 {"text": 指令}
  - 多圖輸入時，**輸出比例以最後一張圖為準**
"""
from __future__ import annotations

import base64
import json
import math
import random
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from runtime_paths import DATA_ROOT, data_path, anchor_path, reject_links

ROOT = DATA_ROOT
PHOTO_DIR = data_path("photos")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

DEFAULT_ENDPOINT = (
    "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/"
    "multimodal-generation/generation"
)

# 該角色可以自己挑的場景（會隨機抽，避免每次一樣）
SCENES: list[tuple[str, str]] = []


STYLE_TAIL = ""

NEGATIVE = (
    "低解析度、低品質、肢體變形、手指錯亂、過度飽和、蠟像感、"
    "缺乏臉部細節、過度光滑、AI 感明顯、構圖混亂、模糊或扭曲的文字、水印。"
)


# ---------------------------------------------------------------- 工具


def _b64_image(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".") or "png"
    if ext == "jpg":
        ext = "jpeg"
    return f"data:image/{ext};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _cfg(cfg: dict) -> dict:
    return cfg.get("imagegen") or {}


def available(cfg: dict) -> bool:
    ic = _cfg(cfg)
    if ic.get("enabled") is not True:
        return False
    required = ("model", "api_key", "endpoint")
    return (ic.get("provider") == "openai_images"
            and all(isinstance(ic.get(k), str) and ic[k].strip() for k in required))


# ---------------------------------------------------------------- 生成


def build_request(cfg: dict, scene: str, size: str | None = None) -> dict:
    ic = _cfg(cfg)
    content: list[dict] = []

    anchor = ic.get("anchor") or ""
    if anchor and anchor_path(anchor).is_file():
        content.append({"image": _b64_image(anchor_path(anchor))})

    content.append({"text": f"以這張參考圖裡的人物為主角，描繪該人物{scene}。{STYLE_TAIL}"})

    return {
        "model": (ic.get("model") or "").strip(),
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {
            "negative_prompt": NEGATIVE,
            "prompt_extend": True,
            "watermark": False,
            "size": size or ic.get("size", "1024*1024"),
        },
    }


def _extract_image_url(body: dict) -> str | None:
    """從 DashScope 回應裡挖出圖片 URL（或 base64）。"""
    try:
        content = body["output"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    for item in content:
        if isinstance(item, dict) and item.get("image"):
            return item["image"]
    return None


def generate(cfg, scene=None, size=None):
    return None, "", "此模板請使用 generate_prompt"


# ------------------------------------------------- GPT Image（OpenAI Images 相容）
# 經本地 EasyCLIProxyAPI（127.0.0.1:8317）呼叫 gpt-image-2.5 系列。
# 只走 /v1/images/generations 與 /v1/images/edits；不走 chat/completions。

DRAW_TRIGGERS = (
    "畫一張", "畫張", "畫一幅", "畫個", "畫一個", "畫圖", "生圖", "生一張",
    "生成圖片", "生成一張", "給我一張圖", "給我一張", "畫一下",
    "來張", "來一張", "拍張", "拍一張", "傳張", "傳一張", "發張", "發一張",
    "自拍", "照片給我", "看看你",
)
SELF_MARKERS = (
    "畫你", "畫自己", "自畫像", "你的自拍", "你自己的",
    "自拍", "你的照片", "照片給我", "看看你", "你長",
)
MANGA_STYLE = ""
CHARACTER_ALIASES: tuple[str, ...] = ()
# 部分簡體字先折成繁體再比對，避免「画一张」「来张自拍」這種寫法漏判。
_FOLD = str.maketrans({"画": "畫", "张": "張", "图": "圖", "个": "個", "给": "給",
                       "来": "來", "传": "傳", "发": "發", "长": "長", "枫": "楓"})


def wants_draw(text: str) -> bool:
    """是否為明確的生圖指令；閒聊提到「畫」不觸發。"""
    t = (text or "").strip().translate(_FOLD)
    return bool(t) and any(k in t for k in DRAW_TRIGGERS)


def wants_self_portrait(text: str) -> bool:
    t = clean_prompt((text or "").translate(_FOLD))
    # A generic mention of selfies is not proof that the subject is Companion.
    if re.search(r"(?:不要|別|别|不是|不畫|不画)\s*(?:畫|画|拍)?(?:一?[張幅個])?\s*(?:你|妳|自己)", t):
        return False
    if re.search(r"畫你(?:的)?(?:朋友|同學|同事|姐姐|姊姊|妹妹|媽媽|爸爸|寵物|貓|狗)", t):
        return False
    explicit = ("畫你", "畫自己", "自畫像", "你的自拍", "你自己的",
                "你的照片", "看看你", "你長")
    aliases = [clean_prompt(a.translate(_FOLD)) for a in CHARACTER_ALIASES if isinstance(a, str) and a.strip()]
    if any(re.search(r"(?:不要|別|别|不是|不畫|不画)\s*(?:畫|画|拍)?(?:一?[張幅個])?\s*" + re.escape(a), t) for a in aliases):
        return False
    if any(re.search(re.escape(a) + r"(?:的)?(?:朋友|同學|同事|姐姐|姊姊|妹妹|媽媽|爸爸|寵物|貓|狗)", t) for a in aliases):
        return False
    if (any(k in t for k in explicit)
            or re.search(r"(?:畫|拍)(?:一?[張幅個])?\s*(?:你|妳|自己)(?!的?(?:朋友|同學|同事|姐姐|姊姊|妹妹|媽媽|爸爸|寵物|貓|狗))", t)
            or any(a and a in t for a in aliases)):
        return True
    # Bare requests conventionally addressed to her; named other subjects fail closed.
    compact = re.sub(r"\s+", "", t).strip("，。！？!?～~")
    return bool(re.fullmatch(
        r"(?:(?:幫我|帮我|請|请|給我|來張|來一張|拍張|拍一張|傳張|傳一張|發張|發一張|畫一張|畫張))*"
        r"(?:自拍|自拍照|照片)(?:給我|看看|吧|嗎|吗|好嗎|好嗎)?", compact))


def save_own_photo(raw: bytes, *, is_self: bool, scope: str = "private") -> Path | None:
    """只歸檔明確以電子伴侶為主角且已送出的圖片，不存提示詞或聊天內容。"""
    if not is_self:
        return None
    if not re.fullmatch(r"private|guild_[0-9]{1,20}_thread_[0-9]{1,20}", scope):
        raise ValueError("Invalid photo scope")
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise ValueError("Invalid photo size")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = "png"
    elif raw.startswith(b"\xff\xd8"):
        ext = "jpg"
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        ext = "webp"
    else:
        raise ValueError("Invalid photo format")
    now = datetime.now()
    folder = PHOTO_DIR / "self" / scope / now.strftime("%Y-%m-%d")
    reject_links(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"companion_self_{now.strftime('%Y%m%d-%H%M%S-%f')}_{uuid.uuid4().hex[:12]}.{ext}"
    # Exclusive creation prevents accidental overwrite, even for concurrent sends.
    with out.open("xb") as stream:
        stream.write(raw)
    return out


def clean_prompt(text: str) -> str:
    """去掉提及、連結與控制字元；上限 800 字，不截掉後半指令前先整句清理。"""
    t = re.sub(r"<@!?\d+>|<@&\d+>|<#\d+>|@everyone|@here", " ", text or "")
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[`*_~\[\]()#>]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:800]


def persona_anchor(cfg: dict, *, group: bool = True) -> tuple[Path, str]:
    """依場域挑人設錨點與風格後綴。

    頻道（group）人設 persona_group=manga 時用漫畫錨點＋漫畫風格；
    私聊維持寫實錨點、無風格後綴。
    """
    ic = _cfg(cfg)
    if group and (ic.get("persona_group") or "").strip() == "manga":
        style = (ic.get("manga_style") or MANGA_STYLE).strip()
        return anchor_path(ic.get("manga_anchor") or ""), style
    return anchor_path(ic.get("anchor") or ""), ""


class ImageUsage:
    """每人每小時／每日生圖次數；主人不限。檔案損壞視為他人額度用盡。"""
    def __init__(self, path=None, *, per_hour: int = 5, per_day: int = 60):
        self.path = reject_links(Path(path)) if path is not None else data_path("companion_image_usage.json")
        self.per_hour = max(1, int(per_hour))
        self.per_day = max(1, int(per_day))
        self.day = datetime.now().date().isoformat()
        self.users: dict[str, dict] = {}
        self.readable = True
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or set(data) != {"day", "users"}:
                    raise ValueError("Invalid image usage data")
                day = data["day"]
                if not isinstance(day, str) or datetime.strptime(day, "%Y-%m-%d").date().isoformat() != day:
                    raise ValueError("Invalid image usage day")
                users = data["users"]
                if not isinstance(users, dict):
                    raise ValueError("Invalid image usage users")
                for uid, rec in users.items():
                    if not isinstance(uid, str) or not re.fullmatch(r"[1-9][0-9]{0,24}|proactive", uid):
                        raise ValueError("Invalid image usage user")
                    if not isinstance(rec, dict) or set(rec) != {"day", "count", "stamps"}:
                        raise ValueError("Invalid image usage record")
                    if (not isinstance(rec["day"], str)
                            or datetime.strptime(rec["day"], "%Y-%m-%d").date().isoformat() != rec["day"]):
                        raise ValueError("Invalid image usage day")
                    count, stamps = rec["count"], rec["stamps"]
                    if type(count) is not int or count < 0 or not isinstance(stamps, list) or len(stamps) > count:
                        raise ValueError("Invalid image usage count")
                    if any(type(s) not in (int, float) or not math.isfinite(s) or s < 0 for s in stamps):
                        raise ValueError("Invalid image usage timestamps")
                self.day, self.users = day, users
            except Exception:
                # 額度不明時對非主人關閉，避免損壞檔自動放行。
                self.readable = False

    def allow(self, uid, *, is_owner: bool = False) -> bool:
        if is_owner:
            return True
        if not self.readable:
            return False
        now = time.time()
        today = datetime.now().date().isoformat()
        key = str(uid)
        if not re.fullmatch(r"[1-9][0-9]{0,24}|proactive", key):
            return False
        rec = self.users.get(key) or {}
        if rec.get("day") != today:
            rec = {"day": today, "count": 0, "stamps": []}
        stamps = [float(s) for s in (rec.get("stamps") or []) if now - float(s) < 3600]
        if len(stamps) >= self.per_hour or int(rec.get("count") or 0) >= self.per_day:
            rec["stamps"] = stamps
            self.users[key] = rec
            return False
        stamps.append(now)
        rec.update(stamps=stamps, count=int(rec.get("count") or 0) + 1)
        self.users[key] = rec
        return self._save()

    def used_today(self, uid) -> int:
        rec = self.users.get(str(uid)) or {}
        today = datetime.now().date().isoformat()
        return int(rec.get("count") or 0) if rec.get("day") == today else 0

    def _save(self):
        try:
            reject_links(self.path)
            self.path.write_text(
                json.dumps({"day": datetime.now().date().isoformat(), "users": self.users},
                           ensure_ascii=False),
                encoding="utf-8")
            return True
        except Exception:
            self.readable = False
            return False


def photo_time(now=None):
    """Use the runtime computer's local timezone; naive injected times are local."""
    if now is None:
        return datetime.now().astimezone()
    if now.tzinfo is not None:
        return now.astimezone()
    return now


def photo_period(now=None):
    hour = photo_time(now).hour
    if hour < 6:
        return "late_night"
    if hour < 9:
        return "morning"
    if hour < 17:
        return "day"
    if hour < 19:
        return "dusk"
    return "night"


_PERIOD_LIGHT = {
    "late_night": "凌晨深夜；室內以床頭燈、暖色檯燈或柔和螢幕光照明；窗外是暗夜，不出現晨光、午後陽光或明亮白晝天空",
    "morning": "清晨；柔和清晨自然光，避免正午烈日與深夜環境，不假設當地日出時刻或天氣",
    "day": "白天；柔和日間自然光，不使用深夜、夕陽或夜間城市背景",
    "dusk": "傍晚過渡時段；柔和漸暗環境光與室內燈光，避免正午強光，不保證固定日落時間",
    "night": "夜晚；室內暖色燈光或戶外路燈，窗外與天空保持暗夜，不出現晨光、午後陽光或白晝天空",
}
_MORNING_SCENE = re.compile(r"清晨|早晨|早上|上午|晨光|晨曦|早餐|剛睡醒|刚睡醒|起床|日出|\b(?:morning|sunrise|breakfast)\b", re.I)
_DAY_SCENE = re.compile(r"白天|日間|日间|午後|午后|正午|中午|陽光|阳光|日光|晴空|藍天|蓝天|\b(?:daytime|daylight|afternoon|noon|sunlight|sunny)\b", re.I)
_DUSK_SCENE = re.compile(r"傍晚|夕陽|夕阳|日落|黃昏|黄昏|\b(?:sunset|dusk|twilight)\b", re.I)
_NIGHT_SCENE = re.compile(r"深夜|凌晨|半夜|夜晚|夜景|晚上|今晚|今夜|夜裡|夜里|夜色|星空|月光|\b(?:night|midnight|moonlight)\b", re.I)
_TIME_OVERRIDE = re.compile(
    r"清晨|早晨|早上|上午|晨光|晨曦|日出|白天|日間|日间|午後|午后|中午|正午|陽光|阳光|日光|傍晚|夕陽|夕阳|日落|黃昏|黄昏|"
    r"深夜|凌晨|半夜|夜晚|夜景|晚上|今晚|今夜|夜裡|夜里|夜色|星空|月光|昨天|昨日|以前|去年|上次|舊照|旧照|回憶|回忆|"
    r"攝影棚|摄影棚|棚拍|背景.*(?:鎖定|锁定|不變|不变)|"
    r"\b(?:morning|sunrise|daytime|daylight|afternoon|noon|sunlight|sunny|sunset|dusk|twilight|night|midnight|moonlight|yesterday|old photo|studio)\b", re.I)


def scene_matches_time(scene, now=None):
    """Conservatively filter explicit time cues; this is not a weather/sunrise service."""
    text = " ".join(scene).split("拍攝時間約束：", 1)[0]
    period = photo_period(now)
    if period in ("late_night", "night"):
        if _MORNING_SCENE.search(text) or _DAY_SCENE.search(text) or _DUSK_SCENE.search(text):
            return False
        if period == "late_night" and re.search(r"咖啡廳|咖啡厅|咖啡館|咖啡馆|\bcaf[eé]\b", text, re.I):
            return False
    elif period == "morning":
        if (_NIGHT_SCENE.search(text) or _DUSK_SCENE.search(text)
                or re.search(r"午後|午后|正午|中午|\b(?:afternoon|noon)\b", text, re.I)):
            return False
    elif period == "day":
        if _MORNING_SCENE.search(text) or _NIGHT_SCENE.search(text) or _DUSK_SCENE.search(text):
            return False
    elif _MORNING_SCENE.search(text) or _DAY_SCENE.search(text) or _NIGHT_SCENE.search(text):
        return False
    return True


def time_photo_hint(now=None):
    current = photo_time(now)
    return ("拍攝時間約束：依執行電腦當地時間 " + current.strftime("%Y-%m-%d %H:%M %z")
            + "，屬於" + _PERIOD_LIGHT[photo_period(current)]
            + "。照片人物可以明亮清晰，夜景不等於把人拍黑；參考圖只約束人物身份，"
              "不要沿用參考圖的白天背景或原始光線。這是虛構角色生活照，不代表使用者真實位置或活動。")


def explicit_photo_time(prompt):
    # Negative requests such as '不要白天' must not disable the night guard.
    text = re.sub(r"(?:不要|別用|别用|避免|禁止|不准|不可)(?:出現|出现|使用|在|於|于)?(?:白天|日光|陽光|阳光|晨光|夜景|夕陽|夕阳)(?:的?(?:陽光|阳光|日光))?", "", prompt)
    text = re.sub(r"\b(?:no|without|avoid|not)(?:\s+any)?\s+(?:daylight|sunlight|daytime|sunny|morning|night|sunset)\b", "", text, flags=re.I)
    return bool(_TIME_OVERRIDE.search(text))


def pick_scene(rng=None, *, now=None) -> tuple[str, str]:
    """Pick a compatible configured scene without copying another private scene library."""
    choices = [scene for scene in SCENES if scene_matches_time(scene, now)]
    if not choices:
        return ("室內日常", "在簡潔室內放鬆，隨手拍一張自然生活照")
    return (rng or random).choice(choices)


def proactive_scene(rng=None, *, now=None):
    label, description = pick_scene(rng, now=now)
    return label, description + "。" + time_photo_hint(now)


def selfie_for_proactive(cfg: dict, scene: tuple[str, str] | None = None, *, now=None) -> tuple[bytes | None, str, str]:
    """Use one time snapshot for the scene, caption context and image request."""
    current = photo_time(now)
    if scene is None or not scene_matches_time(scene, current):
        scene = proactive_scene(now=current)
    label, descr = scene
    # A caller may retain a scene across a time boundary. Rebuild, never trust
    # the old annotation; the bot normally passes one shared time snapshot.
    descr = descr.split("拍攝時間約束：", 1)[0].rstrip("。 ")
    descr += "。" + time_photo_hint(current)
    png, _model, err = generate_prompt(cfg, f"畫你正在{descr}的生活自拍，自然一點",
                                       use_anchor=True, group=False, now=current)
    return png, label, err


def _post_images(cfg: dict, path: str, payload: dict, timeout: int = 120) -> dict:
    """單一請求、無自動重導；僅限本地回環端點，金鑰不進錯誤訊息。"""
    import urllib.parse
    ic = _cfg(cfg)
    endpoint = (ic.get("endpoint") or "").strip()
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("imagegen.endpoint 只接受本地回環地址")
    base = endpoint.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    url = base + path
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + (ic.get("api_key") or ""),
        },
        method="POST",
    )

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(req, timeout=timeout) as r:
        raw = r.read(16 * 1024 * 1024)
    return json.loads(raw.decode("utf-8"))


def _extract_image(body: dict) -> bytes | None:
    """Images API 回傳 b64_json 或 url；只接受可辨識的點陣圖位元組。"""
    rows = body.get("data") or []
    if not rows or not isinstance(rows[0], dict):
        return None
    item = rows[0]
    raw: bytes | None = None
    if item.get("b64_json"):
        try:
            raw = base64.b64decode(item["b64_json"])
        except Exception:
            return None
    elif item.get("url"):
        url = str(item["url"])
        if url.startswith("data:image/"):
            try:
                raw = base64.b64decode(url.split(",", 1)[1])
            except Exception:
                return None
        else:
            # Remote image downloads require a separately reviewed opt-in adapter.
            return None
    if not raw or len(raw) > 8 * 1024 * 1024:
        return None
    if raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:2] == b"\xff\xd8" or raw[:4] == b"RIFF":
        return raw
    return None


def generate_prompt(cfg: dict, prompt: str, *, use_anchor: bool = False,
                    size: str | None = None, group: bool = True,
                    references: list[bytes] | None = None, now=None) -> tuple[bytes | None, str, str]:
    """依指令生圖；畫該角色本人時帶形象錨點走 /v1/images/edits。

    回傳 (圖片位元組 or None, 使用模型, 錯誤訊息)。錯誤不含金鑰與回應全文。
    """
    ic = _cfg(cfg)
    if not available(cfg):
        return None, "", "生圖未啟用或缺少設定"
    model = ic["model"].strip()
    prompt = clean_prompt(prompt)
    if not prompt:
        return None, "", "整理後沒有可用的繪圖指令"
    size_val = (size or ic.get("size") or "1024x1024").replace("*", "x").strip().lower()
    if size_val not in ("1024x1024", "1536x1024", "1024x1536", "auto"):
        size_val = "1024x1024"
    quality = (ic.get("quality") or "medium").strip().lower()
    if quality not in ("low", "medium", "high", "xhigh", "max", "auto"):
        quality = "medium"
    reference_images = []
    if references is not None:
        if not isinstance(references, list) or not 1 <= len(references) <= 2:
            return None, model, "参考图数量必须为1至2张"
        for raw_ref in references:
            if not isinstance(raw_ref, bytes) or not raw_ref or len(raw_ref) > 5 * 1024 * 1024:
                return None, model, "参考图大小无效"
            if raw_ref.startswith(b"\x89PNG\r\n\x1a\n"):
                mime = "image/png"
            elif raw_ref.startswith(b"\xff\xd8"):
                mime = "image/jpeg"
            elif raw_ref.startswith(b"RIFF") and raw_ref[8:12] == b"WEBP":
                mime = "image/webp"
            else:
                return None, model, "参考图只接受PNG、JPEG或WebP"
            reference_images.append({"image_url": "data:" + mime + ";base64," + base64.b64encode(raw_ref).decode("ascii")})
    if use_anchor:
        try:
            anchor, style_tail = persona_anchor(cfg, group=group)
        except ValueError:
            return None, model, "形象锚点未配置或路径不可用"
        if not anchor.is_file():
            return None, model, "找不到形象錨點，這張改用文字描述會不像該角色"
        full_prompt = (
            "图1为已配置的成年陪伴角色形象锚点，需求中的你或角色称呼均指这个人物。"
            "保持该角色的外貌特征；合照只用图1约束该角色，不要把其他参与者也变成同一外貌。"
            "没有其他人的参考外貌时只作示意，不宣称还原本人。绘图需求：" + prompt)
        if reference_images:
            full_prompt += ("。图2起为本次其他人物或素材参考，保持参与者分别对应，不融合脸、不套同一外貌，"
                            "不从照片推断姓名或身份。")
        if style_tail:
            full_prompt += "。" + style_tail
        # CPA edits 走 JSON：images 為物件陣列，每項恰好一個 image_url 或 file_id。
        payload = {
            "model": model,
            "prompt": full_prompt,
            "n": 1,
            "size": size_val,
            "quality": quality,
            "images": [{"image_url": _b64_image(anchor)}] + reference_images,
        }
        path = "/v1/images/edits"
    else:
        payload = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": size_val,
            "quality": quality,
        }
        path = "/v1/images/generations"
        if reference_images:
            payload["images"] = reference_images
            payload["prompt"] += "。附件仅为本次素材参考，不从照片推断姓名或身份，分别保持参与者外貌。"
            if group and (ic.get("persona_group") or "").strip() == "manga":
                reference_style = (ic.get("manga_style") or MANGA_STYLE).strip()
                if reference_style:
                    payload["prompt"] += "。" + reference_style
            path = "/v1/images/edits"
    # Only implicit private character photos follow the clock. Explicit user
    # lighting/history/studio requests and reference templates keep their intent.
    if use_anchor and not group and not reference_images and not explicit_photo_time(prompt):
        payload["prompt"] += "。" + time_photo_hint(now)
    try:
        body = _post_images(cfg, path, payload)
    except urllib.error.HTTPError as e:
        return None, model, f"生圖服務回應 HTTP {e.code}"
    except Exception as e:
        return None, model, f"生圖請求失敗：{type(e).__name__}"
    raw = _extract_image(body)
    if not raw:
        return None, model, "回應裡沒有可辨識的圖片"
    return raw, model, ""
