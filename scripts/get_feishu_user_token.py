#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import time

from feishu_token_utils import (
    get_env_or_default,
    get_app_access_token,
    get_required_env,
    load_dotenv,
    request_json,
    write_saved_token,
)

load_dotenv()


FEISHU_BASE_URL = get_env_or_default("FEISHU_BASE_URL", "https://open.feishu.cn")
FEISHU_REDIRECT_HOST = get_env_or_default("FEISHU_REDIRECT_HOST", "127.0.0.1")
FEISHU_REDIRECT_PORT = int(get_env_or_default("FEISHU_REDIRECT_PORT", "3333"))
FEISHU_REDIRECT_PATH = get_env_or_default("FEISHU_REDIRECT_PATH", "/feishu/callback")
SKILL_ROOT = Path(__file__).resolve().parent.parent
SKILL_SLUG = SKILL_ROOT.name
USER_STATE_DIR = Path.home() / ".codex" / "skills" / SKILL_SLUG
FEISHU_TOKEN_OUTPUT = get_env_or_default(
    "FEISHU_TOKEN_OUTPUT", str(USER_STATE_DIR / "feishu-user-token.json")
)
FEISHU_OAUTH_SCOPES = get_env_or_default("FEISHU_OAUTH_SCOPES", "")
FEISHU_STATE_STORE = Path(
    get_env_or_default(
        "FEISHU_STATE_STORE",
        str(USER_STATE_DIR / "oauth-state.json"),
    )
).expanduser()
FEISHU_STATE_TTL_SECONDS = int(get_env_or_default("FEISHU_STATE_TTL_SECONDS", "600"))


def get_redirect_uri() -> str:
    return f"http://{FEISHU_REDIRECT_HOST}:{FEISHU_REDIRECT_PORT}{FEISHU_REDIRECT_PATH}"


def get_normalized_scopes() -> str | None:
    scopes = [item.strip() for item in FEISHU_OAUTH_SCOPES.split(",") if item.strip()]
    return ",".join(scopes) if scopes else None


def load_state_store() -> dict:
    if not FEISHU_STATE_STORE.exists():
        return {"states": []}

    try:
        return json.loads(FEISHU_STATE_STORE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"states": []}


def save_state_store(store: dict) -> None:
    FEISHU_STATE_STORE.parent.mkdir(parents=True, exist_ok=True)
    FEISHU_STATE_STORE.write_text(
        json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def prune_states(store: dict) -> dict:
    now = int(time())
    store["states"] = [
        item
        for item in store.get("states", [])
        if int(item.get("expires_at", 0)) > now and not item.get("used", False)
    ]
    return store


def register_state(state: str) -> None:
    now = int(time())
    # Keep a single fresh state entry per authorization attempt to avoid
    # stale-but-valid states from older runs causing confusion during testing.
    store = {"states": []}
    store["states"].append(
        {
            "state": state,
            "created_at": now,
            "expires_at": now + FEISHU_STATE_TTL_SECONDS,
            "used": False,
        }
    )
    save_state_store(store)


def validate_and_consume_state(state: str | None) -> tuple[bool, str]:
    if not state:
        return False, "Missing state parameter."

    store = load_state_store()
    now = int(time())
    states = store.get("states", [])

    for item in states:
        if item.get("state") != state:
            continue

        if item.get("used", False):
            return False, "State was already used."

        if int(item.get("expires_at", 0)) <= now:
            return False, "State expired. Generate a fresh authorization URL."

        item["used"] = True
        item["used_at"] = now
        save_state_store(prune_states(store))
        return True, "State validated."

    return False, "State not found. Generate a fresh authorization URL."


def try_open_browser(url: str) -> bool:
    if os.name == "nt":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        except OSError:
            pass

        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            pass

    try:
        return bool(webbrowser.open(url, new=1))
    except webbrowser.Error:
        return False


def exchange_code_for_user_token(code: str) -> dict:
    body = {
        "grant_type": "authorization_code",
        "code": code,
    }
    scopes = get_normalized_scopes()
    if scopes:
        body["scope"] = scopes

    payload = request_json(
        f"{FEISHU_BASE_URL}/open-apis/authen/v1/access_token",
        "POST",
        {
            "Authorization": f"Bearer {get_app_access_token()}",
        },
        body,
    )
    token_data = payload.get("data", {})
    if payload.get("code") != 0 or not token_data.get("access_token"):
        raise RuntimeError(
            f"Failed to get user_access_token: {json.dumps(payload, ensure_ascii=False)}"
        )
    return token_data


def save_token_file(token_data: dict) -> Path:
    return write_saved_token(token_data)


def get_authorize_url(state: str) -> str:
    query = {
        "app_id": get_required_env("FEISHU_APP_ID"),
        "redirect_uri": get_redirect_uri(),
        "state": state,
    }
    scopes = get_normalized_scopes()
    if scopes:
        query["scope"] = scopes
    return (
        f"{FEISHU_BASE_URL}/open-apis/authen/v1/index?{urllib.parse.urlencode(query)}"
    )


def wait_for_authorization_code(expected_state: str) -> str:
    class CallbackHandler(BaseHTTPRequestHandler):
        server_version = "FeishuOAuthCallback/1.0"

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != FEISHU_REDIRECT_PATH:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            query = urllib.parse.parse_qs(parsed.query)
            code = query.get("code", [None])[0]
            returned_state = query.get("state", [None])[0]
            valid_state, state_message = validate_and_consume_state(returned_state)
            if not code:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Invalid callback payload: missing code parameter.")
                self.server.authorization_code = None
                self.server.error_message = (
                    "Invalid callback payload: missing code parameter."
                )
                return

            if not valid_state:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    f"Invalid callback payload: {state_message}".encode("utf-8")
                )
                self.server.authorization_code = None
                self.server.error_message = f"Invalid callback payload: {state_message}"
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Feishu authorization received.</h2><p>You can close this window now.</p></body></html>"
            )
            self.server.authorization_code = code

        def log_message(self, format, *args):
            return

    httpd = HTTPServer((FEISHU_REDIRECT_HOST, FEISHU_REDIRECT_PORT), CallbackHandler)
    httpd.authorization_code = None
    httpd.error_message = None
    print(f"Listening for Feishu callback at {get_redirect_uri()}")

    while httpd.authorization_code is None:
        httpd.handle_request()
        if httpd.error_message:
            raise RuntimeError(httpd.error_message)

    return httpd.authorization_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Obtain a Feishu user_access_token with explicit OAuth scopes."
    )
    parser.add_argument(
        "--code", help="Optional authorization code for manual exchange."
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open the authorization URL in the default browser.",
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Only print the authorization URL and exit without starting a callback server.",
    )
    args = parser.parse_args()

    if args.code:
        token_data = exchange_code_for_user_token(args.code)
        output_path = save_token_file(token_data)
        print(
            json.dumps(
                {"ok": True, "output_file": str(output_path), **token_data},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    state = str(uuid.uuid4())
    register_state(state)
    authorize_url = get_authorize_url(state)
    print("Open this URL in your browser and complete authorization:")
    print(authorize_url)
    print("")
    print(f"State will remain valid for {FEISHU_STATE_TTL_SECONDS} seconds.")
    print(f"State store: {FEISHU_STATE_STORE}")
    print("")

    if args.print_url:
        print("Print-url mode enabled. No callback server was started.")
        return 0

    if not args.no_browser:
        opened = try_open_browser(authorize_url)
        if opened:
            print("Attempted to open the default browser automatically.")
        else:
            print(
                "Could not open the browser automatically. Please open the URL manually."
            )
        print("")

    print(
        "If callback handling is unreliable, copy the authorization code from the redirect URL and rerun with:"
    )
    print('python scripts/get_feishu_user_token.py --code "<authorization_code>"')
    print("")

    code = wait_for_authorization_code(state)
    token_data = exchange_code_for_user_token(code)
    output_path = save_token_file(token_data)
    print(
        json.dumps(
            {"ok": True, "output_file": str(output_path), **token_data},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
