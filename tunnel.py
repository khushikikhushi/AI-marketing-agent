"""A temporary public link so Instagram can download the approved image.

Instagram only accepts images from a public https address. Your app runs privately on your computer, so for the few
seconds of publishing we open a Cloudflare quick tunnel (free, no account). The app refuses every request that arrives
through the tunnel except the one approved image, behind a random one-time token. You can instead set PUBLIC_BASE_URL in
.env if you host the app somewhere public yourself."""
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
_proc = None
_url = None
_lock = threading.Lock()


def executable():
    for cand in [BASE / "tools" / "cloudflared.exe", BASE / "tools" / "cloudflared"]:
        if cand.exists():
            return str(cand)
    return shutil.which("cloudflared")


def public_base():
    env = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if env:
        return env
    return _url if (_proc and _proc.poll() is None) else None


def start(port, timeout=40):
    """Start (or reuse) the tunnel and return its https URL."""
    global _proc, _url
    if os.getenv("PUBLIC_BASE_URL", "").strip():
        return public_base()
    with _lock:
        if _proc and _proc.poll() is None and _url:
            return _url
        exe = executable()
        if not exe:
            raise RuntimeError("The public-link tool (cloudflared) isn't installed. Run setup.bat again — it downloads it — "
                               "or set PUBLIC_BASE_URL in .env.")
        _url = None
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        _proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags)
        found = {}

        def reader():
            for line in _proc.stdout:
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m and "url" not in found:
                    found["url"] = m.group(0)
        threading.Thread(target=reader, daemon=True).start()
        start_t = time.time()
        while "url" not in found:
            if _proc.poll() is not None:
                raise RuntimeError("The public link couldn't start (cloudflared exited). Check your internet connection.")
            if time.time() - start_t > timeout:
                stop()
                raise RuntimeError("The public link took too long to start. Try again in a minute.")
            time.sleep(0.3)
        _url = found["url"]
        time.sleep(4)  # give Cloudflare a moment to route the new hostname
        return _url


def stop():
    global _proc, _url
    with _lock:
        if _proc and _proc.poll() is None:
            _proc.terminate()
        _proc, _url = None, None
