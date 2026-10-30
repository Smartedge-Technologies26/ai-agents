"""
main.py
Runs the daily content pipeline: finds a blog + project topic, researches SEO keywords, writes both in depth,
saves them as drafts, and sends a Telegram notification for EACH one with
Approve/Reject buttons you can tap right from your phone.

Run it manually to test:
    python main.py

For the automatic daily run, see: .github/workflows/daily-content.yml
For handling your Approve/Reject taps, see: poll_telegram.py (runs on its own schedule,
  see .github/workflows/poll-telegram.yml)
"""

import uuid
import browser_client
from pipeline import build_both
from telegram_client import notify_draft
from admin_client import log_step


def run():
    browser_client.start_session()  # opens the real headless browser, passes the security check
    try:
        run_id = uuid.uuid4().hex[:12]
        print(f"Starting run: {run_id}")
        log_step(run_id, "CEO Agent", "started", "New content run started")

        blog, project = build_both(run_id)
        print(f"Blog draft #{blog['draft_id']}: {blog['title']} ({blog['words']:,} words)")
        print(f"Project draft #{project['draft_id']}: {project['title']} ({project['words']:,} words)")

        notify_draft("blog", blog)
        notify_draft("project", project)

        log_step(run_id, "CEO Agent", "waiting_approval",
                  "Both drafts saved. Waiting for approval via Telegram or the dashboard.")
        print("Done! Check Telegram, or: https://admin.smartedgetech.in/agent-status.php")
    finally:
        browser_client.close_session()


if __name__ == "__main__":
    run()
