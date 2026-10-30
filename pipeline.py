"""
pipeline.py
Builds ONE complete, long, SEO-optimised item (blog or project) and saves it as a draft.

How a long article is made (a single AI call cannot write 4,000+ words, so it is done in stages):
  blog   : SEO plan -> outline -> intro -> every section (one call each) -> FAQ -> conclusion
  project: SEO plan -> project spec (parts, pin map, complete code) -> code review -> every section -> FAQ -> conclusion
Then Python assembles it: table of contents with jump links, styled tables, a code box, and
internal links to your other published posts. No images are used.

Used for the daily run (main.py) and to build a replacement after a rejection (poll_telegram.py).
"""

import html as html_lib
import json
import re
from agents import (
    research_agent,
    research_single_agent,
    seo_agent,
    outline_agent,
    write_section_agent,
    intro_agent,
    faq_agent,
    conclusion_agent,
    project_spec_agent,
    code_example_agent,
    code_review_agent,
    word_count,
)
from admin_client import log_step, save_draft, get_recent_titles, get_published_links
from config import SITE_URL, BRAND_NAME

# ---------------------------------------------------------------------------- project outline
# {kw} is replaced by the primary keyword, so every heading carries the search phrase naturally.
PROJECT_SECTIONS = [
    {"heading": "{kw}: Project Overview", "words": 300, "format": "prose", "with_code": False,
     "points": ["what the project does, in simple words", "the real problem it solves",
                "who it is for and what they will gain", "difficulty level and approximate build time",
                "what the finished project looks like and does"]},
    {"heading": "Real-World Uses of {kw}", "words": 300, "format": "prose", "with_code": False,
     "points": ["3-5 realistic places this idea is used in homes, schools, farms, shops or industry",
                "how the same idea scales up to bigger systems", "why learning it is valuable for beginners"]},
    {"heading": "Skills and Prerequisites Before You Start", "words": 230, "format": "list", "with_code": False,
     "points": ["basic electronics knowledge needed", "basic programming knowledge needed",
                "what a total beginner should read or practise first", "how long the learning curve is"]},
    {"heading": "Components Required for {kw}", "words": 450, "format": "components_table", "with_code": False,
     "points": ["introduce the parts list", "what each component is and why it was chosen",
                "specifications that matter", "acceptable substitutes and what to look for when buying"]},
    {"heading": "Tools and Software You Need", "words": 220, "format": "list", "with_code": False,
     "points": ["hardware tools", "Arduino IDE setup and board selection", "libraries and how to install them",
                "optional tools that make the build easier"]},
    {"heading": "How {kw} Works: The Working Principle", "words": 420, "format": "prose", "with_code": False,
     "points": ["the core principle in plain language with an analogy", "the flow from input to processing to output",
                "how each component contributes", "the key formula or logic if there is one"]},
    {"heading": "{kw} Circuit Diagram and Wiring Connections", "words": 380, "format": "pin_table", "with_code": False,
     "points": ["the connection table introduction", "power and ground wiring", "signal wiring for each module",
                "common wiring mistakes and a final checklist before powering on"]},
    {"heading": "Step-by-Step Build Instructions", "words": 650, "format": "steps", "with_code": False,
     "points": ["10 to 14 detailed numbered steps from preparing the parts to the first power-up",
                "what to check after each stage", "how to upload the code"]},
    {"heading": "{kw}: Complete Source Code", "words": 230, "format": "code", "with_code": True,
     "points": ["introduce the code", "the code listing is inserted automatically",
                "libraries to install and how to upload", "how to adjust the main settings"]},
    {"heading": "Code Explanation: How the Program Works", "words": 600, "format": "prose", "with_code": True,
     "points": ["libraries and pin definitions", "setup() line by line", "loop() step by step",
                "each helper function and what it returns", "how to change the behaviour safely"]},
    {"heading": "Testing, Calibration and Expected Output", "words": 380, "format": "prose", "with_code": True,
     "points": ["how to test each part separately", "exactly what the user should see (LEDs, Serial Monitor, display)",
                "how to calibrate and verify accuracy", "what normal readings look like"]},
    {"heading": "Troubleshooting Common {kw} Problems", "words": 420, "format": "table", "with_code": False,
     "points": ["a table with columns Problem, Likely Cause, Fix and at least 8 realistic rows",
                "a systematic way to debug", "how to use the Serial Monitor to find faults"]},
    {"heading": "Upgrade and Customization Ideas", "words": 300, "format": "list", "with_code": False,
     "points": ["5-7 concrete upgrades (more sensors, display, buzzer, wireless, data logging)",
                "what each upgrade needs and how hard it is", "how to turn it into a finished product"]},
    {"heading": "Safety Tips and Best Practices", "words": 230, "format": "list", "with_code": False,
     "points": ["electrical safety and correct voltages", "protecting the components",
                "good wiring and code habits", "power supply advice"]},
]


# ---------------------------------------------------------------------------- html helpers
def _esc(text):
    return html_lib.escape(str(text or ""), quote=False)


def _slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:70].strip("-")


def _add_heading_ids(content_html):
    """Gives every <h2> an id so the table of contents can jump to it."""
    used = set()

    def repl(m):
        attrs, inner = m.group(1), m.group(2)
        if "id=" in attrs:
            return m.group(0)
        base = _slugify(html_lib.unescape(re.sub(r"<[^>]+>", "", inner))) or "section"
        slug, n = base, 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        return f'<h2 id="{slug}"{attrs}>{inner}</h2>'

    return re.sub(r"<h2([^>]*)>(.*?)</h2>", repl, content_html, flags=re.S)


def _build_toc(content_html):
    items = re.findall(r'<h2 id="([^"]+)"[^>]*>(.*?)</h2>', content_html, flags=re.S)
    if len(items) < 4:
        return ""
    lis = "".join(f'<li><a href="#{i}">{re.sub(r"<[^>]+>", "", t).strip()}</a></li>' for i, t in items)
    return (
        '<div class="toc" style="border:1px solid rgba(148,163,184,.55);border-radius:8px;'
        'padding:14px 18px;margin:22px 0;">'
        '<p style="margin:0 0 8px;"><strong>In this guide</strong></p>'
        f'<ol style="margin:0;padding-left:22px;">{lis}</ol></div>'
    )


def _style_html(content_html):
    """Inline styles that look right in both light and dark themes (the site keeps inline styles)."""
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
    content_html = re.sub(
        r"<blockquote(?=[\s>])[^>]*>",
        '<blockquote style="border-left:4px solid rgba(59,130,246,.75);padding:8px 16px;margin:18px 0;'
        'background:rgba(148,163,184,.12);border-radius:0 6px 6px 0;">',
        content_html)
    return content_html


def _code_box(block):
    """
    A dark code box. The code is HTML-escaped and every '=' is written as &#61; so the website's
    sanitizer (which strips things that look like on...= event handlers, e.g. 'onTime=5') can never damage it.
    """
    code = (block.get("code") or "").strip("\n")
    title = html_lib.escape(block.get("title") or "Example code")
    lang = re.sub(r"[^a-z0-9+#-]", "", (block.get("language") or "cpp").lower()) or "cpp"
    safe_code = html_lib.escape(code, quote=False).replace("=", "&#61;")
    return (
        '<div class="code-example" style="margin:22px 0;">'
        f'<p style="margin:0 0 6px;"><strong>{title}</strong> '
        f'<span style="color:#64748b;font-size:12px;">({lang})</span></p>'
        '<pre style="background:#0f172a;color:#e2e8f0;padding:16px;border-radius:8px;overflow-x:auto;'
        'font-size:13.5px;line-height:1.55;white-space:pre;tab-size:2;margin:0;">'
        f'<code class="language-{lang}" style="font-family:Consolas,Menlo,Monaco,monospace;">{safe_code}</code></pre>'
        '</div>'
    )


def _table(headers, rows):
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _components_table(spec):
    rows = [[c.get("name", ""), c.get("qty", "1"), c.get("purpose", ""), c.get("key_specs", "")]
            for c in spec.get("components", [])]
    return _table(["Component", "Quantity", "Purpose in this project", "Key specifications"], rows)


def _pin_table(spec):
    rows = [[p.get("component_pin", ""), p.get("board_pin", ""), p.get("notes", "")] for p in spec.get("pin_map", [])]
    return _table(["Component pin", "Board pin", "Notes"], rows)


def _insert_after_first_paragraph(section_html, block_html):
    m = re.search(r"</p>", section_html)
    if not m:
        return section_html + "\n" + block_html
    return section_html[:m.end()] + "\n" + block_html + "\n" + section_html[m.end():]


def _collect_links():
    """Already-published blogs and projects, as {title, url}, for internal linking."""
    blogs, projects = get_published_links()
    base = SITE_URL.rstrip("/")
    links = [{"title": b["title"], "url": f"{base}/blog/{b['slug']}"} for b in blogs if b.get("slug")]
    links += [{"title": p["title"], "url": f"{base}/projects/{p['slug']}"} for p in projects if p.get("slug")]
    return links


def _related_block(plan, links):
    """A 'related guides' list linking to the most relevant published posts (internal links help SEO)."""
    def tokens(text):
        return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 3}

    mine = tokens(" ".join([plan["primary_keyword"], plan["title"], " ".join(plan["secondary_keywords"])]))
    scored = []
    for link in links:
        score = len(mine & tokens(link["title"]))
        if score >= 1:
            scored.append((score, link))
    scored.sort(key=lambda x: -x[0])
    top = [l for _, l in scored[:4]]
    if not top:
        return ""
    items = "".join(f'<li><a href="{html_lib.escape(l["url"], quote=True)}">{_esc(l["title"])}</a></li>' for l in top)
    return f"<h2>Related Guides on {_esc(BRAND_NAME)}</h2><p>Keep learning with these related guides:</p><ul>{items}</ul>"


def _assemble(plan, intro, body_parts, faq, conclusion, links):
    full = "\n".join([intro, "{{TOC}}", "\n".join(body_parts), faq, conclusion, _related_block(plan, links)])
    full = _add_heading_ids(full)
    full = full.replace("{{TOC}}", _build_toc(full))
    full = re.sub(r"<p>\s*</p>", "", full)
    return _style_html(full)


def _meta_summary(plan, words):
    return (f"Primary keyword: {plan['primary_keyword']}\n"
            f"SEO title: {plan['seo_title']}\n"
            f"Meta description: {plan['seo_desc']}\n"
            f"URL slug: {plan['slug']}\n"
            f"Length: {words:,} words")


def _cut_csv(items, limit):
    out = []
    for item in items:
        item = (item or "").strip()
        if item and len(", ".join(out + [item])) <= limit:
            out.append(item)
    return ", ".join(out)


def _finish(run_id, agent_name, content_type, plan, html, extra_fields):
    words = word_count(html)
    result = save_draft(
        run_id, content_type,
        title=plan["title"], slug=plan["slug"], category=plan["category"],
        description=plan["description"], content=html,
        seo_title=plan["seo_title"], seo_desc=plan["seo_desc"], tags=plan["tags"],
        image_url="", **extra_fields,
    )
    log_step(run_id, agent_name, "done", f"Finished '{plan['title']}': {words:,} words")
    return {
        "draft_id": result.get("draft_id"),
        "title": plan["title"],
        "description": plan["description"],
        "content_html": html,
        "words": words,
        "meta": _meta_summary(plan, words),
    }


def _write_sections(run_id, agent_name, plan, sections, extra_for, decorate):
    """
    Writes every section (one AI call each). `decorate(section, html)` lets the caller insert
    tables / code boxes. A section that fails is skipped instead of failing the whole article.
    """
    headings = [s["heading"] for s in sections]
    parts, done = [], []
    for i, sec in enumerate(sections, start=1):
        log_step(run_id, agent_name, "working", f"Writing section {i}/{len(sections)}: {sec['heading']}")
        try:
            html = write_section_agent(run_id, plan, sec, headings, done, extra_for(sec))
            html = decorate(sec, html)
        except Exception as e:
            log_step(run_id, agent_name, "error", f"Section '{sec['heading']}' failed and was skipped: {e}")
            print(f"[warn] Section failed: {sec['heading']}: {e}")
            continue
        parts.append(html)
        done.append(sec["heading"])
    if len(parts) < max(4, len(sections) // 2):
        raise RuntimeError(f"Too many sections failed ({len(parts)}/{len(sections)} written)")
    return parts


def _closing_parts(run_id, plan, headings, faq_extra):
    try:
        faq = faq_agent(run_id, plan, faq_extra)
    except Exception as e:
        log_step(run_id, "FAQ Agent", "error", f"FAQ failed and was skipped: {e}")
        faq = ""
    conclusion = conclusion_agent(run_id, plan, headings)
    return faq, conclusion


# ---------------------------------------------------------------------------- builders
def build_blog(run_id, topic, angle):
    plan = seo_agent(run_id, topic, angle, "blog")
    outline = outline_agent(run_id, plan, topic, angle)
    sections = outline["sections"]
    headings = [s["heading"] for s in sections]

    code_block = None
    if outline["needs_code"]:
        code_section = next(s for s in sections if s["format"] == "code")
        try:
            code_block = code_example_agent(run_id, plan, topic, code_section)
            context = json.dumps({"topic": topic, "section": code_section["heading"], "points": code_section["points"]})
            code_block = code_review_agent(run_id, plan["title"], context, [code_block])[0]
        except Exception as e:
            log_step(run_id, "Blog Agent", "error", f"Code example skipped: {e}")
            code_section["format"] = "prose"
            code_block = None

    def extra_for(sec):
        if sec["format"] == "code" and code_block:
            return ("Example code (it is inserted automatically after your first paragraph; "
                    "explain it part by part):\n" + code_block["code"])
        return ""

    def decorate(sec, html):
        if sec["format"] == "code" and code_block:
            return _insert_after_first_paragraph(html, _code_box(code_block))
        return html

    intro = intro_agent(run_id, plan, headings)
    parts = _write_sections(run_id, "Blog Agent", plan, sections, extra_for, decorate)
    faq, conclusion = _closing_parts(run_id, plan, headings, "Topic: " + topic)
    html = _assemble(plan, intro, parts, faq, conclusion, _collect_links())
    return _finish(run_id, "Blog Agent", "blog", plan, html, {})


def _spec_for_prompt(spec):
    """The project spec without the code, as compact JSON the section writers must stay consistent with."""
    slim = {k: v for k, v in spec.items() if k not in ("code", "code_title")}
    return json.dumps(slim, ensure_ascii=False, indent=1)


def build_project(run_id, topic, angle):
    plan = seo_agent(run_id, topic, angle, "project")
    spec = project_spec_agent(run_id, plan, topic, angle)

    block = {"title": spec["code_title"], "language": "cpp", "code": spec["code"]}
    block = code_review_agent(run_id, plan["title"], _spec_for_prompt(spec), [block])[0]
    spec["code"] = block["code"]

    kw = plan["primary_keyword"][:1].upper() + plan["primary_keyword"][1:]
    sections = [dict(s, heading=s["heading"].replace("{kw}", kw)) for s in PROJECT_SECTIONS]
    headings = [s["heading"] for s in sections]
    spec_text = "PROJECT SPEC (authoritative):\n" + _spec_for_prompt(spec)

    def extra_for(sec):
        if sec.get("with_code"):
            return spec_text + "\n\nTHE COMPLETE CODE:\n" + spec["code"]
        return spec_text

    # The tables are built from the spec by Python (not by the AI), so they always match the code exactly.
    def decorate(sec, html):
        if sec["format"] == "components_table":
            return _insert_after_first_paragraph(html, _components_table(spec))
        if sec["format"] == "pin_table":
            return _insert_after_first_paragraph(html, _pin_table(spec))
        if sec["format"] == "code":
            return _insert_after_first_paragraph(html, _code_box(block))
        return html

    intro = intro_agent(run_id, plan, headings)
    parts = _write_sections(run_id, "Project Agent", plan, sections, extra_for, decorate)
    faq, conclusion = _closing_parts(run_id, plan, headings, spec_text)
    html = _assemble(plan, intro, parts, faq, conclusion, _collect_links())

    tech = [spec["board"]] + [c.get("name", "")[:30] for c in spec["components"][:5]]
    extra = {"features": ", ".join(spec["features"])[:900], "tech_used": _cut_csv(tech, 250)}
    return _finish(run_id, "Project Agent", "project", plan, html, extra)


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
