"""抖音分享連結 -> 暫存下載 -> 送出後立即刪除，不保留。

下載鏈（本機既有工具，跨專案共用）：
    ~/.workbuddy/tools/douyin-fetch/fetch_standalone.py
        短連結 -> aweme_detail JSON（a_bogus 簽名 + wreq TLS 指紋 + 瀏覽器 cookie）
    再自行用 Range 續傳抓 play_addr，並**比對 data_size**後才算成功。
    失敗時退回 yt-dlp（無 cookie，較易被風控）。

約束：
1. 只接受抖音自家域名（douyin.com / iesdouyin.com）。
2. 只寫系統暫存目錄；呼叫端必須在 finally 呼叫 cleanup()，本模組不留副本。
3. 下載大小與 play_addr.data_size 不符一律視為失敗（dl.py 的靜默截斷坑）。
4. 錯誤訊息不含完整連結，避免私人分享連結被寫進日誌。
"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

try:
    import wreq  # noqa: F401  Chrome TLS 指紋；缺少時只能退回 urllib
    HAS_WREQ = True
except Exception:
    HAS_WREQ = False

MAX_BYTES = 24 * 1024 * 1024   # Discord 一般上限 25MB，留 1MB 餘裕
MIN_BYTES = 100 * 1024
FETCH_TIMEOUT = 120
CONNECT_TIMEOUT = 8
DOWNLOAD_TIMEOUT = 20
DOWNLOAD_ATTEMPTS = 2
MAX_HOSTS = 3          # 每個 CDN host 只試一次；同一 host 的 50 多個候選沒有意義
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")
TOOL_DIR = Path.home() / ".workbuddy" / "tools" / "douyin-fetch"
ALLOWED_HOSTS = ("douyin.com", "iesdouyin.com")
VIDEO_EXTS = (".mp4", ".m4v", ".mov", ".webm")
_LINK_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_TRAILING = ").,，。；;!！?？、）】》\"'"


class DouyinError(RuntimeError):
    """使用者可讀的失敗原因（已去識別化）。"""


def _host_allowed(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    if parts.username or parts.password:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return False
    return any(host == base or host.endswith("." + base) for base in ALLOWED_HOSTS)


def find_links(text) -> list:
    """只回傳抖音連結，去重且保持原順序。"""
    seen, out = set(), []
    for raw in _LINK_RE.findall(str(text or "")):
        url = raw.rstrip(_TRAILING)
        if not url or url in seen or not _host_allowed(url):
            continue
        seen.add(url)
        out.append(url)
    return out


def first_link(text):
    links = find_links(text)
    return links[0] if links else None


def _safe_title(value) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    text = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()[:60]


def human_size(size) -> str:
    value = float(size or 0)
    if value >= 1048576:
        return f"{value / 1048576:.1f}MB"
    if value >= 1024:
        return f"{value / 1024:.0f}KB"
    return f"{int(value)}B"


# ---------- 第一段：拿 aweme_detail ----------

def _run_fetch(url: str, folder: Path) -> Path:
    script = TOOL_DIR / "fetch_standalone.py"
    if not script.exists():
        raise DouyinError("找不到本機的抖音抓取工具")
    cookies = TOOL_DIR / "cookies_raw.txt"
    cmd = [sys.executable, str(script), url, "--out", str(folder)]
    if cookies.exists():
        cmd += ["--cookies", str(cookies)]
    try:
        done = subprocess.run(cmd, cwd=str(TOOL_DIR), capture_output=True,
                              timeout=FETCH_TIMEOUT, text=True,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise DouyinError("抖音那邊回應太慢，逾時了") from None
    except OSError as error:
        raise DouyinError("抖音抓取工具啟動失敗") from error
    files = sorted(glob.glob(str(folder / "aweme_*.json")))
    if files:
        return Path(files[0])
    detail = (done.stdout or "") + (done.stderr or "")
    if "UIFID" in detail:
        raise DouyinError("抖音風控擋住了（cookie 過期），要重抓瀏覽器 cookie")
    if done.returncode != 0:
        raise DouyinError("抖音沒給出這支影片的資料")
    raise DouyinError("抖音回傳的內容不含影片資料")


def _load_detail(json_path: Path) -> dict:
    try:
        body = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        raise DouyinError("抖音回傳的資料解析失敗") from None
    detail = body.get("aweme_detail") or {}
    if not detail:
        raise DouyinError("抖音沒有回傳這支影片的詳情")
    return detail


def _video_candidates(detail: dict) -> list:
    video = detail.get("video") or {}
    urls = []
    for key in ("play_addr_h264", "play_addr", "download_addr"):
        block = video.get(key)
        if isinstance(block, dict):
            urls += list(block.get("url_list") or [])
    for bit in (video.get("bit_rate") or []):
        urls += list((bit.get("play_addr") or {}).get("url_list") or [])
    seen, out = set(), []
    for item in urls:
        if isinstance(item, str) and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ---------- 第二段：續傳下載 + 大小驗收 ----------

def _wreq_client():
    """抖音 CDN 對非 Chrome TLS 指紋會掛住握手；優先用 wreq 的 Chrome 模擬。"""
    import wreq
    from datetime import timedelta

    majors = [int(name[6:]) for name in dir(wreq.Emulation) if re.fullmatch(r"Chrome\d+", name)]
    major = max(majors) if majors else 0
    emulation = getattr(wreq.Emulation, f"Chrome{major}")
    return wreq.Client(emulation=emulation, cookie_store=False, no_proxy=True,
                       connect_timeout=timedelta(seconds=CONNECT_TIMEOUT))


def _fetch_to_wreq(url: str, path: Path, expected: int) -> int:
    from datetime import timedelta

    client = _wreq_client()

    async def pull() -> int:
        for _ in range(DOWNLOAD_ATTEMPTS):
            have = path.stat().st_size if path.exists() else 0
            if expected and have >= expected:
                return have
            headers = {"Referer": "https://www.douyin.com/", "Accept": "*/*"}
            if have:
                headers["Range"] = f"bytes={have}-"
            try:
                response = await client.get(url, headers=headers,
                                            timeout=timedelta(seconds=DOWNLOAD_TIMEOUT))
            except Exception:
                break
            status = getattr(response, "status", 0)
            if status not in (200, 206):
                break
            body = await response.bytes()
            mode = "ab" if (have and status == 206) else "wb"
            with open(path, mode) as handle:
                handle.write(body)
            total = path.stat().st_size if path.exists() else 0
            if not expected or total >= expected:
                return total
        return path.stat().st_size if path.exists() else 0

    try:
        return asyncio.run(pull())
    except Exception:
        return 0
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _fetch_to_urllib(url: str, path: Path, expected: int) -> int:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"User-Agent": UA, "Referer": "https://www.douyin.com/", "Accept": "*/*"}
    for _ in range(DOWNLOAD_ATTEMPTS):
        have = path.stat().st_size if path.exists() else 0
        if expected and have >= expected:
            return have
        hdrs = dict(headers)
        if have:
            hdrs["Range"] = f"bytes={have}-"
        request = urllib.request.Request(url, headers=hdrs)
        try:
            with opener.open(request, timeout=DOWNLOAD_TIMEOUT) as response:
                mode = "ab" if have else "wb"
                if have and response.getcode() == 200:
                    mode = "wb"   # 伺服器不認 Range，整檔重寫避免疊加
                with open(path, mode) as handle:
                    while True:
                        chunk = response.read(1 << 16)
                        if not chunk:
                            break
                        handle.write(chunk)
        except Exception:
            continue
    return path.stat().st_size if path.exists() else 0


def _pick_candidates(urls: list, max_hosts: int = MAX_HOSTS) -> list:
    """同一 CDN host 只留第一個：51 個候選其實只有 3 個 host。"""
    seen, out = set(), []
    for url in urls:
        host = (urlsplit(url).hostname or "").lower()
        if host in seen:
            continue
        seen.add(host)
        out.append(url)
        if len(out) >= max_hosts:
            break
    return out


def _fetch_to(url: str, path: Path, expected: int) -> int:
    """先走 Chrome 指紋，抓不到才退回 urllib。"""
    if HAS_WREQ:
        return _fetch_to_wreq(url, path, expected)
    return _fetch_to_urllib(url, path, expected)


def _download_video(detail: dict, folder: Path, max_bytes: int) -> dict:
    video = detail.get("video") or {}
    play = video.get("play_addr") or {}
    expected = int(play.get("data_size") or 0)
    if expected > max_bytes:
        raise DouyinError(f"影片 {human_size(expected)}，超過 {max_bytes // 1048576}MB 傳不出去")

    if not (video.get("duration") or 0) and detail.get("images"):
        raise DouyinError("這是圖文貼文，不是影片，我只會抓影片")

    aweme_id = str(detail.get("aweme_id") or "douyin")
    target = folder / f"douyin_{re.sub(r'[^0-9A-Za-z_]', '', aweme_id)}.mp4"
    candidates = _pick_candidates(_video_candidates(detail))
    if not candidates:
        raise DouyinError("這支影片沒有可用的下載網址")

    size = 0
    for url in candidates:
        size = _fetch_to(url, target, expected)
        if size >= MIN_BYTES:
            break
        # 換候選網址前先清掉殘檔，避免新舊內容串接。
        if target.exists():
            target.unlink(missing_ok=True)
        size = 0
    if not size:
        raise DouyinError("連不到抖音的影片伺服器（握手沒回應），本機這條線路抓不到本體")
    if expected and size != expected:
        raise DouyinError(f"下載不完整（{human_size(size)}／{human_size(expected)}），先不發壞檔")
    if size > max_bytes:
        raise DouyinError(f"影片 {human_size(size)}，超過 {max_bytes // 1048576}MB 傳不出去")

    return {
        "path": target,
        "size": size,
        "title": _safe_title(detail.get("desc")) or "douyin",
        "ext": ".mp4",
        "duration": (video.get("duration") or 0) / 1000.0 or None,
        "aweme_id": aweme_id,
        "source": "toolchain",
    }


# ---------- 後備：yt-dlp ----------

def _download_with_ytdlp(url: str, folder: Path, max_bytes: int) -> dict:
    try:
        import yt_dlp
    except ImportError:
        raise DouyinError("主要抓取鏈失敗，而且沒有 yt-dlp 可後備") from None

    class _Quiet:
        def debug(self, msg):
            pass

        def info(self, msg):
            pass

        def warning(self, msg):
            pass

        def error(self, msg):
            pass

    options = {
        "outtmpl": str(folder / "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "consoletitle": False,
        "socket_timeout": 20,
        "retries": 2,
        "max_filesize": max_bytes,
        "restrictfilenames": True,
        "logger": _Quiet(),
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True) or {}
    except Exception:
        raise DouyinError("兩條抓取鏈都沒成功，這支影片可能受風控或已刪除") from None

    files = [p for p in folder.rglob("*")
             if p.is_file() and not p.name.endswith(".part") and p.suffix.lower() in VIDEO_EXTS]
    if not files:
        raise DouyinError("抖音回傳的內容裡沒有影片檔")
    path = max(files, key=lambda p: p.stat().st_size)
    size = path.stat().st_size
    if size <= 0:
        raise DouyinError("下載到的檔案是空的")
    if size > max_bytes:
        raise DouyinError(f"影片 {human_size(size)}，超過 {max_bytes // 1048576}MB 傳不出去")
    return {
        "path": path,
        "size": size,
        "title": _safe_title(info.get("title")) or "douyin",
        "ext": path.suffix.lower(),
        "duration": info.get("duration"),
        "aweme_id": str(info.get("id") or ""),
        "source": "yt-dlp",
    }


# ---------- 對外 ----------

def download(url: str, *, max_bytes: int = MAX_BYTES, allow_ytdlp: bool = True):
    """下載到新的暫存目錄，回傳 (folder, meta)。失敗時不留下任何檔案。"""
    if not _host_allowed(url):
        raise ValueError("只接受抖音的連結")
    folder = Path(tempfile.mkdtemp(prefix="kaze_douyin_"))
    work = folder / "work"
    work.mkdir()
    try:
        try:
            json_path = _run_fetch(url, work)
            detail = _load_detail(json_path)
            meta = _download_video(detail, folder, max_bytes)
        except DouyinError as primary:
            if not allow_ytdlp:
                raise
            for stale in folder.glob("*.mp4"):
                stale.unlink(missing_ok=True)   # 不讓第一段的半成品被當成後備結果
            try:
                meta = _download_with_ytdlp(url, folder, max_bytes)
            except DouyinError:
                # 主鏈的原因比「後備也失敗」更具體，優先報給使用者。
                raise DouyinError(str(primary)) from None
    except BaseException:
        cleanup(folder)
        raise
    shutil.rmtree(work, ignore_errors=True)   # 立刻清掉 JSON 與 cookie 相關雜物
    return folder, meta


def cleanup(folder) -> bool:
    """刪除暫存目錄；回傳是否確認已不存在。"""
    if not folder:
        return True
    target = Path(folder)
    for _ in range(3):
        shutil.rmtree(target, ignore_errors=True)
        if not target.exists():
            return True
        time.sleep(0.2)   # Windows 上檔案句柄還沒放掉時，稍等再刪一次
    return not target.exists()


def purge_stale(max_age_seconds: int = 6 * 3600) -> int:
    """清掉被硬殺（逾時／斷電）留下的孤兒暫存：本功能承諾不保留任何檔案。"""
    root = Path(tempfile.gettempdir())
    now = time.time()
    removed = 0
    for path in root.glob("kaze_douyin_*"):
        try:
            if not path.is_dir() or now - path.stat().st_mtime < max_age_seconds:
                continue
        except OSError:
            continue
        if cleanup(path):
            removed += 1
    return removed
