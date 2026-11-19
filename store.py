"""Saving and loading projects and brand profiles (plain JSON files on disk)."""
import json
import re
import threading
import time
import uuid
from pathlib import Path

import os
import shutil

BASE = Path(__file__).resolve().parent
# Everything that changes lives under DATA_DIR. Locally that's ./data; on Render it's the permanent disk (/data).
DATA_DIR = Path(os.getenv("DATA_DIR") or (BASE / "data")).resolve()
DATA = DATA_DIR / "projects"
DATA.mkdir(parents=True, exist_ok=True)
# Brand profiles are editable in the app (logos, references, guidelines), so they live on the data disk too.
# The copies shipped with the app are only the starting point.
BRANDS = DATA_DIR / "brands"
SEED_BRANDS = BASE / "brands"
if not BRANDS.exists():
    shutil.copytree(SEED_BRANDS, BRANDS)
else:
    for d in SEED_BRANDS.iterdir():  # add brands that ship with a newer version of the app
        if d.is_dir() and not (BRANDS / d.name).exists():
            shutil.copytree(d, BRANDS / d.name)

_lock = threading.RLock()
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_id():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def safe(name):
    if not name or not _ID_RE.match(name):
        raise ValueError("Invalid id")
    return name


# ---------- projects ----------

def project_dir(pid):
    return DATA / safe(pid)


def load(pid):
    path = project_dir(pid) / "project.json"
    if not path.exists():
        return None
    with _lock:
        return json.loads(path.read_text(encoding="utf-8"))


def save(project):
    d = project_dir(project["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "project.json.tmp"
    with _lock:
        tmp.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(d / "project.json")


def update(pid, fn):
    """Load, change with fn(project), save — all under one lock. Returns the project."""
    with _lock:
        p = load(pid)
        if p is None:
            raise KeyError(pid)
        fn(p)
        p["updated"] = now()
        save(p)
        return p


def list_projects():
    out = []
    for d in sorted(DATA.iterdir(), reverse=True):
        f = d / "project.json"
        if f.exists():
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out


def find_concept(project, cid):
    for c in project.get("concepts", []):
        if c["id"] == cid:
            return c
    raise KeyError(cid)


def recover_interrupted():
    """If the app was closed mid-generation, mark unfinished work so it can be retried."""
    for p in list_projects():
        changed = False
        if p.get("status") in ("concepting", "designing"):
            p["status"] = "error" if not p.get("concepts") else "ready"
            if not p.get("concepts"):
                p["error"] = "The app was closed while concepts were being developed. Press Retry."
            changed = True
        for a in p.get("approvals", []):
            if a.get("state") == "publishing":
                a["state"] = "unknown"
                a.setdefault("history", []).append({"at": now(), "event": "App closed while publishing — check Instagram before trying again"})
                changed = True
        for c in p.get("concepts", []):
            if c.get("status") in ("pending", "working"):
                c["status"] = "error"
                c["error"] = "Interrupted when the app was closed. Press Retry."
                changed = True
        if changed:
            save(p)


# ---------- brands ----------

def list_brands():
    out = []
    for d in sorted(BRANDS.iterdir()):
        if (d / "profile.json").exists():
            out.append(load_brand(d.name))
    return out


def load_brand(slug):
    d = BRANDS / safe(slug)
    prof = json.loads((d / "profile.json").read_text(encoding="utf-8"))
    g = d / "guidelines.md"
    prof["guidelines"] = g.read_text(encoding="utf-8") if g.exists() else ""
    r = d / "references.json"
    prof["references"] = json.loads(r.read_text(encoding="utf-8")) if r.exists() else []
    return prof


def save_brand_profile(slug, profile):
    d = BRANDS / safe(slug)
    profile = {k: v for k, v in profile.items() if k not in ("guidelines", "references")}
    (d / "profile.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")


def save_guidelines(slug, text):
    (BRANDS / safe(slug) / "guidelines.md").write_text(text, encoding="utf-8")


def save_references(slug, refs):
    (BRANDS / safe(slug) / "references.json").write_text(json.dumps(refs, indent=2, ensure_ascii=False), encoding="utf-8")
