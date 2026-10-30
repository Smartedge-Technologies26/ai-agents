"""
poll_telegram.py
Checks for new Telegram button taps (Approve/Reject) and acts on them:
  - Approve -> publishes that draft immediately (same as clicking Approve on the dashboard)
  - Reject  -> rejects that draft AND automatically generates a brand-new replacement of
               the SAME type (blog or project), then sends a fresh notification for it

This is meant to run on a schedule (every 15-30 minutes) via GitHub Actions — see
.github/workflows/poll-telegram.yml. You can also run it manually to test:
    python poll_telegram.py
"""

import uuid
import requests
import browser_client
from browser_client import call as api_call
from config import TELEGRAM_BOT_TOKEN
from admin_client import log_step
from pipeline import regenerate_one
from telegram_client import notify_draft, get_offset, set_offset

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def answer_callback(callback_id, text):
    try:
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery",
                       json={"callback_query_id": callback_id, "text": text}, timeout=15)
    except Exception as e:
        print(f"[warn] answerCallbackQuery failed: {e}")


def edit_message(chat_id, message_id, text):
    try:
        requests.post(f"{TELEGRAM_API}/editMessageText",
                       json={"chat_id": chat_id, "message_id": message_id, "text": text}, timeout=15)
    except Exception as e:
        print(f"[warn] editMessageText failed: {e}")


def main():
    if not TELEGRAM_BOT_TOKEN:
        print("[info] Telegram not configured, nothing to poll.")
        return

    browser_client.start_session()
    try:
        offset = get_offset()
        resp = requests.get(f"{TELEGRAM_API}/getUpdates", params={"offset": offset}, timeout=30)
        resp.raise_for_status()
        updates = resp.json().get("result", [])

        if not updates:
            print("[info] No new Telegram activity.")
            return

        for update in updates:
            offset = update["update_id"] + 1

            cq = update.get("callback_query")
            if not cq:
                continue  # not a button tap (e.g. a plain text message) - ignore it

            data = cq.get("data", "")  # looks like "approve:12" or "reject:12"
            chat_id = cq["message"]["chat"]["id"]
            message_id = cq["message"]["message_id"]
            callback_id = cq["id"]

            if ":" not in data:
                continue
            action, draft_id_str = data.split(":", 1)
            draft_id = int(draft_id_str)

            draft_info = api_call("get_draft", draft_id=draft_id)
            draft = draft_info.get("draft") or {}
            content_type = draft.get("content_type", "blog")
            title = draft.get("title", "this item")

            if action == "approve":
                api_call("approve", draft_id=draft_id)
                answer_callback(callback_id, "Approved and published!")
                edit_message(chat_id, message_id, f"\u2705 Approved & published: {title}")
                print(f"Approved draft #{draft_id} ({title})")

            elif action == "reject":
                api_call("reject", draft_id=draft_id)
                answer_callback(callback_id, "Rejected. Generating a replacement...")
                edit_message(chat_id, message_id,
                              f"\u274C Rejected: {title}\n\nGenerating a new {content_type}...")
                print(f"Rejected draft #{draft_id} ({title}), regenerating...")

                run_id = uuid.uuid4().hex[:12]
                log_step(run_id, "CEO Agent", "regenerating",
                          f"Rejected draft #{draft_id}, making a new {content_type}")
                new_item = regenerate_one(run_id, content_type)
                notify_draft(content_type, new_item)
                print(f"Replacement ready: #{new_item['draft_id']} {new_item['title']} ({new_item['words']:,} words)")

        set_offset(offset)
    finally:
        browser_client.close_session()


if __name__ == "__main__":
    main()
