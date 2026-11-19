"""OpenAI image generation and editing (gpt-image). Creates visual assets — scenes, backgrounds, product shots, surreal
elements — that the design then composites under real typography. Words are never left to the image model."""
import base64
import hashlib
import io
import os
from pathlib import Path

from PIL import Image

import llm
import usage

SIZES = {"portrait": "1024x1536", "square": "1024x1024", "landscape": "1536x1024"}


def model():
    return os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")


def quality():
    return os.getenv("OPENAI_IMAGE_QUALITY", "high")


def enabled():
    import settings
    k = settings.openai_key()
    on = settings.get("image_generation")
    on = (os.getenv("IMAGE_GENERATION", "on").lower() != "off") if on is None else bool(on)
    return on and bool(k) and not k.startswith("paste")


GUARD = (" Photographic and art-direction quality of a top commercial studio. IMPORTANT: absolutely no text, letters, numbers, "
         "words, logos, watermarks or signatures anywhere in the image.")


def _cutout(png_bytes):
    try:
        from rembg import remove
        return remove(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
    except Exception:
        return None


def make(prompt, shape, transparent, out_dir, refs=None):
    """Generate (or edit from reference images) one asset. Returns the saved file name. Identical requests are reused, never re-billed."""
    size = SIZES.get(shape, SIZES["portrait"])
    refs = [Path(r) for r in (refs or [])]
    key = hashlib.sha256(json_key(model(), quality(), prompt, size, transparent, [r.name for r in refs]).encode()).hexdigest()[:16]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"gen-{key}.png"
    if (out_dir / fname).exists():
        return fname  # cached: no repeated API call
    c = llm.openai_client()
    full = prompt.strip() + GUARD
    args = dict(model=model(), prompt=full, size=size, quality=quality(), n=1)
    want_alpha = bool(transparent)
    if want_alpha:
        args["background"] = "transparent"
        args["output_format"] = "png"
    purpose = "image edit" if refs else "image generation"
    try:
        if refs:
            files = [open(r, "rb") for r in refs]
            try:
                resp = c.images.edit(image=files if len(files) > 1 else files[0], **args)
            finally:
                for f in files:
                    f.close()
        else:
            resp = c.images.generate(**args)
    except Exception as e:
        if want_alpha and "background" in str(e).lower():
            # This model can't do transparent backgrounds: generate normally, then cut the subject out ourselves.
            args.pop("background", None)
            resp = c.images.edit(image=open(refs[0], "rb"), **args) if refs else c.images.generate(**args)
        else:
            raise
    u = getattr(resp, "usage", None)
    usage.record("image", "openai", model(), purpose, llm.current_project(),
                 getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0), images=1, image_quality=quality(), size=size)
    data = base64.b64decode(resp.data[0].b64_json)
    im = Image.open(io.BytesIO(data))
    if want_alpha and im.mode != "RGBA":
        cut = _cutout(data)
        if cut is not None:
            im = cut
    im.save(out_dir / fname)
    return fname


def json_key(*parts):
    import json
    return json.dumps(parts, ensure_ascii=False)
