from __future__ import annotations

import json
import base64
import os
import queue
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
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
GITHUB_API = "https://api.github.com/repos/foolguyisme/shop"
STATUS_BRANCH = "local-ai-status"
STATUS_FILE = "Xiaobei_App_Local_AI_Bundle/live-ai.json"
TOKEN_FILE = BUNDLE / ".public-ai-token"
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


def github_headers() -> dict[str, str]:
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(WORKSPACE),
        check=False,
    )
    credentials = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    access_token = credentials.get("password", "")
    if result.returncode or not access_token:
        raise RuntimeError(
            "Could not get GitHub credentials from Windows Credential Manager. "
            "Sign in to GitHub with Git Credential Manager, then start this BAT again."
        )
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "Xiaobei-Local-AI-Status",
    }


def github_request(method: str, path: str, headers: dict[str, str], payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        GITHUB_API + path,
        data=body,
        headers={**headers, **({"Content-Type": "application/json"} if body else {})},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def github_error(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        detail = payload.get("message", "")
    except Exception:
        detail = ""
    return f"GitHub API HTTP {exc.code}" + (f": {detail}" if detail else "")


def load_public_ai_token() -> str:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8-sig").strip()
        if len(token) >= 32:
            return token
    except FileNotFoundError:
        pass

    token = secrets.token_urlsafe(24)
    try:
        with TOKEN_FILE.open("x", encoding="utf-8") as token_file:
            token_file.write(token + "\n")
    except FileExistsError:
        token = TOKEN_FILE.read_text(encoding="utf-8-sig").strip()
    if len(token) < 32:
        raise RuntimeError(f"Could not create a persistent AI token at {TOKEN_FILE}.")
    return token


def publish_live_ai_status(endpoint: str, token: str) -> None:
    headers = github_headers()
    ref_path = f"/git/ref/heads/{STATUS_BRANCH}"
    try:
        github_request("GET", ref_path, headers)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(github_error(exc)) from exc
        main_ref = github_request("GET", "/git/ref/heads/main", headers)
        try:
            github_request(
                "POST",
                "/git/refs",
                headers,
                {"ref": f"refs/heads/{STATUS_BRANCH}", "sha": main_ref["object"]["sha"]},
            )
        except urllib.error.HTTPError as create_error:
            raise RuntimeError(github_error(create_error)) from create_error

    contents_path = f"/contents/{STATUS_FILE}?ref={STATUS_BRANCH}"
    try:
        existing = github_request("GET", contents_path, headers)
        file_sha = existing.get("sha")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(github_error(exc)) from exc
        file_sha = None

    config = {
        "enabled": bool(endpoint and token),
        "endpoint": endpoint,
        "token": token,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    payload = {
        "message": "Update temporary local AI status",
        "content": base64.b64encode(
            json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("ascii"),
        "branch": STATUS_BRANCH,
    }
    if file_sha:
        payload["sha"] = file_sha
    try:
        github_request("PUT", contents_path, headers, payload)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(github_error(exc)) from exc


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
    token = ""
    live_status_published = False
    try:
        ensure_drive_alias()
        if not OLLAMA.is_file():
            raise RuntimeError(f"Ollama runtime not found: {OLLAMA}")
        if not CLOUDFLARED.is_file():
            raise RuntimeError(
                f"cloudflared was not found at {CLOUDFLARED}. "
                "Install the Cloudflare Windows binary there and run this BAT again."
            )

        token = load_public_ai_token()
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

        public_health = wait_for_json(
            tunnel_url + "/api/health",
            30,
            headers={"Authorization": f"Bearer {token}"},
        )
        if not public_health.get("ok") or public_health.get("model") != MODEL:
            raise RuntimeError("The public tunnel did not reach the expected local model.")
        print("Publishing the current AI connection for automatic website access...")
        publish_live_ai_status(tunnel_url, token)
        live_status_published = True

        print("")
        print("PUBLIC WEBSITE:", PUBLIC_SITE_URL)
        print("Visitors opening the public website will connect to this local AI automatically.")
        print("The model and Ollama remain on this computer. Press Ctrl+C to stop the tunnel and local services.")
        webbrowser.open(PUBLIC_SITE_URL)

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
        if live_status_published:
            try:
                publish_live_ai_status("", "")
                print("Public website AI status set to offline.")
            except Exception as exc:
                print(f"Could not mark the public AI status offline: {exc}")
        stop_tree(tunnel_process, "Cloudflare Tunnel")
        stop_tree(api_process, "Xiaobei API")
        stop_tree(ollama_process, "Ollama")


if __name__ == "__main__":
    raise SystemExit(run())
