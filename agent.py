"""The creative director: every call to the AI lives here (OpenAI by default, Claude as a fallback — see llm.py)."""
import base64
import io
import json
import os
from pathlib import Path

from PIL import Image

import imagegen
import llm
import render

MAX_TOKENS = 20000


# ---------------- images for Claude to look at ----------------

def image_block(path, max_side=1568):
    im = Image.open(path)
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (200, 200, 200))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[3])
        im = bg
    im.convert("RGB").save(buf, "JPEG", quality=88)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(buf.getvalue()).decode()}}


def text_block(t):
    return {"type": "text", "text": t}


# ---------------- who the agent is ----------------

PERSONA = """You are the executive creative director of an elite creative studio — the kind whose work wins at Cannes Lions, \
D&AD and the Type Directors Club. You combine an award-winning art director, an editorial designer from an international \
magazine, a typographer, a senior brand strategist, an advertising copywriter and a commercial photographer's eye.

Your standard: someone seeing the finished work should struggle to believe an automated agent made it. Every post should look \
as if a top studio spent hours developing, refining and art-directing it. You do not optimise for the easiest design to make; \
you optimise for the best final design. You are opinionated, you challenge weak ideas constructively, and you never settle for \
the first obvious idea. "Professional" never means boring. "Luxury" never means black backgrounds and gold text. "Funny" means a \
genuinely funny visual idea, not a joke on a coloured background.

Every design decision must have a purpose. Never use an effect because it looks impressive.

Copywriting: write like a top advertising copywriter — sharp, specific, human. Headlines are short and earn their place; a great \
headline creates a question, a tension or a small surprise that the image resolves. No generic AI phrases ("Unlock your \
potential", "Elevate", "In today's fast-paced world", "Dive into", "game-changer", "Ready to…?", "Look no further"). 0–3 emojis, \
only when they add something. 5–12 relevant hashtags. Captions complement the image rather than repeating its text.

Truthfulness: use supplied facts exactly. Never invent dates, prices, statistics, results, testimonials, awards, websites, phone \
numbers, venues or claims. If information would help but wasn't supplied, leave it out (or use a non-specific call to action \
like "Link in bio")."""


DESIGN_LANGUAGE = """# DESIGN INTELLIGENCE — your toolkit (tools, not mandatory styles; choose what best communicates the idea)

EDITORIAL: international magazine art direction; asymmetric compositions on a deliberate grid; oversized headlines that run \
to the edge of the safe area; intentional, generous negative space; cover-line hierarchies; pull-quote scale; folios, kickers \
and small running heads as quiet texture; images cropped with intent (tight, off-centre, bleeding).
SWISS / INTERNATIONAL STYLE: strict modular grid, flush-left ragged-right, one family in several weights, extreme scale contrast, \
objective photography, rules and fields of flat colour as structure, mathematical rhythm.
BRUTALIST / BOLD TYPOGRAPHIC: type as image — huge words cropped by the canvas edge, tight leading (0.82–0.9), stacked words, \
deliberate collisions between type and image, raw structure. Must still be readable and on-brand.
LUXURY RESTRAINT: very few elements, vast space, small refined type with generous tracking (0.15–0.3em) on caps, one \
exquisite focal object, controlled tonal palette, nothing loud. Restraint is the luxury.
CINEMATIC: one strong frame — dramatic crop, atmospheric colour grade, light falling from one direction, depth from foreground to \
background, letterbox-like bands, subtitles-style type, a story implied by one moment.
CONCEPTUAL / SURREAL: a visual metaphor or unexpected juxtaposition that makes the viewer work for a second and smile when they \
get it — built from photographs, cut-outs, scale shifts, impossible combinations, or graphic shapes. The idea carries the post.
CREATIVE PHOTOGRAPHY TREATMENT: unconventional crops (extreme close-up, a sliver, a detail), duotones in brand colours, \
controlled grading, the subject breaking out of its frame, type placed behind a cut-out subject for depth.

CRAFT RULES (what separates studio work from AI posters):
- One idea per post. One clear focal point. A deliberate reading order: what is seen 1st, 2nd and 3rd.
- Scale contrast: the dominant element is dramatically larger than the rest (a 4:1 to 10:1 size ratio is normal in great work). \
Use at most three or four type sizes.
- Grid: set margins (usually 72–96px on 1080 wide) and align everything to a few shared edges. Fewer alignment lines = more \
professional.
- Display type: tighten letter-spacing as size grows (about -0.02em to -0.05em above 100px), leading 0.85–1.0. Small caps-style \
labels: +0.12em to +0.25em tracking, 22–28px. Body: 30–40px, leading 1.3–1.45, 30–45 characters per line. Avoid widows and \
awkward single-word last lines in headlines — break lines by meaning, manually with <br>.
- Typography is a design element: weight contrast (700 vs 400), case contrast, italic as voice, numerals at poster scale, \
type interacting with image (behind a subject, cropped by the edge, aligned to a feature in the photo).
- Colour: dominant / support / accent. Flat confident fields beat gradients. A gradient only when it does a job (legibility \
over a photo, light).
- Texture and depth, used sparingly with purpose: subtle film grain (SVG feTurbulence noise at 4–8% opacity), soft realistic \
shadows (large blur, low opacity, offset from a consistent light direction), layering.
- Negative space is active, not leftover. If an area is empty it must be empty on purpose.
- Logos sit calmly in a consistent margin position with clear space; they are a signature, not a feature.

BANNED (instant failure): Canva-style templates; predictable text-on-gradient; centred photo with text underneath as a default; \
random floating objects or floating numbers; glassmorphism; generic 3D type; neon glows; cheap stock-photo feel; decorative \
clutter; drop shadows on text; outlines on text; bevels; emoji as graphics; badges/starbursts ("NEW!", "LIMITED!"); clip-art \
icons; more than one typeface style per idea without reason; every concept using the same structure."""


LAYOUTS = ["full-bleed photographic", "editorial cover", "asymmetric split", "typographic poster (type is the image)",
           "single object / still life minimal", "conceptual visual metaphor", "grid / modular Swiss",
           "extreme crop / detail", "layered depth (type behind cut-out subject)", "cinematic frame (letterbox)",
           "diagram / infographic as art", "collage / juxtaposition"]


def _type_note(brand):
    if brand.get("font_faces"):
        return ("This brand has a deliberate type system with more than one family: use the pairing exactly as described — "
                "display vs label vs lead-in roles — with real scale contrast.")
    return ("Because the brand restricts the typeface, create typographic richness through the family itself: weight contrast, "
            "case, italics, tracking, extreme scale, and layout — that is how great studios work inside strict systems.")


def brand_section(brand):
    colours = "\n".join(f"  - {c['name']} {c['hex']}: {c['use']}" for c in brand["colours"])
    rules = "\n".join(f"  - {r}" for r in brand["hard_rules"])
    logos = "\n".join(f"  - asset://{l['id']} — {l['note']}" for l in brand["logos"])
    return f"""# BRAND: {brand['full_name']}
A beautiful design that doesn't suit the brand is a failed design. Brand guidelines take priority over trends: creativity happens \
INSIDE this identity, and this brand must have its own visual personality — never the look of another brand or a generic \
institution. Use ONLY this brand's colours, type and voice.

Summary: {brand['summary']}
Colours (only these; tints/shades of them for shadows, overlays and duotones are acceptable):
{colours}
Typography: {brand['fonts']}
{_type_note(brand)}
Non-negotiable rules:
{rules}
Logo files available:
{logos}

## Official brand guidelines (full text)
{brand['guidelines']}"""


def brief_section(project):
    b = project["brief"]
    fmt = render.FORMATS[b["format"]]
    tones = ", ".join(b.get("tones") or []) or "not specified"
    if b.get("tone_custom"):
        tones += f"; in their words: {b['tone_custom']}"
    idea_modes = {
        "specific": "The client has a specific idea — execute it brilliantly, and also find more interesting ways to deliver the same objective.",
        "topic": "The client has a general topic and needs creative development.",
        "original": "The client wants you to come up with something entirely on your own, based on the brand, its audience and objectives.",
        "concepts": "The client wants several distinct campaign concepts to choose from.",
    }
    lines = []
    for u in project.get("uploads", []):
        o = "portrait" if u["h"] > u["w"] else "landscape" if u["w"] > u["h"] else "square"
        lines.append(f"  - asset://{u['id']} — \"{u['name']}\", {u['w']}x{u['h']}px ({o})")
        if u.get("cutout"):
            lines.append(f"    + asset://{u['id']}-cut — the same photo with the background removed (transparent PNG, SAME "
                         f"{u['w']}x{u['h']} canvas, subject in place). Stack it exactly over asset://{u['id']} (identical size, "
                         "object-fit and position) with text between the two layers to put type BEHIND the subject, or use it "
                         "alone as a cut-out on a brand-colour field.")
    up = "\n".join(lines) or "  (none — design with typography, brand graphics, shapes and colour)"
    slides = f"\nCarousel: {b.get('slides', 5)} slides, each {fmt['w']}x{fmt['h']}." if b["format"] == "carousel" else ""
    return f"""# CREATIVE BRIEF
Tone / creative direction: {tones}
(Creative directions, not templates — combine tones when it makes the work stronger. "Surprise me" = your own judgment.)
Promotion: {idea_modes.get(b.get('idea_mode'), '')}
What they said: {b.get('idea') or '(nothing — develop it yourself)'}
Objectives: {', '.join(b.get('objectives') or []) or 'general brand presence'}
Format: {fmt['label']} {fmt['w']}x{fmt['h']}px{slides}
Additional instructions (exact text, dates, links, hashtags, things to avoid): {b.get('notes') or 'none'}
Image generation: {"ON — you may commission up to 2 assets per design with " + imagegen.model() if imagegen.enabled() else "OFF — generated_images must be empty; work with uploads, type, shapes and colour"}
Uploaded photographs / assets (attached so you can see them):
{up}"""


DESIGN_CONTRACT = """# HOW YOU PRODUCE A FINISHED VISUAL
You art-direct the post as HTML + CSS (+ inline SVG). Headless Chromium renders it into a PNG at EXACTLY the canvas size, and \
that PNG is published as-is — so it must look like a finished studio creative, never like a web page.

Technical contract:
- Your HTML goes inside <div id="post">: position:relative, exactly canvas width x height, overflow hidden. Position elements \
absolutely in px (flex/grid inside positioned containers is fine).
- Images: <img src="asset://NAME"> or CSS url('asset://NAME'). Only listed asset names exist. No external URLs, web fonts or \
JavaScript (stripped).
- Fonts: use ONLY the brand's typefaces exactly as named under BRAND → Typography (they are installed in the renderer, \
with the weights listed). Nothing else.
- Full modern CSS and SVG: object-fit/object-position (photography crops), clip-path polygons (angular crops), filter \
(brightness, contrast, saturate, grayscale, sepia, blur) and mix-blend-mode (multiply/screen) for colour grading and duotones \
in brand colours, gradients only where purposeful, box-shadow for soft realistic shadows, transforms, inline <svg> for \
geometry, rules, diagrams, icons drawn with care, and an <svg> feTurbulence filter for subtle grain.
- Instagram safe areas: keep text ≥ 64px from every edge. Stories/Reel covers: keep the top 250px and bottom 320px free of \
important text. Nothing smaller than 24px; body 30–40px.
- Text must fit its box (never clipped or overflowing), be spelled perfectly and match supplied information exactly.

Image generation (when enabled — see the brief): you may commission up to 2 new visual assets per design from a top image model via `generated_images`, then use them in your HTML as asset://<id>. Use them where they make the work dramatically better: cinematic scenes and environments, premium product/still-life photography with controlled lighting, macro textures and materials, surreal or conceptual visual metaphors, atmospheric backgrounds, isolated objects (transparent: true) to composite with real depth and shadow. Rules: the image model must never render words — ALL text is your HTML typography. Do not generate realistic people presented as real students, staff, parents or winners; real people come only from uploaded photos (generated humans only as anonymous hands, silhouettes or out-of-focus figures). Never use edit_from on a photo containing people (identity must be preserved) — use the cut-out instead. Composite like a retoucher: match light direction, add contact shadows, grade everything to one palette, crop with intent. If image generation is off, `generated_images` must be empty.

Photographs:
- Preserve the subject's identity: never stretch or distort (object-fit: cover/contain only), never crop through eyes or \
mouths awkwardly, don't over-filter skin, don't alter logos in photos.
- Think like an advertising photographer and art director: choose the crop, the scale, where the eye lands, how the photo \
creates depth. A photo is NOT simply placed in the centre with text underneath.
- Text over a photo needs a calm area of the image or a purposeful tonal treatment for legibility.
- Logos: placed as supplied files, never redrawn, never stretched (set width OR height only)."""


# ---------------- tool schemas (force structured answers) ----------------

CONCEPT_ITEM = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short memorable concept name"},
        "direction": {"type": "string", "description": "Creative direction in a few words, e.g. 'Swiss typographic poster'"},
        "layout": {"type": "string", "enum": LAYOUTS, "description": "The structural layout archetype. Every concept must use a DIFFERENT one."},
        "headline": {"type": "string", "description": "The on-image headline / hook, exactly as it will appear"},
        "central_idea": {"type": "string", "description": "The one creative idea in a sentence"},
        "unexpected_element": {"type": "string", "description": "What is surprising or unconventional about it"},
        "visual_idea": {"type": "string", "description": "Composition and art direction: structure, focal point, read order 1st/2nd/3rd, how the photo is used, typography approach"},
        "emotion": {"type": "string"},
        "objective": {"type": "string", "description": "Which marketing objective this serves and how"},
        "caption_direction": {"type": "string"},
        "why_it_works": {"type": "string", "description": "Why it will stop the scroll and why it belongs to this brand"},
        "audience_response": {"type": "string"},
    },
    "required": ["name", "direction", "layout", "headline", "central_idea", "unexpected_element", "visual_idea", "emotion",
                 "objective", "caption_direction", "why_it_works", "audience_response"],
}

CONCEPTS_TOOL = {
    "name": "submit_concepts",
    "description": "Submit the creative exploration and the selected concepts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "explored": {"type": "array", "items": {"type": "string"},
                         "description": "Every idea you considered (at least twice as many as you select), one line each: the idea, then '— kept' or '— rejected: <reason>'."},
            "director_note": {"type": "string", "description": "2-4 sentences to the client: your read of the brief and honest, constructive pushback if any part of it is weak, with the stronger alternative."},
            "concepts": {"type": "array", "items": CONCEPT_ITEM},
        },
        "required": ["explored", "director_note", "concepts"],
    },
}

SLIDE = {"type": "object", "properties": {"html": {"type": "string"}, "css": {"type": "string"}}, "required": ["html", "css"]}

GEN_IMAGE = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Asset name you will reference as asset://<id>, e.g. gen-1"},
        "prompt": {"type": "string", "description": "A complete art-directed image prompt: subject, composition and camera angle, lens, lighting direction and quality, materials and textures, colour grade in brand colours, mood, where empty space must be left for type. Never ask for text."},
        "shape": {"type": "string", "enum": ["portrait", "square", "landscape"]},
        "transparent": {"type": "boolean", "description": "true for an isolated object/subject to composite (cut-out)"},
        "edit_from": {"type": "string", "description": "Optional: an uploaded asset id to EDIT instead of generating from scratch (products, objects, places only — never people)."},
    },
    "required": ["id", "prompt", "shape", "transparent"],
}

PLAN = {
    "type": "object",
    "description": "Your composition plan — decide this BEFORE writing any HTML.",
    "properties": {
        "grid": {"type": "string", "description": "Margins, columns, key alignment edges in px"},
        "focal_point": {"type": "string"},
        "read_order": {"type": "string", "description": "What the viewer sees 1st, 2nd, 3rd"},
        "type_scale": {"type": "string", "description": "Each text role with px size, weight, tracking, leading"},
        "image_treatment": {"type": "string", "description": "Crop, scale, grading, layering — or 'no photo' and what replaces it"},
        "negative_space": {"type": "string", "description": "Where the deliberate empty space is and why"},
        "colour": {"type": "string", "description": "Dominant / support / accent with hex values"},
    },
    "required": ["grid", "focal_point", "read_order", "type_scale", "image_treatment", "negative_space", "colour"],
}

DESIGN_TOOL = {
    "name": "submit_design",
    "description": "Submit the composition plan, the finished design and its copy.",
    "input_schema": {
        "type": "object",
        "properties": {
            "plan": PLAN,
            "generated_images": {"type": "array", "items": GEN_IMAGE,
                                 "description": "Visual assets to create with the image model BEFORE rendering (max 2). Empty if none are needed or image generation is off."},
            "headline": {"type": "string", "description": "The headline as it appears on the image"},
            "slides": {"type": "array", "items": SLIDE, "description": "One slide for single posts; one per slide for carousels."},
            "captions": {
                "type": "object",
                "properties": {
                    "primary": {"type": "string", "description": "Strongest marketing copy: a hook first line, natural, brand voice, clear message, CTA where appropriate. Line breaks allowed."},
                    "alternative": {"type": "string", "description": "A different approach (conversational, emotional, humorous or informative)."},
                    "short": {"type": "string", "description": "Concise version for quick engagement (1-2 lines)."},
                },
                "required": ["primary", "alternative", "short"],
            },
            "hashtags": {"type": "array", "items": {"type": "string"}, "description": "5-12 relevant hashtags, each starting with #"},
            "design_notes": {"type": "string", "description": "1-3 sentences: the key art-direction decisions."},
        },
        "required": ["plan", "headline", "slides", "captions", "hashtags", "design_notes"],
    },
}

REVIEWS = [
    ("creative_direction", "Creative direction", "Is the idea original, relevant and genuinely different from an ordinary ad? Not the first obvious idea?"),
    ("visual_design", "Visual design", "Does it look professionally art-directed: composition, focal point, depth, negative space, colour, balance, crop?"),
    ("typography", "Typography", "Is the type excellent: scale contrast, spacing, alignment, line breaks, readability, integration with the image? Spelling perfect?"),
    ("brand_identity", "Brand identity", "Does it genuinely belong to this brand (palette, type, voice, logo use, rules) — and not look like any other brand?"),
    ("marketing", "Marketing effectiveness", "Would someone actually stop scrolling? Is the message instantly clear and the action obvious?"),
    ("technical", "Technical quality", "Dimensions, safe areas, cropping, nothing clipped or overlapping, legible at phone size, photo and logo undistorted?"),
]
REVIEW_KEYS = [k for k, _, _ in REVIEWS]

REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Submit the six-part creative review of the rendered design.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reviews": {"type": "object", "properties": {
                k: {"type": "object", "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 10},
                                                     "notes": {"type": "string", "description": "Specific observations about what you SEE"}},
                    "required": ["score", "notes"]} for k in REVIEW_KEYS}, "required": REVIEW_KEYS},
            "critique": {"type": "string", "description": "2-4 sentence summary a creative director would say in the room."},
            "verdict": {"type": "string", "enum": ["approve", "refine", "rethink"],
                        "description": "approve: an elite agency would publish it as-is. refine: the idea is right but execution needs work — return improved_slides. rethink: the idea itself is weak — it will be redesigned from scratch."},
            "improved_slides": {"type": "array", "items": SLIDE, "description": "Required for refine: complete improved HTML/CSS for every slide, fixing every problem you named."},
        },
        "required": ["reviews", "critique", "verdict"],
    },
}


def _call(system, content, tool, max_tokens=MAX_TOKENS, purpose=""):
    return llm.call(system, content, tool, max_tokens=max_tokens, purpose=purpose)


def _system(brand):
    return PERSONA + "\n\n" + DESIGN_LANGUAGE + "\n\n" + brand_section(brand) + "\n\n" + DESIGN_CONTRACT


def _upload_blocks(project, updir):
    blocks = []
    for u in project.get("uploads", []):
        blocks.append(text_block(f"Uploaded asset: asset://{u['id']} (\"{u['name']}\")"))
        blocks.append(image_block(Path(updir) / u["file"]))
    return blocks


def _logo_blocks(brand, brand_dir):
    blocks = []
    for l in brand["logos"]:
        blocks.append(text_block(f"Brand logo file: asset://{l['id']}"))
        blocks.append(image_block(Path(brand_dir) / l["file"], max_side=600))
    return blocks


def _reference_blocks(brand, brand_dir, limit):
    refs = (brand.get("references") or [])[:limit]
    if not refs:
        return []
    blocks = [text_block(
        f"REFERENCE LIBRARY — {len(refs)} pieces of this brand's approved past work. Study the PRINCIPLES that make them work: the "
        "recurring brand frame, how scale and colour create hierarchy, how the image carries the idea, the voice of the headlines. "
        "Keep the brand system consistent with them, but NEVER copy a layout, image idea or headline — every new post must be a fresh idea.")]
    for r in refs:
        p = Path(brand_dir) / r["file"]
        if p.exists():
            blocks.append(text_block(f"Reference: {r.get('note', '')}"))
            blocks.append(image_block(p, max_side=900))
    return blocks


def _concept_text(c):
    return "\n".join(f"{k}: {c.get(k, '')}" for k in CONCEPT_ITEM["required"])


def _tokens(fmt, slides_count):
    return MAX_TOKENS + (min(slides_count, 10) * 2500 if fmt == "carousel" else 0)


# ---------------- the agent's jobs ----------------

def develop_concepts(project, brand, brand_dir, updir, count, avoid=None):
    """Return (director_note, [concepts], explored). avoid = existing concepts the new ones must differ from."""
    content = _logo_blocks(brand, brand_dir) + _reference_blocks(brand, brand_dir, 8) + _upload_blocks(project, updir)
    task = f"""{brief_section(project)}

# YOUR TASK NOW: CREATIVE STRATEGY AND CONCEPT DEVELOPMENT
Think as an executive creative director before anything is designed:
- What is the strongest message? What would make THIS audience stop scrolling?
- What is the central creative idea? What is the most interesting, unexpected way to communicate it?
- What visual metaphor, tension or surprise could carry it? What should the viewer notice first, second, third?
- What information actually needs to be on the image (usually much less than you think)?
- How does this stay unmistakably {brand['name']} while feeling fresh?

Explore widely first: generate at least {count * 2} different ideas internally and list them in `explored`. Kill the obvious, \
the generic and the weak. Then select the {count} strongest.

The {count} selected concepts must be {count} DIFFERENT CREATIVE IDEAS, not versions of one poster. Each must have a different \
`layout` archetype (no two the same), a different focal point, a different typographic approach and a different emotional \
register. At least one should be bold and unexpected, at least one should be supremely restrained. Do not present a weak \
concept just to fill a slot — if an idea isn't excellent, replace it."""
    if avoid:
        task += "\n\nThese concepts already exist — your new ones must be completely different ideas AND use layouts not used below:\n" + \
                "\n---\n".join(_concept_text(c) for c in avoid)
    content.append(text_block(task))
    sysmsg = _system(brand)
    out = _call(sysmsg, content, CONCEPTS_TOOL, max_tokens=12000, purpose="concepts")
    concepts = (out.get("concepts") or [])[:count]
    used = [c.get("layout") for c in (avoid or [])]
    layouts = [c.get("layout") for c in concepts]
    if len(set(layouts)) < len(layouts) or any(l in used for l in layouts):
        # Enforce distinct structures: one corrective pass.
        content[-1] = text_block(task + "\n\nYour previous answer repeated a layout archetype (" + ", ".join(layouts) +
                                 "). That is not acceptable. Every concept must use a different layout. Answer again.")
        out = _call(sysmsg, content, CONCEPTS_TOOL, max_tokens=12000, purpose="concepts")
        concepts = (out.get("concepts") or [])[:count]
    if not concepts:
        raise RuntimeError("No concepts came back. Press Retry.")
    return out.get("director_note", ""), concepts, out.get("explored", [])


def design(project, brand, brand_dir, updir, concept, fmt, slides_count=1, instruction=None,
           current=None, current_pngs=None, other=None, other_pngs=None, feedback=None):
    """Produce a finished design for a concept. If current is given, it's a revision of that design."""
    size = render.FORMATS[fmt]
    content = _logo_blocks(brand, brand_dir) + _reference_blocks(brand, brand_dir, 4) + _upload_blocks(project, updir)
    canvas = f"{size['w']}x{size['h']}px"
    if fmt == "carousel":
        canvas += f", {slides_count} slides forming one sequence: a scroll-stopping opening slide, a logical progression with a " \
                  "consistent visual system (shared grid, type and colour logic, with variation), and a final slide with the call to action"
    task = f"""{brief_section(project)}

# CONCEPT
{_concept_text(concept)}

# CANVAS
{size['label']}: {canvas}.
"""
    if current is None:
        task += """
# YOUR TASK NOW: PRODUCTION
Work like a studio: 1) fix the composition plan (grid, focal point, read order, type scale, image treatment, negative space, \
colour) — 2) build the finished visual exactly to that plan — 3) write the captions.
The layout archetype for this concept is mandatory. Make it publishable by an elite agency: exceptional typography, purposeful \
composition, nothing generic. Ask yourself before you answer: would a top creative director be proud to put their name on this?"""
        if feedback:
            task += f"""

# A PREVIOUS ATTEMPT AT THIS CONCEPT WAS REJECTED IN REVIEW
{feedback}
Do not patch that attempt. Start again from the concept with a fundamentally stronger execution that answers every criticism."""
    else:
        task += "\n# CURRENT VERSION (rendered image attached below)\n" + json.dumps(
            {"headline": current.get("headline"), "plan": current.get("plan"), "slides": current.get("slides_src"),
             "captions": current.get("captions"), "hashtags": current.get("hashtags")}, ensure_ascii=False)
        content.append(text_block("Render of the current version:"))
        content += [image_block(p) for p in (current_pngs or [])]
        if other is not None:
            task += "\n\n# SECOND CONCEPT TO COMBINE WITH (rendered image attached)\n" + _concept_text(other["concept"]) + \
                    "\n" + json.dumps({"slides": other["version"].get("slides_src")}, ensure_ascii=False)
            content.append(text_block("Render of the second concept:"))
            content += [image_block(p) for p in (other_pngs or [])]
        task += f"""

# REQUESTED CHANGE
{instruction}

Apply this change to THIS design only, at the same studio standard. Keep what already works unless the change requires \
otherwise. Keep captions and hashtags unless the change affects them (a new headline, tone or concept) — then rewrite them. \
Return the complete plan and design."""
    content.append(text_block(task))
    out = _call(_system(brand), content, DESIGN_TOOL, max_tokens=_tokens(fmt, slides_count), purpose="design")
    if not out.get("slides"):
        raise RuntimeError("The design came back empty. Press Retry.")
    return out


def review(project, brand, brand_dir, updir, concept, fmt, version, pngs, issues, round_no=1):
    """Six-part creative review of the actual rendered image."""
    content = _logo_blocks(brand, brand_dir) + _upload_blocks(project, updir)
    content.append(text_block("RENDERED DESIGN TO REVIEW (exactly what will be published):"))
    content += [image_block(p) for p in pngs]
    probs = "\n".join(f"- slide {i + 1}: {x}" for i, lst in enumerate(issues) for x in lst) or "- none detected"
    checks = "\n".join(f"Review {i + 1} — {label} (`{k}`): {q}" for i, (k, label, q) in enumerate(REVIEWS))
    content.append(text_block(f"""{brief_section(project)}

# CONCEPT
{_concept_text(concept)}

# THE DESIGN SOURCE
{json.dumps({'plan': version.get('plan'), 'slides': version.get('slides_src')}, ensure_ascii=False)}

# AUTOMATIC LAYOUT CHECKS
{probs}

# YOUR TASK NOW: QUALITY CONTROL (review round {round_no})
You are a demanding executive creative director seeing this for the first time. Judge what you SEE in the render, not what \
the code intended. Run six separate reviews and score each 1-10, where 8 means "an elite agency would publish this":
{checks}

Be honest and specific — name exact elements, sizes, positions. Look hard for: anything that looks templated or AI-generated, \
weak scale contrast, timid or generic headline treatment, awkward line breaks, cramped margins, misalignment, poor contrast, \
clipped/overlapping text, a distorted photo or logo, off-palette colour, clutter, emptiness that isn't intentional.
Verdict: approve only if EVERY score is 8 or above and there are no technical problems. If the idea is right but execution \
falls short, verdict refine and return complete improved_slides that fix everything (raise the craft — don't just patch). If the \
idea itself is weak or generic, verdict rethink."""))
    return _call(_system(brand), content, REVIEW_TOOL, max_tokens=_tokens(fmt, len(version.get("slides_src", [])) or 1), purpose="review")


# ---------------- conversation with the client ----------------

CHAT_TOOL = {
    "name": "submit_reply",
    "description": "Reply to the client in the campaign conversation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reply": {"type": "string", "description": "Your reply as their creative director: helpful, specific, opinionated, concise (under 180 words)."},
            "actions": {"type": "array", "description": "Changes you propose. The client must click to run each one; nothing runs automatically.",
                        "items": {"type": "object", "properties": {
                            "kind": {"type": "string", "enum": ["revise", "more_concepts"]},
                            "concept_id": {"type": "string", "description": "For revise: the concept id, e.g. c2"},
                            "instruction": {"type": "string", "description": "For revise: the exact change to make, written as a brief to the designer"},
                            "label": {"type": "string", "description": "Short button label, e.g. 'Make concept 2 warmer'"}},
                            "required": ["kind", "label"]}},
        },
        "required": ["reply", "actions"],
    },
}


def campaign_context(project):
    lines = [f"Campaign: {project.get('title')}", f"Director's note: {project.get('director_note', '')}"]
    sel = project.get("selected") or {}
    for c in project.get("concepts", []):
        vs = c.get("versions", [])
        cur = vs[c.get("current", len(vs) - 1)] if vs else None
        hist = "; ".join(v.get("instruction", "") for v in vs[1:])[:300]
        score = (cur or {}).get("review", {}) or {}
        lines.append(f"- {c['id']}: {c.get('name')} ({c.get('layout', '')}) — headline \"{(cur or {}).get('headline', c.get('headline', ''))}\""
                     f"{' — SELECTED' if sel.get('cid') == c['id'] else ''}{' — score ' + str(score.get('average')) if score.get('average') else ''}"
                     f"{' — revisions: ' + hist if hist else ''} — status {c.get('status')}")
    for a in project.get("approvals", [])[-3:]:
        lines.append(f"Approval {a['id']}: concept {a['cid']} — {a['state']}")
    return "\n".join(lines)


def chat(project, brand, brand_dir, message, current_pngs):
    """One turn of the campaign conversation. The whole campaign history is sent each time, so context is never lost."""
    content = []
    for cid, path in current_pngs[:6]:
        content.append(text_block(f"Current render of {cid}:"))
        content.append(image_block(path, max_side=800))
    history = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in (project.get("chat") or [])[-16:])
    content.append(text_block(f"""{brief_section(project)}

# CAMPAIGN SO FAR
{campaign_context(project)}

# CONVERSATION SO FAR
{history or '(none)'}

# CLIENT'S NEW MESSAGE
{message}

Answer as their executive creative director. If they ask for changes, propose them as actions (they'll click to run them) \
rather than claiming you've done anything. Be honest when an idea is weak and say what would be stronger."""))
    return llm.call(_system(brand), content, CHAT_TOOL, max_tokens=4000, purpose="chat", effort="medium")
