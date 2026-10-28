# -*- coding: utf-8 -*-
"""離線驗收：抖音連結解析、下載驗收、暫存清理、Discord 接線。

全程 mock 網路與工具鏈，不對抖音發任何請求。
"""
import asyncio
import inspect
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

import douyin


def detail(video_size=300_000, duration=15_000, images=None, desc="測試影片",
           aweme_id="7300000000000000000"):
    if images:
        video = {"duration": 0,
                 "play_addr": {"data_size": 0, "url_list": ["https://p3.douyinpic.com/a.webp"]}}
    else:
        video = {"duration": duration,
                 "play_addr": {"data_size": video_size,
                               "url_list": ["https://v3-web.douyinvod.com/a.mp4"]}}
    return {"aweme_id": aweme_id, "desc": desc, "video": video, "images": images or []}


def temp_state():
    return set(Path(tempfile.gettempdir()).glob("kaze_douyin_*"))


class LinkTests(unittest.TestCase):
    def test_share_text(self):
        text = "7.68 复制打开抖音，看看【某某】的作品 https://v.douyin.com/JPgKDfg1zQg/ 复制此链接"
        self.assertEqual(douyin.find_links(text), ["https://v.douyin.com/JPgKDfg1zQg/"])

    def test_full_url(self):
        url = "https://www.douyin.com/video/7300000000000000000"
        self.assertEqual(douyin.first_link(url), url)

    def test_multi_keeps_order_and_dedupes(self):
        text = ("https://v.douyin.com/bbb/ https://www.bilibili.com/video/BV1xx "
                "https://v.douyin.com/aaa/ https://v.douyin.com/bbb/")
        self.assertEqual(douyin.find_links(text),
                         ["https://v.douyin.com/bbb/", "https://v.douyin.com/aaa/"])

    def test_foreign_host_ignored(self):
        self.assertEqual(douyin.find_links("https://www.bilibili.com/video/BV1xx"), [])
        self.assertIsNone(douyin.first_link("今天好累"))

    def test_spoofed_host_rejected(self):
        self.assertEqual(douyin.find_links("https://douyin.com.evil.com/x"), [])
        self.assertFalse(douyin._host_allowed("https://v.douyin.com@evil.com/x"))

    def test_trailing_punctuation_stripped(self):
        self.assertEqual(douyin.find_links("看這個 https://v.douyin.com/abc/。"),
                         ["https://v.douyin.com/abc/"])
        self.assertEqual(douyin.find_links("(https://v.douyin.com/abc/)"),
                         ["https://v.douyin.com/abc/"])

    def test_scheme_limited(self):
        self.assertFalse(douyin._host_allowed("ftp://v.douyin.com/x"))
        self.assertFalse(douyin._host_allowed("javascript:alert(1)"))

    def test_subdomain_allowed(self):
        self.assertTrue(douyin._host_allowed("https://www.iesdouyin.com/share/video/1/"))


class MetaTests(unittest.TestCase):
    def test_candidates_order(self):
        body = detail()
        body["video"]["play_addr_h264"] = {"url_list": ["https://h264/1.mp4"]}
        body["video"]["bit_rate"] = [{"play_addr": {"url_list": ["https://br/1.mp4"]}}]
        urls = douyin._video_candidates(body)
        self.assertEqual(urls[0], "https://h264/1.mp4")
        self.assertIn("https://v3-web.douyinvod.com/a.mp4", urls)
        self.assertEqual(len(urls), len(set(urls)))

    def test_safe_title(self):
        self.assertEqual(douyin._safe_title('a/b:c*?"<>|\n d'), "a b c d")
        self.assertEqual(douyin._safe_title(""), "")
        self.assertEqual(len(douyin._safe_title("長" * 200)), 60)

    def test_human_size(self):
        self.assertEqual(douyin.human_size(999), "999B")
        self.assertEqual(douyin.human_size(2048), "2KB")
        self.assertEqual(douyin.human_size(3 * 1024 * 1024), "3.0MB")

    def test_pick_candidates_collapses_same_host(self):
        urls = [f"https://v26-webf.douyinvod.com/a{i}.mp4" for i in range(30)]
        urls += [f"https://v26-web.douyinvod.com/b{i}.mp4" for i in range(20)]
        urls += ["https://www.douyin.com/aweme/v1/play/?video_id=1"]
        picked = douyin._pick_candidates(urls)
        self.assertEqual(len(picked), 3)
        self.assertEqual(len({urlsplit(url).hostname for url in picked}), 3)


class DownloadTests(unittest.TestCase):
    def test_foreign_host_rejected_without_temp(self):
        before = temp_state()
        with self.assertRaises(ValueError):
            douyin.download("https://www.bilibili.com/video/BV1xx")
        self.assertEqual(before, temp_state())

    def test_missing_toolchain_raises_and_cleans(self):
        before = temp_state()
        with patch.object(douyin, "TOOL_DIR", Path(tempfile.gettempdir()) / "no_such_douyin_dir"):
            with self.assertRaises(douyin.DouyinError):
                douyin.download("https://v.douyin.com/abc/", allow_ytdlp=False)
        self.assertEqual(before, temp_state())

    def test_oversize_rejected_before_download(self):
        payload = detail(video_size=30 * 1024 * 1024)
        with patch.object(douyin, "_run_fetch", lambda url, folder: Path(folder) / "x.json"), \
                patch.object(douyin, "_load_detail", lambda path: payload):
            with self.assertRaises(douyin.DouyinError) as ctx:
                douyin.download("https://v.douyin.com/abc/", allow_ytdlp=False)
        self.assertIn("MB", str(ctx.exception))

    def test_album_rejected(self):
        payload = detail(images=["https://p3.douyinpic.com/a.webp"])
        with patch.object(douyin, "_run_fetch", lambda url, folder: Path(folder) / "x.json"), \
                patch.object(douyin, "_load_detail", lambda path: payload):
            with self.assertRaises(douyin.DouyinError) as ctx:
                douyin.download("https://v.douyin.com/abc/", allow_ytdlp=False)
        self.assertIn("圖文", str(ctx.exception))

    def test_truncated_rejected(self):
        payload = detail(video_size=900_000)

        def short(url, path, expected):
            Path(path).write_bytes(b"0" * douyin.MIN_BYTES)
            return douyin.MIN_BYTES

        with patch.object(douyin, "_run_fetch", lambda url, folder: Path(folder) / "x.json"), \
                patch.object(douyin, "_load_detail", lambda path: payload), \
                patch.object(douyin, "_fetch_to", short):
            with self.assertRaises(douyin.DouyinError) as ctx:
                douyin.download("https://v.douyin.com/abc/", allow_ytdlp=False)
        self.assertIn("不完整", str(ctx.exception))

    def test_success_and_cleanup(self):
        payload = detail(video_size=400_000)

        def exact(url, path, expected):
            Path(path).write_bytes(b"0" * expected)
            return expected

        with patch.object(douyin, "_run_fetch", lambda url, folder: Path(folder) / "x.json"), \
                patch.object(douyin, "_load_detail", lambda path: payload), \
                patch.object(douyin, "_fetch_to", exact):
            folder, meta = douyin.download("https://v.douyin.com/abc/", allow_ytdlp=False)
        self.assertEqual(meta["size"], 400_000)
        self.assertEqual(meta["source"], "toolchain")
        self.assertTrue(meta["path"].exists())
        self.assertFalse((Path(folder) / "work").exists())   # JSON 已即時清掉
        self.assertTrue(douyin.cleanup(folder))
        self.assertFalse(Path(folder).exists())

    def test_cleanup_idempotent(self):
        folder = Path(tempfile.mkdtemp(prefix="kaze_douyin_unit_"))
        self.assertTrue(douyin.cleanup(folder))
        self.assertTrue(douyin.cleanup(folder))
        self.assertTrue(douyin.cleanup(None))

    def test_purge_stale_only_touches_old(self):
        old = Path(tempfile.mkdtemp(prefix="kaze_douyin_old_"))
        fresh = Path(tempfile.mkdtemp(prefix="kaze_douyin_fresh_"))
        past = time.time() - 8 * 3600
        os.utime(old, (past, past))
        try:
            douyin.purge_stale()
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
        finally:
            douyin.cleanup(fresh)

    def test_falls_back_to_ytdlp(self):
        def fake(url, folder, max_bytes):
            path = Path(folder) / "backup.mp4"
            path.write_bytes(b"0" * 200_000)
            return {"path": path, "size": 200_000, "title": "t", "ext": ".mp4",
                    "duration": 10, "aweme_id": "1", "source": "yt-dlp"}

        with patch.object(douyin, "_run_fetch", side_effect=douyin.DouyinError("toolchain down")), \
                patch.object(douyin, "_download_with_ytdlp", fake):
            folder, meta = douyin.download("https://v.douyin.com/abc/")
        self.assertEqual(meta["source"], "yt-dlp")
        douyin.cleanup(folder)
        self.assertFalse(Path(folder).exists())

    def test_fallback_failure_keeps_primary_reason(self):
        before = temp_state()
        with patch.object(douyin, "_run_fetch",
                          side_effect=douyin.DouyinError("連不到抖音的影片伺服器")), \
                patch.object(douyin, "_download_with_ytdlp",
                             side_effect=douyin.DouyinError("後備也不行")):
            with self.assertRaises(douyin.DouyinError) as ctx:
                douyin.download("https://v.douyin.com/abc/")
        self.assertIn("連不到抖音", str(ctx.exception))
        self.assertEqual(before, temp_state())


class _Ctx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Channel:
    def __init__(self):
        self.sent = []

    def typing(self):
        return _Ctx()

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs.get("file")))
        return None


class DiscordWiringTests(unittest.TestCase):
    def setUp(self):
        import discord_bot
        self.bot_module = discord_bot

    def bot_class(self):
        """自用版叫 KazeBot、開源版叫 CompanionBot，用型別找而不是寫死名字。"""
        import discord
        for value in vars(self.bot_module).values():
            if isinstance(value, type) and issubclass(value, discord.Client) \
                    and value is not discord.Client:
                return value
        raise AssertionError("找不到 bot 類別")

    def test_dm_hook_runs_before_llm(self):
        source = inspect.getsource(self.bot_class().on_message)
        self.assertIn("douyin.first_link", source)
        self.assertLess(source.index("douyin.first_link"), source.index("research.needed"))

    def test_limit_matches_module(self):
        self.assertEqual(self.bot_module.DOUYIN_MAX_BYTES, douyin.MAX_BYTES)

    def test_delivery_sends_file_then_deletes(self):
        folder = Path(tempfile.mkdtemp(prefix="kaze_douyin_test_"))
        video = folder / "v.mp4"
        video.write_bytes(b"0" * 4096)
        meta = {"path": video, "size": 4096, "title": "測試影片", "ext": ".mp4",
                "duration": 12, "aweme_id": "1", "source": "toolchain"}
        channel = _Channel()
        message = SimpleNamespace(channel=channel)
        bot_class = self.bot_class()
        bot = bot_class.__new__(bot_class)
        with patch.object(douyin, "download", lambda *a, **k: (folder, meta)), \
                patch.object(self.bot_module, "log", lambda *a, **k: None):
            asyncio.run(bot_class._deliver_douyin(bot, message, "https://v.douyin.com/abc/"))
        self.assertEqual(len(channel.sent), 2)
        self.assertIn("抓一下", channel.sent[0][0])
        self.assertIsNotNone(channel.sent[1][1])
        self.assertFalse(folder.exists())   # finally 已刪除暫存

    def test_delivery_reports_error_without_file(self):
        channel = _Channel()
        message = SimpleNamespace(channel=channel)
        bot_class = self.bot_class()
        bot = bot_class.__new__(bot_class)
        with patch.object(douyin, "download",
                          side_effect=douyin.DouyinError("抓不到")), \
                patch.object(self.bot_module, "log", lambda *a, **k: None):
            asyncio.run(bot_class._deliver_douyin(bot, message, "https://v.douyin.com/abc/"))
        self.assertEqual(channel.sent[-1][0], "抓不到")
        self.assertIsNone(channel.sent[-1][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
