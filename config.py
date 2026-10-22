"""
config.py
Loads all settings (API keys, URLs) from environment variables / a .env file.
Never hardcode secrets directly in this file — always use environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # reads variables from a local .env file, if present

# Your free Gemini API key from https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Your free Pixabay API key from https://pixabay.com/api/docs/ — used to fetch REAL photos.
# If left blank, the system falls back to AI-generated images only.
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")

# Telegram bot token (from @BotFather) and your chat ID — used to send you a mobile
# notification when new content is ready to approve. Both optional; if left blank,
# notifications are simply skipped.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Your admin panel's agent gateway (Step 2)
ADMIN_API_URL = os.environ.get("ADMIN_API_URL", "https://admin.smartedgetech.in/agent-api.php")

# The SAME secret key you put in admin's .env as AGENT_API_KEY (Step 1)
ADMIN_AGENT_KEY = os.environ.get("ADMIN_AGENT_KEY", "")

# Describe your business in one line — agents use this to stay on-topic.
BUSINESS_CONTEXT = os.environ.get(
    "BUSINESS_CONTEXT",
    "IoT, robotics, embedded systems, and practical project solutions with source code, "
    "technical guidance, and expert support"
)
