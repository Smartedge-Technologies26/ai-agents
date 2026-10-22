"""
telegram_client.py
Sends Telegram notifications with the FULL blog/project content (images + readable
text), and inline Approve/Reject buttons you can tap right from your phone — no need
to open the website to review.

One-time setup (free):
1. In Telegram, message @BotFather -> send /newbot -> follow the prompts -> copy the token
2. Open your new bot and send it any message (e.g. "hi") so it's allowed to message you back
3. Visit (replace <TOKEN>): https://api.telegram.org/bot<TOKEN>/getUpdates
   Find "chat":{"id": ...} in the response -> that number is your chat id
4. Put both values in your .env file as TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
"""

import re
import html as html_lib
import requests
import browser_client as bc
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

TELEGRAM_MESSAGE_LIMIT = 3500  # stay safely under Telegram's 4096 char cap


def _api():
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _table_to_text(match):
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", match.group(0), flags=re.DOTALL)
    lines = []
    for row in rows:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.DOTALL)
        lines.append("\u2022 " + " | ".join(re.sub(r"<[^>]+>", "", c).strip() for c in cells))
    return "\n" + "\n".join(lines) + "\n\n"


def _code_to_text(match):
    code = re.sub(r"<[^>]+>", "", match.group(1))
    return "\n\n\U0001F4BB CODE:\n" + code.strip("\n") + "\n\u2014 end of code \u2014\n\n"


def _html_to_text(content_html):
    """Converts the article's HTML into clean, readable plain text for Telegram."""
    text = content_html
    text = re.sub(r"<figure.*?</figure>", "", text, flags=re.DOTALL)  # images are sent separately as photos
    text = re.sub(r"<pre[^>]*>(.*?)</pre>", _code_to_text, text, flags=re.DOTALL)
    text = re.sub(r"<table.*?</table>", _table_to_text, text, flags=re.DOTALL)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", lambda m: f"\n\n\U0001F539 {m.group(1)}\n", text, flags=re.DOTALL)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", lambda m: f"\n\n\u25AA\uFE0F {m.group(1)}\n", text, flags=re.DOTALL)
    text = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: f"\u2022 {m.group(1)}\n", text, flags=re.DOTALL)
    text = re.sub(r"</p>", "\n\n", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)  # strip any remaining tags
    text = html_lib.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse extra blank lines
    return text.strip()


def _send_message(text):
    try:
        requests.post(f"{_api()}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=20)
    except Exception as e:
        print(f"[warn] Telegram sendMessage failed: {e}")


def _send_photo(photo_url):
    """Fallback: ask Telegram to fetch the photo from a URL (may fail if the host blocks bots)."""
    try:
        requests.post(f"{_api()}/sendPhoto", json={"chat_id": TELEGRAM_CHAT_ID, "photo": photo_url}, timeout=30)
    except Exception as e:
        print(f"[warn] Telegram sendPhoto failed: {e}")


def _send_photo_bytes(image_bytes):
    """Uploads the image file itself to Telegram — works regardless of any bot-blocking on the website."""
    try:
        resp = requests.post(
            f"{_api()}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID},
            files={"photo": ("image.jpg", image_bytes)},
            timeout=60,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[warn] Telegram photo upload failed: {e}")


def _send_long_text(text):
    """Splits long content into several messages (on line boundaries) to respect Telegram's length limit."""
    chunk = ""
    for line in text.split("\n"):
        while len(line) > TELEGRAM_MESSAGE_LIMIT:  # a single huge line: hard-split it
            if chunk:
                _send_message(chunk)
                chunk = ""
            _send_message(line[:TELEGRAM_MESSAGE_LIMIT])
            line = line[TELEGRAM_MESSAGE_LIMIT:]
        if len(chunk) + len(line) + 1 > TELEGRAM_MESSAGE_LIMIT:
            _send_message(chunk)
            chunk = line
        else:
            chunk = f"{chunk}\n{line}" if chunk else line
    if chunk.strip():
        _send_message(chunk)


def notify_draft(content_type, item):
    """
    item: dict with draft_id, title, description, content_html, image_urls
    Sends: title -> all images -> full readable text -> Approve/Reject buttons.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[info] Telegram not configured - skipping notification.")
        return

    label = "Blog" if content_type == "blog" else "Project"
    _send_message(f"\U0001F195 New {label} ready for review!\n\n\U0001F4CC {item['title']}")

    image_bytes_list = item.get("image_bytes") or []
    if image_bytes_list:
        for img in image_bytes_list:
            _send_photo_bytes(img)
    else:
        for url in item.get("image_urls", []):
            _send_photo(url)

    plain_text = _html_to_text(item.get("content_html", ""))
    _send_long_text(plain_text)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "Ready to decide?",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "\u2705 Approve", "callback_data": f"approve:{item['draft_id']}"},
                {"text": "\u274C Reject", "callback_data": f"reject:{item['draft_id']}"},
            ]]
        },
    }
    try:
        resp = requests.post(f"{_api()}/sendMessage", json=payload, timeout=20)
        resp.raise_for_status()
        print(f"[info] Telegram notification sent for {content_type} #{item['draft_id']}.")
    except Exception as e:
        print(f"[warn] Telegram notification failed: {e}")


def notify_text(text):
    """Simple text-only notification, no buttons (used for run summaries/errors)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    _send_message(text)


def get_offset():
    """Remembers which Telegram updates we've already processed (stored on the server)."""
    try:
        result = bc.call("get_setting", key="telegram_offset")
        value = result.get("value")
        return int(value) if value else 0
    except Exception:
        return 0


def set_offset(offset):
    try:
        bc.call("set_setting", key="telegram_offset", value=str(offset))
    except Exception as e:
        print(f"[warn] Could not save telegram offset: {e}")
