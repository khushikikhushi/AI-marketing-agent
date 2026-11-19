"""Records every AI call (text tokens and images separately) so you can see what the app spends."""
import json
import os
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "data" / "usage.jsonl"
_lock = threading.Lock()


def _price(name):
    try:
        return float(os.getenv(name, "") or "nan")
    except ValueError:
        return float("nan")


def record(kind, provider, model, purpose, project=None, input_tokens=0, output_tokens=0, images=0, image_quality="", size=""):
    entry = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "provider": provider, "model": model,
             "purpose": purpose, "project": project, "input_tokens": int(input_tokens or 0),
             "output_tokens": int(output_tokens or 0), "images": int(images or 0), "quality": image_quality, "size": size}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with _lock, LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def entries():
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def summary():
    """Totals by kind, by model and by campaign. Costs only where you've set prices in .env (prices change, so none are guessed)."""
    pin, pout, pimg = _price("PRICE_TEXT_INPUT_PER_1M"), _price("PRICE_TEXT_OUTPUT_PER_1M"), _price("PRICE_PER_IMAGE")
    tot = {"text_calls": 0, "input_tokens": 0, "output_tokens": 0, "image_calls": 0, "images": 0}
    by_model, by_project, recent = {}, {}, []
    for e in entries():
        m = by_model.setdefault(f"{e['provider']} · {e['model']}", {"kind": e["kind"], "calls": 0, "input_tokens": 0, "output_tokens": 0, "images": 0})
        m["calls"] += 1
        m["input_tokens"] += e["input_tokens"]
        m["output_tokens"] += e["output_tokens"]
        m["images"] += e["images"]
        p = by_project.setdefault(e.get("project") or "—", {"text_tokens": 0, "images": 0})
        if e["kind"] == "text":
            tot["text_calls"] += 1
            tot["input_tokens"] += e["input_tokens"]
            tot["output_tokens"] += e["output_tokens"]
            p["text_tokens"] += e["input_tokens"] + e["output_tokens"]
        else:
            tot["image_calls"] += 1
            tot["images"] += e["images"]
            p["images"] += e["images"]
        recent.append(e)
    cost = {}
    if pin == pin and pout == pout:  # not NaN
        cost["text"] = round(tot["input_tokens"] / 1e6 * pin + tot["output_tokens"] / 1e6 * pout, 2)
    if pimg == pimg:
        cost["images"] = round(tot["images"] * pimg, 2)
    return {"totals": tot, "cost": cost, "by_model": by_model, "by_project": by_project, "recent": recent[-40:][::-1]}
