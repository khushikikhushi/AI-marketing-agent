"""Settings you enter inside the app (API keys, Instagram connections, test mode).
Secrets are encrypted on disk with a key derived from SECRET_KEY, and are never sent back to the browser."""
import base64
import hashlib
import json
import os
import secrets
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

import store

FILE = store.DATA_DIR / "settings.json"
KEYFILE = store.DATA_DIR / ".secret_key"
_lock = threading.RLock()


def secret_key():
    """SECRET_KEY from the environment (Render generates one), or a random one kept on the data disk."""
    k = os.getenv("SECRET_KEY", "").strip()
    if k:
        return k
    if not KEYFILE.exists():
        KEYFILE.write_text(secrets.token_urlsafe(48))
    return KEYFILE.read_text().strip()


def _fernet():
    digest = hashlib.sha256(("studio-settings:" + secret_key()).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _load():
    if not FILE.exists():
        return {}
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    tmp.replace(FILE)


def get(name, default=None):
    with _lock:
        return _load().get(name, default)


def put(name, value):
    with _lock:
        d = _load()
        if value is None:
            d.pop(name, None)
        else:
            d[name] = value
        _save(d)


def get_secret(name):
    v = get(name)
    if not v:
        return ""
    try:
        return _fernet().decrypt(v.encode()).decode()
    except InvalidToken:
        return ""


def put_secret(name, value):
    put(name, _fernet().encrypt(value.encode()).decode() if value else None)


def masked(value):
    return (value[:3] + "…" + value[-4:]) if value and len(value) > 10 else ("set" if value else "")


# ---- convenience ----

def openai_key():
    """The key entered in the app wins; .env / Render environment is the fallback."""
    return get_secret("openai_api_key") or os.getenv("OPENAI_API_KEY", "").strip()


def meta_app():
    app_id = get("meta_app_id") or os.getenv("META_APP_ID", "").strip()
    secret = get_secret("meta_app_secret") or os.getenv("META_APP_SECRET", "").strip()
    return app_id, secret


def ig_test_mode():
    v = get("ig_test_mode")
    if v is None:
        return os.getenv("IG_TEST_MODE", "true").strip().lower() != "false"
    return bool(v)


def ig_accounts():
    """{brand_slug: {"user_id", "username", "account_type", "expires_at", "connected_at", "connected_by"}} — tokens kept encrypted separately."""
    return get("ig_accounts") or {}


def ig_token(brand):
    return get_secret(f"ig_token__{brand}")


def save_ig_account(brand, token, info):
    put_secret(f"ig_token__{brand}", token)
    accts = ig_accounts()
    accts[brand] = info
    put("ig_accounts", accts)


def remove_ig_account(brand):
    put(f"ig_token__{brand}", None)
    accts = ig_accounts()
    accts.pop(brand, None)
    put("ig_accounts", accts)


def public_base_url():
    """The app's public https address: Render provides RENDER_EXTERNAL_URL automatically."""
    return (os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")


def hosted():
    return bool(os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_URL") or os.getenv("HOSTED"))
