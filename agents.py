"""
agents.py
The "thinking" agents. Every long article is built in stages so it can be genuinely long and detailed:

  research_agent / research_single_agent -> pick a topic people really search for
  seo_agent               -> keyword research + SEO fields (title, slug, meta, tags, FAQ questions)
  outline_agent           -> plans the sections of a blog article
  project_spec_agent      -> designs the real project: parts list, pin map and complete code
  code_example_agent      -> a short code example for a blog article
  code_review_agent       -> second pair of eyes that checks and fixes the code
  write_section_agent     -> writes ONE section (long and detailed), expands it if it is too short
  intro_agent / faq_agent / conclusion_agent -> the remaining parts of the article
"""

import html as html_lib
import json
import re
from gemini_client import ask_gemini, ask_gemini_json
from admin_client import log_step
from config import BUSINESS_CONTEXT, BRAND_NAME

# Topics/content must stay strictly within this niche
SCOPE_RULES = """
STRICT TOPIC SCOPE: Only cover topics directly related to IoT, robotics, embedded systems,
and practical hands-on project solutions (source code, technical guidance, step-by-step builds).
Do NOT cover anything outside this niche (no general web development, no general business/
marketing topics, no unrelated software topics).

DIFFICULTY: BEGINNER to INTERMEDIATE only. Do NOT center any topic or explanation around these
advanced technologies/platforms, and avoid naming or relying on them: Raspberry Pi (RPi),
NVIDIA Jetson, MongoDB, React.js, Python, Node.js, TensorFlow, OpenCV. Instead, focus on simple,
foundational, approachable IoT/robotics/embedded-systems ideas — basic sensors, basic
microcontrollers explained at an introductory level, simple automation/robotics concepts, and
practical mini-projects that someone NEW to electronics/embedded systems could follow without
already knowing advanced frameworks or high-end hardware.
"""


DEMAND_RULES = """
SEARCH DEMAND: pick a topic that many beginners and students really type into Google (how-to, "what is",
project ideas with code, "X not working", "X vs Y", circuit / wiring / working-principle searches) and that one
complete, well-written guide can realistically rank #1 for. Prefer a specific long-tail topic over a vague broad one.
"""


def research_agent(run_id, avoid_blog_titles=None, avoid_project_titles=None):
    log_step(run_id, "Research Agent", "started", "Looking for a fresh blog topic and project idea...")

    avoid_text = ""
    if avoid_blog_titles:
        avoid_text += "\nTopics ALREADY COVERED for blogs — do NOT repeat or closely resemble these:\n"
        avoid_text += "\n".join(f"- {t}" for t in avoid_blog_titles)
    if avoid_project_titles:
        avoid_text += "\nTopics ALREADY COVERED for projects — do NOT repeat or closely resemble these:\n"
        avoid_text += "\n".join(f"- {t}" for t in avoid_project_titles)

    prompt = f"""
You are a content strategist for this business: {BUSINESS_CONTEXT}

{SCOPE_RULES}
{DEMAND_RULES}
Suggest ONE blog topic and ONE project idea that fit the scope and difficulty rules above,
and would attract potential clients/students searching on Google. Be specific and genuinely
useful — avoid generic, overused topics.
{avoid_text}

Reply with ONLY valid JSON, no extra text, in this exact shape:
{{
  "blog_topic": "short topic string",
  "blog_angle": "one sentence describing the unique angle/hook for this blog",
  "project_topic": "short project name/topic string",
  "project_angle": "one sentence describing what problem this project solves"
}}
"""
    data = ask_gemini_json(prompt)
    log_step(run_id, "Research Agent", "done",
              f"Blog topic: {data.get('blog_topic')} | Project topic: {data.get('project_topic')}")
    return data


def research_single_agent(run_id, content_type, avoid_titles=None):
    """Like research_agent, but finds a fresh topic for just ONE content type.
    Used when regenerating a replacement after a rejection."""
    log_step(run_id, "Research Agent", "started", f"Looking for a fresh {content_type} topic...")

    kind = "blog topic" if content_type == "blog" else "project idea"
    avoid_text = ""
    if avoid_titles:
        avoid_text = "\nTopics ALREADY COVERED — do NOT repeat or closely resemble these:\n"
        avoid_text += "\n".join(f"- {t}" for t in avoid_titles)

    prompt = f"""
You are a content strategist for this business: {BUSINESS_CONTEXT}

{SCOPE_RULES}
{DEMAND_RULES}
Suggest ONE {kind} that fits the scope and difficulty rules above. Be specific and genuinely
useful — avoid generic, overused topics, and avoid the most obvious textbook examples.
{avoid_text}

Reply with ONLY valid JSON, no extra text, in this exact shape:
{{
  "topic": "short topic string",
  "angle": "one sentence describing the unique angle/hook"
}}
"""
    data = ask_gemini_json(prompt)
    log_step(run_id, "Research Agent", "done", f"New {content_type} topic: {data.get('topic')}")
    return data



# ============================================================================ prompts
STYLE_RULES = """
WRITING STYLE (this decides whether readers stay and whether Google ranks the page):
- Write for a curious beginner. Warm, direct, conversational "you" voice. Short paragraphs (2-4 sentences). Vary sentence length.
- Open with something concrete: a relatable situation, a direct answer, or a fact you are certain is true.
- Be specific: real part names, realistic values (voltages, ranges, resistor values, baud rates), clear numbers and simple
  analogies. Explain each technical term in plain words the first time it appears.
- Every paragraph must add real value. No filler, no repetition, no padding, no vague generalities.
- BANNED phrases: "in today's fast-paced world", "delve", "unleash", "game-changer", "revolutionize", "in conclusion",
  "it is important to note", "look no further", "dive into", "tapestry", "navigate the world of", "ever-evolving".
- Use the primary keyword and its natural variations where they fit. Never stuff keywords.
- A few times across the article (not in every section) use a callout:
  <blockquote><strong>Pro Tip:</strong> ...</blockquote> or <blockquote><strong>Common Mistake:</strong> ...</blockquote>
- ACCURACY FIRST: only state facts you are sure of. Never invent statistics, studies, case studies, prices, quotes or
  personal experiences. If a value varies between modules, say "typically".
- Allowed HTML tags ONLY: h2, h3, p, ul, ol, li, strong, em, table, thead, tbody, tr, th, td, blockquote.
  No inline styles, no images, no pre/code tags, no markdown, no links.
"""

SEO_PROMPT = """
You are a senior SEO strategist and content planner for this business: <<BUSINESS>>

Topic: <<TOPIC>>
Angle: <<ANGLE>>
Content type: <<CTYPE>>

Goal: plan ONE page that can rank #1 on Google for this topic and for every closely related search. Think about how
real beginners and students actually search (Google autocomplete and "People also ask" phrasing) and what a searcher
wants to see on the page.

Reply with ONLY valid JSON in exactly this shape:
{
  "primary_keyword": "the single best keyword phrase people really search (2-5 words)",
  "secondary_keywords": ["8 to 12 related phrases people search, for example with: for beginners, project, code, circuit diagram, working principle, how to, vs, not working (only where relevant)"],
  "questions": ["8 to 10 real questions people type into Google about this topic"],
  "search_intent": "one sentence: what the searcher wants",
  "title": "the page H1: max 62 characters, primary keyword at the very start, specific and compelling (for projects use words like Project, Step-by-Step or With Code)",
  "slug": "3 to 6 lowercase hyphenated words that contain the primary keyword",
  "category": "one short category name",
  "seo_title": "the <title> tag: max 58 characters, primary keyword first, benefit-driven",
  "seo_desc": "meta description: 140-155 characters, contains the primary keyword, one concrete benefit and a call to action",
  "tags": "8 to 10 comma separated keyword tags",
  "description": "2-3 sentence summary for listing cards that includes the primary keyword",
  "snippet_answer": "a direct 40-60 word answer to the main query, written to win Google's featured snippet"
}
"""

BLOG_OUTLINE_PROMPT = """
You are an expert content strategist for this business: <<BUSINESS>>

<<SCOPE>>

Plan a VERY detailed, genuinely useful article that fully satisfies every search intent around the topic, so a reader
never needs another page.

Title: <<TITLE>>
Primary keyword: <<PRIMARY>>
Secondary keywords: <<SECONDARY>>
Angle: <<ANGLE>>
Questions people ask (they are answered later in a separate FAQ - do NOT turn them into sections): <<QUESTIONS>>

Plan the BODY sections only (the intro, FAQ and conclusion are written separately).
Rules:
- 8 to 10 sections. Section 1 must be a definition section such as "What Is <primary keyword>?" that answers directly.
- Cover, in a logical order: what it is, why it matters, how it works (the mechanism), the key parts / types / options,
  how to actually do or use it step by step, a comparison or quick-reference (format "table"), real-life examples and
  applications, common mistakes and troubleshooting, best practices / pro tips, and what to learn next.
- Headings: descriptive and keyword-rich, some phrased as questions. No two sections may overlap.
- Each section: 4-6 specific points to cover and a target length of 300-450 words.
- "format" is one of: prose, list, steps, table, code.
- Set "needs_code" to true ONLY if one short Arduino-style (C/C++) example would genuinely help this topic. If true,
  exactly one section must have format "code".

Reply with ONLY valid JSON:
{"needs_code": false, "sections": [{"heading": "...", "points": ["...", "..."], "words": 380, "format": "prose"}]}
"""

SECTION_PROMPT = """
You are writing ONE section of a long, in-depth, SEO-optimised article for this business: <<BUSINESS>>

<<SCOPE>>

<<STYLE>>

ARTICLE
Title: <<TITLE>>
Primary keyword: <<PRIMARY>>
Secondary keywords (use naturally where they fit): <<SECONDARY>>
All section headings of the article (so you do not overlap with other sections):
<<ALL_HEADINGS>>
Sections already written (do not repeat their content):
<<DONE>>

THIS SECTION
Heading (use exactly as the opening <h2>): <<HEADING>>
Points to cover thoroughly:
<<POINTS>>
Format: <<FORMAT>>
Length: write AT LEAST <<WORDS>> words. Depth and usefulness matter more than anything: explain the why and the how,
give concrete examples with realistic numbers, and add a simple analogy where it helps.

EXTRA CONTEXT (authoritative - stay fully consistent with it)
<<EXTRA>>

Output ONLY the HTML for this section, starting with the <h2>. No code fences, no commentary.
"""

EXPAND_PROMPT = """
The draft section below is too short or too shallow. Rewrite the WHOLE section so it is at least <<WORDS>> words, with the
same opening <h2> and the same HTML rules. Add real depth: explain the why and the how, concrete examples with realistic
numbers, a simple analogy, common pitfalls and practical tips. No filler, no repetition, no invented facts.

<<STYLE>>

EXTRA CONTEXT (stay consistent with it)
<<EXTRA>>

DRAFT:
<<DRAFT>>

Output ONLY the improved HTML.
"""

INTRO_PROMPT = """
Write the INTRODUCTION of an in-depth, SEO-optimised article for this business: <<BUSINESS>>

<<STYLE>>

Title: <<TITLE>>
Primary keyword: <<PRIMARY>>
Secondary keywords: <<SECONDARY>>
The article's sections:
<<ALL_HEADINGS>>
Direct answer to the main query (work it in naturally, do not paste it word for word): <<SNIPPET>>

Requirements:
- 200-260 words. Output only <p> paragraphs plus one short <ul> (4-5 bullets: what the reader will learn or be able to do).
  No heading.
- The first sentence is a relatable hook or a direct statement. The primary keyword must appear within the first 100 words.
- Say who the guide is for and promise something specific the reader will be able to do by the end.

Output ONLY the HTML.
"""

FAQ_PROMPT = """
Write the FAQ section of an in-depth article for this business: <<BUSINESS>>

<<SCOPE>>

<<STYLE>>

Title: <<TITLE>>
Primary keyword: <<PRIMARY>>
Questions (use these questions in this order; reword only where needed to be grammatical):
<<QUESTIONS>>

Format: start with <h2>Frequently Asked Questions About <<PRIMARY>></h2>. Then, for each question, an <h3> with the
question followed by a <p> answer of 55-90 words. Every answer must begin with the direct answer in its first sentence
(so Google can use it as a snippet) and then add one genuinely useful detail. Accuracy only.

Context the answers must stay consistent with:
<<EXTRA>>

Output ONLY the HTML.
"""

CONCLUSION_PROMPT = """
Write the CONCLUSION of an in-depth article for this business: <<BUSINESS>>

<<STYLE>>

Title: <<TITLE>>
Primary keyword: <<PRIMARY>>
Sections covered:
<<ALL_HEADINGS>>

Format: <h2>Final Thoughts on <<PRIMARY>></h2>, then 180-240 words: a short summary of what the reader learned, a <ul> of
4-6 key takeaways, one motivating line about their next step, and finally a call to action inviting them to contact
<<BRAND>> for ready-made source code, technical guidance and expert support for their own IoT, robotics or
embedded-systems project. Output ONLY the HTML.
"""

PROJECT_SPEC_PROMPT = """
You are a senior embedded-systems engineer and technical writer for this business: <<BUSINESS>>

<<SCOPE>>

Design ONE complete, REAL, buildable project that a beginner-to-intermediate maker can build and that people search for.

Title: <<TITLE>>
Topic: <<TOPIC>>
Angle: <<ANGLE>>
Primary keyword: <<PRIMARY>>

Rules:
- Use realistic, commonly available parts (for example Arduino Uno or Nano, named sensors/modules, breadboard, jumper wires,
  resistors with real values, USB cable / battery pack). Use ESP8266/ESP32 only if the project truly needs Wi-Fi.
- "pin_map" must list EVERY connection, including power and ground for every part, with exact pins.
- The code must be ONE complete, compile-ready Arduino sketch (C/C++): includes, pin definitions, setup(), loop(), helper
  functions, Serial debug prints, 70-160 lines, clear comments, meaningful names, no placeholders like "..." or
  "your code here". Use only the Arduino core and very common libraries (Wire.h, Servo.h, LiquidCrystal.h,
  LiquidCrystal_I2C.h, DHT.h, SoftwareSerial.h, ...). Pin numbers in the code must match "pin_map" exactly.

Reply with ONLY valid JSON in exactly this shape:
{
  "board": "Arduino Uno",
  "summary": "what the project does, 2-3 sentences",
  "difficulty": "Beginner or Intermediate",
  "build_time": "for example 2-3 hours",
  "components": [{"name": "...", "qty": "1", "purpose": "what it does in this project", "key_specs": "for example 5V, range 2-400 cm"}],
  "tools": ["tools and software needed, for example USB cable, Arduino IDE, screwdriver"],
  "pin_map": [{"component_pin": "HC-SR04 VCC", "board_pin": "5V", "notes": "power"}],
  "libraries": ["library name and how to get it, or 'built into the Arduino IDE'"],
  "behaviour": "step by step description of what the running project does",
  "features": ["5 to 8 short feature phrases"],
  "code_title": "Complete sketch: <project name>",
  "code": "the complete Arduino sketch as plain text"
}
"""

CODE_EXAMPLE_PROMPT = """
Write ONE short, correct, beginner-friendly Arduino-style (C/C++) example for an article.

Article topic: <<TOPIC>>
Primary keyword: <<PRIMARY>>
It accompanies this section: <<HEADING>>
Points the section covers:
<<POINTS>>

Rules: 15-45 lines, clear helpful comments, only the Arduino core or very common libraries, must compile as written,
nothing hypothetical.

Reply with ONLY valid JSON: {"title": "short descriptive title", "language": "cpp", "code": "plain code text"}
"""

CODE_REVIEW_PROMPT = """
You are a meticulous embedded-systems code reviewer (Arduino C/C++). Below is the project/article context and the code
blocks that go with it.

Check EVERY code block for:
- syntax errors (missing semicolons/braces/parentheses), undeclared or misspelled variables, wrong function names
- missing #include lines, wrong library or class names, calls that do not exist in that library
- wrong pin usage (analogRead on a digital-only pin, PWM on a non-PWM pin, I2C on the wrong pins - Uno uses A4/A5)
- missing pinMode() / Serial.begin(), wrong baud rates, missing delays or timing the module needs
- logic bugs, and behaviour that does not match what the context says the project does
- any disagreement with the pin map in the context

Fix everything you find. If the code and the pin map disagree, change the CODE to match the pin map (never change the
context). Keep the code beginner-friendly with helpful comments. Do not shorten it or remove features.

Reply with ONLY valid JSON in exactly this shape (same number of blocks, same order as given):
{"issues_fixed": ["short description of each fix"], "code_blocks": [{"title": "...", "language": "cpp", "code": "..."}]}

CONTEXT:
<<ARTICLE>>

CODE BLOCKS (JSON):
<<CODE>>
"""

FORMAT_GUIDE = {
    "prose": "flowing paragraphs with 2-3 <h3> sub-headings",
    "list": "a short intro paragraph, then a <ul> or <ol> whose items are each 1-3 full sentences, plus closing paragraphs",
    "steps": "an <ol> of detailed numbered steps (each 2-4 sentences: what to do, how to do it, what you should see), with short paragraphs around it",
    "table": "paragraphs plus ONE clear <table> (with <thead> and <tbody>) that fits the points, followed by explanation of how to read it",
    "code": "this section accompanies a code listing that is inserted automatically right after your FIRST paragraph; do not write any code yourself; refer to it as 'the code below', and after the first paragraph explain it part by part",
    "components_table": "your FIRST paragraph introduces the parts; the components table is inserted automatically right after it (do NOT write a table); afterwards write one <h3> per component: what it is, how it works in simple terms, why it was chosen and what can replace it",
    "pin_table": "your FIRST paragraph introduces the wiring; the connection table is inserted automatically right after it (do NOT write a table); afterwards explain the wiring in groups (power, each sensor/module, outputs), colour-coding tips, a double-check list and safety warnings",
}


# ============================================================================ helpers
def _fill(template, **values):
    out = template
    for key, val in values.items():
        out = out.replace("<<" + key.upper() + ">>", str(val))
    return out


def _cut(text, limit):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-\u2013\u2014") or text[:limit]


def word_count(html):
    return len(re.sub(r"<[^>]+>", " ", html or "").split())


def _strip_fences(text):
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _clean_section_html(html, heading):
    html = _strip_fences(html)
    html = re.sub(r"<(/?)h1\b", r"<\1h2", html)
    if not re.match(r"\s*<h2", html):
        html = f"<h2>{html_lib.escape(heading)}</h2>\n" + html
    return html


def _as_list(value):
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    return [str(v).strip() for v in (value or []) if str(v).strip()]


def _clean_plan(plan, topic):
    title = _cut(plan.get("title") or topic, 70)
    primary = (plan.get("primary_keyword") or topic).strip()
    slug = re.sub(r"[^a-z0-9]+", "-", (plan.get("slug") or title).lower()).strip("-")[:90].strip("-") or "post"
    return {
        "title": title,
        "slug": slug,
        "category": _cut(plan.get("category") or "IoT & Robotics", 60),
        "seo_title": _cut(plan.get("seo_title") or title, 60),
        "seo_desc": _cut(plan.get("seo_desc") or plan.get("description") or "", 158),
        "tags": _cut(", ".join(_as_list(plan.get("tags"))), 250),
        "description": _cut(plan.get("description") or plan.get("seo_desc") or "", 400),
        "primary_keyword": primary,
        "secondary_keywords": _as_list(plan.get("secondary_keywords"))[:14],
        "questions": _as_list(plan.get("questions"))[:10],
        "search_intent": plan.get("search_intent") or "",
        "snippet_answer": plan.get("snippet_answer") or "",
    }


def _ctx(plan):
    return dict(
        business=BUSINESS_CONTEXT, scope=SCOPE_RULES, style=STYLE_RULES, title=plan["title"],
        primary=plan["primary_keyword"], secondary=", ".join(plan["secondary_keywords"]),
        questions="\n".join(f"- {q}" for q in plan["questions"]), brand=BRAND_NAME,
    )


# ============================================================================ agents
def seo_agent(run_id, topic, angle, content_type):
    """Keyword research + every SEO field. Returns the 'plan' used by all later steps."""
    log_step(run_id, "SEO Agent", "started", f"Keyword research and SEO plan for: {topic}")
    prompt = _fill(SEO_PROMPT, business=BUSINESS_CONTEXT, topic=topic, angle=angle, ctype=content_type)
    plan = _clean_plan(ask_gemini_json(prompt, temperature=0.4), topic)
    log_step(run_id, "SEO Agent", "done",
             f"Primary keyword: {plan['primary_keyword']} | {len(plan['secondary_keywords'])} secondary keywords, "
             f"{len(plan['questions'])} search questions | SEO title: {plan['seo_title']}")
    return plan


def outline_agent(run_id, plan, topic, angle):
    log_step(run_id, "Blog Agent", "started", "Planning the article outline...")
    prompt = _fill(BLOG_OUTLINE_PROMPT, angle=angle, **_ctx(plan))
    data = ask_gemini_json(prompt, temperature=0.5, max_output_tokens=8000)
    sections = []
    for s in data.get("sections") or []:
        if not s.get("heading"):
            continue
        fmt = s.get("format") if s.get("format") in ("prose", "list", "steps", "table", "code") else "prose"
        try:
            words = max(300, min(480, int(s.get("words") or 380)))
        except (TypeError, ValueError):
            words = 380
        sections.append({"heading": str(s["heading"]).strip(), "points": _as_list(s.get("points")),
                         "words": words, "format": fmt})
    sections = sections[:10]
    if len(sections) < 6:
        raise ValueError("The outline had too few sections")
    needs_code = bool(data.get("needs_code")) and any(s["format"] == "code" for s in sections)
    if not needs_code:
        for s in sections:
            if s["format"] == "code":
                s["format"] = "prose"
    log_step(run_id, "Blog Agent", "done", f"Outline ready: {len(sections)} sections")
    return {"sections": sections, "needs_code": needs_code}


def write_section_agent(run_id, plan, section, all_headings, done_headings, extra=""):
    """Writes one section. If the first draft is too short, asks for a deeper rewrite."""
    target = section["words"]
    prompt = _fill(
        SECTION_PROMPT, all_headings="\n".join(f"- {h}" for h in all_headings),
        done="\n".join(f"- {h}" for h in done_headings) or "(none yet)",
        heading=section["heading"], points="\n".join(f"- {p}" for p in section.get("points", [])),
        format=FORMAT_GUIDE.get(section.get("format", "prose"), FORMAT_GUIDE["prose"]),
        words=target, extra=extra or "None", **_ctx(plan))
    html = _clean_section_html(ask_gemini(prompt, temperature=0.75, max_output_tokens=7000), section["heading"])
    if word_count(html) < 0.65 * target:
        expand = _fill(EXPAND_PROMPT, words=target, style=STYLE_RULES, extra=extra or "None", draft=html)
        html = _clean_section_html(ask_gemini(expand, temperature=0.75, max_output_tokens=7000), section["heading"])
    return html


def intro_agent(run_id, plan, all_headings):
    prompt = _fill(INTRO_PROMPT, all_headings="\n".join(f"- {h}" for h in all_headings),
                   snippet=plan["snippet_answer"], **_ctx(plan))
    return _strip_fences(ask_gemini(prompt, temperature=0.75, max_output_tokens=3000))


def faq_agent(run_id, plan, extra=""):
    prompt = _fill(FAQ_PROMPT, extra=extra or "None", **_ctx(plan))
    html = _strip_fences(ask_gemini(prompt, temperature=0.6, max_output_tokens=6000))
    return re.sub(r"<(/?)h1\b", r"<\1h2", html)


def conclusion_agent(run_id, plan, all_headings):
    prompt = _fill(CONCLUSION_PROMPT, all_headings="\n".join(f"- {h}" for h in all_headings), **_ctx(plan))
    return _strip_fences(ask_gemini(prompt, temperature=0.7, max_output_tokens=3000))


def project_spec_agent(run_id, plan, topic, angle):
    """Designs the real project: parts list, pin map and the complete sketch."""
    log_step(run_id, "Project Agent", "started", f"Designing the project (parts, wiring, code): {plan['title']}")
    prompt = _fill(PROJECT_SPEC_PROMPT, topic=topic, angle=angle, **_ctx(plan))
    last_error = None
    for _ in range(2):
        spec = ask_gemini_json(prompt, temperature=0.5, max_output_tokens=16000)
        if spec.get("components") and spec.get("pin_map") and (spec.get("code") or "").strip():
            spec["board"] = spec.get("board") or "Arduino Uno"
            spec["features"] = _as_list(spec.get("features"))
            spec["tools"] = _as_list(spec.get("tools"))
            spec["libraries"] = _as_list(spec.get("libraries"))
            spec["code_title"] = spec.get("code_title") or f"Complete sketch: {plan['title']}"
            log_step(run_id, "Project Agent", "done",
                     f"Project designed: {len(spec['components'])} components, {len(spec['pin_map'])} connections, "
                     f"{len(spec['code'].splitlines())} lines of code")
            return spec
        last_error = "the spec was missing components, pin_map or code"
    raise ValueError(f"Project spec failed: {last_error}")


def code_example_agent(run_id, plan, topic, section):
    prompt = _fill(CODE_EXAMPLE_PROMPT, topic=topic, heading=section["heading"],
                   points="\n".join(f"- {p}" for p in section.get("points", [])), **_ctx(plan))
    block = ask_gemini_json(prompt, temperature=0.4, max_output_tokens=4000)
    if not (block.get("code") or "").strip():
        raise ValueError("code example was empty")
    block.setdefault("language", "cpp")
    block["title"] = block.get("title") or "Example code"
    return block


def code_review_agent(run_id, title, context_text, code_blocks):
    """Second pair of eyes on the code: fixes syntax/library/pin/logic problems."""
    log_step(run_id, "Code Reviewer", "started", f"Reviewing the code for: {title}")
    try:
        prompt = _fill(CODE_REVIEW_PROMPT, article=context_text, code=json.dumps(code_blocks, ensure_ascii=False))
        result = ask_gemini_json(prompt, temperature=0.1, max_output_tokens=20000)
        fixed = result.get("code_blocks") or []
        valid = (len(fixed) == len(code_blocks)
                 and all(isinstance(b, dict) and (b.get("code") or "").strip() for b in fixed))
        if not valid:
            log_step(run_id, "Code Reviewer", "warning", "Reviewer reply was unusable; keeping the original code")
            return code_blocks
        issues = result.get("issues_fixed") or []
        log_step(run_id, "Code Reviewer", "done",
                 (f"{len(issues)} issue(s) fixed: " + "; ".join(str(i) for i in issues))[:400] if issues
                 else "No problems found in the code")
        return fixed
    except Exception as e:
        log_step(run_id, "Code Reviewer", "error", f"Review failed ({e}); keeping the original code")
        return code_blocks
