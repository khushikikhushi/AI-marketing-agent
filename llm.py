"""One door to the AI models. TEXT_PROVIDER in .env picks OpenAI (default) or Claude (the original, kept as a fallback).
Every call returns structured JSON that matches a schema, and is recorded in the usage log."""
import copy
import json
import os
import threading

import usage

_local = threading.local()


def set_project(pid):
    """Tag the calls made on this thread with a campaign id (for the usage page)."""
    _local.project = pid


def current_project():
    return getattr(_local, "project", None)


def provider():
    return os.getenv("TEXT_PROVIDER", "openai").strip().lower()


def text_model():
    if provider() == "claude":
        return os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    return os.getenv("OPENAI_TEXT_MODEL", "gpt-5.6")


def has_key():
    k = os.getenv("ANTHROPIC_API_KEY" if provider() == "claude" else "OPENAI_API_KEY", "")
    return bool(k) and not k.startswith("paste")


# ---------------- OpenAI ----------------

_openai = None


def openai_client():
    global _openai
    if _openai is None:
        key = os.getenv("OPENAI_API_KEY", "")
        if not key or key.startswith("paste"):
            raise RuntimeError("No OpenAI API key found. Open the .env file, paste your key after OPENAI_API_KEY=, save, and restart the app.")
        from openai import OpenAI
        _openai = OpenAI(api_key=key, timeout=900, max_retries=3)
    return _openai


def strict_schema(schema):
    """OpenAI strict structured outputs need every property listed as required and no extra properties.
    Properties that were optional become nullable instead."""
    s = copy.deepcopy(schema)

    def walk(node):
        if not isinstance(node, dict):
            return
        for k in ("minimum", "maximum", "minItems", "maxItems"):
            node.pop(k, None)
        if node.get("type") == "object" and "properties" in node:
            req = set(node.get("required", []))
            for name, prop in node["properties"].items():
                walk(prop)
                if name not in req:
                    t = prop.get("type")
                    if isinstance(t, str):
                        prop["type"] = [t, "null"]
                    if "enum" in prop and None not in prop["enum"]:
                        prop["enum"] = prop["enum"] + [None]
            node["required"] = list(node["properties"].keys())
            node["additionalProperties"] = False
        if node.get("type") == "array" or (isinstance(node.get("type"), list) and "array" in node["type"]):
            walk(node.get("items"))
    walk(s)
    return s


def _to_openai_content(content):
    out = []
    for b in content:
        if b["type"] == "text":
            out.append({"type": "input_text", "text": b["text"]})
        elif b["type"] == "image":
            src = b["source"]
            out.append({"type": "input_image", "detail": "high",
                        "image_url": f"data:{src['media_type']};base64,{src['data']}"})
    return out


def _openai_call(system, content, tool, max_tokens, purpose, effort):
    c = openai_client()
    model = text_model()
    kwargs = dict(
        model=model,
        instructions=system,
        input=[{"role": "user", "content": _to_openai_content(content)}],
        text={"format": {"type": "json_schema", "name": tool["name"], "description": tool.get("description", ""),
                         "schema": strict_schema(tool["input_schema"]), "strict": True}},
        max_output_tokens=max_tokens + 40000,  # reasoning tokens count against this limit too
        store=False,
    )
    effort = effort or os.getenv("OPENAI_REASONING_EFFORT", "high")
    if effort and effort != "none":
        kwargs["reasoning"] = {"effort": effort}
    resp = c.responses.create(**kwargs)
    u = getattr(resp, "usage", None)
    usage.record("text", "openai", model, purpose, current_project(),
                 getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0))
    if getattr(resp, "status", "") == "incomplete":
        reason = getattr(getattr(resp, "incomplete_details", None), "reason", "")
        if reason == "max_output_tokens":
            raise RuntimeError("The AI ran out of space while writing this. Press Retry (or ask for fewer carousel slides).")
        raise RuntimeError(f"The AI stopped early ({reason or 'unknown reason'}). Press Retry.")
    for item in getattr(resp, "output", []) or []:
        for part in getattr(item, "content", []) or []:
            if getattr(part, "type", "") == "refusal":
                raise RuntimeError("The AI declined this request: " + (getattr(part, "refusal", "") or "")[:200])
    text = getattr(resp, "output_text", "") or ""
    try:
        return json.loads(text)
    except Exception:
        raise RuntimeError("The AI's answer wasn't valid structured data. Press Retry.")


# ---------------- Claude (original implementation, kept) ----------------

_claude = None


def _claude_call(system, content, tool, max_tokens, purpose):
    global _claude
    if _claude is None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("No Claude API key found. Add ANTHROPIC_API_KEY to .env, or set TEXT_PROVIDER=openai.")
        import anthropic
        _claude = anthropic.Anthropic(max_retries=3, timeout=900)
    model = text_model()
    resp = _claude.messages.create(model=model, max_tokens=max_tokens, system=system, tools=[tool],
                                   tool_choice={"type": "tool", "name": tool["name"]},
                                   messages=[{"role": "user", "content": content}])
    u = getattr(resp, "usage", None)
    usage.record("text", "claude", model, purpose, current_project(),
                 getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0))
    for block in resp.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return block.input
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("The AI ran out of space while writing this. Press Retry.")
    raise RuntimeError("The AI didn't return a usable answer. Press Retry.")


def call(system, content, tool, max_tokens=20000, purpose="", effort=None):
    """content: list of {"type":"text"} / {"type":"image","source":{base64}} blocks. Returns a dict matching tool['input_schema']."""
    if provider() == "claude":
        return _claude_call(system, content, tool, max_tokens, purpose)
    return _openai_call(system, content, tool, max_tokens, purpose, effort)


def friendly_error(e):
    """Turn provider exceptions into plain-English messages."""
    name, msg = type(e).__name__, str(e)
    low = msg.lower()
    if name == "AuthenticationError":
        return "The API key was rejected. Check the key in the .env file and restart the app."
    if name == "PermissionDeniedError" or "organization must be verified" in low or "verify" in low and "organization" in low:
        return ("Your OpenAI account doesn't have access to this model yet. Some models (including GPT Image) need "
                "Organization Verification at platform.openai.com → Settings → Organization → General.")
    if name == "NotFoundError" or "model_not_found" in low or "does not exist" in low:
        return "That model name isn't available to your account. Check OPENAI_TEXT_MODEL / OPENAI_IMAGE_MODEL in .env."
    if "insufficient_quota" in low or "credit balance" in low or "billing" in low:
        return "Your API account is out of credit. Add credit (platform.openai.com → Billing), then press Retry."
    if name == "RateLimitError":
        return "The API is rate-limiting requests. Wait a minute and press Retry."
    if name in ("APIConnectionError", "APITimeoutError"):
        return "Couldn't reach the AI service (internet connection or timeout). Press Retry."
    if "content_policy" in low or "safety" in low and "image" in low:
        return "The image request was blocked by the provider's safety system. Try rewording the change."
    if "Executable doesn't exist" in msg or "playwright install" in msg:
        return "The image renderer isn't installed. Close the app, run setup.bat again, then restart."
    return msg[:400]
