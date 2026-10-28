# -*- coding: utf-8 -*-
"""把要說的話變成 Discord 語音訊息（ogg + opus）。

為什麼不是「一次唸完整段」
    真人講話有停頓；整段合成會變成平直的機器朗讀。
    做法：按標點拆句 → 逐句合成 → 句間插入停頓 → 串接。
    再依情緒微調全段的語速／音高，讓同一句話在撒嬌與難過時聽起來不同。

邊界
    - 只用公開的神經語音服務（預設微軟 edge-tts），沒有克隆任何真人聲音。
    - 自己不模仿特定真人；使用者要換音色，應使用本人聲音、已授權配音員
      或商用授權音色庫。
    - 輸出為暫存檔，送出後由呼叫端刪除；不累積在磁碟。

前置需求
    - 套件：`pip install edge-tts`
    - 執行檔：ffmpeg / ffprobe 需在 PATH，或以環境變數 FFMPEG / FFPROBE
      指定完整路徑，或在 config.json 的 `voice.ffmpeg` / `voice.ffprobe` 指定。
      找不到就回 None（不產生語音），不會中斷文字回覆。
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache

DEFAULT_VOICE = "zh-TW-HsiaoYuNeural"

# 情緒 → (語速, 音高, 基礎停頓秒數)
EMO_PARAMS: dict[str, tuple[str, str, float]] = {
    "love": ("+6%", "+14Hz", 0.34),
    "shy": ("-4%", "+10Hz", 0.42),
    "happy": ("+14%", "+24Hz", 0.26),
    "tease": ("+12%", "+20Hz", 0.24),
    "angry": ("+10%", "+18Hz", 0.22),
    "sad": ("-10%", "-6Hz", 0.55),
    "confused": ("+2%", "+10Hz", 0.38),
    "surprise": ("+16%", "+28Hz", 0.28),
    "sleepy": ("-18%", "-8Hz", 0.62),
    "comfort": ("-10%", "+2Hz", 0.46),
    "smug": ("+8%", "+16Hz", 0.28),
    "speechless": ("-6%", "+2Hz", 0.5),
    "curious": ("+6%", "+14Hz", 0.3),
    "selfmock": ("+2%", "+8Hz", 0.34),
}

MAX_CHARS = 120          # 太長就截斷，避免一次生成過久
SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?～~])|(?<=[，,、；;：:])")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@lru_cache(maxsize=4)
def _bin(name: str, override: str = "") -> str | None:
    """找 ffmpeg/ffprobe：設定值 → 環境變數 → PATH。找不到回 None。"""
    if override and pathlib.Path(override).is_file():
        return override
    env = os.environ.get(name.upper(), "").strip()
    if env and pathlib.Path(env).is_file():
        return env
    return shutil.which(name)


def available(cfg: dict) -> bool:
    """語音功能是否可用：需設定啟用，且 ffmpeg/ffprobe 找得到。"""
    vc = (cfg or {}).get("voice") or {}
    if not vc.get("enabled"):
        return False
    return bool(_bin("ffmpeg", str(vc.get("ffmpeg") or ""))
                and _bin("ffprobe", str(vc.get("ffprobe") or "")))


def _sentences(text: str) -> list[str]:
    raw = [s.strip() for s in SENTENCE_SPLIT.split(text or "") if s and s.strip()]
    out: list[str] = []
    for s in raw:
        s = re.sub(r"[\s]+", " ", s).strip(" ，,、；;：:")
        if s:
            out.append(s)
    return out[:12]


def _probe_seconds(path: pathlib.Path, cfg: dict | None = None) -> float:
    probe = _bin("ffprobe", str(((cfg or {}).get("voice") or {}).get("ffprobe") or ""))
    if not probe:
        return 0.0
    r = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                       creationflags=_NO_WINDOW)
    try:
        return float((r.stdout or "0").strip())
    except ValueError:
        return 0.0


async def _one(text: str, voice: str, rate: str, pitch: str, out: pathlib.Path) -> None:
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(out))


async def build_voice(text: str, *, emotion: str | None = None,
                      voice: str = DEFAULT_VOICE) -> pathlib.Path | None:
    """產生 ogg（語音訊息格式）。失敗回 None，由呼叫端安靜退回文字。"""
    ffmpeg = _bin("ffmpeg")
    if not ffmpeg:
        return None
    body = re.sub(r"\s+", " ", (text or "").strip())[:MAX_CHARS]
    if not body:
        return None
    rate, pitch, pause = EMO_PARAMS.get(emotion or "", ("+8%", "+14Hz", 0.3))
    parts = _sentences(body) or [body]

    work = pathlib.Path(tempfile.mkdtemp(prefix="companion_voice_"))
    try:
        clips: list[pathlib.Path] = []
        for i, sent in enumerate(parts, 1):
            clip = work / f"{i:02d}.mp3"
            try:
                await _one(sent, voice, rate, pitch, clip)
            except Exception:
                continue
            if clip.is_file() and clip.stat().st_size > 512:
                clips.append(clip)
                sil = work / f"{i:02d}_sil.mp3"
                subprocess.run([ffmpeg, "-y", "-loglevel", "error",
                                "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                                "-t", f"{pause:.2f}", "-c:a", "libmp3lame",
                                "-b:a", "128k", str(sil)], check=False,
                               creationflags=_NO_WINDOW)
                if sil.is_file():
                    clips.append(sil)
        if not clips:
            return None

        lst = work / "list.txt"
        lst.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
        merged = work / "merged.mp3"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", str(lst), "-c:a", "libmp3lame",
                        "-b:a", "128k", "-ar", "24000", "-ac", "1", str(merged)], check=False,
                       creationflags=_NO_WINDOW)
        if not merged.is_file() or merged.stat().st_size < 1024:
            return None

        ogg = work / "voice.ogg"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(merged),
                        "-ac", "1", "-ar", "48000", "-c:a", "libopus",
                        "-b:a", "64k", "-application", "voip", "-f", "ogg", str(ogg)],
                       check=False, creationflags=_NO_WINDOW)
        if not ogg.is_file() or ogg.stat().st_size < 512:
            return None
        return ogg
    except Exception:
        return None


def speak_sync(text: str, *, emotion: str | None = None,
               voice: str = DEFAULT_VOICE) -> pathlib.Path | None:
    """同步包裝，給非 async 的呼叫端用。"""
    try:
        return asyncio.run(build_voice(text, emotion=emotion, voice=voice))
    except Exception:
        return None


# ---- 發送（Discord REST）--------------------------------------------------
# 為什麼不直接用 channel.send(flags=voice)：Discord 要求語音訊息必須帶
# attachments[0].duration_secs 與 waveform，discord.py 的 File 不支援，
# 直接送會回 400「Voice messages must have supporting metadata」(50161)。
def _waveform(path: pathlib.Path, cfg: dict | None = None,
              points: int = 256) -> tuple[str, float]:
    import array
    import base64

    ffmpeg = _bin("ffmpeg")
    secs = _probe_seconds(path, cfg)
    if not ffmpeg:
        return "", round(secs, 3)
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(path),
                          "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, creationflags=_NO_WINDOW).stdout
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    n = len(samples) or 1
    step = max(1, n // points)
    peaks = bytearray()
    for i in range(points):
        chunk = samples[i * step:(i + 1) * step]
        peaks.append(min(255, int(max((abs(x) for x in chunk), default=0) * 255 / 32768)))
    return base64.b64encode(bytes(peaks)).decode("ascii"), round(secs, 3)


async def send_voice_message(token: str, channel_id: int, ogg: pathlib.Path,
                             cfg: dict | None = None) -> dict:
    """用 REST 送出語音訊息；不建立 Gateway，不會踢掉正在運行的 bot 連線。"""
    import json
    import urllib.error
    import urllib.request
    import uuid

    wf, secs = _waveform(ogg, cfg)
    payload: dict = {"flags": 8192,
                     "attachments": [{"id": "0", "filename": "voice-message.ogg"}]}
    if wf:
        payload["attachments"][0]["waveform"] = wf
    if secs:
        payload["attachments"][0]["duration_secs"] = secs
    boundary = "----CompanionVoice" + uuid.uuid4().hex
    body = bytearray()
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="payload_json"\r\n'
    body += b"Content-Type: application/json\r\n\r\n"
    body += json.dumps(payload, ensure_ascii=False).encode("utf-8")
    body += f"\r\n--{boundary}\r\n".encode()
    body += (b'Content-Disposition: form-data; name="files[0]"; '
             b'filename="voice-message.ogg"\r\n')
    body += b"Content-Type: audio/ogg\r\n\r\n"
    body += ogg.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        method="POST", data=bytes(body),
        headers={"Authorization": f"Bot {token}", "User-Agent": "CompanionBot/1.0",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        return {"ok": True, "id": data.get("id"), "seconds": secs}
    except urllib.error.HTTPError as e:
        # 只回狀態碼與截斷訊息，不回傳完整請求或憑證
        return {"ok": False, "status": e.code,
                "body": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": type(e).__name__}
