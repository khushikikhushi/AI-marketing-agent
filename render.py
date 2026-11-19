"""Turns a design (HTML + CSS written by Claude) into a pixel-perfect PNG using headless Chromium."""
import base64
import io
import os
import re
import threading
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
FONTS = BASE / "static" / "fonts"

FORMATS = {
    "square": {"label": "Square post", "w": 1080, "h": 1080},
    "portrait": {"label": "Portrait post", "w": 1080, "h": 1350},
    "story": {"label": "Story", "w": 1080, "h": 1920},
    "reel": {"label": "Reel cover", "w": 1080, "h": 1920},
    "carousel": {"label": "Carousel", "w": 1080, "h": 1350},
}

_render_lock = threading.Lock()
LOW_MEMORY = os.getenv("LOW_MEMORY", "").lower() in ("1", "true", "yes")
_font_css = None
_data_uri_cache = {}


def _font_face_css():
    """The Carlito fonts (a free Calibri look-alike), loaded from disk so renders look right on any computer."""
    global _font_css
    if _font_css is None:
        parts = []
        for file, weight, style in [("Carlito-Regular.ttf", 400, "normal"), ("Carlito-Bold.ttf", 700, "normal"),
                                    ("Carlito-Italic.ttf", 400, "italic"), ("Carlito-BoldItalic.ttf", 700, "italic")]:
            p = FONTS / file
            if p.exists():
                parts.append(f"@font-face{{font-family:'Carlito';src:url('{p.resolve().as_uri()}') format('truetype');"
                             f"font-weight:{weight};font-style:{style};}}")
        _font_css = "\n".join(parts)
    return _font_css


def _asset_uri(path):
    """Images are loaded by the browser straight from disk (no base64 copies in memory)."""
    import cloudsync
    p = cloudsync.ensure(Path(path))
    return p.resolve().as_uri()


def image_data_uri(path, max_side=None):
    """Read an image file as a data: URI (downscaled if huge) so the page needs no network."""
    import cloudsync
    path = cloudsync.ensure(Path(path))
    max_side = max_side or (1700 if LOW_MEMORY else 2400)
    key = (str(path), path.stat().st_mtime, max_side)
    if key in _data_uri_cache:
        return _data_uri_cache[key]
    if LOW_MEMORY and len(_data_uri_cache) > 12:
        _data_uri_cache.clear()
    im = Image.open(path)
    has_alpha = im.mode in ("RGBA", "LA", "P")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    if has_alpha:
        im.convert("RGBA").save(buf, "PNG")
        mime = "image/png"
    else:
        im.convert("RGB").save(buf, "JPEG", quality=92)
        mime = "image/jpeg"
    uri = f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()
    _data_uri_cache[key] = uri
    return uri


def _clean(text):
    # Designs are pure HTML/CSS: strip scripts, event handlers and remote imports.
    text = re.sub(r"<script\b.*?</script\s*>", "", text, flags=re.I | re.S)
    text = re.sub(r"<script\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", text, flags=re.I)
    text = re.sub(r"@import[^;]*;", "", text, flags=re.I)
    return text


def build_document(html, css, w, h, assets, font_css=""):
    """assets: {"photo-1": Path, "logo-ease": Path, ...}. Claude refers to them as asset://name."""
    def sub(m):
        name = m.group(1)
        p = assets.get(name)
        return _asset_uri(p) if p else "about:blank#missing-" + name
    html = re.sub(r"asset://([A-Za-z0-9_-]+)", sub, _clean(html or ""))
    css = re.sub(r"asset://([A-Za-z0-9_-]+)", sub, _clean(css or ""))
    # Brands with their own fonts don't need the Calibri look-alike (saves memory on small servers).
    base_fonts = _font_face_css()
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{base_fonts}
{font_css}
*,*::before,*::after{{box-sizing:border-box}}
html,body{{margin:0;padding:0;width:{w}px;height:{h}px;overflow:hidden;background:#fff}}
body{{font-family:Calibri,Carlito,'Trebuchet MS',Arial,sans-serif;-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}}
#post{{position:relative;width:{w}px;height:{h}px;overflow:hidden}}
img{{display:block}}
</style><style>{css}</style></head><body><div id="post">{html}</div></body></html>"""


# Finds layout problems a human creative director would spot: clipped text, text off-canvas, broken images.
CHECK_JS = """
([W, H]) => {
  const issues = [];
  const all = Array.from(document.querySelectorAll('#post *'));
  for (const el of all) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const label = el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : '');
    if (el.tagName === 'IMG' && (!el.complete || el.naturalWidth === 0)) issues.push('Image failed to load: ' + label);
    const hasText = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (!hasText) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.left < -2 || r.top < -2 || r.right > W + 2 || r.bottom > H + 2)
      issues.push('Text runs outside the canvas: ' + label + ' "' + el.textContent.trim().slice(0, 40) + '"');
    if (el.scrollWidth > el.clientWidth + 3 && cs.overflowX !== 'visible')
      issues.push('Text is clipped horizontally: ' + label + ' "' + el.textContent.trim().slice(0, 40) + '"');
    if (el.scrollHeight > el.clientHeight + 3 && cs.overflowY !== 'visible')
      issues.push('Text is clipped vertically: ' + label + ' "' + el.textContent.trim().slice(0, 40) + '"');
    if (r.left < 40 || r.right > W - 40) { if (r.left >= -2 && r.right <= W + 2) issues.push('Text sits closer than 40px to the edge (Instagram crops/feels cramped): ' + label); }
  }
  return Array.from(new Set(issues)).slice(0, 15);
}
"""


def _headless_shell():
    """The lightweight browser that Playwright installs (used directly on small servers)."""
    import glob
    roots = [os.getenv("PLAYWRIGHT_BROWSERS_PATH") or "", "/ms-playwright", str(Path.home() / ".cache/ms-playwright"),
             str(Path(os.getenv("LOCALAPPDATA", "")) / "ms-playwright")]
    for r in roots:
        if not r:
            continue
        for pattern in ("chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell*",
                        "chromium-*/chrome-*/chrome", "chromium-*/chrome-*/chrome.exe"):
            hits = sorted(glob.glob(os.path.join(r, pattern)))
            if hits:
                return hits[-1]
    return None


def _render_cli(slides, fmt, assets, out_paths, scale, font_css):
    """Low-memory renderer: one short-lived browser process per slide, no automation layer, no network."""
    import subprocess
    import tempfile
    size = FORMATS[fmt]
    w, h = size["w"], size["h"]
    exe = _headless_shell()
    if not exe:
        raise RuntimeError("The image renderer isn't installed (playwright install chromium).")
    results = []
    with _render_lock:
        for slide, out in zip(slides, out_paths):
            doc = build_document(slide.get("html", ""), slide.get("css", ""), w, h, assets, font_css)
            with tempfile.TemporaryDirectory() as td:
                f = Path(td) / "post.html"
                f.write_text(doc, encoding="utf-8")
                shot = Path(td) / "shot.png"
                cmd = [exe, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--hide-scrollbars",
                       "--mute-audio", "--no-first-run", "--disable-extensions", "--disable-background-networking",
                       "--host-resolver-rules=MAP * ~NOTFOUND", "--allow-file-access-from-files",
                       f"--force-device-scale-factor={scale}", f"--window-size={w},{h}", "--virtual-time-budget=4000",
                       "--run-all-compositor-stages-before-draw", f"--screenshot={shot}", f.as_uri()]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, cwd=td)
                if not shot.exists():
                    raise RuntimeError("The renderer couldn't draw this design. Press Retry.")
                im = Image.open(shot)
                if im.size != (w * scale, h * scale):
                    im = im.crop((0, 0, w * scale, h * scale))
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                im.save(out)
            results.append([])  # layout checks need the full browser; the AI review still checks the image
    return results


def render_slides(slides, fmt, assets, out_paths, scale=1, font_css=""):
    """Render each slide to a PNG. Returns a list of layout issues per slide."""
    if LOW_MEMORY:
        return _render_cli(slides, fmt, assets, out_paths, scale, font_css)
    size = FORMATS[fmt]
    w, h = size["w"], size["h"]
    results = []
    with _render_lock, sync_playwright() as pw:
        args = ["--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions", "--js-flags=--max-old-space-size=160"]
        if LOW_MEMORY:
            args += ["--single-process", "--no-zygote", "--renderer-process-limit=1", "--disable-site-isolation-trials",
                     "--disable-features=site-per-process,Translate,BackForwardCache", "--disk-cache-size=1"]
        browser = pw.chromium.launch(args=args)
        try:
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
            # Block all network access: designs may only use the embedded assets.
            page.route("**/*", lambda route: route.abort() if route.request.url.startswith(("http:", "https:")) else route.continue_())
            import tempfile
            for slide, out in zip(slides, out_paths):
                doc = build_document(slide.get("html", ""), slide.get("css", ""), w, h, assets, font_css)
                with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tf:
                    tf.write(doc)
                try:
                    page.goto(Path(tf.name).as_uri(), wait_until="load", timeout=60000)
                finally:
                    try:
                        os.unlink(tf.name)
                    except OSError:
                        pass
                page.evaluate("document.fonts.ready.then(() => true)")
                page.wait_for_timeout(150)
                issues = page.evaluate(CHECK_JS, [w, h])
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": w, "height": h})
                results.append(issues)
        finally:
            browser.close()
    return results


_brand_font_cache = {}


def brand_font_css(brand_dir, brand):
    """@font-face rules for a brand's own font files (loaded from disk)."""
    import cloudsync
    out = []
    for f in brand.get("font_faces") or []:
        p = cloudsync.ensure(Path(brand_dir) / f["file"])
        if not p.exists():
            continue
        fmt = "woff2" if p.suffix == ".woff2" else "woff" if p.suffix == ".woff" else "truetype"
        out.append(f"@font-face{{font-family:'{f['family']}';src:url('{p.resolve().as_uri()}') format('{fmt}');"
                   f"font-weight:{f.get('weight', 400)};font-style:{f.get('style', 'normal')};font-display:block;}}")
    return "\n".join(out)
