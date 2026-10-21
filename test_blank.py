"""Offline tests; no owner credentials, Discord traffic or external model calls."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import companion
import discord_bot as bot
import imagegen
import llm
import memory
import sources
from check_config import validate
ROOT = Path(__file__).resolve().parent
class BlankTemplate(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8-sig"))
        companion.PROFILE = {}; companion.PERSONA = ""
    def test_blank_credentials_and_persona(self):
        companion.configure(self.cfg)
        self.assertFalse(companion.persona_ready())
        self.assertTrue(all(v == "" for v in companion.PROFILE.values()))
        self.assertIsNone(companion.owner_id(self.cfg))
        self.assertFalse(companion.allowed_channels(self.cfg))
        self.assertFalse(llm.generate(self.cfg, "system", "test"))
        self.assertFalse(imagegen.available(self.cfg))
        self.assertTrue(validate(self.cfg))
    def test_empty_profile_has_no_character(self):
        text = companion.system_prompt()
        self.assertIn("人格尚未設定", text)
        self.assertNotIn("女友", text)
        self.assertNotIn("男友", text)
    def test_custom_boyfriend_or_girlfriend(self):
        for gender in ("男", "女", "不指定"):
            companion.PROFILE = {"name": "測試角色", "gender": gender, "personality": "由本人填寫"}
            companion.PERSONA = "由本人填寫"
            self.assertIn(gender, companion.system_prompt())
            self.assertTrue(companion.persona_ready())
    def test_channel_allowlist_only_explicit(self):
        self.cfg["discord"]["allowed_channels"] = [{"guild_id": "11", "channel_id": "22"}]
        self.assertEqual(companion.allowed_channels(self.cfg), {(11,22)})
        self.assertEqual(companion.group_scope(33,11,22,cfg=self.cfg), "guild_11_thread_22_user_33")
        with self.assertRaises(ValueError): companion.group_scope(33,11,44,cfg=self.cfg)
    def test_invalid_owner_and_channels_fail_closed(self):
        for value in ("", "bad", -1, None):
            self.cfg["discord"]["owner_user_id"] = value
            self.assertIsNone(companion.owner_id(self.cfg))
        self.cfg["discord"]["allowed_channels"] = [{"guild_id": "bad", "channel_id": 1}]
        self.assertFalse(companion.allowed_channels(self.cfg))
    def test_unauthorized_group_and_other_dm_denied(self):
        self.cfg["discord"]["owner_user_id"] = 11
        msg = SimpleNamespace(author=SimpleNamespace(id=22,bot=False), guild=SimpleNamespace(id=33),channel=SimpleNamespace(id=44),content="<@99>",mentions=[SimpleNamespace(id=99)])
        self.assertIsNone(bot.authorized(msg,self.cfg,99))
        msg.guild = None; msg.channel = Mock(spec=bot.discord.DMChannel)
        self.assertIsNone(bot.authorized(msg,self.cfg,99))
        msg.author.id=11
        self.assertEqual(bot.authorized(msg,self.cfg,99), "private")
    def test_memory_empty_and_private_group_isolation(self):
        with TemporaryDirectory() as d, patch.object(memory,"VAULT",Path(d)):
            self.assertFalse(memory.recent(scope="dm_11"))
            memory.append("PRIVATE",scope="dm_11")
            self.assertNotIn("PRIVATE", memory.history_block(scope="guild_1_thread_2_user_3"))
    def test_people_room_isolation(self):
        with TemporaryDirectory() as d, patch.object(memory,"VAULT",Path(d)):
            memory.remember_people("guild_1_thread_2",[(3,"測試")],"測試備忘",speaker_id=1,speaker_is_owner=True)
            self.assertIn("測試備忘",memory.people_block("guild_1_thread_2",[3]))
            self.assertFalse(memory.people_block("guild_1_thread_4",[3]))
    def test_source_collection_off_by_default(self):
        self.assertFalse(sources.collect(self.cfg))
    def test_no_default_scene_or_appearance(self):
        companion.configure(self.cfg)
        self.assertFalse(imagegen.SCENES)
        self.assertFalse(self.cfg["imagegen"]["anchor"])
        self.assertEqual(imagegen.STYLE_TAIL, "")
    def test_only_own_photo_saved(self):
        raw=b"\x89PNG\r\n\x1a\nfixture"
        with TemporaryDirectory() as d, patch.object(imagegen,"PHOTO_DIR",Path(d)):
            self.assertIsNone(imagegen.save_own_photo(raw,is_self=False))
            p=imagegen.save_own_photo(raw,is_self=True)
            self.assertEqual(p.read_bytes(),raw)
            self.assertIn("private",p.parts)
    def test_other_subject_selfie_not_own(self):
        for text in ("畫一張貓咪自拍","畫一張別人的自拍","不要畫你 畫一隻貓"):
            self.assertFalse(imagegen.wants_self_portrait(text))
        self.assertTrue(imagegen.wants_self_portrait("來張自拍"))
    def test_send_failure_does_not_save(self):
        channel=Mock(send=AsyncMock(side_effect=RuntimeError("failed")))
        with patch.object(imagegen,"save_own_photo") as save:
            with self.assertRaises(RuntimeError):
                asyncio.run(bot.CompanionBot._send_image(None,channel,"test",b"test",is_self=True))
        save.assert_not_called()
    def test_neutral_image_prompt(self):
        with TemporaryDirectory() as d:
            a=Path(d)/"anchor.png"; a.write_bytes(b"fixture")
            cfg={"imagegen":{"enabled":True,"provider":"openai_images","endpoint":"http://127.0.0.1:8317/v1","api_key":"unit-test-only","anchor":str(a)}}
            with patch.object(imagegen,"_post_images",return_value={"data":[]}) as post:
                imagegen.generate_prompt(cfg,"畫你的自拍",use_anchor=True)
            prompt=post.call_args.args[2]["prompt"]
            self.assertNotIn("女生",prompt); self.assertIn("人物",prompt)
    def test_split_messages_and_protected_links(self):
        self.assertEqual(bot.split_reply("第一則\n---\n第二則"),["第一則","第二則"])
        link="https://example.com/test?q=1"
        self.assertIn(link," ".join(bot.split_reply("參考 " + link)))
    def test_public_private_prompt_rules(self):
        companion.PROFILE={"name":"測試","personality":"測試"}; companion.PERSONA="測試"
        self.assertIn("不得讀取或轉述私人",companion.system_prompt(group=True))
    def test_remote_insecure_endpoint_rejected(self):
        self.cfg["llm"].update(enabled=True,model="test",endpoint="http://example.com/v1/chat/completions")
        self.assertIn("Remote model endpoint must use HTTPS",validate(self.cfg))
    def test_vault_starts_with_no_memory_files(self):
        with TemporaryDirectory() as d, patch.object(companion,"VAULT",Path(d)):
            companion.initialize_vault()
            self.assertFalse(any(p.is_file() for p in Path(d).rglob("*")))
    def test_research_disabled_even_with_chat_enabled(self):
        import research
        self.cfg["llm"]["enabled"] = True
        with patch.object(research, "_fetch_bing_rss") as fetch, patch.object(llm,"generate") as generate:
            result = research.answer(self.cfg,"搜尋公開資料")
        fetch.assert_not_called(); generate.assert_not_called()
        self.assertFalse(result["searched"])
    def test_remote_image_url_not_downloaded(self):
        with patch.object(imagegen.urllib.request,"build_opener") as opener:
            self.assertIsNone(imagegen._extract_image({"data":[{"url":"https://example.com/img.png"}]}))
        opener.assert_not_called()
    def test_invalid_selfie_scene_and_schedule_rejected(self):
        self.cfg["imagegen"]["chance"] = 0.5
        self.assertIn("Add scenes before enabling proactive selfies",validate(self.cfg))
        self.cfg["quiet_hours"] = [[25,0],[8,0]]
        self.assertIn("Invalid quiet hours",validate(self.cfg))
    def test_main_direct_entry_checks_before_network(self):
        with patch.object(bot,"load_config",return_value=self.cfg), patch.object(bot.CompanionBot,"run") as run, patch.object(bot,"acquire_instance") as acquire, patch("sys.argv",["discord_bot.py"]):
            self.assertEqual(bot.main(),1)
        run.assert_not_called(); acquire.assert_not_called()
    def test_private_reply_not_copied_into_log(self):
        cfg=json.loads(json.dumps(self.cfg)); cfg["discord"]["owner_user_id"]=11
        companion.PROFILE={"name":"測試","personality":"測試"}; companion.PERSONA="測試"
        with TemporaryDirectory() as d, patch.object(memory,"VAULT",Path(d)), patch.object(bot,"UsageBudget"), patch.object(imagegen,"ImageUsage"), patch.object(bot,"load_state",return_value={}):
            client=bot.CompanionBot(cfg,timer_on=False,intents=bot.discord.Intents.none()); client._connection.user=SimpleNamespace(id=99)
            ch=Mock(spec=bot.discord.DMChannel); ch.send=AsyncMock()
            class Typing:
                async def __aenter__(self): return None
                async def __aexit__(self,*args): return False
            ch.typing=Mock(return_value=Typing())
            msg=SimpleNamespace(author=SimpleNamespace(id=11,bot=False),guild=None,channel=ch,content="hello",mentions=[],attachments=[])
            with patch("research.needed",return_value=False), patch.object(llm,"generate",return_value="PRIVATE_REPLY_SENTINEL"),patch.object(bot,"log") as logger:
                asyncio.run(client.on_message(msg))
            self.assertNotIn("PRIVATE_REPLY_SENTINEL",str(logger.call_args_list))
            self.assertIn("chunks=1",str(logger.call_args_list))
    def test_local_persona_overrides_empty_example(self):
        with TemporaryDirectory() as d, patch.object(companion,"ROOT",Path(d)):
            Path(d,"persona.example.json").write_text('{"name":"","personality":""}',encoding="utf-8")
            companion.configure(self.cfg)
            self.assertFalse(companion.persona_ready())
            Path(d,"persona.json").write_text('{"name":"test","personality":"custom"}',encoding="utf-8")
            companion.configure(self.cfg)
            self.assertTrue(companion.persona_ready())
            self.assertEqual(companion.PROFILE["name"],"test")
    def test_published_profile_example_is_empty(self):
        doc=json.loads((ROOT/"persona.example.json").read_text(encoding="utf-8-sig"))
        self.assertTrue(all(v=="" for v in doc.values()))
        self.assertIn("persona.json",(ROOT/".gitignore").read_text(encoding="utf-8-sig").splitlines())
    def test_vision_opt_in_works_without_public_search(self):
        import research
        self.cfg["llm"].update(enabled=True,vision_model="test-vision")
        with patch.object(research,"_image_data",return_value=["data:image/png;base64,ZmFrZQ=="]), patch.object(llm,"analyze_images",return_value="測試圖片內容") as analyze, patch.object(research,"_fetch_bing_rss") as search:
            result=research.answer(self.cfg,"這張圖片是什麼",attachments=[{"data":b"fake"}])
        analyze.assert_called_once(); search.assert_not_called()
        self.assertIn("測試圖片內容",result["text"])
    def test_vision_unconfigured_never_sends_attachments(self):
        import research
        self.cfg["llm"]["enabled"]=True
        with patch.object(llm,"analyze_images") as analyze, patch.object(research,"_fetch_bing_rss") as search:
            research.answer(self.cfg,"看圖片",attachments=[{"data":b"fake"}])
        analyze.assert_not_called(); search.assert_not_called()
if __name__ == "__main__": unittest.main(verbosity=2)
