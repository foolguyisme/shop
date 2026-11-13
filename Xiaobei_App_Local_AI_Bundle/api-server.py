"""Local Xiaobei web app and authenticated Ollama proxy."""
from __future__ import annotations

import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import defaultdict, deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLLAMA_URL = os.environ.get("OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_TAGS_URL = os.environ.get("OLLAMA_TAGS_URL", OLLAMA_URL.rsplit("/", 1)[0] + "/tags")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")
PUBLIC_SITE_ORIGIN = os.environ.get("PUBLIC_SITE_ORIGIN", "https://foolguyisme.github.io")
PUBLIC_AI_TOKEN = os.environ.get("PUBLIC_AI_TOKEN", "")
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        f"{PUBLIC_SITE_ORIGIN},http://127.0.0.1:8000,http://localhost:8000",
    ).split(",")
    if origin.strip()
}
MAX_BODY = 24_000
MAX_REQUESTS_PER_MINUTE = 10
RATE_WINDOW_SECONDS = 60
CHAT_SEMAPHORE = threading.BoundedSemaphore(1)
REQUEST_TIMES: dict[str, deque[float]] = defaultdict(deque)
REQUEST_TIMES_LOCK = threading.Lock()

SYSTEM_PROMPT = """你是小北百貨購物 App 的繁體中文本機客服示範。
以簡短、友善的繁體中文回答，優先根據使用者問題與提供的門市/商品資料。
本網站是展示原型：價格、庫存、會員、優惠券與訂單都是模擬資料；不可宣稱查到正式 POS、付款或訂單，不可捏造庫存、門市服務或活動。
不可以結帳、送出訂單、付款、退款或修改正式訂單。
只有在購物車權限已開啟、且使用者這一則訊息明確要求把指定商品加入購物車時，才呼叫 add_products_to_cart。
只可使用 availableProducts 內的 product_id，且不可超過提供的庫存數量；單純詢問、索取建議或提及商品時不可加入。
若購物車權限未開啟，絕不可呼叫工具或聲稱商品已加入，應請使用者按下「授權 AI 加入購物車」。
若缺少資訊，請建議使用 App 的門市搜尋/訂單頁，或聯絡小北官方客服 0800-002-198。
不要要求使用者提供密碼、完整信用卡號或其他敏感個資。"""
EXPLICIT_CART_REQUEST = re.compile(
    r"(?:加入|加到|加進|放進|放入|添加|加上).{0,16}(?:購物車|購物袋)"
    r"|(?:購物車|購物袋).{0,16}(?:加入|加到|加進|放進|放入|添加|加上)"
)


def _allowed_products(context: dict) -> dict[str, dict]:
    rows = context.get("availableProducts", []) if isinstance(context, dict) else []
    allowed: dict[str, dict] = {}
    if not isinstance(rows, list):
        return allowed
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        product_id = str(row.get("id", "")).strip()
        try:
            stock = max(0, min(1000, int(row.get("stock", 0))))
        except (TypeError, ValueError):
            stock = 0
        if product_id and stock:
            allowed[product_id] = {"stock": stock, "name": str(row.get("name", ""))[:120]}
    return allowed


def _cart_tool(product_ids: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "add_products_to_cart",
            "description": (
                "Add explicitly requested in-stock products to the demo shopping cart. "
                "Use only when the latest user message clearly asks to add or buy the named items. "
                "Never check out or pay."
            ),
            "parameters": {
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "required": ["product_id", "quantity"],
                            "properties": {
                                "product_id": {"type": "string", "enum": product_ids},
                                "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
                            },
                            "additionalProperties": False,
                        },
                    }
                },
                "additionalProperties": False,
            },
        },
    }


def _validated_cart_action(tool_calls: list, allowed: dict[str, dict]) -> dict | None:
    items_by_id: dict[str, int] = {}
    for call in tool_calls[:5]:
        if not isinstance(call, dict):
            continue
        function = call.get("function", {})
        if not isinstance(function, dict) or function.get("name") != "add_products_to_cart":
            continue
        args = function.get("arguments", {})
        if not isinstance(args, dict):
            continue
        rows = args.get("items", [])
        if not isinstance(rows, list):
            continue
        for row in rows[:5]:
            if not isinstance(row, dict):
                continue
            product_id = str(row.get("product_id", "")).strip()
            product = allowed.get(product_id)
            if not product:
                continue
            try:
                quantity = int(row.get("quantity", 0))
            except (TypeError, ValueError):
                continue
            quantity = max(0, min(10, product["stock"], quantity))
            if quantity:
                items_by_id[product_id] = min(
                    product["stock"], items_by_id.get(product_id, 0) + quantity
                )
    if not items_by_id:
        return None
    return {
        "type": "add_to_cart",
        "items": [{"product_id": key, "quantity": value} for key, value in items_by_id.items()],
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return not origin or origin in ALLOWED_ORIGINS

    def _apply_cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Max-Age", "600")

    def _authorized(self) -> bool:
        origin = self.headers.get("Origin", "")
        from_tunnel = bool(self.headers.get("CF-Connecting-IP") or self.headers.get("CF-Ray"))
        public_browser = origin == PUBLIC_SITE_ORIGIN
        if not (from_tunnel or public_browser):
            return True
        if not PUBLIC_AI_TOKEN:
            return False
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return supplied.startswith(prefix) and hmac.compare_digest(
            supplied[len(prefix):], PUBLIC_AI_TOKEN
        )

    def _json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._apply_cors()
        self.end_headers()
        self.wfile.write(data)

    def _client_key(self) -> str:
        forwarded = self.headers.get("CF-Connecting-IP", "").strip()
        if forwarded and len(forwarded) <= 64:
            return forwarded
        return self.client_address[0]

    def _within_rate_limit(self) -> bool:
        key = self._client_key()
        now = time.monotonic()
        with REQUEST_TIMES_LOCK:
            times = REQUEST_TIMES[key]
            while times and now - times[0] > RATE_WINDOW_SECONDS:
                times.popleft()
            if len(times) >= MAX_REQUESTS_PER_MINUTE:
                return False
            times.append(now)
            if len(REQUEST_TIMES) > 2000:
                for stale in [k for k, v in REQUEST_TIMES.items() if not v]:
                    REQUEST_TIMES.pop(stale, None)
        return True

    def do_OPTIONS(self):
        if self.path.split("?", 1)[0] not in ("/api/chat", "/api/health"):
            self._json(404, {"error": "not found"})
            return
        if not self._origin_allowed():
            self._json(403, {"error": "origin not allowed"})
            return
        self.send_response(204)
        self._apply_cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/api/health", "/api/chat"):
            if not self._origin_allowed():
                self._json(403, {"error": "origin not allowed"})
                return
            if not self._authorized():
                self._json(401, {"error": "valid access code required"})
                return
        if path == "/api/health":
            try:
                with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=3) as response:
                    data = json.loads(response.read().decode("utf-8"))
                names = [item.get("name", "") for item in data.get("models", [])]
                ok = MODEL in names
                self._json(200 if ok else 503, {"ok": ok, "model": MODEL, "installed": names})
            except Exception as exc:
                self._json(503, {"ok": False, "model": MODEL, "error": str(exc)})
            return
        if path == "/api/chat":
            self._json(405, {"error": "method not allowed"})
            return
        if path == "/":
            self.path = "/xiaobei-smart-shopping-app.html"
        elif path not in ("/xiaobei-smart-shopping-app.html", "/stores-tw.js", "/qrcode.min.js"):
            self._json(404, {"error": "not found"})
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/chat":
            self._json(404, {"error": "not found"})
            return
        if not self._origin_allowed():
            self._json(403, {"error": "origin not allowed"})
            return
        if not self._authorized():
            self._json(401, {"error": "valid access code required"})
            return
        if not self._within_rate_limit():
            self._json(429, {"error": "請稍候再試，本機客服目前有請求頻率限制。"})
            return
        length_text = self.headers.get("Content-Length", "0")
        try:
            length = int(length_text)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._json(413, {"error": "request too large"})
            return
        if not CHAT_SEMAPHORE.acquire(blocking=False):
            self._json(429, {"error": "本機 AI 正在處理其他問題，請稍後重試。"})
            return
        try:
            request_data = json.loads(self.rfile.read(length).decode("utf-8"))
            message = str(request_data.get("message", "")).strip()[:2000]
            if not message:
                self._json(400, {"error": "message is required"})
                return
            context = request_data.get("context", {})
            context_text = json.dumps(context, ensure_ascii=False)[:12_000]
            allowed_products = _allowed_products(context)
            history = request_data.get("history", [])
            history_messages = []
            if isinstance(history, list):
                for item in history[-8:]:
                    if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
                        continue
                    content = str(item.get("content", "")).strip()[:1200]
                    if content:
                        history_messages.append({"role": item["role"], "content": content})
            cart_permission = request_data.get("cart_permission") is True
            explicit_cart_request = bool(EXPLICIT_CART_REQUEST.search(message))
            allow_cart_action = cart_permission and explicit_cart_request
            system_prompt = SYSTEM_PROMPT
            if allow_cart_action:
                system_prompt += "\n購物車權限已由使用者按鈕開啟，而且本則訊息明確要求加入購物車；仍只可處理這一則訊息中明確指定的商品。"
            else:
                system_prompt += "\n本則訊息沒有同時符合購物車授權與明確加入要求；不可提出或執行購物車操作，也不可聲稱已修改購物車。"
            body = {
                "model": MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    *history_messages,
                    {"role": "user", "content": f"App context (simulated data): {context_text}\n\nUser question: {message}"},
                ],
                "options": {"temperature": 0.1, "num_ctx": 2048, "num_predict": 280},
            }
            if allow_cart_action and allowed_products:
                body["tools"] = [_cart_tool(list(allowed_products))]
            req = urllib.request.Request(
                OLLAMA_URL,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
            assistant_message = result.get("message", {})
            reply = str(assistant_message.get("content", "")).strip()
            tool_calls = assistant_message.get("tool_calls", [])
            cart_action = (
                _validated_cart_action(tool_calls, allowed_products)
                if allow_cart_action and isinstance(tool_calls, list)
                else None
            )
            if not allow_cart_action and re.search(
                r"(?:已加入|已經加入|已放進|已放入|幫你加入|已為你加入).{0,12}購物車", reply
            ):
                reply = "目前沒有取得符合條件的購物車操作授權，因此我沒有修改購物車。若要加入商品，請按下授權按鈕，再明確說出要加入購物車的商品。"
            if not reply and cart_action:
                reply = "已找到你指定的商品，正準備加入購物車。"
            if not reply:
                self._json(502, {"error": "empty response from local model"})
                return
            self._json(
                200,
                {"reply": reply, "model": MODEL, "mode": "local", "cart_action": cart_action},
            )
        except urllib.error.URLError as exc:
            self._json(503, {"error": f"Ollama is unavailable: {exc}"})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": f"invalid request: {exc}"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})
        finally:
            CHAT_SEMAPHORE.release()

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Xiaobei app: http://{host}:{port}/")
    print(f"Local LLM: {MODEL} via {OLLAMA_URL}")
    print("This server listens on loopback; only the Cloudflare Tunnel should expose the API.")
    if os.environ.get("OPEN_BROWSER", "1") == "1" and host in ("127.0.0.1", "localhost"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        server.server_close()
