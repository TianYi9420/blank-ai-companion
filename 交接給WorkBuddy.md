# 空白電子伴侶：WorkBuddy 可選交接入口

本專案已提供不依賴特定Agent的 README.md、AGENTS.md、HANDOFF.md；請優先閱讀它們。本檔僅保留WorkBuddy使用方式，非安裝或執行依賴。

## 給接手 WorkBuddy 的任務

請以同資料夾的空白電子伴侶程式建立使用者自己的成年 AI 電子女友／男友。這是可自訂的程式模板，不是原使用者伴侶的人格或記憶備份。

### 必守邊界

1. 先讀本檔、config.example.json、persona.example.json、check_config.py 與 PUBLIC_MANIFEST.json，再操作。只修改解壓出的新資料夾；改既有檔前先備份。
2. 姓名、性別／代名詞、伴侶關係、性格、外貌、語言與使用者暱稱全部未設定。請詢問新使用者，不沿用任何其他人的伴侶、角色或生活史。不因稱女友／男友而推定使用者性別。
3. 無聊天、人物備忘、照片、外貌參考圖、主人 ID、頻道白名單、Token、API Key 或 OAuth 憑證。不得向原使用者索取或複製這些資料。
4. 不宣稱「完全沒有系統規則」：基礎身分、成年角色、誠實、安全及私聊隔離規則必須保留；空白的是可自訂人格與個人資料。
5. 預設不連網：模型、生圖、主動陪伴停用；無固定主人／Bot Token／姓名與性格時拒絕啟動。先離線測試，再由新使用者確認首次連線與可能費用。
6. 不公開 config.json、OAuth 憑證、聊天庫或本人照片；不自動把它們提交到版本庫或同步到公開資料夾。日後再次分享只能重用原始空白ZIP，不要打包已使用的資料夾。

## 檔案與填寫順序

| 檔案 | 用途 |
|---|---|
| persona.example.json | 全空人格範本；先複製為本機 persona.json，再填寫及重啟。persona.json 不入版控 |
| config.example.json | 無憑證設定範本，複製為 config.json 後填朋友自己的資料 |
| setup.bat | Windows 以已安裝的 Python 建本資料夾 .venv 並安裝依賴；會連線套件來源，需同意後執行 |
| check_config.py | 僅本機檢查、不顯示憑證、不測網路 |
| start.bat | 先檢查再以前景視窗啟動，關閉視窗即停止；未設自啟或排程 |
| test_blank.py | 27 項離線基礎、啟動、安全、人格範本、識圖授權與隔離測試 |
| PUBLIC_MANIFEST.json | 發行檔案清單與 SHA256；不包含執行後資料 |

### 一、詢問人格

收集 name、gender、relationship、appearance、personality、language、owner_nickname。至少姓名與性格填好才允許扮演；其餘可空白並保持中性，不自行補故事。角色明確設定為成年人。

### 二、由朋友建立獨立 Discord 機器人

使用朋友自己的應用程式與 Bot Token、固定使用者 ID；不要重用另一人的 Bot Token。確認平台現行設定，啟用所需的 Message Content Intent，邀請到朋友自己的伺服器時只給必要權限，不給管理員。

config.json 的 discord.owner_user_id 填朋友 ID；discord.bot_token 填朋友 Token。allowed_channels 預設 []，代表不處理任何群聊，仍可在設定完整後回覆固定使用者私訊。要開群聊才填：

```json
{"guild_id": "朋友的伺服器ID", "channel_id": "朋友的頻道或討論串ID"}
```

群聊需在白名單且發送時直接 @ 機器人才回；其他人的私訊不回。15 秒冷卻、全域每小時 40 次及忙碌保護可能忽略訊息；不要當成任何 @ 必回的保證。

### 三、模型

模板不綁定免費方案、訂閱、模型名或付費備援。先詢問朋友現有的 OpenAI 相容服務／本機代理；核對實際 /models 清單，填 llm.endpoint（完整 /v1/chat/completions）、api_token、model，再 enabled=true。遠端使用 HTTPS；本機 CPA 可用回環 HTTP，不開公開代理。

llm.vision_model 空白代表不使用圖片理解；需要時核對所選模型確實支援圖片，再填實際模型名。llm.py 留有可選的受限路由工具，但範本不啟用 route_chain，也不讀取 WorkBuddy 其他帳號或原使用者 CPA 設定。不直接套用舊路由名稱；若要備援，先另做參數化及隔離測試。不能保證 API 或訂閱免費。

### 四、可選生圖與主動陪伴

imagegen 預設 disabled，model／endpoint／api_key／anchor／manga_anchor／manga_style／persona_group 皆空。先確認朋友自己的服務相容性再接：此版本圖片編輯採 images:[{image_url: data_url}] 形狀，不保證所有官方／相容接口都接受；通用 API 可能需改 multipart adapter，未驗證前不要宣稱能用。

目前生圖端點只接受 loopback，圖片回傳只接受 b64_json 或 data:image；遠端圖片 URL 不自動下載，需另經授權與安全改造。朋友自行設定外貌參考圖，文字提示使用中性「人物」，不固定女性。本人照片以「來張自拍」「畫你的自拍」等語句觸發參考圖，任意角色名目前不自動識別，可按朋友設定另擴充觸發詞並測試。

只有判定為本人角色的圖片且傳送成功才存 photos/self/private/日期 或 photos/self/guild_ID_thread_ID/日期；其他題材與使用者上傳附件不存。不回溯、不刪舊照片；這是請求語意判定而非視覺人臉辨識。磁碟存檔失敗會提示手動下載。

其他成員每小時 5 張／每天 60 張；固定使用者不限，但不代表費用不限。主動自拍需填 scenes 為 [["場景標籤","場景描述"]]，chance 設 0 到 1 的比例；原本 scenes=[]、chance=0。不要自行替使用者編好喜好。主動自拍另限每小時 1 張／每天 3 張。

主動陪伴需要 proactive.enabled=true。預設每日最多 4 次、間隔 150~360 分鐘、00:00~08:00 靜音；會依當地時間找話題，不讀桌面、不猜朋友正在做什麼。不建立 WorkBuddy 自動排程或開機自啟。

### 五、記憶與資料範圍

首次使用前先將 persona.example.json 複製成 persona.json。原始倉庫無 companion_vault、photos、logs、state 或用量檔。執行後在新資料夾內建立。私聊按固定使用者隔離，群聊按伺服器／頻道／發話者分檔；人物備忘另按頻道隔離。人格唯一設定來源是 persona.json，不會自動由聊天修改或從 Obsidian 普通筆記載入。

目前上下文有讀取數量與大小上限，不是無限長期記憶，不保證永不忘記。research.enabled 與 bilibili_enabled 預設均 false，必須先告知朋友搜尋關鍵字會外發到 Bing／B站、取得同意後才開啟。來源檢索保留公開文字／B站候選元資料能力，未具備完整影片觀看、字幕下載、抽幀或小紅書／抖音登入能力；公開接口可能限流。不要向朋友誇稱完整讀過影片。

## 執行與驗收

目標 Windows，Python 3.10+（建議 3.13），第三方依賴 discord.py、Pillow、PyYAML。模板不含 Python 執行環境／EasyCLI／任何模型權限。其他作業系統需另改 Windows 單例鎖，不直接承諾可啟動。

1. 取得朋友同意後安裝依賴到本資料夾 .venv，不全域安裝。
2. 執行 `python -m unittest test_blank -v`，全程離線。測試使用臨時資料與假 ID，不連真正 Discord 或模型。
3. 執行 `python discord_bot.py --dry-run`，只看存在性，不輸出秘密。
4. 設定朋友自己的 persona.json／config.json；執行 `python check_config.py`，成功不代表模型可連。
5. 經朋友同意後 `start.bat`；先只測固定使用者私訊，再測陌生私訊拒絕及群聊白名單／直接@。
6. 模型、生圖、主動發話分別驗收；未測的項目寫「待驗」，不可用離線 PASS 冒充實網成功。
7. 改程式前後核 hash、保存測試輸出與備份；不要修改原模板 manifest 後冒稱仍是原版。

## 可直接交給 WorkBuddy 的提示詞

```text
請先讀同資料夾的「交接給WorkBuddy.md」，接手這份空白電子伴侶模板。先向我確認名稱、成年角色性別／代名詞、女友／男友／其他關係、性格、外貌、語言和稱呼，不要自行套任何原人物設定。只在這個解壓資料夾工作，保留隱私隔離與安全規則；先跑離線測試，再協助我建立自己的 Discord Bot、固定使用者設定和模型連線。所有密鑰只寫本機 config.json，不顯示、不外傳、不提交。API／生圖／主動發話或安裝依賴需事前告知費用與連線範圍。未經我確認不要啟動、發訊、建立排程或上雲。請分開回報已實測與待驗證功能。
```
