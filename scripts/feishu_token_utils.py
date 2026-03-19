#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SKILL_SLUG = SKILL_ROOT.name
USER_STATE_DIR = Path.home() / ".codex" / "skills" / SKILL_SLUG
DEFAULT_TOKEN_OUTPUT = USER_STATE_DIR / "feishu-user-token.json"


def load_dotenv() -> None:
    candidates = [
        Path.cwd() / ".env",
        SKILL_ROOT / ".env",
        Path(__file__).resolve().parent / ".env",
        USER_STATE_DIR / ".env",
    ]

    for env_path in candidates:
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        break


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_env_or_default(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return default

    normalized = value.strip()
    return normalized if normalized else default


def get_feishu_base_url() -> str:
    return get_env_or_default("FEISHU_BASE_URL", "https://open.feishu.cn")


def get_token_output_path() -> Path:
    return Path(get_env_or_default("FEISHU_TOKEN_OUTPUT", str(DEFAULT_TOKEN_OUTPUT))).expanduser().resolve()


def request_json(url: str, method: str, headers: dict[str, str], body: dict | None = None) -> dict:
    data = None
    final_headers = dict(headers)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        final_headers["Content-Type"] = "application/json; charset=utf-8"

    request = urllib.request.Request(url, data=data, method=method, headers=final_headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc


def get_app_access_token() -> str:
    payload = request_json(
        f"{get_feishu_base_url()}/open-apis/auth/v3/app_access_token/internal",
        "POST",
        {},
        {
            "app_id": get_required_env("FEISHU_APP_ID"),
            "app_secret": get_required_env("FEISHU_APP_SECRET"),
        },
    )
    token = payload.get("app_access_token")
    if payload.get("code") != 0 or not token:
        raise RuntimeError(f"Failed to get app_access_token: {json.dumps(payload, ensure_ascii=False)}")
    return str(token)


def normalize_token_payload(token_data: dict) -> dict:
    now = datetime.now(timezone.utc)
    normalized = dict(token_data)
    normalized["created_at"] = normalized.get("created_at") or now.isoformat()
    expires_in = int(normalized.get("expires_in") or 0)
    if expires_in > 0:
        normalized["expires_at"] = (now + timedelta(seconds=expires_in)).isoformat()
    return normalized


def write_saved_token(token_data: dict) -> Path:
    token_path = get_token_output_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        json.dumps(normalize_token_payload(token_data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return token_path


def read_saved_token() -> dict | None:
    token_path = get_token_output_path()
    if not token_path.exists():
        return None

    try:
        return json.loads(token_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def token_is_usable(token_data: dict, safety_seconds: int = 120) -> bool:
    access_token = token_data.get("access_token")
    if not access_token:
        return False

    expires_at = token_data.get("expires_at")
    if not expires_at:
        return True

    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return True

    return expiry > datetime.now(timezone.utc) + timedelta(seconds=safety_seconds)


def refresh_user_access_token(refresh_token: str) -> dict:
    payload = request_json(
        f"{get_feishu_base_url()}/open-apis/authen/v1/refresh_access_token",
        "POST",
        {
            "Authorization": f"Bearer {get_app_access_token()}",
        },
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    token_data = payload.get("data", {})
    if payload.get("code") != 0 or not token_data.get("access_token"):
        raise RuntimeError(f"Failed to refresh user_access_token: {json.dumps(payload, ensure_ascii=False)}")
    return token_data


def resolve_user_access_token(explicit_token: str | None) -> str:
    if explicit_token:
        return explicit_token

    env_token = os.environ.get("FEISHU_USER_ACCESS_TOKEN")
    if env_token:
        return env_token

    saved = read_saved_token()
    if not saved:
        raise RuntimeError(
            "No Feishu access token found. Set FEISHU_USER_ACCESS_TOKEN, use --access-token, or run get_feishu_user_token.py."
        )

    if token_is_usable(saved):
        return str(saved["access_token"])

    refresh_token = saved.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Saved Feishu token is expired and has no refresh_token. Re-run get_feishu_user_token.py.")

    refreshed = refresh_user_access_token(str(refresh_token))
    write_saved_token(refreshed)
    return str(refreshed["access_token"])
