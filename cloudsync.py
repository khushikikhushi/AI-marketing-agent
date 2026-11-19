"""Keeps the studio's data safe when the server's own disk is temporary (Render's free plan).

Everything lives in DATA_DIR as normal files. When SUPABASE_URL and SUPABASE_SERVICE_KEY are set:
  - on start-up, the small files (accounts, settings, campaigns, brands) are restored from Supabase Storage;
  - images are fetched the first time something needs them (ensure());
  - every few seconds, new or changed files are uploaded; deletions are mirrored.
Without those settings this module does nothing and the app uses the local disk as before."""
import mimetypes
import os
import threading
import time
from pathlib import Path

import requests

import store

URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
BUCKET = os.getenv("SUPABASE_BUCKET", "studio-data").strip()
ROOT = store.DATA_DIR
LAZY_DIRS = ("renders", "uploads", "generated", "approvals", "exports")  # big files: fetched on demand
SKIP = {".secret_key"}

_lock = threading.RLock()
_known = {}      # relative path -> (mtime, size) as last uploaded / downloaded
_remote = set()  # relative paths known to exist remotely
_pending_deletes = set()
_ready = False
_error = None
_last_try = 0.0


def enabled():
    return bool(URL and KEY)


def _h(extra=None):
    # New Supabase keys (sb_secret_...) are sent in the apikey header only; legacy service_role keys also as Bearer.
    h = {"apikey": KEY} if KEY.startswith("sb_") else {"Authorization": f"Bearer {KEY}", "apikey": KEY}
    if extra:
        h.update(extra)
    return h


def _rel(path):
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return None


def _is_lazy(rel):
    parts = rel.split("/")
    return len(parts) >= 3 and parts[0] == "projects" and parts[2] in LAZY_DIRS or parts[0] == "tests"


# ---------------- Supabase Storage REST ----------------

def _ensure_bucket():
    r = requests.get(f"{URL}/storage/v1/bucket/{BUCKET}", headers=_h(), timeout=30)
    if r.status_code == 200:
        return
    r = requests.post(f"{URL}/storage/v1/bucket", headers=_h({"Content-Type": "application/json"}),
                      json={"id": BUCKET, "name": BUCKET, "public": False}, timeout=30)
    if r.status_code not in (200, 201) and "already exists" not in r.text.lower():
        raise RuntimeError(f"Couldn't create the Supabase storage bucket: {r.status_code} {r.text[:200]}")


def _list(prefix=""):
    """All object paths under prefix (recursive)."""
    out, stack = [], [prefix]
    while stack:
        pre = stack.pop()
        offset = 0
        while True:
            r = requests.post(f"{URL}/storage/v1/object/list/{BUCKET}", headers=_h({"Content-Type": "application/json"}),
                              json={"prefix": pre, "limit": 1000, "offset": offset, "sortBy": {"column": "name", "order": "asc"}},
                              timeout=60)
            r.raise_for_status()
            items = r.json()
            for it in items:
                name = (pre.rstrip("/") + "/" + it["name"]).lstrip("/") if pre else it["name"]
                if it.get("id") is None and not it.get("metadata"):
                    stack.append(name + "/")   # a folder
                else:
                    out.append(name)
            if len(items) < 1000:
                break
            offset += 1000
    return out


def _download(rel):
    r = requests.get(f"{URL}/storage/v1/object/{BUCKET}/{rel}", headers=_h(), timeout=120)
    if r.status_code != 200:
        return False
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".dl")
    tmp.write_bytes(r.content)
    tmp.replace(p)
    st = p.stat()
    _known[rel] = (st.st_mtime, st.st_size)
    _remote.add(rel)
    return True


def _upload(rel):
    p = ROOT / rel
    if not p.exists():
        return
    st = p.stat()
    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    with p.open("rb") as f:
        r = requests.post(f"{URL}/storage/v1/object/{BUCKET}/{rel}", data=f,
                          headers=_h({"Content-Type": ctype, "x-upsert": "true", "cache-control": "no-cache"}), timeout=180)
    if r.status_code in (200, 201):
        _known[rel] = (st.st_mtime, st.st_size)
        _remote.add(rel)
    else:
        print(f"  [cloudsync] upload failed for {rel}: {r.status_code} {r.text[:120]}")


def _delete(rels):
    rels = [r for r in rels if r in _remote]
    for i in range(0, len(rels), 500):
        chunk = rels[i:i + 500]
        requests.delete(f"{URL}/storage/v1/object/{BUCKET}", headers=_h({"Content-Type": "application/json"}),
                        json={"prefixes": chunk}, timeout=60)
        for r in chunk:
            _remote.discard(r)
            _known.pop(r, None)


# ---------------- public API ----------------

def restore():
    """Call at start-up, before anything reads DATA_DIR. Never raises: on failure the app shows a clear message."""
    global _ready, _error, _last_try
    if not enabled() or _ready:
        return
    _last_try = time.time()
    try:
        _restore()
        _error = None
    except Exception as e:
        _error = ("Can't reach your Supabase storage, so the studio is paused to keep your data safe. "
                  "If your free Supabase project was paused after a quiet week, open supabase.com, select the project, "
                  "click Restore, wait a minute, then reload this page.")
        print(f"  [cloudsync] restore failed: {e}")


def blocked():
    """True while cloud storage is configured but not yet restored (retries every 30 seconds)."""
    if not enabled() or _ready:
        return False
    if time.time() - _last_try > 30:
        with _lock:
            restore()
    return not _ready


def error():
    return _error


def _restore():
    global _ready
    t0 = time.time()
    _ensure_bucket()
    names = _list()
    eager = 0
    for rel in names:
        _remote.add(rel)
        if rel.split("/")[-1] in SKIP:
            continue
        if not _is_lazy(rel):
            if _download(rel):
                eager += 1
    _ready = True
    print(f"  [cloudsync] restored {eager} files ({len(names)} in storage) from Supabase in {time.time() - t0:.1f}s")


def ensure(path):
    """Make sure a file exists locally, fetching it from storage if needed. Returns the path."""
    p = Path(path)
    if enabled() and not p.exists():
        rel = _rel(p)
        if rel and rel in _remote:
            with _lock:
                if not p.exists():
                    _download(rel)
    return p


def flush():
    """Upload everything new or changed, and mirror deletions."""
    if not enabled() or not _ready:
        return
    with _lock:
        seen = set()
        for p in ROOT.rglob("*"):
            if not p.is_file() or p.name in SKIP or p.name.endswith((".tmp", ".dl")):
                continue
            rel = _rel(p)
            if not rel:
                continue
            seen.add(rel)
            st = p.stat()
            if _known.get(rel) != (st.st_mtime, st.st_size):
                _upload(rel)
        if _pending_deletes:
            _delete(list(_pending_deletes))
            _pending_deletes.clear()


def forget(path):
    """Mark a deleted file or folder so it is removed from storage too."""
    if not enabled():
        return
    rel = _rel(path)
    if rel is None:
        return
    with _lock:
        for r in list(_remote):
            if r == rel or r.startswith(rel.rstrip("/") + "/"):
                _pending_deletes.add(r)


def start(interval=4):
    if not enabled():
        return

    def loop():
        while True:
            try:
                flush()
            except Exception as e:
                print(f"  [cloudsync] {e}")
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True).start()


def status():
    return {"enabled": enabled(), "ready": _ready, "files": len(_remote), "bucket": BUCKET if enabled() else None}
