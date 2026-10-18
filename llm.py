#!/usr/bin/env python3
"""LLM provider abstraction — Content Engine v2. APPROVED 2026-10-17.

Primary:  Google Gemini (free tier) — GEMINI_API_KEY, read at call time.
Fallback: OpenRouter (:free models) — OPENROUTER_API_KEY. When unset, the
          engine runs primary-only and logs one clear line (no crash).

Provider switch is ONE env var, no code changes:
    LLM_PROVIDER=gemini|openrouter   (default: gemini)
    LLM_MODEL=<model id>             (default per provider)
    LLM_TEMPERATURE, LLM_MAX_TOKENS  (optional overrides)

Both providers speak the OpenAI-compatible chat-completions shape:
    POST {base_url}/chat/completions
    {model, messages:[{role,content}], temperature, max_tokens}

Gemini base:    https://generativelanguage.googleapis.com/v1beta/openai/
OpenRouter base: https://openrouter.ai/api/v1
(Default models: gemini-2.5-flash | meta-llama/llama-3.3-70b-instruct:free)

Security: keys are read from the environment AT CALL TIME only, never stored,
never logged. Free-tier prompts may be used by providers for product
improvement — do not send sensitive client data through this module.
"""
import json
import os
import sys
import urllib.error
import urllib.request

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
}
TIMEOUT = 120


class LLMError(Exception):
    pass


class LLMUnavailable(LLMError):
    """No provider key set, or all providers failed."""


def _gemini_key():
    # same lookup pattern as clinic-demo /pharma-ai and /style
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_APIkey")


def _openrouter_key():
    return os.environ.get("OPENROUTER_API_KEY")


def available():
    """Which providers are usable right now. Never raises."""
    return {
        "provider": os.environ.get("LLM_PROVIDER", "gemini"),
        "gemini": bool(_gemini_key()),
        "openrouter": bool(_openrouter_key()),
    }


def _post(base, key, model, messages, temperature, max_tokens):
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "HTTP-Referer": "https://localhost/content-engine",
                 "X-Title": "Content Engine v2"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:300]
        raise LLMError(f"{base} HTTP {e.code}: {body}")
    except Exception as e:
        raise LLMError(f"{base} request failed: {type(e).__name__}: {str(e)[:160]}")
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        err = data.get("error", {})
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
        raise LLMError(f"bad LLM response shape: {msg[:160]}")
    if not text or not text.strip():
        raise LLMError("empty LLM response")
    return text.strip()


def _log(msg):
    print(f"[llm] {msg}", file=sys.stderr, flush=True)


def chat(messages, temperature=None, max_tokens=None, timeout=None,
         prefer=None):
    """Chat completion with automatic provider fallback.

    Returns the assistant text. Raises LLMUnavailable when no key is set or
    every configured provider fails. Never crashes on a missing key.
    """
    global TIMEOUT
    if timeout:
        TIMEOUT = timeout
    temperature = float(os.environ.get("LLM_TEMPERATURE", temperature or 0.7))
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", max_tokens or 1500))

    primary = prefer or os.environ.get("LLM_PROVIDER", "gemini")
    if primary not in ("gemini", "openrouter"):
        _log(f"unknown LLM_PROVIDER={primary!r}, using gemini")
        primary = "gemini"
    order = [primary] + [p for p in ("gemini", "openrouter") if p != primary]

    keys = {"gemini": _gemini_key(), "openrouter": _openrouter_key()}
    if not keys["openrouter"]:
        _log("OPENROUTER_API_KEY not set — primary-only mode "
             "(set it via dashboard secret form to enable fallback)")
    tried = []
    for prov in order:
        key = keys[prov]
        if not key:
            continue
        base = GEMINI_BASE if prov == "gemini" else OPENROUTER_BASE
        model = os.environ.get("LLM_MODEL") or DEFAULT_MODELS[prov]
        tried.append(f"{prov}/{model}")
        try:
            text = _post(base, key, model, messages, temperature, max_tokens)
            _log(f"ok via {prov} ({model}, {len(text)} chars)")
            return text
        except LLMError as e:
            _log(f"{prov} failed: {e}")
    if not tried:
        raise LLMUnavailable(
            "No LLM key available. Set GEMINI_API_KEY (primary, free at "
            "aistudio.google.com) and optionally OPENROUTER_API_KEY "
            "(fallback, free at openrouter.ai). Engine features needing "
            "the LLM will use their non-LLM fallbacks.")
    raise LLMUnavailable(f"All LLM providers failed: {'; '.join(tried)}")


def ask(system, user, **kw):
    """Single-turn ask. messages=[system, user]."""
    return chat([{"role": "system", "content": system},
                 {"role": "user", "content": user}], **kw)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", default="")
    ap.add_argument("--system", default="You are a helpful assistant.")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        print(json.dumps(available(), indent=2))
        return
    if not a.ask:
        sys.exit("pass --ask '...' or --status")
    try:
        print(ask(a.system, a.ask))
    except LLMUnavailable as e:
        print(f"LLM unavailable: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
