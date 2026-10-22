"""
image_client.py
Finds the MOST RELEVANT image for a section of an article and returns (image_bytes, credit_html).

How it works (this is the "AI image search"):
  1. Collect candidate REAL photos for the search phrase from
       - Wikimedia Commons (free, no key; has real photos of specific parts like Arduino Uno,
         HC-SR04, DHT11, servo motors, breadboards...) — only commercially-usable licenses
       - Pixabay (free key; good generic electronics/robotics photos)
  2. Show all the candidates to Gemini (it can SEE images) and let it pick the one that best
     matches the topic — or say none are suitable.
  3. Only if nothing suitable exists, fall back to an AI-generated image (Pollinations).

Wikimedia photos need a small credit line (license requirement) — we return it as `credit_html`
so the article can show it under the picture. Pixabay photos need no credit.
"""

import html as html_lib
import random
import re
import time
import urllib.parse
import requests
from config import PIXABAY_API_KEY
from gemini_client import ask_gemini_json

HEADERS = {"User-Agent": "SmartEdgeContentBot/1.0 (https://smartedgetech.in; blog automation)"}
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
PIXABAY_URL = "https://pixabay.com/api/"
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"

MAX_CANDIDATES = 10
AI_MIN_GAP_SECONDS = 16
_last_ai_request = 0.0
_used_keys = set()  # never use the same photo twice in one run

# Broad, always-on-niche searches used when the specific search finds little
NICHE_FALLBACKS = [
    "electronic circuit board",
    "arduino",
    "microcontroller electronics",
    "robotics technology",
    "electronic components",
    "sensor module electronics",
]

STOPWORDS = {
    "a", "an", "the", "with", "and", "for", "of", "on", "in", "to", "using", "simple",
    "basic", "beginner", "beginners", "guide", "close", "up", "closeup", "how", "work",
    "works", "your", "connected", "multiple", "illustration", "labeled",
    "complete", "working", "setup", "main", "hands", "assembling", "project",
}


# ----------------------------------------------------------------------------- helpers
def _search_terms(query):
    """Specific phrase first, then progressively shorter versions of it."""
    tokens = re.findall(r"[A-Za-z0-9]+", query)
    words = [w for w in tokens if w.lower() not in STOPWORDS]
    terms = []
    for n in (4, 3, 2):
        if len(words) >= n:
            terms.append(" ".join(words[:n]))
    if len(words) == 1:
        terms.append(words[0])
    seen, ordered = set(), []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            ordered.append(t)
    return ordered


def _strip_tags(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:80]


def _license_ok(lic):
    """Only licenses that allow commercial use of the unmodified image (with credit)."""
    l = (lic or "").lower().strip()
    if not l or re.search(r"\bnc\b|-nc|\bnd\b|-nd", l):
        return False
    return l.startswith(("cc0", "public domain", "pd", "cc by", "cc-by"))


def _mime_for(content, header_ctype):
    if header_ctype and header_ctype.startswith("image/"):
        return header_ctype.split(";")[0]
    if content.startswith(b"\x89PNG"):
        return "image/png"
    if content.startswith(b"RIFF"):
        return "image/webp"
    return "image/jpeg"


# ----------------------------------------------------------------------------- sources
def _commons_candidates(term, limit=5):
    try:
        resp = requests.get(
            COMMONS_API,
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"{term} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 15,
                "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
                "iiurlwidth": 960,   # Wikimedia only serves standard thumbnail widths; 960 is one of them
            },
            headers=HEADERS, timeout=25,
        )
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
    except Exception as e:
        print(f"[warn] Wikimedia search failed for '{term}': {e}")
        return []

    out = []
    for page in sorted(pages.values(), key=lambda p: p.get("index", 999)):
        info = (page.get("imageinfo") or [None])[0]
        if not info or info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if info.get("width", 0) < 700 or not info.get("thumburl"):
            continue
        ext = info.get("extmetadata", {})
        lic = ext.get("LicenseShortName", {}).get("value", "")
        if not _license_ok(lic):
            continue
        key = "commons:" + page["title"]
        if key in _used_keys:
            continue
        artist = _strip_tags(ext.get("Artist", {}).get("value", "")) or "Unknown author"
        title = re.sub(r"^File:|\.[A-Za-z0-9]+$", "", page["title"]).replace("_", " ")
        credit = (
            f'Image: <a href="{html_lib.escape(info.get("descriptionurl", ""), quote=True)}" '
            f'target="_blank" rel="noopener">{html_lib.escape(title)}</a> by {html_lib.escape(artist)} '
            f'({html_lib.escape(lic)}), via Wikimedia Commons'
        )
        out.append({"key": key, "judge_url": info["thumburl"], "final_url": info["thumburl"],
                    "credit": credit})
        if len(out) >= limit:
            break
    return out


def _pixabay_candidates(term, limit=3):
    if not PIXABAY_API_KEY:
        return []
    try:
        resp = requests.get(
            PIXABAY_URL,
            params={"key": PIXABAY_API_KEY, "q": term[:100], "image_type": "photo",
                    "orientation": "horizontal", "safesearch": "true", "min_width": 900, "per_page": 15},
            timeout=20,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
    except Exception as e:
        print(f"[warn] Pixabay search failed for '{term}': {e}")
        return []

    out = []
    for h in hits:
        key = f"pixabay:{h['id']}"
        if key in _used_keys:
            continue
        out.append({"key": key, "judge_url": h["webformatURL"], "final_url": h["largeImageURL"], "credit": ""})
        if len(out) >= limit:
            break
    return out


def _gather_candidates(query, relaxed=False, exclude=None):
    """
    strict  (relaxed=False): only the specific search phrases for this exact subject.
    relaxed (relaxed=True) : also broad electronics searches, used only if the strict pass found nothing good.
    `exclude` = photos already judged unsuitable in an earlier pass.
    """
    candidates, seen = [], set(exclude or [])
    specific = _search_terms(query)
    terms = list(specific)
    if relaxed:
        fallbacks = NICHE_FALLBACKS[:]
        random.shuffle(fallbacks)
        terms += fallbacks

    for idx, term in enumerate(terms):
        if idx >= len(specific) and len(candidates) >= 4:
            break  # enough broad options to choose from
        for cand in _commons_candidates(term) + _pixabay_candidates(term):
            if cand["key"] not in seen:
                seen.add(cand["key"])
                candidates.append(cand)
        time.sleep(0.5)  # be polite to the free APIs
        if len(candidates) >= MAX_CANDIDATES:
            break
    return candidates[:MAX_CANDIDATES]


# ----------------------------------------------------------------------------- AI choice
STRICT_RULE = ("Be strict: choose an image ONLY if it clearly shows the exact subject described (the same specific "
               "component, board, tool or setup). If none does, answer 0.")
RELAXED_RULE = ("No exact match was found, so choose the cleanest, most professional photo of the same kind of "
                "electronics/robotics hardware that would still make sense next to this text. Answer 0 ONLY if every "
                "image is unsuitable.")


def _pick_best(query, topic, candidates, strict=True):
    """Downloads candidate previews, lets Gemini look at them, returns (candidate, image_bytes) or (None, None)."""
    loaded = []  # (candidate, bytes, mime)
    for cand in candidates:
        try:
            r = requests.get(cand["judge_url"], headers=HEADERS, timeout=30)
            if r.status_code == 200 and len(r.content) > 3000:
                loaded.append((cand, r.content, _mime_for(r.content, r.headers.get("Content-Type"))))
        except Exception as e:
            print(f"[warn] Could not load a candidate preview: {e}")
    if not loaded:
        return None, None

    rule = STRICT_RULE if strict else RELAXED_RULE
    prompt = f"""
You are choosing a photo for one section of a beginner-friendly IoT / robotics / embedded-systems blog post.

Article topic: {topic or query}
This image should show: {query}

Below are {len(loaded)} candidate images, numbered in order (Image 1, Image 2, ...).
Pick the ONE that best matches what the image should show.

Prefer: a clear, sharp, professional-looking photo of the actual subject (real hardware, a close-up of the
component, a neat workbench setup).
Avoid: screenshots, diagrams crammed with text, logos, watermarks, cartoons, close-ups of people's faces,
or anything unrelated to electronics/robotics.
{rule}

Reply with ONLY valid JSON: {{"choice": <number>, "reason": "<very short reason>"}}
"""
    try:
        result = ask_gemini_json(prompt, temperature=0.2, images=[(b, m) for _, b, m in loaded])
        choice = int(result.get("choice", 0))
        print(f"[info] AI picked image {choice} of {len(loaded)} for '{query}': {result.get('reason', '')}")
    except Exception as e:
        if strict:
            print(f"[warn] AI image choice failed ({e}); trying the broader search instead.")
            return None, None
        print(f"[warn] AI image choice failed ({e}); using the top search result instead.")
        choice = 1

    if choice < 1 or choice > len(loaded):
        return None, None
    cand, content, _ = loaded[choice - 1]

    if cand["final_url"] != cand["judge_url"]:  # e.g. Pixabay: fetch the larger version
        try:
            r = requests.get(cand["final_url"], headers=HEADERS, timeout=60)
            if r.status_code == 200 and len(r.content) > 5000:
                content = r.content
        except Exception:
            pass  # the preview is still a usable image
    return cand, content


# ----------------------------------------------------------------------------- AI fallback
def _ai_image(query, max_attempts=3):
    """Last resort: AI-generated image (free service, so requests are spaced out)."""
    global _last_ai_request
    style = "professional product photograph, macro lens, sharp focus, studio lighting, no text, no watermark"
    prompt = urllib.parse.quote(f"{query}, {style}")
    last_error = None
    for attempt in range(1, max_attempts + 1):
        wait = AI_MIN_GAP_SECONDS - (time.time() - _last_ai_request)
        if wait > 0:
            time.sleep(wait)
        _last_ai_request = time.time()
        url = f"{POLLINATIONS_URL.format(prompt=prompt)}?width=1024&height=683&nologo=true&seed={random.randint(1, 999999)}"
        try:
            resp = requests.get(url, timeout=120)
            ctype = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and ctype.startswith("image/") and len(resp.content) > 5000:
                return resp.content
            last_error = f"HTTP {resp.status_code}, type '{ctype}'"
        except Exception as e:
            last_error = str(e)
        print(f"[warn] AI image attempt {attempt}/{max_attempts} failed for '{query}': {last_error}")
        if attempt < max_attempts:
            time.sleep(10 * attempt)
    raise RuntimeError(f"Could not get any image for '{query}': {last_error}")


# ----------------------------------------------------------------------------- public
def find_image(query, topic=""):
    """Returns (image_bytes, credit_html). credit_html is '' when no credit is required."""
    rejected = set()
    for relaxed in (False, True):  # pass 1: exact subject only; pass 2: similar hardware is acceptable
        candidates = _gather_candidates(query, relaxed=relaxed, exclude=rejected)
        if not candidates:
            continue
        cand, content = _pick_best(query, topic, candidates, strict=not relaxed)
        if cand and content:
            _used_keys.add(cand["key"])
            return content, cand["credit"]
        rejected.update(c["key"] for c in candidates)
        if not relaxed:
            print(f"[info] No exact photo for '{query}', widening the search...")
    print(f"[info] No suitable real photo for '{query}', falling back to an AI image.")
    return _ai_image(query), ""
