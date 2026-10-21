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
import random
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PHOTO_DIR = ROOT / "photos"
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
    if not ic.get("enabled"):
        return False
    provider = (ic.get("provider") or "qwen").strip()
    if provider == "openai_images":
        return bool((ic.get("api_key") or "").strip() and (ic.get("endpoint") or "").strip())
    return bool((ic.get("api_key") or "").strip())


# ---------------------------------------------------------------- 生成


def build_request(cfg: dict, scene: str, size: str | None = None) -> dict:
    ic = _cfg(cfg)
    content: list[dict] = []

    anchor = ic.get("anchor") or ""
    if anchor and Path(anchor).exists():
        content.append({"image": _b64_image(Path(anchor))})

    content.append({"text": f"以這張參考圖裡的人物為主角，描繪該人物{scene}。{STYLE_TAIL}"})

    return {
        "model": ic.get("model", "qwen-image-2.0-pro"),
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
    if re.search(r"(?:不要|別|别|不是|不畫|不画)\s*(?:畫|画|拍)?\s*(?:你|自己)", t):
        return False
    if re.search(r"畫你(?:的)?(?:朋友|同學|同事|姐姐|姊姊|妹妹|媽媽|爸爸|寵物|貓|狗)", t):
        return False
    explicit = ("畫你", "畫自己", "自畫像", "你的自拍", "你自己的",
                "你的照片", "看看你", "你長")
    if any(k in t for k in explicit):
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
        return Path(ic.get("manga_anchor") or ""), style
    return Path(ic.get("anchor") or ""), ""


class ImageUsage:
    """每人每小時／每日生圖次數；主人不限。檔案損壞視為他人額度用盡。"""
    def __init__(self, path=None, *, per_hour: int = 5, per_day: int = 60):
        self.path = path or (ROOT / "companion_image_usage.json")
        self.per_hour = max(1, int(per_hour))
        self.per_day = max(1, int(per_day))
        self.day = datetime.now().date().isoformat()
        self.users: dict[str, dict] = {}
        self.readable = True
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.day = str(data.get("day") or self.day)
                self.users = {str(k): v for k, v in (data.get("users") or {}).items()
                              if isinstance(v, dict)}
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
        self._save()
        return True

    def used_today(self, uid) -> int:
        rec = self.users.get(str(uid)) or {}
        today = datetime.now().date().isoformat()
        return int(rec.get("count") or 0) if rec.get("day") == today else 0

    def _save(self):
        try:
            self.path.write_text(
                json.dumps({"day": datetime.now().date().isoformat(), "users": self.users},
                           ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass


def pick_scene(rng=None) -> tuple[str, str]:
    """從場景庫挑一個「該角色正在做什麼」，回傳 (標籤, 描述)。"""
    return (rng or random).choice(SCENES)


def selfie_for_proactive(cfg: dict, scene: tuple[str, str] | None = None) -> tuple[bytes | None, str, str]:
    """主動私聊用的生活自拍；私聊一律真人版錨點（group=False）。"""
    label, descr = scene or pick_scene()
    png, _model, err = generate_prompt(cfg, f"畫你正在{descr}的生活自拍，自然一點",
                                       use_anchor=True, group=False)
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
                    size: str | None = None, group: bool = True) -> tuple[bytes | None, str, str]:
    """依指令生圖；畫該角色本人時帶形象錨點走 /v1/images/edits。

    回傳 (圖片位元組 or None, 使用模型, 錯誤訊息)。錯誤不含金鑰與回應全文。
    """
    ic = _cfg(cfg)
    if not available(cfg):
        return None, "", "生圖未啟用或缺少設定"
    model = (ic.get("model") or "gpt-image-2.5-flare").strip()
    prompt = clean_prompt(prompt)
    if not prompt:
        return None, "", "整理後沒有可用的繪圖指令"
    size_val = (size or ic.get("size") or "1024x1024").replace("*", "x").strip().lower()
    if size_val not in ("1024x1024", "1536x1024", "1024x1536", "auto"):
        size_val = "1024x1024"
    quality = (ic.get("quality") or "medium").strip().lower()
    if quality not in ("low", "medium", "high", "xhigh", "max", "auto"):
        quality = "medium"
    if use_anchor:
        anchor, style_tail = persona_anchor(cfg, group=group)
        if not anchor.is_file():
            return None, model, "找不到形象錨點，這張改用文字描述會不像該角色"
        full_prompt = "以這張參考圖裡的人物為主角，" + prompt
        if style_tail:
            full_prompt += "。" + style_tail
        # CPA edits 走 JSON：images 為物件陣列，每項恰好一個 image_url 或 file_id。
        payload = {
            "model": model,
            "prompt": full_prompt,
            "n": 1,
            "size": size_val,
            "quality": quality,
            "images": [{"image_url": _b64_image(anchor)}],
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
