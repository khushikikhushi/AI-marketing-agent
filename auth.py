"""Team accounts. The first person to open a fresh install creates the admin account; the admin adds everyone else."""
import json
import secrets
import threading
import time

from werkzeug.security import check_password_hash, generate_password_hash

import store

FILE = store.DATA_DIR / "users.json"
_lock = threading.RLock()
_failures = {}  # email -> [timestamps] for simple brute-force protection


def _load():
    if not FILE.exists():
        return []
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(users):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, indent=2), encoding="utf-8")
    tmp.replace(FILE)


def norm(email):
    return (email or "").strip().lower()


def has_users():
    return bool(_load())


def public(u):
    return {k: u.get(k) for k in ("id", "email", "name", "role", "created", "last_login", "must_change")}


def all_users():
    return [public(u) for u in _load()]


def find(uid):
    for u in _load():
        if u["id"] == uid:
            return u
    return None


def create(email, name, password, role="member", must_change=False):
    email = norm(email)
    if "@" not in email:
        raise ValueError("Enter a valid email address.")
    if len(password) < 10:
        raise ValueError("Passwords need at least 10 characters.")
    with _lock:
        users = _load()
        if any(u["email"] == email for u in users):
            raise ValueError("Someone with that email already has an account.")
        u = {"id": secrets.token_hex(6), "email": email, "name": (name or email.split("@")[0]).strip()[:60],
             "role": role, "pw": generate_password_hash(password), "created": store.now(), "last_login": None,
             "must_change": must_change}
        users.append(u)
        _save(users)
        return public(u)


def login(email, password):
    email = norm(email)
    now = time.time()
    recent = [t for t in _failures.get(email, []) if now - t < 900]
    if len(recent) >= 8:
        raise ValueError("Too many attempts. Wait 15 minutes and try again.")
    with _lock:
        users = _load()
        for u in users:
            if u["email"] == email and check_password_hash(u["pw"], password):
                u["last_login"] = store.now()
                _save(users)
                _failures.pop(email, None)
                return public(u)
    _failures[email] = recent + [now]
    raise ValueError("Wrong email or password.")


def set_password(uid, password):
    if len(password) < 10:
        raise ValueError("Passwords need at least 10 characters.")
    with _lock:
        users = _load()
        for u in users:
            if u["id"] == uid:
                u["pw"] = generate_password_hash(password)
                u["must_change"] = False
                _save(users)
                return public(u)
    raise ValueError("User not found.")


def remove(uid):
    with _lock:
        users = _load()
        target = next((u for u in users if u["id"] == uid), None)
        if not target:
            raise ValueError("User not found.")
        if target["role"] == "admin" and sum(1 for u in users if u["role"] == "admin") == 1:
            raise ValueError("You can't remove the only admin.")
        _save([u for u in users if u["id"] != uid])
