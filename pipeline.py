"""
pipeline.py
Shared logic to build ONE complete content item (blog or project): topic -> SEO ->
write -> generate images -> save as a draft. Used both for the daily full run
(main.py) and for regenerating a single replacement item after a rejection
(poll_telegram.py), so the logic only lives in one place.

Also handles: avoiding topic repeats, guaranteeing at least 3 images per item, and
returning the full content + image bytes so Telegram can show the complete item.
"""

import html as html_lib
import re
import time
from agents import (
    research_agent,
    research_single_agent,
    seo_agent,
    blog_writer_agent,
    project_writer_agent,
    code_review_agent,
)
from admin_client import log_step, save_draft, upload_image_data, get_recent_titles
from image_client import find_image

MIN_IMAGES = 3

# Used when we have to add extra images ourselves, so each one looks different
IMAGE_VARIATIONS = [
    "close-up of the main electronic components",
    "wiring and circuit connections on a breadboard",
    "complete working setup on a workbench",
    "simple labeled diagram illustration",
    "hands assembling the project",
]


def _ensure_min_placeholders(content_html, image_queries, topic, minimum=MIN_IMAGES):
    """
    Safety net: if Gemini didn't include enough {{IMAGE_n}} placeholders (it's an
    instruction, not a guarantee), add more by spacing them across the article's
    paragraphs, so every post reliably ends up with at least `minimum` images.
    Every added image gets a DIFFERENT prompt so they don't all look identical.
    """
    image_queries = list(image_queries or [])
    existing_nums = [int(n) for n in re.findall(r"\{\{IMAGE_(\d+)\}\}", content_html)]
    highest = max(existing_nums) if existing_nums else 0

    # Make sure every placeholder number has a matching search phrase
    variation_idx = 0
    while len(image_queries) < highest:
        image_queries.append(f"{topic}, {IMAGE_VARIATIONS[variation_idx % len(IMAGE_VARIATIONS)]}")
        variation_idx += 1

    need = minimum - len(existing_nums)
    if need <= 0:
        return content_html, image_queries

    paragraphs = content_html.split("</p>")
    if len(paragraphs) < need + 2:
        return content_html, image_queries  # not enough structure to insert safely

    next_num = highest + 1
    step = max(1, len(paragraphs) // (need + 1))
    inserted = 0
    rebuilt = []
    for i, para in enumerate(paragraphs):
        is_last = (i == len(paragraphs) - 1)
        rebuilt.append(para)
        if not is_last:
            rebuilt.append("</p>")
        if i > 0 and i % step == 0 and inserted < need and not is_last:
            rebuilt.append(f"\n\n{{{{IMAGE_{next_num}}}}}\n\n")
            image_queries.append(f"{topic}, {IMAGE_VARIATIONS[variation_idx % len(IMAGE_VARIATIONS)]}")
            variation_idx += 1
            next_num += 1
            inserted += 1

    return "".join(rebuilt), image_queries


def _replace_placeholder(content_html, marker, replacement):
    """Swaps a {{MARKER}} for real HTML. If the model wrapped the marker in its own <p>, drop that wrapper."""
    pattern = r"(?:<p>\s*)?" + re.escape(marker) + r"(?:\s*</p>)?"
    new_html, count = re.subn(pattern, lambda m: replacement, content_html)
    return new_html, count


def _render_code_blocks(content_html, code_blocks):
    """
    Turns the code_blocks (plain text) into nice dark code boxes at their {{CODE_n}} markers.
    The code is HTML-escaped, and every '=' is written as &#61; so the website's sanitizer
    (which strips things that look like on...= event handlers, e.g. 'onTime=5') can never damage it.
    """
    for i, block in enumerate(code_blocks or [], start=1):
        code = (block.get("code") or "").strip("\n")
        marker = "{{CODE_%d}}" % i
        if not code:
            content_html, _ = _replace_placeholder(content_html, marker, "")
            continue
        title = html_lib.escape(block.get("title") or "Example code")
        lang = re.sub(r"[^a-z0-9+#-]", "", (block.get("language") or "cpp").lower()) or "cpp"
        safe_code = html_lib.escape(code, quote=False).replace("=", "&#61;")
        box = (
            '<div class="code-example" style="margin:22px 0;">'
            f'<p style="margin:0 0 6px;"><strong>{title}</strong> '
            f'<span style="color:#64748b;font-size:12px;">({lang})</span></p>'
            '<pre style="background:#0f172a;color:#e2e8f0;padding:16px;border-radius:8px;overflow-x:auto;'
            'font-size:13.5px;line-height:1.55;white-space:pre;tab-size:2;margin:0;">'
            f'<code class="language-{lang}" style="font-family:Consolas,Menlo,Monaco,monospace;">{safe_code}</code></pre>'
            '</div>'
        )
        content_html, count = _replace_placeholder(content_html, marker, box)
        if count == 0:  # the model forgot the marker: add the code at the end rather than losing it
            content_html += box
    content_html = re.sub(r"(?:<p>\s*)?\{\{CODE_\d+\}\}(?:\s*</p>)?", "", content_html)
    return content_html


def _style_tables(content_html):
    """Gives every table a clean look that works in both light and dark themes (inline styles)."""
    content_html = re.sub(
        r"<table(?=[\s>])[^>]*>",
        '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:15px;">',
        content_html)
    content_html = content_html.replace("</table>", "</table></div>")
    content_html = re.sub(
        r"<th(?=[\s>])[^>]*>",
        '<th style="border:1px solid rgba(148,163,184,.55);padding:8px 10px;text-align:left;background:rgba(148,163,184,.18);">',
        content_html)
    content_html = re.sub(
        r"<td(?=[\s>])[^>]*>",
        '<td style="border:1px solid rgba(148,163,184,.55);padding:8px 10px;vertical-align:top;">',
        content_html)
    return content_html


def insert_inline_images(run_id, content_type, content_html, image_queries, topic=""):
    """
    Generates each image, uploads it to the website, and swaps the {{IMAGE_n}}
    placeholders for real <img> tags.
    Returns (final_html, thumbnail_url, list_of_image_urls, list_of_image_bytes).
    """
    thumbnail_url = ""
    image_urls = []
    image_bytes_list = []

    for i, query in enumerate(image_queries or [], start=1):
        placeholder = "{{IMAGE_%d}}" % i
        if placeholder not in content_html:
            continue

        log_step(run_id, "Image Agent", "started", f"Generating image {i}: {query}")
        final_url = ""
        last_error = None
        img_bytes = None
        credit = ""

        for attempt in range(1, 3):  # image search already retries internally; 2 tries covers upload hiccups
            try:
                if img_bytes is None:
                    img_bytes, credit = find_image(query, topic)
                uploaded = upload_image_data(content_type, img_bytes)
                final_url = uploaded.get("image_url", "")
                if final_url:
                    break
                last_error = uploaded.get("error", "no image_url in response")
            except Exception as e:
                last_error = e
            print(f"[warn] Image upload attempt {attempt} failed for '{query}': {last_error}")
            time.sleep(5)

        if final_url:
            if not thumbnail_url:
                thumbnail_url = final_url
            image_urls.append(final_url)
            image_bytes_list.append(img_bytes)
            caption = (
                f'<figcaption style="font-size:12px;color:#777;text-align:center;margin-top:4px;">{credit}</figcaption>'
                if credit else ""
            )
            img_tag = (
                f'<figure class="blog-inline-image">'
                f'<img src="{final_url}" alt="{html_lib.escape(query, quote=True)}" '
                f'style="max-width:100%;height:auto;border-radius:8px;" />{caption}</figure>'
            )
            content_html, _ = _replace_placeholder(content_html, placeholder, img_tag)
            log_step(run_id, "Image Agent", "done", f"Inserted image {i}: {query}")
        else:
            log_step(run_id, "Image Agent", "error", f"Could not create image for '{query}': {last_error}")
            print(f"[warn] Giving up on image for '{query}': {last_error}")
            content_html, _ = _replace_placeholder(content_html, placeholder, "")

    content_html = re.sub(r"\{\{IMAGE_\d+\}\}", "", content_html)
    return content_html, thumbnail_url, image_urls, image_bytes_list


def _finish_item(run_id, content_type, seo, data, extra_fields, topic):
    code_blocks = data.get("code_blocks") or []
    if code_blocks:
        code_blocks = code_review_agent(run_id, seo["title"], data["content_html"], code_blocks)

    padded_html, padded_queries = _ensure_min_placeholders(data["content_html"], data.get("image_queries", []), topic)
    html, thumb, image_urls, image_bytes = insert_inline_images(run_id, content_type, padded_html, padded_queries, topic)
    html = _render_code_blocks(html, code_blocks)
    html = _style_tables(html)
    result = save_draft(
        run_id, content_type,
        title=seo["title"], slug=seo["slug"], category=seo["category"],
        description=seo["description"], content=html,
        seo_title=seo["seo_title"], seo_desc=seo["seo_desc"], tags=seo["tags"],
        image_url=thumb,
        **extra_fields,
    )
    return {
        "draft_id": result.get("draft_id"),
        "title": seo["title"],
        "description": seo["description"],
        "content_html": html,
        "image_urls": image_urls,
        "image_bytes": image_bytes,
    }


def build_blog(run_id, topic, angle):
    seo = seo_agent(run_id, topic, angle, "blog")
    data = blog_writer_agent(run_id, topic, angle, seo)
    return _finish_item(run_id, "blog", seo, data, {}, topic)


def build_project(run_id, topic, angle):
    seo = seo_agent(run_id, topic, angle, "project")
    data = project_writer_agent(run_id, topic, angle, seo)
    extra = {"features": data["features"], "tech_used": data["tech_used"]}
    return _finish_item(run_id, "project", seo, data, extra, topic)


def build_both(run_id):
    """Used for the daily run: one fresh blog + one fresh project, avoiding past topics."""
    avoid_blog_titles, avoid_project_titles = get_recent_titles()
    research = research_agent(run_id, avoid_blog_titles, avoid_project_titles)
    blog = build_blog(run_id, research["blog_topic"], research["blog_angle"])
    project = build_project(run_id, research["project_topic"], research["project_angle"])
    return blog, project


def regenerate_one(run_id, content_type):
    """Used after a rejection: picks a brand-new topic (avoiding past ones) and builds just one item."""
    avoid_blog_titles, avoid_project_titles = get_recent_titles()
    avoid_titles = avoid_blog_titles if content_type == "blog" else avoid_project_titles

    topic_data = research_single_agent(run_id, content_type, avoid_titles)
    if content_type == "blog":
        return build_blog(run_id, topic_data["topic"], topic_data["angle"])
    return build_project(run_id, topic_data["topic"], topic_data["angle"])
