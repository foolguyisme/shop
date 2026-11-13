from __future__ import annotations

import json
import os
import queue
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
WORKSPACE = BUNDLE.parent
MODEL = "qwen2.5:1.5b"
OLLAMA_HOST = "127.0.0.1:11435"
OLLAMA_TAGS_URL = f"http://{OLLAMA_HOST}/api/tags"
APP_HEALTH_URL = "http://127.0.0.1:8000/api/health"
APP_URL = "http://127.0.0.1:8000/"
PUBLIC_SITE_URL = "https://foolguyisme.github.io/shop/"
PUBLIC_SITE_ORIGIN = "https://foolguyisme.github.io"
DRIVE_ALIAS = "X:"
CLOUDFLARED = WORKSPACE / "Cloudflared" / "cloudflared.exe"
OLLAMA = Path(r"X:\Ollama\ollama.exe")
MODEL_MARKER = Path(r"X:\OllamaModels\manifests\registry.ollama.ai\library\qwen2.5\1.5b")
APP_MARKER = Path(r"X:\Xiaobei_App_Local_AI_Bundle\xiaobei-smart-shopping-app.html")
QUICK_TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ensure_drive_alias() -> None:
    if APP_MARKER.is_file() and OLLAMA.is_file() and MODEL_MARKER.is_file():
        return
    result = subprocess.run(
        ["subst", DRIVE_ALIAS, str(WORKSPACE)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode or not (APP_MARKER.is_file() and OLLAMA.is_file() and MODEL_MARKER.is_file()):
        detail = (result.stderr or result.stdout or "Drive X: is in use.").strip()
        raise RuntimeError(f"Cannot map X: to the Xiaobei folder. {detail}")


def start_hidden(args: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen:
    return subprocess.Popen(
        args,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )


def wait_for_json(url: str, timeout: int, headers: dict[str, str] | None = None) -> dict:
    deadline = time.monotonic() + timeout
    last_error = "service did not respond"
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.5)
    raise RuntimeError(last_error)


def stop_tree(process: subprocess.Popen | None, name: str) -> None:
    if process is None or process.poll() is not None:
        return
    print(f"Stopping {name}...")
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()


def run() -> int:
    ollama_process = None
    api_process = None
    tunnel_process = None
    try:
        ensure_drive_alias()
        if not OLLAMA.is_file():
            raise RuntimeError(f"Ollama runtime not found: {OLLAMA}")
        if not CLOUDFLARED.is_file():
            raise RuntimeError(
                f"cloudflared was not found at {CLOUDFLARED}. "
                "Install the Cloudflare Windows binary there and run this BAT again."
            )

        token = secrets.token_urlsafe(24)
        ollama_env = os.environ.copy()
        ollama_env.update(
            {
                "OLLAMA_MODELS": r"X:\OllamaModels",
                "OLLAMA_HOST": OLLAMA_HOST,
                "OLLAMA_NO_CLOUD": "1",
            }
        )

        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", 11435)) == 0:
                raise RuntimeError(
                    "Port 11435 is already in use. Stop the old Ollama service before starting this BAT."
                )

        print("Starting local Ollama with the model stored in D:\\小北...")
        ollama_process = start_hidden([str(OLLAMA), "serve"], ollama_env, WORKSPACE)
        tags = wait_for_json(OLLAMA_TAGS_URL, 45)
        model_names = [item.get("name", "") for item in tags.get("models", [])]
        if MODEL not in model_names:
            print(f"Downloading {MODEL} into D:\\小北\\OllamaModels...")
            pull = subprocess.run([str(OLLAMA), "pull", MODEL], env=ollama_env, cwd=str(WORKSPACE))
            if pull.returncode:
                raise RuntimeError("The local model download failed.")
        if ollama_process.poll() is not None:
            raise RuntimeError("Ollama stopped unexpectedly.")

        api_env = os.environ.copy()
        api_env.update(
            {
                "APP_HOST": "127.0.0.1",
                "APP_PORT": "8000",
                "OPEN_BROWSER": "0",
                "OLLAMA_MODEL": MODEL,
                "OLLAMA_CHAT_URL": f"http://{OLLAMA_HOST}/api/chat",
                "OLLAMA_TAGS_URL": OLLAMA_TAGS_URL,
                "PUBLIC_AI_TOKEN": token,
                "PUBLIC_SITE_ORIGIN": PUBLIC_SITE_ORIGIN,
                "CORS_ALLOWED_ORIGINS": (
                    f"{PUBLIC_SITE_ORIGIN},http://127.0.0.1:8000,http://localhost:8000"
                ),
            }
        )
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", 8000)) == 0:
                raise RuntimeError(
                    "Port 8000 is already in use. Stop the existing Xiaobei web server before starting this BAT."
                )
        print("Starting the local website and authenticated AI API...")
        api_process = start_hidden([sys.executable, str(BUNDLE / "api-server.py")], api_env, BUNDLE)
        health = wait_for_json(APP_HEALTH_URL, 30)
        if not health.get("ok") or health.get("model") != MODEL:
            raise RuntimeError("The local AI API did not report the expected model.")
        if api_process.poll() is not None:
            raise RuntimeError("The local web server stopped unexpectedly.")

        print("Starting the temporary HTTPS tunnel...")
        tunnel_process = subprocess.Popen(
            [
                str(CLOUDFLARED),
                "tunnel",
                "--url",
                APP_URL,
                "--no-autoupdate",
            ],
            cwd=str(WORKSPACE),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )
        tunnel_url_queue: queue.Queue[str] = queue.Queue()

        def show_tunnel_output() -> None:
            if tunnel_process is None or tunnel_process.stdout is None:
                return
            for line in tunnel_process.stdout:
                print(line.rstrip(), flush=True)
                match = QUICK_TUNNEL_RE.search(line)
                if match:
                    tunnel_url_queue.put(match.group(0))

        threading.Thread(target=show_tunnel_output, daemon=True).start()
        try:
            tunnel_url = tunnel_url_queue.get(timeout=60)
        except queue.Empty:
            if tunnel_process.poll() is not None:
                raise RuntimeError("cloudflared stopped before creating a public URL.")
            raise RuntimeError("Timed out waiting for the Cloudflare Tunnel URL.")

        ai_link = PUBLIC_SITE_URL + "?ai_endpoint=" + urllib.parse.quote(tunnel_url, safe="")
        print("")
        print("PUBLIC WEBSITE:", PUBLIC_SITE_URL)
        print("AI-READY LINK:", ai_link)
        print("LOCAL AI ACCESS CODE:", token)
        print("Share the AI-ready link and access code only with intended visitors.")
        print("The model and Ollama remain on this computer. Press Ctrl+C to stop the tunnel and local services.")
        webbrowser.open(ai_link)

        while tunnel_process.poll() is None:
            if api_process.poll() is not None:
                raise RuntimeError("The local web server stopped.")
            if ollama_process.poll() is not None:
                raise RuntimeError("Ollama stopped.")
            time.sleep(1)
        return tunnel_process.returncode or 0
    except KeyboardInterrupt:
        print("\nStopping local AI sharing...")
        return 0
    except Exception as exc:
        print(f"\nERROR: {exc}")
        return 1
    finally:
        stop_tree(tunnel_process, "Cloudflare Tunnel")
        stop_tree(api_process, "Xiaobei API")
        stop_tree(ollama_process, "Ollama")


if __name__ == "__main__":
    raise SystemExit(run())
