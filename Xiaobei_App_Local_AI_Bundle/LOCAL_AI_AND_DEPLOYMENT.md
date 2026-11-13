# 小北智慧購物 App：本機 AI 與公開網站

## 網站與本機客服

- 公開網站：https://foolguyisme.github.io/shop/
- 網站由 GitHub Pages 提供。
- 客服模型 `qwen2.5:1.5b` 與 Ollama 留在 `D:\小北\Ollama` 和 `D:\小北\OllamaModels`。
- 公開訪客共用這台電腦的模型。只有在這台電腦啟動本機 AI 分享 BAT、且視窗持續執行時，客服 AI 才能連線。

## 啟動公開客服 AI

1. 確認 `D:\小北\Cloudflared\cloudflared.exe` 已安裝，並且 Ollama、模型、Python 3.10+ 均在本機資料夾與環境中。
2. 雙擊 `Xiaobei_App_Local_AI_Bundle\start-local-ai.bat`。
3. BAT 會用已登入的 Git Credential Manager 更新公開連線狀態；啟動視窗會顯示固定的公開網站網址。
4. 訪客直接開啟固定網址即可。網站會自動尋找並連線本機 AI，不需輸入網址、存取碼或按連線；已開啟的頁面也會定期更新狀態。
5. 保持 BAT 視窗開啟。按 Ctrl+C 或關閉視窗會停止隧道、客服 API 和本機 Ollama，並將網站狀態設為離線。

Cloudflare Quick Tunnel 不需把 Ollama 或 API 連接埠直接開到網際網路；API 僅監聽 `127.0.0.1`。BAT 每次啟動會產生新的隧道網址，並更新公開的 `local-ai-status` 狀態分支，讓固定 Pages 網址找到當次服務。此公開示範在 BAT 執行期間開放給網站訪客使用；停止後狀態會轉為離線。Quick Tunnel 是臨時隧道，不是固定服務網址。

## 客服購物車權限

訪客連上本機 AI 後，可按「授權 AI 加入購物車」。未按之前 AI 不可修改購物車；授權可隨時撤回，而且只在目前頁面有效。即使已授權，AI 也只有在訪客明確說要把指定商品加入購物車時才會執行；購物車仍是瀏覽器中的示範資料，不會結帳、付款或送出真實訂單。

## GitHub Pages 發佈

`/.github/workflows/deploy-pages.yml` 只發佈網站 HTML、門市資料和 QR Code 腳本。Ollama 執行檔、模型和 Cloudflare 執行檔不會發佈。為了讓公開訪客自動連線，BAT 會將當次隧道網址與存取碼放在公開的 `local-ai-status` 分支；因此所有能開啟網站的訪客都能在 BAT 執行時使用客服 AI。啟動 BAT 的 Windows 帳號需有此 GitHub repository 的寫入憑證。

## 示範資料說明

商品名稱、價格、庫存、會員、優惠與訂單都是前端示範資料，並未連接小北正式 POS、會員、付款或訂單系統。門市資訊來源與更新方式請見 `fetch_showba_stores.py`。
