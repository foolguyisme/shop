# 小北智慧購物 App：本機 AI 與公開網站

## 網站與本機客服

- 公開網站：https://foolguyisme.github.io/shop/
- 網站由 GitHub Pages 提供。
- 客服模型 `qwen2.5:1.5b` 與 Ollama 留在 `D:\小北\Ollama` 和 `D:\小北\OllamaModels`。
- 公開訪客共用這台電腦的模型。只有在這台電腦啟動本機 AI 分享 BAT、且視窗持續執行時，客服 AI 才能連線。

## 啟動公開客服 AI

1. 確認 `D:\小北\Cloudflared\cloudflared.exe` 已安裝，並且 Ollama、模型、Python 3.9+ 均在本機資料夾與環境中。
2. 雙擊 `Xiaobei_App_Local_AI_Bundle\start-local-ai.bat`。
3. 在啟動視窗找到 `AI-READY LINK` 和 `LOCAL AI ACCESS CODE`。
4. 分享公開網站連結與本次啟動的存取碼給訪客。AI-ready link 會預填本次隧道網址；訪客在客服窗輸入存取碼並按「連線本機 AI」。
5. 保持 BAT 視窗開啟。按 Ctrl+C 或關閉視窗會停止隧道、客服 API 和本機 Ollama；之後訪客只能看到網站，無法使用本機模型。

Cloudflare Quick Tunnel 不需把 Ollama 或 API 連接埠直接開到網際網路；API 僅監聽 `127.0.0.1`。每次啟動都會產生新的暫時網址與存取碼，因此舊連結/存取碼在停止或重新啟動後失效。這是展示與試用用的臨時隧道，不是固定服務網址。

## 客服購物車權限

訪客連上本機 AI 後，可按「授權 AI 加入購物車」。未按之前 AI 不可修改購物車；授權可隨時撤回，而且只在目前頁面有效。即使已授權，AI 也只有在訪客明確說要把指定商品加入購物車時才會執行；購物車仍是瀏覽器中的示範資料，不會結帳、付款或送出真實訂單。

## GitHub Pages 發佈

`/.github/workflows/deploy-pages.yml` 只發佈網站 HTML、門市資料和 QR Code 腳本。Ollama 執行檔、模型、Cloudflare 執行檔與本機存取碼不在公開網站中。第一次部署時，請在 GitHub repository 的 Settings → Pages → Build and deployment 將 Source 設為 GitHub Actions。

## 示範資料說明

商品名稱、價格、庫存、會員、優惠與訂單都是前端示範資料，並未連接小北正式 POS、會員、付款或訂單系統。門市資訊來源與更新方式請見 `fetch_showba_stores.py`。
