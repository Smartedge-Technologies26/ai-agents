"""
browser_client.py
InfinityFree blocks ALL plain automated requests (curl, python-requests, etc.) by
design — this is documented InfinityFree policy, not a bug. Their own suggested
workaround is: "use a web browser". So instead of requests.post(), we drive a real
(invisible/headless) Chromium browser via Playwright. It executes the site's
JavaScript challenge exactly like a human visitor's browser would, then we reuse
that same verified browser tab to call agent-api.php for the rest of the run.
"""

from playwright.sync_api import sync_playwright
from config import ADMIN_API_URL, ADMIN_AGENT_KEY

_playwright = None
_browser = None
_page = None


def start_session():
    """Opens a real headless browser and lets it pass the site's security check."""
    global _playwright, _browser, _page
    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(headless=True)
    _page = _browser.new_page()

    print("[browser] Opening admin site to pass the security check...")
    _page.goto(ADMIN_API_URL, wait_until="networkidle", timeout=60000)
    print("[browser] Security check passed. Session is ready.")


def close_session():
    """Closes the browser at the end of the run. Always call this when done."""
    global _playwright, _browser
    if _browser:
        _browser.close()
    if _playwright:
        _playwright.stop()


def call(action, **kwargs):
    """
    Calls agent-api.php from INSIDE the already-verified browser tab, using the
    browser's own fetch() — so it automatically carries the security cookie the
    browser already solved.
    """
    if _page is None:
        raise RuntimeError("Browser session not started. Call start_session() first.")

    payload = {"action": action, **kwargs}
    result = _page.evaluate(
        """async ({ url, key, payload }) => {
            const resp = await fetch(url, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Agent-Key": key
                },
                body: JSON.stringify(payload)
            });
            const text = await resp.text();
            try { return JSON.parse(text); }
            catch (e) { return { error: "Non-JSON response from server", raw: text.slice(0, 300) }; }
        }""",
        {"url": ADMIN_API_URL, "key": ADMIN_AGENT_KEY, "payload": payload},
    )
    if isinstance(result, dict) and result.get("error") == "Non-JSON response from server":
        raise RuntimeError(f"agent-api.php returned a non-JSON response: {result.get('raw')}")
    return result
