# 小北生活提案｜智慧購物 App 示範

繁體中文購物 App 原型，含情境導購、門市查詢、示範庫存、會員與自取流程。公開網站由 GitHub Pages 提供，本機客服使用 Ollama 與 `qwen2.5:1.5b`。

- 公開網站：https://foolguyisme.github.io/shop/
- 本機 AI 分享與啟動說明：`Xiaobei_App_Local_AI_Bundle/LOCAL_AI_AND_DEPLOYMENT.md`
- 網站與 API 原始碼：`Xiaobei_App_Local_AI_Bundle/`

公開網站不會包含 Ollama 或模型檔。訪客只有在主機啟動 `start-local-ai.bat` 並持續執行期間，才可用每次啟動產生的臨時 HTTPS 隧道連線客服。購物車 AI 需要訪客先按授權按鈕，並明確要求加入指定商品；不會結帳或付款。

商品、庫存、會員與訂單都是示範資料，沒有連接正式 POS 或交易系統。
