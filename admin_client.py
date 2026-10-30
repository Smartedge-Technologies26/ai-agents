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
    """
    Saves a blog/project draft. Shows up as 'Pending Approval' on the dashboard.
    The (long) article is sent base64-encoded so the host's firewall can't mistake
    code samples or long HTML for an attack, and nothing gets mangled in transit.
    """
    content = fields.pop("content", "") or ""
    fields["content_b64"] = base64.b64encode(content.encode("utf-8")).decode("ascii")
    result = bc.call("save_draft", run_id=run_id, content_type=content_type, **fields)
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"save_draft failed: {result}")
    return result


def get_recent_titles():
    """Returns recently used blog/project titles, so new topics can avoid repeating them."""
    try:
        result = bc.call("recent_titles")
        return result.get("blog_titles", []), result.get("project_titles", [])
    except Exception as e:
        print(f"[warn] get_recent_titles failed: {e}")
        return [], []


def get_published_links():
    """Returns already-published blogs/projects (title + slug), used for internal links."""
    try:
        result = bc.call("published_links")
        return result.get("blogs", []), result.get("projects", [])
    except Exception as e:
        print(f"[warn] get_published_links failed: {e}")
        return [], []
