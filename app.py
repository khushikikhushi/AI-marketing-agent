"""AI Creative Agency — run with:  python app.py   then open http://127.0.0.1:5000"""
import io
import json
import secrets
import shutil
import time as _time
import os
import re
import threading
import traceback
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

from flask import Flask, abort, jsonify, redirect, request, send_file, send_from_directory, session  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402

import auth  # noqa: E402
import settings  # noqa: E402
import agent  # noqa: E402
import imagegen  # noqa: E402
import instagram  # noqa: E402
import llm  # noqa: E402
import render  # noqa: E402
import store  # noqa: E402
import tunnel  # noqa: E402
import usage  # noqa: E402

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024
app.secret_key = settings.secret_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=settings.hosted(), PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14)
if settings.hosted():
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

pool = ThreadPoolExecutor(max_workers=3)  # how many designs the AI works on at the same time
PORT = int(os.getenv("PORT", "5000"))

ALLOWED_IMG = {".jpg", ".jpeg", ".png", ".webp"}
TONES = ["Professional & Corporate", "Premium & Luxury", "Funny & Humorous", "Relatable & Meme-style",
         "Cinematic & Emotional", "Bold & Attention-grabbing", "Educational & Informative",
         "Inspirational & Motivational", "Promotional & Advertising", "Minimalist & Elegant",
         "Experimental & Artistic", "Trend-driven & Youthful", "Surprise me"]
OBJECTIVES = ["Brand awareness", "Product promotion", "Event promotion", "Registrations", "Sales and conversions",
              "Audience engagement", "Education and information", "Community building", "Announcements",
              "General brand presence"]

PRESETS = {
    "typography": "Improve the typography: sharper hierarchy, better scale contrast, tighter kerning/leading, more intentional alignment and spacing. Keep the concept.",
    "professional": "Make it more professional and polished — cleaner, more credible, more restrained, while keeping the idea.",
    "funnier": "Make it funnier — a wittier hook and a more playful visual idea, while staying on-brand and respectful.",
    "premium": "Make it more premium — more negative space, refined typography, richer art direction and colour grading. Real premium, not fake luxury.",
    "variation": "Create a variation: keep the same concept and message, but explore a noticeably different composition and art direction.",
}


# ---------------- helpers ----------------

def brand_dir(slug):
    return store.BRANDS / store.safe(slug)


def updir(pid):
    return store.project_dir(pid) / "uploads"


def assets_for(project, brand):
    a = {u["id"]: updir(project["id"]) / u["file"] for u in project.get("uploads", [])}
    for u in project.get("uploads", []):
        if u.get("cutout"):
            a[u["id"] + "-cut"] = updir(project["id"]) / u["cutout"]
    for l in brand["logos"]:
        a[l["id"]] = brand_dir(brand["slug"]) / l["file"]
    gdir = store.project_dir(project["id"]) / "generated"
    if gdir.exists():
        for f in gdir.glob("gen-*.png"):
            a[f.stem] = f
    return a


def fonts_for(brand):
    return render.brand_font_css(brand_dir(brand["slug"]), brand)


def png_paths(pid, version):
    return [store.project_dir(pid) / p for p in version.get("pngs", [])]


def set_concept(pid, cid, **fields):
    def fn(p):
        store.find_concept(p, cid).update(fields)
    return store.update(pid, fn)


def concept_fields(c):
    return {k: c.get(k, "") for k in agent.CONCEPT_ITEM["required"]}


def current_version(c):
    vs = c.get("versions", [])
    if not vs:
        return None
    i = c.get("current", len(vs) - 1)
    return vs[i] if 0 <= i < len(vs) else vs[-1]


# ---------------- the design pipeline ----------------

MAX_REVIEWS = int(os.getenv("REVIEW_ROUNDS", "3"))  # review -> refine -> review -> refine -> review


def _render_candidate(pid, cid, vnum, tag, slides, fmt, assets, font_css=""):
    slides = [{"html": s.get("html", ""), "css": s.get("css", "")} for s in slides]
    rel = [f"renders/{cid}-v{vnum}{tag}-s{i + 1}.png" for i in range(len(slides))]
    issues = render.render_slides(slides, fmt, assets, [store.project_dir(pid) / r for r in rel], font_css=font_css)
    return {"slides_src": slides, "pngs": rel, "issues": issues}


def produce(pid, cid, fmt, instruction=None, base_version=None, other=None, concept_override=None, label=""):
    """Design (or revise) one concept, render it, run the six-part review with refine/rethink rounds, save the best."""
    llm.set_project(pid)
    project = store.load(pid)
    brand = store.load_brand(project["brief"]["brand"])
    concept = concept_override or store.find_concept(project, cid)
    cf = concept_fields(concept)
    font_css = fonts_for(brand)
    slides_count = int(project["brief"].get("slides", 5))
    assets = assets_for(project, brand)
    bdir, udir = brand_dir(brand["slug"]), updir(pid)
    vnum = len(store.find_concept(project, cid).get("versions", [])) + 1

    def make(feedback=None, tag=""):
        set_concept(pid, cid, status="working", step="Planning the composition & designing…" if not feedback else "Rethinking from scratch…", error=None)
        if feedback:
            out = agent.design(project, brand, bdir, udir, cf, fmt, slides_count, feedback=feedback)
        else:
            out = agent.design(project, brand, bdir, udir, cf, fmt, slides_count, instruction,
                               current=base_version, current_pngs=png_paths(pid, base_version) if base_version else None,
                               other=other, other_pngs=png_paths(pid, other["version"]) if other else None)
        slides = make_generated_images(pid, cid, out, assets)
        set_concept(pid, cid, step="Rendering…")
        cand = _render_candidate(pid, cid, vnum, tag, slides, fmt, assets, font_css)
        cand.update(plan=out.get("plan"), headline=out.get("headline", ""), captions=out.get("captions", {}),
                    hashtags=out.get("hashtags", []), design_notes=out.get("design_notes", ""))
        return cand

    cand = make()
    best, rounds, rethought = None, [], False
    if project["brief"].get("review", True):
        for r in range(1, MAX_REVIEWS + 1):
            set_concept(pid, cid, step=f"Creative review {r} of up to {MAX_REVIEWS}…")
            rv = agent.review(project, brand, bdir, udir, cf, fmt, cand,
                              [store.project_dir(pid) / x for x in cand["pngs"]], cand["issues"], round_no=r)
            reviews = rv.get("reviews", {})
            scores = {k: int((reviews.get(k) or {}).get("score", 0)) for k in agent.REVIEW_KEYS}
            avg = round(sum(scores.values()) / len(scores), 1)
            verdict = rv.get("verdict", "approve")
            rounds.append({"round": r, "average": avg, "verdict": verdict, "critique": rv.get("critique", "")})
            cand["review"] = {"scores": scores, "notes": {k: (reviews.get(k) or {}).get("notes", "") for k in agent.REVIEW_KEYS},
                              "critique": rv.get("critique", ""), "verdict": verdict, "average": avg}
            if best is None or avg >= best["review"]["average"]:
                best = cand
            if verdict == "approve" or r == MAX_REVIEWS:
                break
            if verdict == "rethink" and not rethought and base_version is None and other is None:
                rethought = True
                cand = make(feedback=rv.get("critique", "") + "\n" + "\n".join(
                    f"{k}: {(reviews.get(k) or {}).get('notes', '')}" for k in agent.REVIEW_KEYS), tag=f"-r{r + 1}")
                continue
            improved = rv.get("improved_slides")
            if not improved:
                break
            set_concept(pid, cid, step=f"Refining after review {r}…")
            nxt = _render_candidate(pid, cid, vnum, f"-r{r + 1}", improved, fmt, assets, font_css)
            cand = {**cand, **nxt, "review": None}
        best["review"]["rounds"] = rounds
        best["review"]["improved"] = best is not None and len(rounds) > 1
    else:
        best = cand
        best["review"] = None

    version = {"v": vnum, "format": fmt, "slides_src": best["slides_src"], "pngs": best["pngs"],
               "plan": best.get("plan"), "headline": best.get("headline", ""), "captions": best.get("captions", {}),
               "hashtags": best.get("hashtags", []), "design_notes": best.get("design_notes", ""),
               "instruction": label or instruction or "", "issues": best["issues"], "concept": cf,
               "review": best.get("review"), "created": store.now()}

    def save_version(p):
        c = store.find_concept(p, cid)
        if concept_override:
            c.update(concept_fields(concept_override))
        c.setdefault("versions", []).append(version)
        c["current"] = len(c["versions"]) - 1
        c.update(status="ready", step="", error=None)
    store.update(pid, save_version)


def make_generated_images(pid, cid, out, assets):
    """Commission the image assets the design asked for, then point the HTML at the unique saved files."""
    slides = out["slides"]
    reqs = [g for g in (out.get("generated_images") or []) if g and g.get("id") and g.get("prompt")][:2]
    if not reqs:
        return slides
    if not imagegen.enabled():
        return slides
    p = store.load(pid)
    gdir = store.project_dir(pid) / "generated"
    blob = json.dumps(slides)
    for i, g in enumerate(reqs):
        set_concept(pid, cid, step=f"Creating image {i + 1} of {len(reqs)} ({imagegen.model()})…")
        refs = []
        src = (g.get("edit_from") or "").strip()
        if src and src in assets and not src.startswith("logo"):
            refs = [assets[src]]
        fname = imagegen.make(g["prompt"], g.get("shape") or "portrait", bool(g.get("transparent")), gdir, refs)
        stem = Path(fname).stem
        assets[stem] = gdir / fname
        blob = blob.replace(f"asset://{g['id']}", f"asset://{stem}")
    return json.loads(blob)


def run_safely(pid, cid, fn, retry_action, user=None):
    llm.set_user(user)
    try:
        fn()
    except Exception as e:  # show a friendly error on the card, keep the details in the terminal
        traceback.print_exc()
        try:
            set_concept(pid, cid, status="error", step="", error=friendly(e), retry=retry_action)
        except Exception:
            traceback.print_exc()
    finally:
        finish_if_done(pid)


def friendly(e):
    if isinstance(e, instagram.IGError):
        return str(e)
    return llm.friendly_error(e)


def finish_if_done(pid):
    def fn(p):
        if p.get("status") == "designing" and all(c.get("status") in ("ready", "error") for c in p.get("concepts", [])):
            p["status"] = "ready"
    try:
        store.update(pid, fn)
    except Exception:
        traceback.print_exc()


def start_designs(pid, cids):
    p = store.load(pid)
    fmt = p["brief"]["format"]
    for cid in cids:
        set_concept(pid, cid, status="pending", step="Queued…", error=None)
        pool.submit(run_safely, pid, cid, lambda cid=cid: produce(pid, cid, fmt, label="Original design"),
                    {"action": "regenerate"}, llm.current_user())


def prepare_cutouts(pid):
    """Remove the background from each uploaded photo (once) so designs can layer type behind the subject.
    Optional: skipped quietly if the background-removal package isn't installed."""
    project = store.load(pid)
    todo = [u for u in project.get("uploads", []) if "cutout" not in u]
    if not todo:
        return
    try:
        from rembg import new_session, remove
    except Exception:
        store.update(pid, lambda p: [u.setdefault("cutout", None) for u in p.get("uploads", [])])
        return
    store.update(pid, lambda p: p.update(stage="Cutting out subjects from your photos…"))
    session = new_session("u2net")
    results = {}
    for u in todo:
        try:
            im = Image.open(updir(pid) / u["file"]).convert("RGB")
            out = remove(im, session=session)
            alpha = out.split()[3]
            coverage = sum(alpha.point(lambda v: 255 if v > 128 else 0).histogram()[255:]) / (im.width * im.height)
            if 0.03 < coverage < 0.9:  # a real subject, not empty and not the whole frame
                fname = f"{u['id']}-cut.png"
                out.save(updir(pid) / fname)
                results[u["id"]] = fname
            else:
                results[u["id"]] = None
        except Exception:
            traceback.print_exc()
            results[u["id"]] = None

    def fn(p):
        for u in p.get("uploads", []):
            if u["id"] in results:
                u["cutout"] = results[u["id"]]
        p["stage"] = ""
    store.update(pid, fn)


def run_concepting(pid, count, avoid_existing=False, user=None):
    llm.set_project(pid)
    llm.set_user(user)
    try:
        prepare_cutouts(pid)
        project = store.load(pid)
        brand = store.load_brand(project["brief"]["brand"])
        avoid = project.get("concepts") if avoid_existing else None
        note, concepts, explored = agent.develop_concepts(project, brand, brand_dir(brand["slug"]), updir(pid), count, avoid)
        new_ids = []

        def fn(p):
            if not avoid_existing:
                p["director_note"] = note
                p["explored"] = explored
            start = len(p.get("concepts", []))
            for i, c in enumerate(concepts):
                cid = f"c{start + i + 1}"
                new_ids.append(cid)
                entry = concept_fields(c)
                entry.update(id=cid, status="pending", step="Queued…", favourite=False, versions=[], current=0)
                p.setdefault("concepts", []).append(entry)
            p["status"] = "designing"
            p["error"] = None
        store.update(pid, fn)
        start_designs(pid, new_ids)
    except Exception as e:
        traceback.print_exc()

        def fn(p):
            p["status"] = "ready" if p.get("concepts") else "error"
            p["error"] = friendly(e)
        store.update(pid, fn)


# ---------------- pages & files ----------------

@app.route("/")
def index():
    return send_from_directory(BASE / "templates", "index.html")


@app.route("/files/<pid>/<path:sub>")
def project_file(pid, sub):
    return send_from_directory(store.project_dir(pid), sub)


@app.route("/brand-assets/<slug>/<path:fname>")
def brand_file(slug, fname):
    return send_from_directory(brand_dir(slug), fname)


# ---------------- API ----------------

@app.get("/api/config")
def config():
    accts = settings.ig_accounts()
    return jsonify(has_key=llm.has_key(), provider=llm.provider(), model=llm.text_model(),
                   image_generation=imagegen.enabled(), image_model=imagegen.model() if imagegen.enabled() else None,
                   instagram=bool(accts) or instagram.configured(), ig_test_mode=instagram.test_mode(),
                   ig_accounts={k: v.get("username") for k, v in accts.items()}, user=current(), hosted=settings.hosted(),
                   formats=render.FORMATS, tones=TONES, objectives=OBJECTIVES,
                   brands=[{k: b.get(k) for k in ("slug", "name", "full_name", "default_format", "summary", "draft")} | {"logo": b["logos"][0]["file"]}
                           for b in store.list_brands()])


@app.get("/api/brands")
def brands():
    return jsonify(store.list_brands())


@app.put("/api/brands/<slug>/guidelines")
def put_guidelines(slug):
    store.save_guidelines(slug, (request.json or {}).get("text", ""))
    return jsonify(ok=True)


@app.post("/api/brands/<slug>/logos")
def add_logo(slug):
    f = request.files.get("file")
    lid = re.sub(r"[^a-z0-9-]", "-", (request.form.get("id") or "").lower()).strip("-")
    note = request.form.get("note", "").strip()
    if not f or not lid:
        return jsonify(error="Choose a file and give the logo a short name."), 400
    if Path(f.filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return jsonify(error="Logos must be PNG, JPG or WEBP (PNG with transparency is best)."), 400
    if not lid.startswith("logo-"):
        lid = "logo-" + lid
    im = Image.open(f.stream)
    fname = lid + ".png"
    im.convert("RGBA").save(brand_dir(slug) / fname)
    prof = store.load_brand(slug)
    transparent = im.mode in ("RGBA", "LA", "P")
    auto = f"{'Transparent' if transparent else 'Solid background (not transparent)'} PNG, {im.width}x{im.height}px (aspect {im.width / im.height:.2f}:1)."
    entry = {"id": lid, "file": fname, "note": (note + " " if note else "") + auto}
    prof["logos"] = [l for l in prof["logos"] if l["id"] != lid] + [entry]
    store.save_brand_profile(slug, prof)
    return jsonify(ok=True)


@app.delete("/api/brands/<slug>/logos/<lid>")
def delete_logo(slug, lid):
    prof = store.load_brand(slug)
    if len(prof["logos"]) <= 1:
        return jsonify(error="A brand needs at least one logo."), 400
    prof["logos"] = [l for l in prof["logos"] if l["id"] != lid]
    store.save_brand_profile(slug, prof)
    return jsonify(ok=True)


@app.get("/api/projects")
def projects():
    out = []
    for p in store.list_projects():
        thumb = None
        sel = p.get("selected")
        for c in p.get("concepts", []):
            v = current_version(c)
            if v and v.get("pngs") and (thumb is None or (sel and sel.get("cid") == c["id"])):
                thumb = f"/files/{p['id']}/{v['pngs'][0]}"
        out.append({"id": p["id"], "title": p.get("title"), "brand": p["brief"]["brand"], "created": p.get("created"),
                    "status": p.get("status"), "thumb": thumb, "count": len(p.get("concepts", [])),
                    "selected": bool(sel)})
    return jsonify(out)


@app.get("/api/library")
def library():
    """Favourite and approved designs across every campaign."""
    favs, approved = [], []
    for p in store.list_projects():
        sel = p.get("selected") or {}
        for c in p.get("concepts", []):
            v = current_version(c)
            item = {"pid": p["id"], "cid": c["id"], "title": p.get("title"), "brand": p["brief"]["brand"],
                    "name": c.get("name"), "thumb": f"/files/{p['id']}/{v['pngs'][0]}" if v and v.get("pngs") else None}
            if c.get("favourite") and item["thumb"]:
                favs.append(item)
            if sel.get("cid") == c["id"]:
                vs = c.get("versions", [])
                sv = vs[sel["index"]] if sel.get("index", 0) < len(vs) else v
                if sv and sv.get("pngs"):
                    approved.append({**item, "thumb": f"/files/{p['id']}/{sv['pngs'][0]}", "at": sel.get("at")})
    return jsonify(favourites=favs, approved=approved)


@app.post("/api/projects")
def create_project():
    brief = json.loads(request.form.get("brief", "{}"))
    if brief.get("brand") not in {b["slug"] for b in store.list_brands()}:
        return jsonify(error="Choose a brand."), 400
    if brief.get("format") not in render.FORMATS:
        brief["format"] = store.load_brand(brief["brand"])["default_format"]
    brief["count"] = max(5, min(8, int(brief.get("count", 5))))
    brief["slides"] = max(2, min(10, int(brief.get("slides", 5))))
    pid = store.new_id()
    d = updir(pid)
    d.mkdir(parents=True, exist_ok=True)
    uploads = []
    for i, f in enumerate(request.files.getlist("files")):
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_IMG:
            continue
        try:
            im = ImageOps.exif_transpose(Image.open(f.stream))  # fixes sideways phone photos
        except Exception:
            continue
        uid = f"photo-{len(uploads) + 1}"
        if im.mode in ("RGBA", "LA", "P"):
            fname = uid + ".png"
            im.convert("RGBA").save(d / fname)
        else:
            fname = uid + ".jpg"
            im.convert("RGB").save(d / fname, "JPEG", quality=95)
        uploads.append({"id": uid, "file": fname, "name": f.filename, "w": im.width, "h": im.height})
    brand = store.load_brand(brief["brand"])
    title = (brief.get("title") or "").strip() or (brief.get("idea") or "").strip()[:60] or f"{brand['name']} campaign"
    project = {"id": pid, "title": title, "created": store.now(), "updated": store.now(), "brief": brief,
               "uploads": uploads, "status": "concepting", "director_note": "", "error": None,
               "concepts": [], "selected": None}
    store.save(project)
    threading.Thread(target=run_concepting, args=(pid, brief["count"]), kwargs=dict(user=llm.current_user()), daemon=True).start()
    return jsonify(id=pid)


@app.get("/api/projects/<pid>")
def get_project(pid):
    p = store.load(pid)
    if not p:
        abort(404)
    return jsonify(p)


@app.delete("/api/projects/<pid>")
def delete_project(pid):
    import shutil
    shutil.rmtree(store.project_dir(pid), ignore_errors=True)
    return jsonify(ok=True)


@app.post("/api/projects/<pid>/retry")
def retry_project(pid):
    p = store.load(pid)
    if p.get("concepts"):
        failed = [c["id"] for c in p["concepts"] if c.get("status") == "error"]
        for cid in failed:
            do_action(pid, cid, store.find_concept(p, cid).get("retry") or {"action": "regenerate"})
        return jsonify(ok=True)
    store.update(pid, lambda q: q.update(status="concepting", error=None))
    threading.Thread(target=run_concepting, args=(pid, p["brief"]["count"]), kwargs=dict(user=llm.current_user()), daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/projects/<pid>/more")
def more_concepts(pid):
    n = max(1, min(5, int((request.json or {}).get("count", 3))))
    store.update(pid, lambda q: q.update(status="concepting", error=None))
    threading.Thread(target=run_concepting, args=(pid, n, True), kwargs=dict(user=llm.current_user()), daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/projects/<pid>/concepts/<cid>/action")
def concept_action(pid, cid):
    body = request.json or {}
    p = store.load(pid)
    c = store.find_concept(p, cid)
    if c.get("status") in ("pending", "working"):
        return jsonify(error="This design is still being worked on."), 409
    err = do_action(pid, cid, body)
    if err:
        return jsonify(error=err), 400
    return jsonify(ok=True)


def do_action(pid, cid, body):
    p = store.load(pid)
    c = store.find_concept(p, cid)
    action = body.get("action")
    base = current_version(c)
    fmt = base["format"] if base else p["brief"]["format"]
    store.update(pid, lambda q: q.update(status="designing") if q.get("status") == "ready" else None)

    if action == "regenerate" or (action != "new_direction" and base is None):
        job = lambda: produce(pid, cid, p["brief"]["format"] if base is None else fmt, label="Regenerated from scratch")
    elif action in PRESETS:
        job = lambda: produce(pid, cid, fmt, PRESETS[action], base, label=action.capitalize())
    elif action == "revise":
        text = (body.get("instruction") or "").strip()
        if not text:
            return "Write what you'd like changed."
        job = lambda: produce(pid, cid, fmt, text, base, label=text)
    elif action == "headline":
        text = (body.get("instruction") or "").strip()
        instr = f"Change the headline to exactly: \"{text}\" — re-balance the layout so it fits beautifully." if text else \
            "Write a stronger, more scroll-stopping headline for this concept and re-balance the layout around it."
        job = lambda: produce(pid, cid, fmt, instr, base, label="New headline" + (f": {text}" if text else ""))
    elif action == "combine":
        oc = store.find_concept(p, body.get("with_cid", ""))
        ov = current_version(oc)
        if not ov:
            return "That concept has no design yet."
        instr = (f"Combine this design with the second concept attached (\"{oc['name']}\"). "
                 + (body.get("instruction") or "Take the strongest elements of each into one coherent, superior design."))
        other = {"concept": oc, "version": ov}
        job = lambda: produce(pid, cid, fmt, instr, base, other=other, label=f"Combined with {oc['name']}")
    elif action == "format":
        target = body.get("format")
        if target not in render.FORMATS:
            return "Unknown format."
        size = render.FORMATS[target]
        instr = (f"Recompose this design for {size['label']} {size['w']}x{size['h']}px. Do NOT simply stretch or crop the "
                 "existing layout — re-art-direct it properly for the new canvas, keeping the concept, copy and identity.")
        job = lambda: produce(pid, cid, target, instr, base, label=f"Recomposed as {size['label']}")
    elif action == "new_direction":
        def job():
            set_concept(pid, cid, status="working", step="Finding a new direction…", error=None)
            proj = store.load(pid)
            brand = store.load_brand(proj["brief"]["brand"])
            _, new, _ = agent.develop_concepts(proj, brand, brand_dir(brand["slug"]), updir(pid), 1, proj["concepts"])
            produce(pid, cid, p["brief"]["format"], concept_override=new[0], label="Completely different direction")
    else:
        return "Unknown action."

    set_concept(pid, cid, status="pending", step="Queued…", error=None)
    pool.submit(run_safely, pid, cid, job, body, llm.current_user())
    return None


@app.post("/api/projects/<pid>/concepts/<cid>/favourite")
def favourite(pid, cid):
    def fn(p):
        c = store.find_concept(p, cid)
        c["favourite"] = not c.get("favourite")
    return jsonify(store.update(pid, fn))


@app.post("/api/projects/<pid>/concepts/<cid>/current")
def set_current(pid, cid):
    idx = int((request.json or {}).get("index", 0))
    return jsonify(store.update(pid, lambda p: store.find_concept(p, cid).update(current=idx)))


@app.post("/api/projects/<pid>/select")
def select(pid):
    body = request.json or {}

    def fn(p):
        if body.get("cid") is None:
            p["selected"] = None
            return
        c = store.find_concept(p, body["cid"])
        p["selected"] = {"cid": c["id"], "index": int(body.get("index", c.get("current", 0))),
                         "caption": body.get("caption", "primary"), "at": store.now()}
    return jsonify(store.update(pid, fn))


@app.get("/api/projects/<pid>/download/<cid>/<int:index>")
def download(pid, cid, index):
    p = store.load(pid)
    c = store.find_concept(p, cid)
    v = c["versions"][index]
    scale = 2 if request.args.get("scale") == "2" else 1
    slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{p['brief']['brand']}-{c['name']}").strip("-")[:60]
    if scale == 1:
        files = png_paths(pid, v)
    else:
        brand = store.load_brand(p["brief"]["brand"])
        files = [store.project_dir(pid) / f"exports/{cid}-v{v['v']}-s{i + 1}@2x.png" for i in range(len(v["slides_src"]))]
        render.render_slides(v["slides_src"], v["format"], assets_for(p, brand), files, scale=2, font_css=fonts_for(brand))
    suffix = "@2x" if scale == 2 else ""
    if len(files) == 1:
        return send_file(files[0], as_attachment=True, download_name=f"{slug}{suffix}.png")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, f in enumerate(files):
            z.write(f, f"{slug}-slide-{i + 1}{suffix}.png")
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"{slug}-carousel{suffix}.zip", mimetype="application/zip")


# ======================================================================
#  SECURITY: only the approved image may be reached through the public link
# ======================================================================

LOCAL_HOSTS = {"127.0.0.1", "localhost"}
OPEN_PATHS = ("/public/", "/static/", "/brand-assets/")
OPEN_API = {"/api/auth/state", "/api/auth/login", "/api/auth/setup-admin"}
ADMIN_API = ("/api/settings", "/api/users", "/api/diagnostics/")


def _is_remote():
    host = (request.host or "").split(":")[0].lower()
    return host not in LOCAL_HOSTS or "Cf-Ray" in request.headers or "Cf-Connecting-Ip" in request.headers


def current():
    uid = session.get("uid")
    u = auth.find(uid) if uid else None
    return auth.public(u) if u else None


@app.before_request
def guard():
    path = request.path
    # Running on your own computer with a temporary public link: only the approved image may be reached from outside.
    if not settings.hosted() and _is_remote() and not path.startswith("/public/"):
        abort(403)
    if path.startswith(OPEN_PATHS) or path == "/" or path in OPEN_API:
        return None
    u = current()
    if not u:
        if path.startswith("/api/"):
            return jsonify(error="Please sign in.", login=True), 401
        return redirect("/")
    # Mutating API calls must come from the app itself (blocks cross-site request forgery).
    if path.startswith("/api/") and request.method not in ("GET", "HEAD") and request.headers.get("X-Studio") != "1":
        return jsonify(error="Request blocked."), 403
    admin_only = path.startswith(ADMIN_API) or (path.startswith("/api/brands/") and request.method != "GET") \
        or path.startswith("/auth/instagram")
    if admin_only and u["role"] != "admin" and not (path == "/api/settings" and request.method == "GET"):
        return jsonify(error="Only an admin can do that."), 403
    llm.set_user(u["email"])
    return None


@app.after_request
def no_store(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------------- sign in ----------------

@app.get("/api/auth/state")
def auth_state():
    u = current()
    needs = bool(u and u["role"] == "admin" and not llm.has_key())
    return jsonify(has_users=auth.has_users(), user=u, needs_setup=needs, hosted=settings.hosted())


@app.post("/api/auth/setup-admin")
def setup_admin():
    if auth.has_users():
        return jsonify(error="This studio already has an admin."), 409
    b = request.json or {}
    try:
        u = auth.create(b.get("email"), b.get("name"), b.get("password", ""), role="admin")
    except ValueError as e:
        return jsonify(error=str(e)), 400
    session.clear()
    session.permanent = True
    session["uid"] = u["id"]
    return jsonify(user=u)


@app.post("/api/auth/login")
def do_login():
    b = request.json or {}
    try:
        u = auth.login(b.get("email"), b.get("password", ""))
    except ValueError as e:
        return jsonify(error=str(e)), 401
    session.clear()
    session.permanent = True
    session["uid"] = u["id"]
    return jsonify(user=u)


@app.post("/api/auth/logout")
def do_logout():
    session.clear()
    return jsonify(ok=True)


@app.post("/api/auth/password")
def change_password():
    b = request.json or {}
    u = current()
    try:
        auth.login(u["email"], b.get("current", ""))
        return jsonify(user=auth.set_password(u["id"], b.get("new", "")))
    except ValueError as e:
        return jsonify(error=str(e)), 400


# ---------------- team (admin) ----------------

@app.get("/api/users")
def users_list():
    return jsonify(auth.all_users())


@app.post("/api/users")
def users_add():
    b = request.json or {}
    temp = secrets.token_urlsafe(9)
    try:
        u = auth.create(b.get("email"), b.get("name"), temp, role="admin" if b.get("role") == "admin" else "member", must_change=True)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(user=u, temp_password=temp)


@app.post("/api/users/<uid>/reset")
def users_reset(uid):
    temp = secrets.token_urlsafe(9)
    auth.set_password(uid, temp)
    return jsonify(temp_password=temp)


@app.delete("/api/users/<uid>")
def users_remove(uid):
    if uid == current()["id"]:
        return jsonify(error="You can't remove yourself."), 400
    try:
        auth.remove(uid)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


# ---------------- connections (admin) ----------------

def _redirect_uri():
    base = settings.public_base_url() or request.host_url.rstrip("/")
    return base + "/auth/instagram/callback"


@app.get("/api/settings")
def get_settings():
    app_id, app_secret = settings.meta_app()
    now = _time.time()
    accts = {}
    for b in store.list_brands():
        a = settings.ig_accounts().get(b["slug"])
        accts[b["slug"]] = {"brand": b["name"], "connected": bool(a),
                            **({"username": a.get("username"), "account_type": a.get("account_type"), "picture": a.get("picture"),
                                "days_left": int((a.get("expires_at", 0) - now) / 86400), "connected_at": a.get("connected_at"),
                                "connected_by": a.get("connected_by")} if a else {})}
    key = settings.openai_key()
    return jsonify(openai=settings.masked(key), openai_from_env=bool(key) and not settings.get_secret("openai_api_key"),
                   image_generation=imagegen.enabled(), meta_app_id=app_id, meta_secret=bool(app_secret),
                   redirect_uri=_redirect_uri(), instagram=accts, ig_test_mode=settings.ig_test_mode(),
                   hosted=settings.hosted(), public_base=settings.public_base_url())


@app.put("/api/settings/openai")
def put_openai():
    key = ((request.json or {}).get("key") or "").strip()
    if not key.startswith("sk-") or len(key) < 20:
        return jsonify(error="That doesn't look like an OpenAI API key (they start with sk-)."), 400
    try:
        from openai import OpenAI
        OpenAI(api_key=key, timeout=30, max_retries=1).models.list()  # free check: no tokens used
    except Exception as e:
        return jsonify(error=llm.friendly_error(e)), 400
    settings.put_secret("openai_api_key", key)
    return jsonify(ok=True, masked=settings.masked(key))


@app.delete("/api/settings/openai")
def del_openai():
    settings.put_secret("openai_api_key", "")
    return jsonify(ok=True)


@app.put("/api/settings/meta")
def put_meta():
    b = request.json or {}
    app_id = re.sub(r"\D", "", str(b.get("app_id", "")))
    if not app_id:
        return jsonify(error="Enter the Instagram App ID (numbers only)."), 400
    settings.put("meta_app_id", app_id)
    if b.get("app_secret"):
        settings.put_secret("meta_app_secret", str(b["app_secret"]).strip())
    return jsonify(ok=True)


@app.put("/api/settings/flags")
def put_flags():
    b = request.json or {}
    if "ig_test_mode" in b:
        if b["ig_test_mode"] is False and b.get("confirm") != "GO LIVE":
            return jsonify(error="Type GO LIVE to confirm."), 400
        settings.put("ig_test_mode", bool(b["ig_test_mode"]))
    if "image_generation" in b:
        settings.put("image_generation", bool(b["image_generation"]))
    return jsonify(ok=True)


@app.get("/auth/instagram/start")
def ig_start():
    brand = request.args.get("brand", "")
    if brand not in {b["slug"] for b in store.list_brands()}:
        abort(400)
    app_id, app_secret = settings.meta_app()
    if not (app_id and app_secret):
        return redirect("/#/settings")
    state = secrets.token_urlsafe(24)
    session["ig_oauth"] = {"state": state, "brand": brand, "at": _time.time()}
    return redirect(instagram.authorize_url(app_id, _redirect_uri(), state))


@app.get("/auth/instagram/callback")
def ig_callback():
    st = session.pop("ig_oauth", None) or {}
    if not st or request.args.get("state") != st.get("state") or _time.time() - st.get("at", 0) > 900:
        return redirect("/#/settings?ig=expired")
    if request.args.get("error"):
        return redirect("/#/settings?ig=cancelled")
    app_id, app_secret = settings.meta_app()
    try:
        tok, info = instagram.connect_with_code(app_id, app_secret, _redirect_uri(), request.args.get("code", ""))
    except Exception as e:
        traceback.print_exc()
        settings.put("last_ig_error", friendly(e))
        return redirect("/#/settings?ig=failed")
    info.update(connected_at=store.now(), connected_by=current()["email"])
    settings.save_ig_account(st["brand"], tok, info)
    settings.put("last_ig_error", None)
    return redirect(f"/#/settings?ig=connected")


@app.put("/api/settings/instagram/<brand>/token")
def ig_paste_token(brand):
    """For running on your own computer: paste a token generated in the Meta app dashboard."""
    brand = store.safe(brand)
    tok = ((request.json or {}).get("token") or "").strip()
    if len(tok) < 20:
        return jsonify(error="Paste the whole access token from your Meta app."), 400
    try:
        acc = instagram.account(tok)
    except Exception as e:
        return jsonify(error=friendly(e)), 400
    settings.save_ig_account(brand, tok, {"user_id": acc["id"], "username": acc.get("username"), "account_type": acc.get("account_type"),
                                          "picture": acc.get("picture"), "expires_at": int(_time.time()) + 60 * 86400,
                                          "connected_at": store.now(), "connected_by": current()["email"], "method": "token"})
    return jsonify(ok=True, username=acc.get("username"))


@app.get("/api/settings/last-error")
def last_ig_error():
    return jsonify(error=settings.get("last_ig_error") or "")


@app.delete("/api/settings/instagram/<brand>")
def ig_disconnect(brand):
    settings.remove_ig_account(store.safe(brand))
    return jsonify(ok=True)


def refresh_instagram_tokens():
    """Keep connections alive: renew any token with less than 20 days left (Instagram allows renewal after 24h)."""
    for brand, a in settings.ig_accounts().items():
        try:
            left = a.get("expires_at", 0) - _time.time()
            if 0 < left < 20 * 86400 and left < 60 * 86400 - 86400:
                tok, exp = instagram.refresh(settings.ig_token(brand))
                a["expires_at"] = exp
                a["refreshed_at"] = store.now()
                settings.save_ig_account(brand, tok, a)
                print(f"  Renewed Instagram connection for {brand}")
        except Exception:
            traceback.print_exc()


def _refresher():
    while True:
        refresh_instagram_tokens()
        _time.sleep(6 * 3600)


# ======================================================================
#  APPROVAL & PUBLISHING — the AI creates, you review, you approve, Instagram publishes
# ======================================================================

_publish_lock = threading.Lock()
_public_tokens = {}  # token -> (pid, aid, expires)


def _approval(p, aid):
    for a in p.get("approvals", []):
        if a["id"] == aid:
            return a
    raise KeyError(aid)


def _log(a, event, detail=""):
    a.setdefault("history", []).append({"at": store.now(), "event": event, "detail": detail})
    a["updated"] = store.now()


def _caption_text(a):
    tags = " ".join(t if t.startswith("#") else "#" + t for t in (a.get("hashtags") or []) if t.strip())
    return (a.get("caption") or "").strip() + (("\n\n" + tags) if tags else "")


@app.post("/api/projects/<pid>/approvals")
def create_approval(pid):
    """Step 6-7: the chosen design becomes an editable draft (a frozen copy, so later design changes can't alter it)."""
    body = request.json or {}
    p = store.load(pid)
    c = store.find_concept(p, body.get("cid", ""))
    idx = int(body.get("index", c.get("current", 0)))
    v = c["versions"][idx]
    for a in p.get("approvals", []):
        if a["cid"] == c["id"] and a["index"] == idx and a["state"] in ("draft", "approved"):
            return jsonify(store.update(pid, lambda q: q.update(selected={"cid": c["id"], "index": idx, "caption": "primary", "at": store.now(), "approval": a["id"]})))
    aid = "a" + secrets.token_hex(4)
    adir = store.project_dir(pid) / "approvals" / aid
    adir.mkdir(parents=True, exist_ok=True)
    pngs = []
    for i, rel in enumerate(v["pngs"]):
        shutil.copy(store.project_dir(pid) / rel, adir / f"slide-{i + 1}.png")
        pngs.append(f"approvals/{aid}/slide-{i + 1}.png")
    cap_key = body.get("caption", "primary")
    already = [x for x in p.get("approvals", []) if x["cid"] == c["id"] and x["index"] == idx and x["state"] == "published"]
    a = {"id": aid, "cid": c["id"], "index": idx, "name": (v.get("concept") or {}).get("name") or c.get("name"),
         "format": v["format"], "pngs": pngs, "caption": (v.get("captions") or {}).get(cap_key, ""),
         "hashtags": v.get("hashtags", []), "state": "draft", "created": store.now(), "history": [],
         "ig": None, "already_published": bool(already)}
    _log(a, "Draft created", f"From {a['name']} v{v.get('v')}")

    def fn(q):
        q.setdefault("approvals", []).append(a)
        q["selected"] = {"cid": c["id"], "index": idx, "caption": cap_key, "at": store.now(), "approval": aid}
    return jsonify(store.update(pid, fn))


@app.put("/api/projects/<pid>/approvals/<aid>")
def edit_approval(pid, aid):
    """Edit caption / hashtags. Editing an approved version sends it back to draft — it must be approved again."""
    body = request.json or {}

    def fn(p):
        a = _approval(p, aid)
        if a["state"] not in ("draft", "approved", "failed", "tested"):
            raise ValueError("This post can no longer be edited.")
        a["caption"] = str(body.get("caption", a["caption"]))[:2200]
        tags = body.get("hashtags", a["hashtags"])
        if isinstance(tags, str):
            tags = [t for t in re.split(r"[\s,]+", tags) if t]
        a["hashtags"] = [t if t.startswith("#") else "#" + t for t in tags][:30]
        if a["state"] != "draft":
            _log(a, "Edited — needs approval again")
        a["state"] = "draft"
    try:
        return jsonify(store.update(pid, fn))
    except ValueError as e:
        return jsonify(error=str(e)), 409


@app.post("/api/projects/<pid>/approvals/<aid>/<step>")
def approval_step(pid, aid, step):
    body = request.json or {}
    if step == "approve":           # step 8: approve the final version
        def fn(p):
            a = _approval(p, aid)
            if a["state"] not in ("draft", "failed", "tested"):
                raise ValueError("Only a draft can be approved.")
            if len(_caption_text(a)) > 2200:
                raise ValueError("Instagram captions are limited to 2,200 characters.")
            a["state"] = "approved"
            _log(a, "Final version approved", "Caption and image locked")
    elif step == "draft":           # save as draft / back to editing
        def fn(p):
            a = _approval(p, aid)
            if a["state"] in ("publishing", "published", "unknown"):
                raise ValueError("This post can no longer be changed.")
            a["state"] = "draft"
            _log(a, "Saved as draft")
    elif step == "cancel":          # cancel publishing
        def fn(p):
            a = _approval(p, aid)
            if a["state"] in ("publishing", "published"):
                raise ValueError("Publishing has already started or finished.")
            a["state"] = "cancelled"
            _log(a, "Publishing cancelled")
            if (p.get("selected") or {}).get("approval") == aid:
                p["selected"] = None
    elif step == "checked":         # after an uncertain result, the user confirms the post is NOT on Instagram
        def fn(p):
            a = _approval(p, aid)
            if a["state"] != "unknown":
                raise ValueError("Nothing to confirm.")
            a["state"] = "approved"
            _log(a, "User confirmed the post is not on Instagram — may try again")
    elif step == "publish":         # step 10-11: explicit APPROVE & PUBLISH
        return start_publish(pid, aid, body)
    else:
        abort(404)
    try:
        return jsonify(store.update(pid, fn))
    except ValueError as e:
        return jsonify(error=str(e)), 409


def start_publish(pid, aid, body):
    if body.get("confirm") != "APPROVE & PUBLISH" or body.get("reviewed") is not True:
        return jsonify(error="Publishing needs your explicit confirmation."), 400
    with _publish_lock:  # no double clicks, no duplicate posts
        p = store.load(pid)
        a = _approval(p, aid)
        if a["state"] != "approved":
            return jsonify(error={"publishing": "This post is already being published.", "published": "This post has already been published.",
                                  "unknown": "The last attempt may have gone through. Check Instagram first."}.get(a["state"], "Approve the final version first.")), 409
        if a.get("already_published") and not body.get("publish_again"):
            return jsonify(error="This exact design was already published once. Tick 'publish it again' to confirm."), 409
        test = instagram.test_mode()
        if not test and not instagram.configured(p["brief"]["brand"]):
            return jsonify(error="This brand's Instagram account isn't connected. An admin can connect it in Settings."), 409

        def fn(q):
            x = _approval(q, aid)
            x["state"] = "publishing"
            x["test"] = test
            x["progress"] = "Starting…"
            x["published_by"] = llm.current_user()
            _log(x, "APPROVE & PUBLISH clicked", ("Test mode — nothing will be sent to Instagram" if test else "Live publishing")
                 + (f" · by {llm.current_user()}" if llm.current_user() else ""))
        store.update(pid, fn)
    threading.Thread(target=run_publish, args=(pid, aid, test), daemon=True).start()
    return jsonify(store.load(pid))


def run_publish(pid, aid, test):
    def prog(msg):
        def fn(q):
            _approval(q, aid)["progress"] = msg
        store.update(pid, fn)

    token = None
    used_tunnel = False
    try:
        p = store.load(pid)
        a = _approval(p, aid)
        brand = p["brief"]["brand"]
        tok = instagram.token(brand)
        prog("Preparing JPEG files (Instagram accepts JPEG only)…")
        adir = store.project_dir(pid) / "approvals" / aid
        jpgs = []
        for i, rel in enumerate(a["pngs"]):
            im = Image.open(store.project_dir(pid) / rel).convert("RGB")
            out = adir / f"slide-{i + 1}.jpg"
            im.save(out, "JPEG", quality=95, subsampling=0, optimize=True)
            jpgs.append(out.name)
        caption = _caption_text(a)
        token = secrets.token_urlsafe(24)
        _public_tokens[token] = (pid, aid, _time.time() + 1800)

        public = settings.public_base_url()
        if test and not public and not tunnel.executable():
            urls = []
            note = "Public link not tested (cloudflared not installed)."
        else:
            if public:
                base = public
            else:
                prog("Opening the temporary public link…")
                base = tunnel.start(PORT)
                used_tunnel = True
            urls = [f"{base}/public/{token}/{n}" for n in jpgs]
            prog("Checking Instagram will be able to download the image…")
            import requests
            r = requests.get(urls[0], timeout=30)
            if r.status_code != 200 or not r.headers.get("Content-Type", "").startswith("image/jpeg"):
                raise RuntimeError(f"The public link didn't serve the image (HTTP {r.status_code}). Nothing was published.")
            note = "Public link verified: Instagram would be able to fetch the image."

        if test:
            if tok:
                prog("Checking the Instagram account (read-only)…")
                acc = instagram.account(tok)
                note += f" Connected account: @{acc.get('username')} ({acc.get('account_type')})."
            def fn(q):
                x = _approval(q, aid)
                x["state"] = "tested"
                x["progress"] = ""
                _log(x, "Test run complete — NOTHING was posted", note + " Turn off IG_TEST_MODE in .env to publish for real.")
            store.update(pid, fn)
            return

        res = instagram.publish(urls, caption, a["format"], prog, tok)
        res["account"] = (settings.ig_accounts().get(brand) or {}).get("username")

        def fn(q):
            x = _approval(q, aid)
            x["state"] = "published"
            x["progress"] = ""
            x["ig"] = res | {"published_at": store.now()}
            _log(x, "Published — confirmed by Instagram", res.get("permalink") or res.get("media_id"))
        store.update(pid, fn)
    except Exception as e:
        traceback.print_exc()
        sent = getattr(e, "sent", False)

        def fn(q):
            x = _approval(q, aid)
            x["progress"] = ""
            if sent:
                x["state"] = "unknown"
                _log(x, "Result unknown — check Instagram before trying again", friendly(e))
            else:
                x["state"] = "failed"
                _log(x, "Publishing failed — nothing was posted", friendly(e))
        store.update(pid, fn)
    finally:
        if token:
            _public_tokens.pop(token, None)
        if used_tunnel and not os.getenv("KEEP_TUNNEL"):
            tunnel.stop()


@app.get("/public/<token>/<name>")
def public_image(token, name):
    entry = _public_tokens.get(token)
    if not entry or entry[2] < _time.time() or not re.fullmatch(r"(slide-\d+|probe)\.jpg", name):
        abort(404)
    pid, aid, _ = entry
    if pid == "__probe__":
        return send_from_directory(TESTS_DIR, "probe.jpg", mimetype="image/jpeg")
    return send_from_directory(store.project_dir(pid) / "approvals" / aid, name, mimetype="image/jpeg")


@app.get("/api/instagram/account")
def ig_account():
    brand = request.args.get("brand") or None
    if not instagram.configured(brand):
        return jsonify(connected=False, test_mode=instagram.test_mode())
    saved = settings.ig_accounts().get(brand or "") if brand else None
    if saved:  # avoid an Instagram call every time the approval screen opens
        return jsonify(connected=True, test_mode=instagram.test_mode(), account={"username": saved.get("username"),
                       "account_type": saved.get("account_type"), "picture": saved.get("picture"), "id": saved.get("user_id")})
    try:
        return jsonify(connected=True, test_mode=instagram.test_mode(), account=instagram.account(instagram.token(brand)))
    except Exception as e:
        return jsonify(connected=False, test_mode=instagram.test_mode(), error=friendly(e))


@app.get("/api/drafts")
def drafts():
    out = []
    for p in store.list_projects():
        for a in p.get("approvals", []):
            out.append({"pid": p["id"], "title": p.get("title"), "brand": p["brief"]["brand"], **{k: a.get(k) for k in
                        ("id", "name", "state", "format", "updated", "created", "ig", "test")},
                        "thumb": f"/files/{p['id']}/{a['pngs'][0]}"})
    out.sort(key=lambda x: x.get("updated") or x.get("created") or "", reverse=True)
    return jsonify(out)


# ======================================================================
#  CONVERSATION, USAGE, REFERENCES, SETUP & TESTS
# ======================================================================

@app.post("/api/projects/<pid>/chat")
def chat(pid):
    msg = ((request.json or {}).get("message") or "").strip()
    if not msg:
        return jsonify(error="Type a message."), 400
    llm.set_project(pid)
    p = store.load(pid)
    brand = store.load_brand(p["brief"]["brand"])
    pngs = []
    for c in p.get("concepts", []):
        v = current_version(c)
        if v and v.get("pngs"):
            pngs.append((c["id"], store.project_dir(pid) / v["pngs"][0]))
    store.update(pid, lambda q: q.setdefault("chat", []).append({"role": "client", "text": msg, "at": store.now()}))
    try:
        out = agent.chat(store.load(pid), brand, brand_dir(brand["slug"]), msg, pngs)
    except Exception as e:
        traceback.print_exc()
        return jsonify(error=friendly(e)), 502
    acts = [x for x in (out.get("actions") or []) if x and x.get("kind")]
    store.update(pid, lambda q: q.setdefault("chat", []).append({"role": "director", "text": out.get("reply", ""), "actions": acts, "at": store.now()}))
    return jsonify(store.load(pid))


@app.get("/api/usage")
def usage_summary():
    return jsonify(usage.summary())


@app.post("/api/brands/<slug>/references")
def add_reference(slug):
    files = request.files.getlist("files")
    note = request.form.get("note", "").strip()
    prof = store.load_brand(slug)
    refs = prof.get("references", [])
    d = brand_dir(slug) / "references"
    d.mkdir(exist_ok=True)
    for f in files:
        if Path(f.filename or "").suffix.lower() not in ALLOWED_IMG:
            continue
        im = ImageOps.exif_transpose(Image.open(f.stream)).convert("RGB")
        im.thumbnail((1350, 1350))
        name = f"ref-{secrets.token_hex(3)}.jpg"
        im.save(d / name, "JPEG", quality=90)
        refs.append({"file": f"references/{name}", "note": note or Path(f.filename).stem})
    store.save_references(slug, refs)
    return jsonify(ok=True)


@app.delete("/api/brands/<slug>/references")
def del_reference(slug):
    f = (request.json or {}).get("file", "")
    store.save_references(slug, [r for r in store.load_brand(slug).get("references", []) if r["file"] != f])
    return jsonify(ok=True)


@app.get("/api/diagnostics")
def diagnostics():
    """Free checks only — no API calls are made here."""
    import importlib.util
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            renderer = Path(pw.chromium.executable_path).exists()
    except Exception:
        renderer = False
    okey = settings.openai_key()
    return jsonify(
        provider=llm.provider(), text_model=llm.text_model(), image_model=imagegen.model(), image_quality=imagegen.quality(),
        openai_key=bool(okey) and not okey.startswith("paste"), claude_key=bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        image_generation=imagegen.enabled(), renderer=renderer, cutouts=importlib.util.find_spec("rembg") is not None,
        cloudflared=bool(tunnel.executable()) or bool(settings.public_base_url()), hosted=settings.hosted(),
        instagram=bool(settings.ig_accounts()) or instagram.configured(),
        ig_accounts={k: v.get("username") for k, v in settings.ig_accounts().items()},
        ig_test_mode=instagram.test_mode(), review_rounds=MAX_REVIEWS,
        brands=[{"slug": b["slug"], "name": b["name"], "logos": len(b["logos"]), "references": len(b.get("references", [])),
                 "fonts": len(b.get("font_faces") or []), "guidelines_chars": len(b.get("guidelines", ""))} for b in store.list_brands()])


TESTS_DIR = store.DATA_DIR / "tests"


@app.post("/api/diagnostics/<name>")
def run_test(name):
    """Real checks with your real keys. Image tests cost a little (low quality is used)."""
    llm.set_project("setup-tests")
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    t0 = _time.time()
    try:
        if name == "text":
            tool = {"name": "check", "description": "Connectivity check", "input_schema": {"type": "object", "properties": {
                "headline": {"type": "string"}, "brand_colour_hex": {"type": "string"}}, "required": ["headline", "brand_colour_hex"]}}
            b = store.load_brand("ease")
            out = llm.call(agent.brand_section(b)[:6000], [agent.text_block(
                "Write a 4-word headline for a Mental Math class and give the brand's teal hex code.")], tool, max_tokens=500,
                purpose="setup test", effort="low")
            detail = f"{llm.provider()} · {llm.text_model()} answered: “{out.get('headline')}” · teal = {out.get('brand_colour_hex')} (expected #14B8B4)"
            return jsonify(ok=True, detail=detail, seconds=round(_time.time() - t0, 1))
        if name in ("image", "edit"):
            os.environ.setdefault("OPENAI_IMAGE_QUALITY", "high")
            prev = os.environ["OPENAI_IMAGE_QUALITY"]
            os.environ["OPENAI_IMAGE_QUALITY"] = "low"
            try:
                if name == "image":
                    f = imagegen.make("A single brass compass on a dark slate desk, soft window light from the left, shallow depth of field",
                                      "square", False, TESTS_DIR)
                else:
                    src = sorted(TESTS_DIR.glob("gen-*.png"))
                    if not src:
                        return jsonify(ok=False, detail="Run the image generation test first (the edit test edits that image).")
                    f = imagegen.make("Keep the same object and composition, but make it night time with warm lamp light",
                                      "square", False, TESTS_DIR, refs=[src[0]])
            finally:
                os.environ["OPENAI_IMAGE_QUALITY"] = prev
            return jsonify(ok=True, detail=f"{imagegen.model()} {'edited' if name == 'edit' else 'generated'} an image.",
                           image=f"/test-files/{f}", seconds=round(_time.time() - t0, 1))
        if name == "brands":
            results = []
            for b in store.list_brands():
                pal = "".join(f'<div style="flex:1;background:{c["hex"]}"></div>' for c in b["colours"][:5])
                fam = (b.get("font_faces") or [{"family": "Calibri"}])[0]["family"]
                html = (f'<div style="position:absolute;inset:0;display:flex">{pal}</div><div style="position:absolute;left:60px;right:60px;'
                        f'top:60px;background:#fff;padding:40px;border-radius:20px"><img src="asset://{b["logos"][0]["id"]}" style="height:110px">'
                        f'<p style="font-family:\'{fam}\',Calibri,Carlito;font-weight:800;font-size:64px;margin:30px 0 0;color:#111">{b["name"]}: type check</p></div>')
                out = TESTS_DIR / f"brand-{b['slug']}.png"
                render.render_slides([{"html": html, "css": ""}], "square",
                                     {l["id"]: brand_dir(b["slug"]) / l["file"] for l in b["logos"]}, [out], font_css=fonts_for(b))
                results.append(f"/test-files/{out.name}")
            return jsonify(ok=True, detail="Each brand's logo, colours and typeface rendered from its own profile.", images=results,
                           seconds=round(_time.time() - t0, 1))
        if name == "instagram":
            lines, ok = [], True
            targets = list(settings.ig_accounts().keys()) or ([None] if instagram.configured() else [])
            if not targets:
                return jsonify(ok=False, detail="No Instagram account is connected yet (Settings → Connections).")
            for brand in targets:
                try:
                    acc = instagram.account(instagram.token(brand))
                    lim = acc.get("limit") or {}
                    lines.append(f"{brand or 'default'}: @{acc.get('username')} ({acc.get('account_type')}), quota {lim.get('used', '?')}/{lim.get('total', '?')} in 24h")
                except Exception as e:
                    ok = False
                    lines.append(f"{brand or 'default'}: {friendly(e)}")
            return jsonify(ok=ok, detail=" · ".join(lines) + ". Read-only check — nothing posted.", seconds=round(_time.time() - t0, 1))
        if name == "tunnel":
            import requests
            tok = secrets.token_urlsafe(16)
            probe = TESTS_DIR / "probe.jpg"
            Image.new("RGB", (64, 64), (255, 106, 19)).save(probe, "JPEG")
            _public_tokens[tok] = ("__probe__", "", _time.time() + 120)
            hosted_base = settings.public_base_url()
            try:
                base = hosted_base or tunnel.start(PORT)
                r = requests.get(f"{base}/public/{tok}/probe.jpg", timeout=30)
                r2 = requests.get(f"{base}/api/projects", timeout=30)
            finally:
                _public_tokens.pop(tok, None)
                if not hosted_base:
                    tunnel.stop()
            ok = r.status_code == 200 and r2.status_code in (401, 403)
            return jsonify(ok=ok, detail=f"Public link {'works' if r.status_code == 200 else 'FAILED (HTTP %s)' % r.status_code}; "
                                         f"the rest of the app is {'blocked from the internet ✓' if r2.status_code == 403 else 'NOT blocked — do not publish!'}",
                           seconds=round(_time.time() - t0, 1))
        abort(404)
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False, detail=friendly(e), seconds=round(_time.time() - t0, 1))


@app.get("/test-files/<name>")
def test_file(name):
    return send_from_directory(TESTS_DIR, name)


_started = False


def startup():
    """Runs once per server process (both `python app.py` and gunicorn on Render)."""
    global _started
    if _started:
        return
    _started = True
    store.recover_interrupted()
    threading.Thread(target=_refresher, daemon=True).start()


if os.getenv("STUDIO_AUTOSTART", "1") == "1":
    startup()

if __name__ == "__main__":
    port = PORT
    url = f"http://127.0.0.1:{port}"
    print(f"\n  Studio is running at {url}  (text AI: {llm.provider()} {llm.text_model()}; "
          f"images: {imagegen.model() if imagegen.enabled() else 'off'}; Instagram: {'TEST MODE' if instagram.test_mode() else 'LIVE'})"
          "\n  Keep this window open. Press Ctrl+C to stop.\n")
    if os.getenv("OPEN_BROWSER", "1") == "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
