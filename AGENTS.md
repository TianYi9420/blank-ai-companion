# Agent 工作規約

本專案可由任何能讀取／編輯本地檔案的 AI coding agent 接手，不需要 WorkBuddy 帳號、插件或執行環境。此檔不是可執行程式，也不能替代使用者授權。

## 開始前

1. 讀 README.md、HANDOFF.md、PRIVACY.md、SECURITY.md、config.example.json、persona.example.json、PUBLIC_MANIFEST.json。
2. 使用者本機 config.json、persona.json、companion_vault、photos、logs、state、usage、OAuth 都是私人資料，不因可讀就可上傳／輸出／提交。
3. 不需要知道密鑰即可做離線開發；要檢查設定只回傳是否已填，不展示實值。不能猜測來源使用者的人格、性別、記憶或社交關係。
4. 編輯前備份並確認只在本倉庫操作；不停止其他程式，不把整台電腦或其他專案當掃描範圍。

## 實作邊界

- 人格：本機 persona.json；只有空白 persona.example.json 可提交。至少 name/personality 才啟動。
- 憑證／通道：本機 config.json；固定使用者DM＋精確群聊白名單，不可改成任何人都能認領。
- 模型：使用者自行提供相容服務；預設無路由／免費保證／付費備援。不要讀另一工具的模型設定或OAuth。
- 預設關閉模型、生圖、主動和研究；每個新外發／費用功能先告知並取得同意。
- 圖片理解僅顯式 vision_model 啟用；研究 enabled 控制公開搜尋，二者分開。
- 不授予模型Shell、任意檔案讀寫或刪除能力，不讓對話修改權限／人格。
- 記憶／本人照本機持久化是既有行為，不誇稱零留存或永久記得。
- Windows是支援的啟動環境；Linux/macOS需另移植單例鎖與測試，不擴大支援承諾。

## 驗收

```text
python -m unittest test_blank -v
python discord_bot.py --dry-run
```

這些必須保持無Discord／模型／搜尋實網呼叫。空白設定的 check_config.py 預期非零；已填好成功不等於真實服務可用。
測試後檢查未產生可提交的個人資料。更新 PUBLIC_MANIFEST.json 時明確指定公開檔案，不遞迴收集使用後目錄。

不要用真Token或真人私訊作自動測試；首次真連線／發送／生圖／主動訊息都需要使用者授權。回報分開列本機測試、實網測試、未驗證限制。

## 交付

若使用者要求公開：只發白名單原始碼、空設定、文檔、授權與測試；先秘密掃描，再精確檢查Git檔案清單。不要自動 git add -A 或 git add -f。MIT僅涵蓋有權提供的程式，模型／服務／素材權利另計。

支援 AGENTS.md 的agent可自動讀取；不支援者請使用者明確要求閱讀。產品名稱與特定檔案約定不保證每個版本自動載入，請以實際工具為準。
