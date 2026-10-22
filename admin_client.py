"""
admin_client.py
Talks to agent-api.php through the verified browser session (see browser_client.py),
since InfinityFree blocks plain HTTP requests from scripts.
"""

import base64
import browser_client as bc


def log_step(run_id, agent_name, status, message=""):
    """Records one line of progress, visible live on the agent-status.php dashboard."""
    try:
        bc.call("log_step", run_id=run_id, agent_name=agent_name, status=status, message=message)
    except Exception as e:
        # Never let a logging failure crash the whole run
        print(f"[warn] log_step failed: {e}")


def save_draft(run_id, content_type, **fields):
    """Saves a blog/project draft. Shows up as 'Pending Approval' on the dashboard."""
    return bc.call("save_draft", run_id=run_id, content_type=content_type, **fields)


def upload_image(content_type, image_url):
    """Tells the server to download image_url and save it properly (used from Step 5 onward)."""
    return bc.call("upload_image", content_type=content_type, image_url=image_url)


def upload_image_data(content_type, image_bytes):
    """Uploads an image we already downloaded (as raw bytes) straight to the server."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return bc.call("upload_image_data", content_type=content_type, data_b64=b64)


def get_recent_titles():
    """Returns recently used blog/project titles, so new topics can avoid repeating them."""
    try:
        result = bc.call("recent_titles")
        return result.get("blog_titles", []), result.get("project_titles", [])
    except Exception as e:
        print(f"[warn] get_recent_titles failed: {e}")
        return [], []
