"""Official Instagram publishing (Instagram API with Instagram Login — graph.instagram.com).

How Instagram publishing works: Instagram downloads the image from a PUBLIC https URL (JPEG only), you create a "media
container", wait until it's ready, then publish it. This app never publishes on its own — publish() is only ever called from
the APPROVE & PUBLISH button, and while IG_TEST_MODE is on (the default) nothing is sent to Instagram at all."""
import os
import time

import requests


class IGError(Exception):
    def __init__(self, message, sent=False):
        super().__init__(message)
        self.sent = sent  # True if the final publish request may have reached Instagram


def test_mode():
    return os.getenv("IG_TEST_MODE", "true").strip().lower() != "false"


def token():
    t = os.getenv("IG_ACCESS_TOKEN", "").strip()
    return "" if t.startswith("paste") else t


def configured():
    return bool(token())


def _base():
    host = os.getenv("IG_API_HOST", "https://graph.instagram.com").rstrip("/")
    ver = os.getenv("IG_API_VERSION", "").strip().strip("/")
    return f"{host}/{ver}" if ver else host


def _req(method, path, **params):
    if not token():
        raise IGError("Instagram isn't connected yet. Add IG_ACCESS_TOKEN to the .env file (see README → Instagram).")
    params["access_token"] = token()
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


def account():
    """Read-only check of the connected account (safe in test mode)."""
    me = _req("GET", "me", fields="user_id,username,account_type,profile_picture_url,name")
    ig_id = os.getenv("IG_USER_ID", "").strip() or str(me.get("user_id") or me.get("id") or "")
    limit = None
    try:
        lim = _req("GET", f"{ig_id}/content_publishing_limit", fields="quota_usage,config")
        d = (lim.get("data") or [{}])[0]
        limit = {"used": d.get("quota_usage"), "total": (d.get("config") or {}).get("quota_total")}
    except IGError:
        pass
    return {"id": ig_id, "username": me.get("username"), "account_type": me.get("account_type"),
            "name": me.get("name"), "picture": me.get("profile_picture_url"), "limit": limit}


def _wait_ready(container_id, log, timeout=120):
    start = time.time()
    while True:
        st = _req("GET", container_id, fields="status_code,status")
        code = st.get("status_code")
        if code in ("FINISHED", None):
            return
        if code in ("ERROR", "EXPIRED"):
            raise IGError(f"Instagram couldn't process the image ({st.get('status') or code}).")
        if time.time() - start > timeout:
            raise IGError("Instagram took too long to process the image. Nothing was published; you can try again.")
        log(f"Instagram is processing… ({code})")
        time.sleep(3)


def publish(image_urls, caption, fmt, log):
    """image_urls: public JPEG URLs (one, or several for a carousel). Returns {media_id, permalink}.
    Raises IGError; err.sent tells whether the final publish call may have gone through."""
    ig = account()["id"]
    if fmt == "carousel" and len(image_urls) > 1:
        children = []
        for i, url in enumerate(image_urls[:10]):
            log(f"Uploading slide {i + 1} of {len(image_urls)}…")
            c = _req("POST", f"{ig}/media", image_url=url, is_carousel_item="true")
            children.append(c["id"])
        for cid in children:
            _wait_ready(cid, log)
        log("Creating the carousel…")
        container = _req("POST", f"{ig}/media", media_type="CAROUSEL", children=",".join(children), caption=caption)["id"]
    elif fmt == "story":
        log("Uploading the story image…")
        container = _req("POST", f"{ig}/media", image_url=image_urls[0], media_type="STORIES")["id"]
    else:
        log("Uploading the image…")
        container = _req("POST", f"{ig}/media", image_url=image_urls[0], caption=caption)["id"]
    _wait_ready(container, log)
    log("Publishing…")
    try:
        res = _req("POST", f"{ig}/media_publish", creation_id=container)
    except IGError as e:
        e.sent = True  # the request was made; Instagram may or may not have published
        raise
    media_id = res.get("id")
    permalink = None
    try:
        permalink = _req("GET", media_id, fields="permalink").get("permalink")
    except IGError:
        pass
    return {"media_id": media_id, "permalink": permalink, "container_id": container}
