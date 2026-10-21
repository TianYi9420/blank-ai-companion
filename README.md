# Blank AI Companion

從空白人格、空白記憶開始的 Discord AI 電子伴侶，可自行設定為成年女友、男友或其他陪伴角色。

**Windows · Python 3.10+（建議 3.13）· MIT · 實驗性原始碼模板**

**不需要 WorkBuddy，也不需要任何 AI Agent。** 可以照本頁直接安裝，或交給你習慣的 coding agent 協助。
不包含帳號、模型／圖片服務權限、API 額度、人物設定、外貌參考圖、聊天記憶或 Python 執行環境。基礎 AI 身分、成年角色、安全與隱私規則保留。

## 選擇使用方式

| 方式 | 入口 |
|---|---|
| 直接安裝，不用 AI Agent | 依本頁「Windows 快速開始」操作 |
| 任意可讀寫檔案的 coding agent | 先讀 [AGENTS.md](AGENTS.md) 與 [HANDOFF.md](HANDOFF.md)，再貼下方提示詞 |
| Codex、Claude Code、Cursor、Copilot、WorkBuddy 等 | 都可用通用交接方式；不依賴某產品自動讀規則，也不保證各版本已實測 |
| 只有網頁聊天助手 | 提供本頁與交接檔，請它逐步指引；不能宣稱它已在你的電腦完成操作 |

## 功能與預設

- 固定使用者私訊；其他人的私訊不回覆，不讓第一個陌生人自動認領。
- 群聊只回覆精確白名單頻道中發送時直接 @ 機器人的訊息。
- 短訊息自然分段，私聊／群聊／發話者歷史隔離，另有同頻道人物備忘。
- 可接 OpenAI 相容聊天服務；圖片理解、生圖、公開摘要搜尋與主動陪伴皆可選。
- 只將成功發送且被請求判定為本人角色的圖存到本機；普通題材不歸檔。
- **姓名／性別／性格／外貌／關係／稱呼範本全部空白；模型、生圖、公開搜尋及主動陪伴全部停用。**

記憶是本機紀錄與有界上下文，不是無限長期記憶。程式不內建模型，也不提供免費或不限額服務。

## Windows 快速開始

### 1. 下載與安裝

1. 點 GitHub **Code → Download ZIP**，完整解壓到獨立資料夾；也可 clone 倉庫。不要在 ZIP 裡直接執行。
2. 安裝 Python 3.10+（建議 3.13），包含 Windows `py` 啟動器。
3. 雙擊 `setup.bat`。它會在此資料夾建立 `.venv`、連線安裝依賴、複製空白設定並顯示離線狀態；**不會啟動機器人或呼叫模型**。

安裝後會有本機 `config.json`、`persona.json`；檔案存在時不覆寫。不要分享、截圖或提交這兩個檔案。

### 2. 設定你自己的角色

用文字編輯器開啟 `persona.json`，保留 JSON 結構並填入想要的設定：

| 欄位 | 填寫內容 |
|---|---|
| name | 角色名稱，必填 |
| gender | 成年角色性別／代名詞，可空白 |
| relationship | 女友、男友或其他關係，可空白 |
| appearance | 角色外貌文字；不代表已有圖片參考 |
| personality | 性格與說話風格，必填；可註明角色為成年人 |
| language | 回覆語言偏好 |
| owner_nickname | 私聊時如何稱呼你，可空白 |

至少填姓名與性格；空白部分保持中性，不自造過往關係。設定只在啟動時載入，修改後需重啟。對話不能直接改人格。

### 3. 建立自己的 Discord Bot

1. 在 Discord Developer Portal 建立你自己的 Application/Bot，取得 Bot Token；不要使用他人的 Token。
2. 開啟 **Message Content Intent**。平台若要求額外核准，以平台實際規則為準。
3. 透過 OAuth2 安裝／邀請到自己的伺服器，授予查看目標頻道、傳訊、附加檔案等必要權限；討論串依使用位置授傳訊權限，**不需要管理員**。
4. 在 Discord 開發者模式複製你自己的數字使用者 ID。
5. `config.json` 的 `discord.bot_token` 填 Token，`discord.owner_user_id` 填自己的 ID。

先讓 `discord.allowed_channels` 保持空陣列，只測私聊。私訊還受 Discord 的隱私與共同伺服器等設定影響，不保證 Bot 能主動傳給任何人。

群聊要開放時再加入以下**結構**，以自己的數字字串取代說明文字：

```json
"allowed_channels": [
  {"guild_id": "你的伺服器數字ID", "channel_id": "你的頻道或討論串數字ID"}
]
```

只有這個位置發送時直接 @ Bot 才觸發；角色提及、@everyone、事後編輯補 @ 不觸發。忙碌、每人15秒冷卻及全域每小時40次保護可能略過訊息，不保證每次 @ 必回。

### 4. 接入你的聊天模型

需要一個可用的 OpenAI 相容 `/chat/completions` 服務。先向服務商或本機代理確認真實模型 ID、權限與費用。

在 `config.json` 的 `llm` 填寫：

| 欄位 | 說明 |
|---|---|
| enabled | 完成設定並同意連線後改成 `true` |
| endpoint | **完整** `/v1/chat/completions` URL；不是只填 `/v1` |
| api_token | 你自己的服務憑證；僅服務明確允許無Token時才空白 |
| model | 服務實際提供的模型 ID，不猜測名稱 |
| vision_model | 可選，圖片理解模型 ID；空白就不把附件送去識圖 |
| timeout_seconds / max_tokens | 逾時／單次輸出限制，不是精確費用上限 |

遠端端點必須 HTTPS；本機 `127.0.0.1`、`localhost`、`::1` 可 HTTP。不能把憑證放在 URL。
你可以自行安裝／管理本機 CPA 等代理，但本專案不附代理或OAuth，不讀其他應用的帳號設定。預設沒有免費路由或自動付費備援。

### 5. 檢查、啟動、停止

雙擊 `start.bat`，它會先檢查設定，再在前景視窗啟動。第一次確認可能費用與資料外發後才啟動。
在 Discord 對自己的 Bot 發新的私訊測試；再分別測陌生私訊拒絕與群聊規則。

- 視窗需保持開啟；按 **Ctrl+C** 停止。先確認舊視窗已停止，再啟動新視窗。
- 關閉程式不刪記憶。更新設定後停止再啟動，不重複運行多份。
- 不自動建立開機啟動、系統排程或雲端服務。
- 姓名、性格、固定使用者、Bot Token、模型設定缺失會拒絕啟動，這是保護而非故障。

### 不用 BAT 的 PowerShell 方式

在新解壓的專案資料夾開終端機執行：

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path config.json)) { Copy-Item config.example.json config.json }
if (-not (Test-Path persona.json)) { Copy-Item persona.example.json persona.json }
.venv\Scripts\python.exe -m unittest test_blank -v
.venv\Scripts\python.exe discord_bot.py --dry-run
```

編輯設定後再執行：

```powershell
.venv\Scripts\python.exe check_config.py
.venv\Scripts\python.exe discord_bot.py
```

空白配置的 `check_config.py` 預期失敗；成功也只代表本機檢查，不代表 Discord／模型可用。`--dry-run` 不呼叫 Discord／模型。

## 選配功能

### 圖片理解

先確認所選模型支援圖片，填 `llm.vision_model`。附件將傳給你所選的模型服務，可能收費。
不需要開公開搜尋；只做圖片觀察不等於查證版本、數字或日期。沒有 vision_model 時附件不送去識圖。

### 公開搜尋

`research.enabled=true` 才向公開搜尋服務送出當前查詢；B站候選另需 `research.bilibili_enabled=true`。預設 `provider="bing_rss"`。
只有搜尋摘要和影片候選元資料，不是全文、字幕下載、抽幀或實際觀看。公開接口可能限流，無結果不能當作查證成功。
不要把秘密輸入搜尋問題；不因有隱私過濾就保證自動匿名化。

### 生圖與角色自拍

自備本機回環圖片服務後，填 `imagegen.endpoint`（通常為本機 `/v1`）、`api_key`、`model`，確認相容才設 `enabled=true`。
此版編輯使用 `images:[{image_url: data_url}]`，**不保證所有官方／相容Images API都接受**；可能需要改 multipart adapter。
只接受 inline base64 結果，不自動下載遠端圖片URL。沒有內建GPU推理或圖片模型。

角色自拍要自備有權使用的成人角色參考圖，將檔案放 `anchors/`，在 `imagegen.anchor` 填路徑；可先用完整路徑避免工作目錄歧義。用「來張自拍／畫你的自拍」測試，任意角色名尚不會自動識別。
群聊要用不同漫畫外貌時，設定 `persona_group="manga"`、`manga_anchor` 和 `manga_style`。預設皆空白，不預設性別或漫畫風格。

其他成員每人每小時5張／每天60張；固定使用者不限次數，但**不等於免費**，請自行在上游設定費用預算。
成功傳出的本人圖會存到 `photos/self/private/日期` 或 `photos/self/guild_ID_thread_ID/日期`，不回溯舊圖、不自動刪除。這是請求語意判定，不是視覺人臉驗證。

### 主動陪伴與主動自拍

- `proactive.enabled=true` 才啟動背景輪詢；每15分鐘檢查一次，不代表固定15分鐘傳訊。
- 預設每日最多4次，兩次間隔150~360分鐘，00:00~08:00靜音；依執行電腦時間。
- `daily_limit`、`min_interval_minutes`、`max_interval_minutes`、`quiet_hours` 是頂層設定。
- 只以時間為話題，不讀你桌面，不猜測你在線、醒著或正在做什麼。
- 主動自拍另需可用生圖服務、`imagegen.chance` 設0~1，以及 `scenes`，格式為 `[["場景標籤", "你自行設定的場景描述"]]`。
- 預設 chance=0、scenes=[]；主動自拍另限每小時1張／每日3張。

開啟代表可能在你沒發新訊息時呼叫模型、傳DM與產生費用，請明確決定後再開。

## 常見問題

| 現象 | 先檢查 |
|---|---|
| `py` 找不到 | 安裝Python及Windows啟動器，或用你自己的Python完整路徑建venv |
| 安裝失敗 | 網路、Python版本、套件來源及終端錯誤；不要改成全域安裝或下載陌生修復程式 |
| 空白設定檢查失敗 | 正常，先填 persona.json 的名稱／性格及 config.json 的Bot／模型欄位 |
| 401／403 或 Bot 登入失敗 | 朋友自己的Bot Token、Intent與權限；疑似外洩就先撤銷重發，不貼公開Issue |
| Bot在線但不回 | 固定使用者ID、陌生DM規則、精確群聊ID、發送時直接@、冷卻／忙碌／全域上限 |
| 無法私訊 | Discord隱私設定、共同伺服器與Bot接收限制 |
| 取得不到模型回覆 | 模型ID、完整endpoint、認證、服務健康與計費；本機設定PASS不保證上游可用 |
| 圖片不理解 | 是否填 vision_model，模型是否真的支援圖片；每則最多2張、每張5MiB |
| 自拍失敗 | 參考圖是否存在、成人角色使用權、回環服務及edits格式／base64輸出相容性 |
| 沒有主動訊息 | proactive.enabled、靜音、每日上限、間隔、Bot是否持續運行、能否傳DM |
| 想清空記憶 | 先停程式，查看PRIVACY.md，備份並自行確認具體檔案；沒有一鍵自動清理 |
| Linux／macOS無法啟動 | Windows mutex尚未移植；測試可匯入不代表跨平台可運行 |

## 讓任意 AI Agent 協助

先提供資料夾／乾淨ZIP／GitHub連結及 [AGENTS.md](AGENTS.md)、[HANDOFF.md](HANDOFF.md)。貼上：

```text
請先閱讀 blank-ai-companion 的 README.md、AGENTS.md 與 HANDOFF.md，協助我直接使用這個專案。
先詢問名稱、成年角色性別／代名詞、關係、性格、外貌、語言與稱呼，不套用既有人物。
先跑離線測試，再設定我自己的Discord Bot與模型；密鑰只寫config.json，個人人格只寫persona.json，不公開或提交。
安裝套件、呼叫API、發送訊息、搜尋、生圖、主動陪伴或部署前，先說明資料外發與費用，取得我確認。
只在這個專案修改並先備份。如果你無法讀寫檔案或執行命令，明說並給我可照做的步驟，不假裝已完成。
```

WorkBuddy專用舊入口 [交接給WorkBuddy.md](交接給WorkBuddy.md) 保留相容，但不是必要步驟。各Agent規則載入方式隨產品／版本不同，本專案不自動替你安裝或授權它們。

## 隱私、測試與授權

- 本機 `config.json`、`persona.json`、`anchors/`、記憶、照片、日誌、狀態與OAuth已排除版控；`.gitignore`不是安全沙箱，不要 `git add -f` 或公開已使用整目錄。
- 使用後會持久保存新聊天與人物備忘，沒有完整「不留記憶」開關、預設加密或自動清理；不接受此行為者先不要啟動。
- Discord及你選擇的模型／圖片／搜尋服務可能收到資料；各服務留存與費用由其決定。本專案不授予模型Shell或任意本機檔案能力，提示注入防護不保證絕對有效。
- 離線測試使用假ID、mock模型與臨時檔案，不證明真Discord、供應商生圖或計費可用。
- Windows是目前啟動目標；依賴只有版本範圍，更新環境後請重新測試。
- [PRIVACY.md](PRIVACY.md) · [SECURITY.md](SECURITY.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [MIT](LICENSE) · Copyright (c) 2026 TianYi9420。軟體按原樣提供，沒有可用性或安全保證；第三方服務、素材與模型權利另計。
