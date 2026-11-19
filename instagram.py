"""Official Instagram publishing (Instagram API with Instagram Login — graph.instagram.com).

How Instagram publishing works: Instagram downloads the image from a PUBLIC https URL (JPEG only), you create a "media
container", wait until it's ready, then publish it. This app never publishes on its own — publish() is only ever called from
the APPROVE & PUBLISH button, and while IG_TEST_MODE is on (the default) nothing is sent to Instagram at all."""
import os
import time
import urllib.parse

import requests

import settings


class IGError(Exception):
    def __init__(self, message, sent=False):
        super().__init__(message)
        self.sent = sent  # True if the final publish request may have reached Instagram


def test_mode():
    return settings.ig_test_mode()


def token(brand=None):
    """The token for a brand's connected account; falls back to IG_ACCESS_TOKEN from .env (local single-account setup)."""
    if brand:
        t = settings.ig_token(brand)
        if t:
            return t
    t = os.getenv("IG_ACCESS_TOKEN", "").strip()
    return "" if t.startswith("paste") else t


def configured(brand=None):
    return bool(token(brand))


def _base():
    host = os.getenv("IG_API_HOST", "https://graph.instagram.com").rstrip("/")
    ver = os.getenv("IG_API_VERSION", "").strip().strip("/")
    return f"{host}/{ver}" if ver else host


def _req(method, path, tok=None, **params):
    tok = tok or token()
    if not tok:
        raise IGError("This brand's Instagram account isn't connected yet. An admin can connect it in Settings.")
    params["access_token"] = tok
    try:
        r = requests.request(method, f"{_base()}/{path.lstrip('/')}", params=params if method == "GET" else None,
                             data=params if method != "GET" else None, timeout=60)
    except requests.RequestException as e:
        raise IGError(f"Couldn't reach Instagram: {e}")
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        msg = err.get("error_user_msg") or err.get("message") or f"HTTP {r.status_code}"
        code = err.get("code")
        if code == 190:
            msg = "Your Instagram access token is invalid or expired. Generate a new one (README → Instagram) and update .env."
        raise IGError(f"Instagram said: {msg}")
    return data


def account(tok=None):
    """Read-only check of the connected account (safe in test mode)."""
    me = _req("GET", "me", tok, fields="user_id,username,account_type,profile_picture_url,name")
    ig_id = str(me.get("user_id") or me.get("id") or "") or os.getenv("IG_USER_ID", "").strip()
    limit = None
    try:
        lim = _req("GET", f"{ig_id}/content_publishing_limit", tok, fields="quota_usage,config")
        d = (lim.get("data") or [{}])[0]
        limit = {"used": d.get("quota_usage"), "total": (d.get("config") or {}).get("quota_total")}
    except IGError:
        pass
    return {"id": ig_id, "username": me.get("username"), "account_type": me.get("account_type"),
            "name": me.get("name"), "picture": me.get("profile_picture_url"), "limit": limit}


def _wait_ready(container_id, log, tok, timeout=120):
    start = time.time()
    while True:
        st = _req("GET", container_id, tok, fields="status_code,status")
        code = st.get("status_code")
        if code in ("FINISHED", None):
            return
        if code in ("ERROR", "EXPIRED"):
            raise IGError(f"Instagram couldn't process the image ({st.get('status') or code}).")
        if time.time() - start > timeout:
            raise IGError("Instagram took too long to process the image. Nothing was published; you can try again.")
        log(f"Instagram is processing… ({code})")
        time.sleep(3)


def publish(image_urls, caption, fmt, log, tok=None):
    """image_urls: public JPEG URLs (one, or several for a carousel). Returns {media_id, permalink}.
    Raises IGError; err.sent tells whether the final publish call may have gone through."""
    tok = tok or token()
    ig = account(tok)["id"]
    if fmt == "carousel" and len(image_urls) > 1:
        children = []
        for i, url in enumerate(image_urls[:10]):
            log(f"Uploading slide {i + 1} of {len(image_urls)}…")
            c = _req("POST", f"{ig}/media", tok, image_url=url, is_carousel_item="true")
            children.append(c["id"])
        for cid in children:
            _wait_ready(cid, log, tok)
        log("Creating the carousel…")
        container = _req("POST", f"{ig}/media", tok, media_type="CAROUSEL", children=",".join(children), caption=caption)["id"]
    elif fmt == "story":
        log("Uploading the story image…")
        container = _req("POST", f"{ig}/media", tok, image_url=image_urls[0], media_type="STORIES")["id"]
    else:
        log("Uploading the image…")
        container = _req("POST", f"{ig}/media", tok, image_url=image_urls[0], caption=caption)["id"]
    _wait_ready(container, log, tok)
    log("Publishing…")
    try:
        res = _req("POST", f"{ig}/media_publish", tok, creation_id=container)
    except IGError as e:
        e.sent = True  # the request was made; Instagram may or may not have published
        raise
    media_id = res.get("id")
    permalink = None
    try:
        permalink = _req("GET", media_id, tok, fields="permalink").get("permalink")
    except IGError:
        pass
    return {"media_id": media_id, "permalink": permalink, "container_id": container}


# ---------------- "Log in with Instagram" (Instagram API with Instagram Login) ----------------

SCOPES = "instagram_business_basic,instagram_business_content_publish"


def authorize_url(app_id, redirect_uri, state):
    q = urllib.parse.urlencode({"client_id": app_id, "redirect_uri": redirect_uri, "response_type": "code",
                                "scope": SCOPES, "state": state, "force_reauth": "true"})
    return f"https://www.instagram.com/oauth/authorize?{q}"


def _json(r):
    try:
        d = r.json()
    except ValueError:
        d = {}
    if r.status_code >= 400 or (isinstance(d, dict) and ("error" in d or "error_type" in d)):
        err = d.get("error") if isinstance(d.get("error"), dict) else d
        msg = (err or {}).get("error_message") or (err or {}).get("message") or f"HTTP {r.status_code}"
        raise IGError(f"Instagram login failed: {msg}")
    return d


def connect_with_code(app_id, app_secret, redirect_uri, code):
    """Swap the login code for a long-lived (about 60-day) token. Returns (token, info)."""
    code = code.split("#")[0]
    r = requests.post("https://api.instagram.com/oauth/access_token", data={
        "client_id": app_id, "client_secret": app_secret, "grant_type": "authorization_code",
        "redirect_uri": redirect_uri, "code": code}, timeout=30)
    d = _json(r)
    if isinstance(d.get("data"), list) and d["data"]:
        d = d["data"][0]
    short = d.get("access_token")
    if not short:
        raise IGError("Instagram login didn't return a token.")
    r = requests.get("https://graph.instagram.com/access_token", params={
        "grant_type": "ig_exchange_token", "client_secret": app_secret, "access_token": short}, timeout=30)
    d2 = _json(r)
    long_tok = d2.get("access_token") or short
    expires_in = int(d2.get("expires_in") or 3600)
    acc = account(long_tok)
    if (acc.get("account_type") or "").upper() not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR", ""):
        raise IGError("That Instagram account isn't a Professional (Business or Creator) account, so it can't publish through the API.")
    info = {"user_id": acc["id"], "username": acc.get("username"), "account_type": acc.get("account_type"),
            "picture": acc.get("picture"), "expires_at": int(time.time()) + expires_in}
    return long_tok, info


def refresh(tok):
    """Extend a long-lived token by another ~60 days (allowed once it's at least 24 hours old)."""
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": tok}, timeout=30)
    d = _json(r)
    return d["access_token"], int(time.time()) + int(d.get("expires_in") or 5184000)
