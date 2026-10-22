"""
gemini_client.py
Talks to Google's Gemini API (free tier) — this is the "brain" every agent uses to think/write.
It can also LOOK at images (used to pick the most relevant photo for a section).
"""

import base64
import json
import re
import time
import requests
from config import GEMINI_API_KEY

GEMINI_MODEL = "gemini-3.1-flash-lite"  # officially "Stable" (GA) model, fast + reliable free tier
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def ask_gemini(prompt, temperature=0.8, max_retries=4, images=None, json_mode=False, max_output_tokens=None):
    """
    Sends a prompt to Gemini, returns the plain text reply. Auto-retries on temporary errors.
    images: optional list of (image_bytes, mime_type) — Gemini will be able to see them.
    json_mode: forces Gemini to return strictly valid JSON (important when the reply contains code).
    max_output_tokens: raise the reply length limit for long articles.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")

    parts = [{"text": prompt}]
    for idx, (img_bytes, mime) in enumerate(images or [], start=1):
        parts.append({"text": f"Image {idx}:"})
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(img_bytes).decode("ascii")}})

    gen_cfg = {"temperature": temperature}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"
    if max_output_tokens:
        gen_cfg["maxOutputTokens"] = max_output_tokens

    last_error = None
    for attempt in range(1, max_retries + 1):
        resp = requests.post(
            GEMINI_URL,
            headers={
                "x-goog-api-key": GEMINI_API_KEY,   # newer "AQ." keys require the header, not ?key=
                "Content-Type": "application/json",
            },
            json={
                "contents": [{"parts": parts}],
                "generationConfig": gen_cfg,
            },
            timeout=120,
        )

        if resp.status_code in (429, 500, 502, 503, 504):
            # Temporary overload / rate limit — wait and try again (2s, 4s, 8s, 16s)
            wait = 2 ** attempt
            print(f"[info] Gemini busy ({resp.status_code}), retrying in {wait}s... (attempt {attempt}/{max_retries})")
            last_error = resp
            time.sleep(wait)
            continue

        resp.raise_for_status()
        data = resp.json()
        reply_parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in reply_parts if not p.get("thought"))

    # All retries used up
    last_error.raise_for_status()


def ask_gemini_json(prompt, temperature=0.7, images=None, max_output_tokens=None, attempts=3):
    """
    Sends a prompt that asks Gemini to reply as JSON, and parses it.
    Uses Gemini's strict JSON mode, and retries if the reply still isn't valid JSON.
    """
    last_error = None
    for attempt in range(1, attempts + 1):
        text = ask_gemini(prompt, temperature=temperature, images=images,
                          json_mode=True, max_output_tokens=max_output_tokens)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
            try:
                if match:
                    return json.loads(match.group(0))
            except json.JSONDecodeError as e:
                last_error = e
        print(f"[warn] Gemini reply was not valid JSON (attempt {attempt}/{attempts}), retrying...")
    raise ValueError(f"Gemini did not return valid JSON after {attempts} attempts: {last_error}")
