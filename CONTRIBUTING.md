# 貢獻指南

1. 從乾淨倉庫建立分支，使用虛擬環境安裝 requirements.txt。
2. 絕不提交 config.json、persona.json、聊天庫、參考圖、用量、日誌、OAuth 或本機路徑。
3. 修改先加對應離線測試，不對真實Discord、模型或付費服務自動測試。
4. 執行 `python -m unittest test_blank -v` 及 `python discord_bot.py --dry-run`。
5. PR 說明改動、測試環境、已實測與未實測邊界；涉及外發資料或費用時明列。
6. 更新公開檔案後依新的白名單產生 PUBLIC_MANIFEST.json；manifest不含自身雜湊，也不取代秘密掃描。
7. 提交貢獻表示你有權以本專案 MIT 條款提供該內容；不要複製不相容授權的程式或未授權素材。

專案目前僅支援Windows實際啟動。跨平台、模組化與額度守門改造歡迎，但需獨立測試，不在PR中擴大已驗證範圍。
