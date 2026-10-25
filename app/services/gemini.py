from __future__ import annotations

import json
import logging
import threading

import requests
from flask import current_app

log = logging.getLogger("watercast.gemini")

PLACEHOLDER = "PASTE_YOUR_GEMINI_API_KEY_HERE"
_local = threading.local()
_no_thinking: set[str] = set()


class GeminiError(Exception):
    pass


def configured() -> bool:
    key = (current_app.config.get("GEMINI_API_KEY") or "").strip()
    return bool(key) and key != PLACEHOLDER


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        _local.session = s
    return s


def _models() -> list[str]:
    cfg = current_app.config
    out = []
    for m in (cfg.get("GEMINI_MODEL"), cfg.get("GEMINI_FALLBACK_MODEL")):
        m = (m or "").strip()
        if m and m not in out:
            out.append(m)
    return out


def _describe(resp: requests.Response) -> str:
    try:
        msg = (resp.json().get("error") or {}).get("message") or ""
    except ValueError:
        msg = ""
    code = resp.status_code
    hint = {400: "request rejected", 401: "API key not accepted", 403: "API key not allowed for this API",
            404: "model not found", 429: "quota or rate limit reached"}.get(code, "server error" if code >= 500 else "")
    return f"Gemini answered HTTP {code}" + (f" ({hint})" if hint else "") + (f": {msg[:160]}" if msg else "")


def generate_json(system: str, prompt: str, schema: dict, thinking: str = "low") -> tuple[dict, str]:
    if not configured():
        raise GeminiError("Gemini API key is not set")
    cfg = current_app.config
    gen = {"temperature": 0.2, "responseMimeType": "application/json", "responseSchema": schema}
    headers = {"x-goog-api-key": cfg["GEMINI_API_KEY"].strip(), "Content-Type": "application/json"}
    last = "Gemini did not answer"
    for model in _models():
        url = f"{cfg['GEMINI_API_URL'].rstrip('/')}/models/{model}:generateContent"
        use_thinking = bool(thinking) and model not in _no_thinking
        while True:
            conf = dict(gen, thinkingConfig={"thinkingLevel": thinking}) if use_thinking else gen
            body = {"systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": conf}
            try:
                resp = _session().post(url, json=body, headers=headers, timeout=cfg["GEMINI_TIMEOUT"])
            except requests.exceptions.Timeout:
                resp, last = None, "Gemini took too long to answer (timeout)"
            except requests.RequestException:
                resp, last = None, "could not connect to Gemini"
            if resp is not None and resp.status_code == 400 and use_thinking and "thinking" in resp.text.lower():
                _no_thinking.add(model)
                use_thinking = False
                continue
            break
        if resp is None:
            continue
        if resp.status_code == 404:
            last = _describe(resp)
            log.warning("Gemini model %s not available, trying next", model)
            continue
        if not resp.ok:
            raise GeminiError(_describe(resp))
        try:
            data = resp.json()
            cand = (data.get("candidates") or [{}])[0]
            parts = (cand.get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if not text:
                reason = cand.get("finishReason") or (data.get("promptFeedback") or {}).get("blockReason") or "empty"
                raise GeminiError(f"Gemini returned no answer ({reason})")
            text = text.strip()
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            return json.loads(text), model
        except (ValueError, KeyError, IndexError) as exc:
            raise GeminiError("Gemini returned data that could not be read") from exc
    raise GeminiError(last)
