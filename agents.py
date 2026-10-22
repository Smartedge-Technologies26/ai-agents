"""
agents.py
The "thinking" agents. Each one has ONE job:
  - research_agent        -> finds today's blog topic + project topic (beginner/intermediate,
                              strictly within the IoT / robotics / embedded-systems niche)
  - seo_agent              -> builds SEO fields (title, slug, meta, tags) for a topic
  - blog_writer_agent      -> writes the full blog article (HTML) + marks where inline images should go
  - project_writer_agent   -> writes the full project write-up (HTML) + marks where inline images should go
"""

import json
from gemini_client import ask_gemini_json
from admin_client import log_step
from config import BUSINESS_CONTEXT

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


def seo_agent(run_id, topic, angle, content_type):
    log_step(run_id, "SEO Agent", "started", f"Building SEO fields for: {topic}")

    prompt = f"""
You are an SEO specialist for this business: {BUSINESS_CONTEXT}

Topic: {topic}
Angle: {angle}
Content type: {content_type}

Create SEO metadata for this {content_type}. Reply with ONLY valid JSON in this exact shape:
{{
  "title": "compelling human-friendly title, under 65 characters",
  "slug": "url-friendly-slug-with-hyphens",
  "category": "one short category name",
  "seo_title": "SEO title tag, under 60 characters",
  "seo_desc": "meta description, under 155 characters, includes a call to action",
  "tags": "comma,separated,keywords",
  "description": "one paragraph (2-3 sentences) summary for the listing card"
}}
"""
    data = ask_gemini_json(prompt)
    log_step(run_id, "SEO Agent", "done", f"SEO title: {data.get('seo_title')}")
    return data


BLOG_PROMPT = """
You are a friendly, clear, technically careful writer for this business: <<BUSINESS>>

<<SCOPE>>

Write a complete, original, SEO-friendly and genuinely DETAILED blog post for BEGINNER to INTERMEDIATE
readers — people new to IoT / robotics / embedded systems. Explain things simply, like teaching a smart
friend who doesn't know the jargon yet.

Title: <<TITLE>>
Topic: <<TOPIC>>
Angle: <<ANGLE>>
Target keywords: <<TAGS>>

CONTENT RULES
- Length: 1800 to 2400 words of article text (code is not counted). Detailed, practical, concrete.
- Do NOT repeat the title as a heading (the page already shows it). Start directly with a short, engaging intro.
- Allowed HTML tags ONLY: h2, h3, p, ul, ol, li, strong, em, table, thead, tbody, tr, th, td, blockquote.
  No html/head/body tags, no inline styles, no img/pre/code tags (images and code are inserted via markers).
- Structure: intro -> "Quick Summary" (h2 + ul with 3-5 key takeaways) -> 5-7 main sections (h2/h3) ->
  practical tips -> common mistakes and how to fix them -> "Frequently Asked Questions" (h2, then 3-4 questions
  as h3 each followed by a p answer) -> conclusion with a call to action to contact us for source code,
  technical guidance and expert support.
- Include at least one useful table (for example a comparison or quick-reference table) where it fits naturally.
- Explain every technical term the first time it appears, in plain language. Use real-world analogies and
  concrete examples with realistic values.
- ACCURACY: state only facts you are confident are correct (typical voltages, pin names, protocol behaviour).
  Never invent statistics, case studies, prices or quotes.

CODE
- If the topic is practical (a sensor, protocol, component, wiring or programming idea), include ONE correct,
  beginner-friendly Arduino-style (C/C++) example of 15-50 lines with helpful comments. Put the marker
  {{CODE_1}} on its own line right after the paragraph introducing it, then explain in the next paragraph what the
  code does. If the topic is purely conceptual, return an empty code_blocks list.
- Code goes ONLY into the code_blocks JSON field as plain text (no HTML, no markdown fences).

IMAGES
- Put 4 or 5 markers {{IMAGE_1}} ... {{IMAGE_5}} (never fewer than 3), each on its own line, spread evenly through
  the article, each placed right after the paragraph about the thing the picture shows.
- image_queries[i] is the search phrase for IMAGE_{i+1}. It must name the EXACT real-world item that the nearby text
  talks about, as a 2-4 word phrase using the real part/product/tool name. Good examples: "HC-SR04 ultrasonic
  sensor", "Arduino Uno board", "breadboard jumper wires", "SG90 servo motor", "DHT11 sensor", "16x2 LCD display",
  "L298N motor driver", "soldering iron". Bad: sentences, or words like "beginner", "simple", "concept".

Reply with ONLY valid JSON in exactly this shape:
{
  "content_html": "the full HTML article including the IMAGE markers (and the CODE marker if code is used)",
  "image_queries": ["phrase for IMAGE_1", "phrase for IMAGE_2", "phrase for IMAGE_3", "phrase for IMAGE_4"],
  "code_blocks": [{"title": "short title", "language": "cpp", "code": "plain code text"}]
}
"""

PROJECT_PROMPT = """
You are a friendly, meticulous technical writer for this business: <<BUSINESS>>

<<SCOPE>>

Write a complete, original, DETAILED build guide for a project that readers can actually build, aimed at BEGINNER to
INTERMEDIATE readers. It must be accurate and consistent: the parts list, wiring table, steps and code must all agree.

Title: <<TITLE>>
Topic: <<TOPIC>>
Angle: <<ANGLE>>
Target keywords: <<TAGS>>

CONTENT RULES
- Length: 2000 to 2800 words of article text (code is not counted). Detailed and practical.
- Do NOT repeat the title as a heading (the page already shows it). Start directly with an engaging overview.
- Allowed HTML tags ONLY: h2, h3, p, ul, ol, li, strong, em, table, thead, tbody, tr, th, td, blockquote.
  No html/head/body tags, no inline styles, no img/pre/code tags (images and code are inserted via markers).
- Use EXACTLY these sections, in this order, each as an h2:
  1. "Project Overview"  - the problem it solves, what it does, who it is for, difficulty level, approximate build time.
  2. "What You Will Learn" - ul of 4-6 skills.
  3. "Components Required" - a table with columns: Component | Quantity | Purpose. Use real, commonly available parts
     (for example Arduino Uno or Nano, named sensors/modules, breadboard, jumper wires, resistors with values, power source).
  4. "How It Works" - the working principle in simple terms, step by step (input -> processing -> output).
  5. "Circuit Connections" - a table with columns: Component Pin | Board Pin | Notes. Every pin number must be exact
     and must match the code. Mention power (3.3V/5V) and grounds correctly.
  6. "Step-by-Step Build" - an ol with 8-12 detailed steps (placing parts, wiring, power-up checks, uploading code).
  7. "Complete Example Code" - one short intro paragraph, the marker {{CODE_1}} on its own line, then h3 sub-sections that
     explain the code part by part (libraries and pin definitions, setup(), loop(), key functions), and a paragraph on
     which libraries to install (Arduino IDE > Library Manager) if any are used.
  8. "Testing and Expected Output" - exactly what the user should see (LED behaviour, Serial Monitor text, LCD text).
  9. "Troubleshooting" - a table with columns: Problem | Likely Cause | Fix (at least 5 rows).
  10. "Ideas to Extend This Project" - ul of 4-5 upgrade ideas.
  11. "Conclusion" - short wrap-up and a call to action to contact us for the full source code, technical guidance and
      expert support.
- Explain every technical term the first time it appears, in plain language.
- ACCURACY: only use facts you are sure are correct. Never invent prices, statistics or case studies.

CODE (very important)
- code_blocks[0] must be ONE COMPLETE, compile-ready Arduino sketch (C/C++): includes, pin definitions, setup(),
  loop(), helper functions, Serial debug prints. 50-150 lines, clear comments, meaningful names, no placeholders
  like "..." or "your code here".
- Use only the standard Arduino core and very common libraries (Wire.h, Servo.h, LiquidCrystal.h,
  LiquidCrystal_I2C.h, DHT.h, SoftwareSerial.h, ...). Pin numbers must match the Circuit Connections table exactly.
- You may add a second small block (for example a wiring/sensor test sketch) as code_blocks[1] with marker {{CODE_2}}.
- Code goes ONLY into the code_blocks JSON field as plain text (no HTML, no markdown fences).

IMAGES
- Put 4 or 5 markers {{IMAGE_1}} ... {{IMAGE_5}} (never fewer than 3), each on its own line, spread across the guide
  (for example near Components Required, Circuit Connections, the build steps and the finished result), each placed right
  after the paragraph about the thing the picture shows.
- image_queries[i] is the search phrase for IMAGE_{i+1}. It must name the EXACT real-world item that the nearby text
  talks about, as a 2-4 word phrase using the real part/product/tool name (for example "HC-SR04 ultrasonic sensor",
  "Arduino Uno board", "breadboard jumper wires", "SG90 servo motor", "DHT11 sensor", "16x2 LCD display",
  "L298N motor driver"). Bad: sentences, or words like "beginner", "simple", "concept".

Reply with ONLY valid JSON in exactly this shape:
{
  "content_html": "the full HTML guide including the IMAGE markers and the CODE marker(s)",
  "image_queries": ["phrase for IMAGE_1", "phrase for IMAGE_2", "phrase for IMAGE_3", "phrase for IMAGE_4"],
  "code_blocks": [{"title": "Complete sketch: <project name>", "language": "cpp", "code": "plain code text"}],
  "features": "comma,separated,list,of,key,features",
  "tech_used": "comma,separated,list,of,components,and,boards,used"
}
"""

CODE_REVIEW_PROMPT = """
You are a meticulous embedded-systems code reviewer (Arduino C/C++). Below is an article (HTML) and the example code
blocks that go with it.

Check EVERY code block for:
- syntax errors (missing semicolons/braces/parentheses), undeclared or misspelled variables, wrong function names
- missing #include lines, wrong library or class names, calls that do not exist in that library
- wrong pin usage (analogRead on a digital-only pin, PWM on a non-PWM pin, I2C on the wrong pins - Uno uses A4/A5)
- missing pinMode() / Serial.begin(), wrong baud rates, missing delays/timing the module needs
- logic bugs, and behaviour that does not match what the article says the project does
- any disagreement with the article's connection table or described behaviour

Fix everything you find. If the code and the article's pin table disagree, change the CODE to match the table (never
change the article). Keep the code beginner-friendly with helpful comments. Do not shorten it or remove features.

Reply with ONLY valid JSON in exactly this shape (same number of blocks, same order as given):
{"issues_fixed": ["short description of each fix"], "code_blocks": [{"title": "...", "language": "cpp", "code": "..."}]}

ARTICLE (HTML):
<<ARTICLE>>

CODE BLOCKS (JSON):
<<CODE>>
"""


def _fill(template, **values):
    out = template
    for key, val in values.items():
        out = out.replace("<<" + key.upper() + ">>", str(val))
    return out


def blog_writer_agent(run_id, topic, angle, seo):
    log_step(run_id, "Blog Agent", "started", f"Writing blog: {seo.get('title')}")
    prompt = _fill(BLOG_PROMPT, business=BUSINESS_CONTEXT, scope=SCOPE_RULES, title=seo.get("title"),
                   topic=topic, angle=angle, tags=seo.get("tags"))
    data = ask_gemini_json(prompt, temperature=0.8, max_output_tokens=20000)
    log_step(run_id, "Blog Agent", "done", "Blog content ready")
    return data


def project_writer_agent(run_id, topic, angle, seo):
    log_step(run_id, "Project Agent", "started", f"Writing project guide: {seo.get('title')}")
    prompt = _fill(PROJECT_PROMPT, business=BUSINESS_CONTEXT, scope=SCOPE_RULES, title=seo.get("title"),
                   topic=topic, angle=angle, tags=seo.get("tags"))
    data = ask_gemini_json(prompt, temperature=0.7, max_output_tokens=24000)
    log_step(run_id, "Project Agent", "done", "Project guide ready")
    return data


def code_review_agent(run_id, title, content_html, code_blocks):
    """Second pair of eyes on the example code: fixes syntax/library/pin/logic problems."""
    log_step(run_id, "Code Reviewer", "started", f"Reviewing example code for: {title}")
    try:
        prompt = _fill(CODE_REVIEW_PROMPT, article=content_html, code=json.dumps(code_blocks, ensure_ascii=False))
        result = ask_gemini_json(prompt, temperature=0.1, max_output_tokens=20000)
        fixed = result.get("code_blocks") or []
        valid = (len(fixed) == len(code_blocks)
                 and all(isinstance(b, dict) and (b.get("code") or "").strip() for b in fixed))
        if not valid:
            log_step(run_id, "Code Reviewer", "warning", "Reviewer reply was unusable; keeping the original code")
            return code_blocks
        issues = result.get("issues_fixed") or []
        log_step(run_id, "Code Reviewer", "done",
                 f"{len(issues)} issue(s) fixed: " + "; ".join(str(i) for i in issues)[:400] if issues
                 else "No problems found in the code")
        return fixed
    except Exception as e:
        log_step(run_id, "Code Reviewer", "error", f"Review failed ({e}); keeping the original code")
        return code_blocks
