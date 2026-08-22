#!/usr/bin/env python3
"""Build the interview study-guide PDF for the production API wrapper."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).with_name("interview-study-guide.pdf")

INK = colors.HexColor("#1b2430")
MUTED = colors.HexColor("#4b5563")
NAVY = colors.HexColor("#1e3a5f")
TEAL = colors.HexColor("#0f766e")
RULE = colors.HexColor("#d1d5db")
ROW = colors.HexColor("#f4f7fa")
HEAD = colors.HexColor("#1e3a5f")
HEAD_TEXT = colors.white
SOFT = colors.HexColor("#e8eef5")
WARN = colors.HexColor("#7c2d12")
WARN_BG = colors.HexColor("#fff7ed")


def styles():
    base = getSampleStyleSheet()
    s = {
        "cover_kicker": ParagraphStyle(
            "cover_kicker",
            parent=base["Normal"],
            fontName="Times-Bold",
            fontSize=11,
            textColor=TEAL,
            alignment=TA_CENTER,
            letterSpacing=1.2,
            spaceAfter=10,
        ),
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontName="Times-Bold",
            fontSize=28,
            leading=34,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            parent=base["Normal"],
            fontName="Times-Italic",
            fontSize=13,
            leading=18,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="Times-Bold",
            fontSize=18,
            leading=22,
            textColor=NAVY,
            spaceBefore=6,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Times-Bold",
            fontSize=14,
            leading=18,
            textColor=TEAL,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=base["Heading3"],
            fontName="Times-Bold",
            fontSize=12,
            leading=15,
            textColor=NAVY,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=10.5,
            leading=15,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=7,
        ),
        "body_left": ParagraphStyle(
            "body_left",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=10.5,
            leading=15,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=7,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=10.5,
            leading=14.5,
            textColor=INK,
            leftIndent=12,
            spaceAfter=3,
        ),
        "callout": ParagraphStyle(
            "callout",
            parent=base["Normal"],
            fontName="Times-Italic",
            fontSize=10.5,
            leading=15,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=0,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=8.5,
            leading=11.5,
            textColor=INK,
        ),
        "cell_h": ParagraphStyle(
            "cell_h",
            parent=base["Normal"],
            fontName="Times-Bold",
            fontSize=8.5,
            leading=11.5,
            textColor=HEAD_TEXT,
        ),
        "mono": ParagraphStyle(
            "mono",
            parent=base["Code"],
            fontName="Courier",
            fontSize=8,
            leading=11,
            textColor=INK,
            backColor=SOFT,
            leftIndent=6,
            rightIndent=6,
            spaceBefore=4,
            spaceAfter=10,
        ),
        "caption": ParagraphStyle(
            "caption",
            parent=base["Normal"],
            fontName="Times-Italic",
            fontSize=9,
            leading=12,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "toc": ParagraphStyle(
            "toc",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=11,
            leading=18,
            textColor=INK,
            leftIndent=8,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=8,
            textColor=MUTED,
        ),
    }
    return s


S = styles()


def p(text, style="body"):
    return Paragraph(text, S[style])


def bullets(items, style="bullet"):
    flow = []
    for item in items:
        flow.append(Paragraph(f"-  {item}", S[style]))
    flow.append(Spacer(1, 4))
    return flow


def callout(text):
    inner = Paragraph(text, S["callout"])
    table = Table([[inner]], colWidths=[6.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                ("BOX", (0, 0), (-1, -1), 0.75, TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return KeepTogether([Spacer(1, 4), table, Spacer(1, 10)])


def warn_box(text):
    inner = Paragraph(text, ParagraphStyle("warn", parent=S["callout"], textColor=WARN))
    table = Table([[inner]], colWidths=[6.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
                ("BOX", (0, 0), (-1, -1), 0.75, WARN),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return KeepTogether([Spacer(1, 4), table, Spacer(1, 10)])


def make_table(headers, rows, widths):
    cell = S["cell"]
    head = S["cell_h"]
    data = [[Paragraph(h, head) for h in headers]]
    for row in rows:
        data.append([Paragraph(str(c), cell) for c in row])
    table = Table(data, colWidths=widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD),
        ("TEXTCOLOR", (0, 0), (-1, 0), HEAD_TEXT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), ROW))
    table.setStyle(TableStyle(style_cmds))
    return table


def header_footer(canvas, doc):
    canvas.saveState()
    w, h = letter
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 28, w, 28, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Times-Roman", 8)
    canvas.drawString(0.75 * inch, h - 18, "Production API Wrapper  ·  Interview Study Guide")
    canvas.drawRightString(w - 0.75 * inch, h - 18, "Internal FastAPI + OpenAI + Redis")
    canvas.setFillColor(TEAL)
    canvas.rect(0, 0, w, 22, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Times-Roman", 8)
    canvas.drawString(0.75 * inch, 8, "Read in order. Speak each stage out loud before moving on.")
    canvas.drawRightString(w - 0.75 * inch, 8, f"Page {doc.page}")
    canvas.restoreState()


def cover_page(canvas, doc):
    canvas.saveState()
    w, h = letter
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    canvas.setFillColor(TEAL)
    canvas.rect(0, h - 14, w, 14, fill=1, stroke=0)
    canvas.rect(0, 0, w, 90, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Times-Roman", 10)
    canvas.drawCentredString(w / 2, h - 120, "INTERVIEW PREPARATION  ·  END-TO-END UNDERSTANDING")
    canvas.setFont("Times-Bold", 30)
    canvas.drawCentredString(w / 2, h / 2 + 40, "Production API Wrapper")
    canvas.setFont("Times-Italic", 14)
    canvas.drawCentredString(w / 2, h / 2 + 12, "A plain-English study guide for the whole project")
    canvas.setStrokeColor(colors.white)
    canvas.setLineWidth(0.8)
    canvas.line(w / 2 - 90, h / 2 - 4, w / 2 + 90, h / 2 - 4)
    canvas.setFont("Times-Roman", 11)
    canvas.drawCentredString(w / 2, h / 2 - 28, "FastAPI  ·  OpenAI Responses API  ·  Redis")
    canvas.drawCentredString(w / 2, h / 2 - 46, "prod-api-wrapper")
    canvas.setFont("Times-Roman", 9)
    canvas.drawCentredString(w / 2, 50, "Study outside-in: problem > doors > guards > two jobs > Redis > failures > tests")
    canvas.restoreState()


def story():
    out = []

    # ----- TOC -----
    out.append(p("Contents", "h1"))
    toc_items = [
        "1. The one-sentence story",
        "2. The picture to keep in your head",
        "3. How to study this project",
        "4. Stage 0 — The business problem",
        "5. Stage 1 — The six public doors",
        "6. Stage 2 — How the app boots",
        "7. Stage 3 — The three guards",
        "8. Stage 4 — Synchronous path (wait for the answer)",
        "9. Stage 5 — Background path, polling, and webhooks",
        "10. Stage 6 — Errors, health, and fail-closed",
        "11. Stage 7 — Redis as the shared brain",
        "12. Stage 8 — Tests as a second teacher",
        "13. Stage 9 — Built vs still on the old roadmap",
        "14. File map",
        "15. Whiteboard scripts",
        "16. Five-day study plan",
        "17. Interview questions and answers",
        "18. Words you must not mix up",
    ]
    for item in toc_items:
        out.append(p(item, "toc"))
    out.append(Spacer(1, 12))
    out.append(
        callout(
            "How to use this PDF: read one stage, open the listed files, then close the laptop and "
            "explain the stage in plain English. If you cannot explain it without looking, you do not "
            "own it yet."
        )
    )
    out.append(PageBreak())

    # ----- 1 -----
    out.append(p("1. The one-sentence story", "h1"))
    out.append(
        p(
            "This project is a <b>gatekeeper</b> between your internal application and OpenAI. "
            "Your app never talks to OpenAI. It talks to this wrapper. The wrapper holds the real "
            "OpenAI key, checks who is calling, limits how often they can call, stops accidental "
            "double billing, and either waits for the answer or says “here is a job ID, poll later.”"
        )
    )
    out.append(
        callout(
            "Interview opener: “This is not a chatbot. It is an internal production API that hides "
            "the provider, shrinks the contract, and adds the controls you need before you let many "
            "services call a paid model.”"
        )
    )
    out.append(
        p(
            "If you can tell that story clearly, you already have the first two minutes of the interview. "
            "Everything else is detail that proves you actually built it."
        )
    )

    out.append(p("What this project proves", "h2"))
    out.extend(
        bullets(
            [
                "An internal application can use AI without holding the OpenAI API key.",
                "A small, explicit API contract is safer to operate than forwarding every upstream option.",
                "Redis can coordinate state shared by multiple API instances.",
                "Background work needs durable job state and verified event delivery.",
                "Reliable services make retries safe, failures predictable, and requests traceable.",
            ]
        )
    )

    # ----- 2 -----
    out.append(p("2. The picture to keep in your head", "h1"))
    diagram = """Internal app
   |  Bearer key + Idempotency-Key + optional X-Correlation-ID
   v
FastAPI wrapper
   |  1. Stamp a correlation ID
   |  2. Check the internal key
   |  3. Count this request in Redis (rate limit)
   |  4. Validate the small request body
   |  5. Claim "I already did this?" in Redis
   |  6. Call OpenAI (or skip if already done)
   |
   +-----> OpenAI Responses API
   |
   +-----> Redis
              rate-limit counters
              idempotency records
              job records
              processed webhook events

OpenAI later
   |  signed webhook
   v
POST /webhooks/openai
   |  verify signature, update job in Redis
   v
Internal app polls GET /v1/responses/{job_id}"""
    out.append(Preformatted(diagram, S["mono"]))
    out.append(p("The three actors and what each one is allowed to know.", "caption"))
    out.append(
        make_table(
            ["Actor", "Talks to", "Holds", "Must never see"],
            [
                [
                    "Internal app",
                    "Only this wrapper",
                    "Wrapper API key",
                    "OpenAI API key, webhook secret, Redis internals",
                ],
                [
                    "This wrapper",
                    "OpenAI + Redis",
                    "OpenAI key, webhook secret, wrapper key",
                    "Must not leak secrets in logs or error bodies",
                ],
                [
                    "OpenAI",
                    "Webhook URL on this wrapper",
                    "The model work",
                    "Your wrapper bearer key (webhooks use a signature instead)",
                ],
            ],
            [1.4 * inch, 1.6 * inch, 1.7 * inch, 1.8 * inch],
        )
    )
    out.append(Spacer(1, 10))

    # ----- 3 -----
    out.append(p("3. How to study this project", "h1"))
    out.append(
        p(
            "Do not start in random files. Do not start with <font face='Courier'>roadmap.md</font> — "
            "that is a build plan, not a teaching order. Study <b>outside-in</b>, like a request walking "
            "through a building."
        )
    )
    out.extend(
        bullets(
            [
                "<b>Why</b> this service exists",
                "The <b>six public doors</b> (endpoints)",
                "What happens to <b>every</b> request (middleware)",
                "The two real jobs: <b>wait for the answer</b> vs <b>start a job</b>",
                "<b>Redis</b>: the shared notebook",
                "<b>Failures</b>: retries, errors, health",
                "<b>Tests</b>: how you prove it works",
                "What is still unfinished, so you do not oversell",
            ]
        )
    )
    out.append(
        p(
            "You already have notes in the <font face='Courier'>Learning/</font> folder. Use those "
            "<i>after</i> you understand the story. This PDF is the teaching order."
        )
    )

    # ----- 4 -----
    out.append(p("4. Stage 0 — The business problem", "h1"))
    out.append(p("Question you must answer: why not give every service the OpenAI key?", "h2"))
    out.extend(
        bullets(
            [
                "Keys leak from frontends and from many repositories.",
                "Every team would invent their own retries, limits, and errors.",
                "OpenAI’s API is huge; your company only needs a few fields.",
                "Background work needs a place to store “is this job done?”",
                "Networks retry; you must not pay twice for the same click.",
            ]
        )
    )
    out.append(p("Read", "h3"))
    out.append(
        p(
            "<font face='Courier'>Learning/README.md</font>, <font face='Courier'>roadmap.md</font> "
            "sections 1–2, and the first ten answers in "
            "<font face='Courier'>Learning/questions-and-answers.md</font>."
        )
    )
    out.append(
        callout(
            "Interview line: “The wrapper is a security and operations boundary. The product talks "
            "to our API. We talk to OpenAI.”"
        )
    )
    out.append(p("You are done with this stage when…", "h3"))
    out.append(
        p(
            "You can explain the project to a non-engineer in under one minute, and then add the "
            "engineering reasons in a second minute."
        )
    )

    # ----- 5 -----
    out.append(p("5. Stage 1 — The six public doors", "h1"))
    out.append(
        p(
            "Question: what can a caller actually do? The wrapper publishes a small, stable contract. "
            "Unknown request fields are rejected. All bodies are JSON."
        )
    )
    out.append(
        make_table(
            ["Door", "Who is allowed", "Success", "What it means in English"],
            [
                [
                    "POST /v1/responses",
                    "Internal bearer key + Idempotency-Key",
                    "200",
                    "Do this now and wait.",
                ],
                [
                    "POST /v1/responses/background",
                    "Internal bearer key + Idempotency-Key",
                    "202",
                    "Start this, do not wait. Return a job id.",
                ],
                [
                    "GET /v1/responses/{job_id}",
                    "Internal bearer key",
                    "202 or 200",
                    "Is that job done yet? Reads Redis only.",
                ],
                [
                    "POST /webhooks/openai",
                    "OpenAI signature, not your key",
                    "200",
                    "OpenAI is telling us the job finished.",
                ],
                [
                    "GET /health/live",
                    "Internal bearer key",
                    "200",
                    "Is the process alive? Never talks to Redis or OpenAI.",
                ],
                [
                    "GET /health/ready",
                    "Internal bearer key",
                    "200 or 503",
                    "Can I do real work? Pings Redis.",
                ],
            ],
            [1.7 * inch, 1.7 * inch, 0.7 * inch, 2.4 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(p("The only fields a caller may send", "h2"))
    out.append(
        p(
            "Both create endpoints accept the same body. Extra fields are rejected "
            "(<font face='Courier'>extra='forbid'</font> on the Pydantic model)."
        )
    )
    out.append(
        make_table(
            ["Field", "Required", "Validation"],
            [
                ["input", "Yes", "Non-blank string, 1–50,000 characters."],
                [
                    "instructions",
                    "No",
                    "If present: non-blank, at most 10,000 characters.",
                ],
                [
                    "model",
                    "No",
                    "Must be in OPENAI_ALLOWED_MODELS. If omitted, OPENAI_DEFAULT_MODEL is used.",
                ],
                ["max_output_tokens", "No", "Integer from 1 to 16,384."],
                [
                    "metadata",
                    "No",
                    "At most 16 string key/value pairs. Keys 1–64 chars, values at most 512.",
                ],
            ],
            [1.6 * inch, 0.9 * inch, 4.0 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(
        p(
            "The wrapper never accepts client-supplied API keys, tools, streaming options, callbacks, "
            "or arbitrary OpenAI fields. That is a design choice, not a missing feature."
        )
    )
    out.append(p("Standard headers", "h2"))
    out.append(
        make_table(
            ["Header", "Who sends it", "Rule"],
            [
                [
                    "Authorization: Bearer …",
                    "Internal app",
                    "Required on every door except the OpenAI webhook.",
                ],
                [
                    "Idempotency-Key",
                    "Internal app",
                    "Required on both create endpoints. Makes retries safe.",
                ],
                [
                    "X-Correlation-ID",
                    "Optional from client",
                    "Must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$. If missing, the wrapper creates one.",
                ],
            ],
            [1.8 * inch, 1.4 * inch, 3.3 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(p("Read", "h3"))
    out.append(
        p(
            "<font face='Courier'>Learning/api-design.md</font>, "
            "<font face='Courier'>app/schemas/responses.py</font>, "
            "<font face='Courier'>app/schemas/jobs.py</font>."
        )
    )
    out.append(p("Practice", "h3"))
    out.append(
        p(
            "Draw the six endpoints on paper. For each, write: who authenticates, success code, "
            "who calls it, and whether Redis or OpenAI is touched."
        )
    )

    # ----- 6 -----
    out.append(p("6. Stage 2 — How the app boots", "h1"))
    out.append(
        p(
            "<font face='Courier'>app/main.py</font> is the front door of the code. On startup "
            "(<font face='Courier'>lifespan</font>) the process:"
        )
    )
    out.extend(
        bullets(
            [
                "Loads settings from the environment (<font face='Courier'>load_settings</font>).",
                "Opens one shared Redis client.",
                "Opens one shared OpenAI client.",
                "Serves traffic.",
                "On shutdown, closes both clients (OpenAI first, then Redis).",
            ]
        )
    )
    out.append(p("Middleware order — this is an interview question", "h2"))
    out.append(
        p(
            "In code the middlewares are added as: rate limiting, then authentication, then correlation. "
            "Starlette wraps the last one first. So a real request hits:"
        )
    )
    out.append(Preformatted("correlation  ->  authentication  ->  rate limit  ->  route", S["mono"]))
    out.extend(
        bullets(
            [
                "<b>Correlation first</b> so even a 401 still has an ID on the response.",
                "<b>Auth before rate limit</b> so random internet traffic does not burn Redis counters.",
                "<b>Webhooks skip auth and rate limit</b> because OpenAI cannot send your bearer key.",
            ]
        )
    )
    out.append(p("Configuration that refuses to start", "h2"))
    out.append(
        p(
            "<font face='Courier'>app/config.py</font> fails at boot if anything important is missing "
            "or invalid. Secrets are stored with <font face='Courier'>repr=False</font> so they do "
            "not print in errors."
        )
    )
    out.append(
        make_table(
            ["Setting", "Why it exists"],
            [
                ["OPENAI_API_KEY", "The real provider key. Lives only in this service."],
                ["OPENAI_WEBHOOK_SECRET", "Used to verify that a webhook really came from OpenAI."],
                ["WRAPPER_API_KEY", "The internal key your own app sends."],
                ["REDIS_URL", "Must be redis:// or rediss:// with a hostname."],
                ["OPENAI_ALLOWED_MODELS", "Comma list. Callers cannot pick any model they want."],
                ["OPENAI_DEFAULT_MODEL", "Must be on the allowlist."],
                ["OPENAI_TIMEOUT_SECONDS", "How long we wait for OpenAI. Default 30."],
                ["RATE_LIMIT_REQUESTS / WINDOW", "Shared fixed-window limit. Defaults 60 / 60."],
                ["JOB_TTL_SECONDS", "How long a background job lives in Redis. Default 24 hours."],
                ["IDEMPOTENCY_TTL_SECONDS", "How long a replay record lives. Default 24 hours."],
                ["LOG_LEVEL", "CRITICAL, ERROR, WARNING, INFO, or DEBUG."],
            ],
            [2.3 * inch, 4.2 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(
        p(
            "The OpenAI client is built with <font face='Courier'>max_retries=0</font>. That is "
            "deliberate: <b>you</b> retry in <font face='Courier'>retry_async</font>, the SDK does "
            "not. Otherwise you would double-retry and hide the policy."
        )
    )
    out.append(p("Read", "h3"))
    out.append(
        p(
            "<font face='Courier'>app/main.py</font>, <font face='Courier'>app/config.py</font>, "
            "<font face='Courier'>app/clients/openai_client.py</font>, "
            "<font face='Courier'>app/clients/redis_client.py</font>."
        )
    )

    # ----- 7 -----
    out.append(p("7. Stage 3 — The three guards", "h1"))
    out.append(
        p(
            "These three middlewares run on (almost) every request. Interviewers love this layer "
            "because it is where “toy API” becomes “production API.”"
        )
    )

    out.append(p("7.1 Correlation ID — a name tag, not a password", "h2"))
    out.append(p("File: <font face='Courier'>app/middleware/correlation.py</font>"))
    out.extend(
        bullets(
            [
                "Client may send <font face='Courier'>X-Correlation-ID</font>.",
                "If missing or invalid, the wrapper generates a UUID.",
                "Invalid format returns <font face='Courier'>400 invalid_correlation_id</font>.",
                "The ID is always returned in the response header.",
                "It is attached to errors and to background job records.",
                "It does <b>not</b> authorize anyone. It only lets you find one request in logs.",
            ]
        )
    )

    out.append(p("7.2 Authentication — prove you are the internal app", "h2"))
    out.append(p("File: <font face='Courier'>app/middleware/authentication.py</font>"))
    out.extend(
        bullets(
            [
                "Header must be <font face='Courier'>Authorization: Bearer &lt;WRAPPER_API_KEY&gt;</font>.",
                "Compared with <font face='Courier'>hmac.compare_digest</font> so timing is harder to guess.",
                "The webhook path is skipped; it uses OpenAI’s signature instead.",
                "Failed auth never reaches Redis-backed business work or OpenAI.",
            ]
        )
    )

    out.append(p("7.3 Rate limiting — one shared counter", "h2"))
    out.append(
        p(
            "Files: <font face='Courier'>app/middleware/rate_limiting.py</font> and "
            "<font face='Courier'>app/services/rate_limit.py</font>."
        )
    )
    out.extend(
        bullets(
            [
                "Fixed window in Redis: one counter per time window "
                "(<font face='Courier'>wrapper:rate-limit:{window_index}</font>).",
                "<font face='Courier'>INCR</font> and <font face='Courier'>EXPIRE NX</font> run in one transaction.",
                "Over the limit -> <font face='Courier'>429</font> plus <font face='Courier'>Retry-After</font>.",
                "Health and webhooks are exempt. Probes must still work. OpenAI must still deliver.",
                "If Redis is down, rate limiting fails closed with 503. Live still works.",
            ]
        )
    )
    out.append(
        p(
            "Why Redis, not a Python variable? Two workers or two machines would each have their own "
            "counter. After a restart the count would be zero. Redis is the shared counter that "
            "survives process death."
        )
    )
    out.append(
        p(
            "Why must increment and expiry be atomic? If two first-in-window requests race, one might "
            "increment while neither sets expiry, leaving a counter that never resets."
        )
    )
    out.append(
        callout(
            "You are done with this stage when you can say: “If Redis is down, rate limiting fails "
            "closed with 503. Live still works. Correlation still stamps every response.”"
        )
    )

    # ----- 8 -----
    out.append(p("8. Stage 4 — Synchronous path (wait for the answer)", "h1"))
    out.append(
        p(
            "This is the core interview walkthrough. File: "
            "<font face='Courier'>app/api/responses.py</font> -> "
            "<font face='Courier'>create_response</font>."
        )
    )
    out.append(p("Walk this until you can do it on a whiteboard with no notes.", "h2"))
    out.extend(
        bullets(
            [
                "Require <font face='Courier'>Idempotency-Key</font>. Empty -> 422.",
                "Pick the model: request model or default. Must be on the allowlist -> otherwise "
                "<font face='Courier'>400 unsupported_model</font>.",
                "Hash the validated request (<font face='Courier'>request_hash</font>). The hash "
                "includes the effective model so “same key, different model” is a conflict.",
                "Claim the key in Redis with <font face='Courier'>SET NX</font> and an "
                "<font face='Courier'>in_progress</font> record.",
                "First caller: you own the work.",
                "Same key + same body + done: return the saved answer. No second OpenAI call.",
                "Same key + same body + still running: <font face='Courier'>409 idempotency_in_progress</font>.",
                "Same key + different body: <font face='Courier'>409 idempotency_key_reused</font>.",
                "Call OpenAI through <font face='Courier'>retry_async</font>.",
                "If OpenAI fails for good: <b>delete</b> the claim so a later retry can try again.",
                "Shrink OpenAI’s fat object into your small response "
                "(<font face='Courier'>normalize_response</font>).",
                "Store the completed record in Redis.",
                "Return it as 200.",
            ]
        )
    )
    out.append(p("What you send to OpenAI", "h2"))
    out.append(
        p(
            "Only <font face='Courier'>input</font>, <font face='Courier'>model</font>, and the optional "
            "<font face='Courier'>instructions</font>, <font face='Courier'>max_output_tokens</font>, "
            "and <font face='Courier'>metadata</font>. Nothing else."
        )
    )
    out.append(p("What you return to the caller", "h2"))
    out.append(
        make_table(
            ["Field", "Meaning"],
            [
                ["id", "A wrapper id, wrp_resp_…, not OpenAI’s id."],
                ["openai_response_id", "The provider id, kept for traceability."],
                ["status", "Provider status, usually completed."],
                ["model", "Which model actually ran."],
                ["output_text", "The text the internal app needs."],
                ["usage", "Token counts when the provider sent them."],
                ["correlation_id", "The same name tag as the request."],
            ],
            [1.8 * inch, 4.7 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(
        p(
            "Normalization lives in <font face='Courier'>app/services/responses.py</font>. The route "
            "owns the wrapper contract. The OpenAI SDK stays behind "
            "<font face='Courier'>app/clients/openai_client.py</font>. That split makes tests easy: "
            "fake the client, keep the contract."
        )
    )
    out.append(p("Retries — only the flaky stuff", "h2"))
    out.append(p("File: <font face='Courier'>app/services/retry.py</font>."))
    out.extend(
        bullets(
            [
                "At most 2 extra tries (3 attempts total).",
                "Retry only transient errors: connection errors, timeouts, provider 429, provider 5xx.",
                "Never retry auth failures, validation, or unsupported models.",
                "Delay is Retry-After if the provider sent one, otherwise exponential backoff plus jitter.",
                "Jitter exists so a provider outage does not create a synchronized retry storm.",
            ]
        )
    )
    out.append(p("Idempotency — the client sent this already", "h2"))
    out.append(p("File: <font face='Courier'>app/services/idempotency.py</font>."))
    out.extend(
        bullets(
            [
                "The Redis key is <font face='Courier'>wrapper:idempotency:{sha256(key)}</font>, "
                "not the raw header. That keeps keys short and avoids odd characters in Redis.",
                "<font face='Courier'>SET NX EX</font> means “create only if missing, and auto-delete later.”",
                "On final provider failure the in-progress record is deleted so the next attempt can claim.",
                "If storing the completed result fails, the claim is deleted and the caller gets 503. "
                "Better to let them retry than to leave a stuck lock or a success the wrapper cannot replay.",
            ]
        )
    )
    out.append(
        callout(
            "Two words people mix up. Retry = this service tries OpenAI again after a blip. "
            "Idempotency = the client sent the same request again and you must not start a second "
            "billable job. Retries without idempotency can double-charge. Idempotency without retries "
            "still fails on a flaky network."
        )
    )
    out.append(p("Read next", "h3"))
    out.append(
        p(
            "<font face='Courier'>app/services/idempotency.py</font>, "
            "<font face='Courier'>app/services/retry.py</font>, "
            "<font face='Courier'>app/services/responses.py</font>."
        )
    )

    # ----- 9 -----
    out.append(p("9. Stage 5 — Background path, polling, and webhooks", "h1"))
    out.append(
        p(
            "This is the hardest part of the project. Slow down. There is no Celery worker and no "
            "background thread doing the model work. OpenAI does the long work when you send "
            "<font face='Courier'>background=True</font>. You only store state and listen."
        )
    )

    out.append(p("9.1 Create a background job", "h2"))
    out.append(
        p(
            "<font face='Courier'>POST /v1/responses/background</font> in "
            "<font face='Courier'>app/api/responses.py</font>."
        )
    )
    out.extend(
        bullets(
            [
                "Same auth, validation, rate limit, and idempotency as the sync path.",
                "The idempotency hash includes <font face='Courier'>background: true</font> so a "
                "sync call and a background call with the same body are different work.",
                "Create a wrapper job id: <font face='Courier'>job_</font> plus a UUID4.",
                "Save the job in Redis as <font face='Courier'>pending</font> with an expiry.",
                "Call OpenAI with <font face='Courier'>background=True</font>.",
                "Save OpenAI’s response id on the job and mark it <font face='Courier'>in_progress</font>.",
                "Also store a reverse lookup: OpenAI id -> your job id, so a webhook can find the job.",
                "Store the public 202 body in the idempotency record.",
                "Return 202 with <font face='Courier'>status_url</font>.",
            ]
        )
    )
    out.append(
        p(
            "If OpenAI or Redis fails after the job was created, "
            "<font face='Courier'>_release_background</font> deletes the job and the idempotency "
            "claim so the client can retry cleanly."
        )
    )

    out.append(p("9.2 Poll the job", "h2"))
    out.append(p("<font face='Courier'>GET /v1/responses/{job_id}</font>."))
    out.extend(
        bullets(
            [
                "Rejects ids that are not <font face='Courier'>job_</font> plus a lowercase UUID4. "
                "That stops garbage and path tricks from hitting Redis oddly.",
                "Reads <b>only Redis</b>. Does not call OpenAI. Does not extend the TTL.",
                "Still running (pending / in_progress) -> 202.",
                "Finished / failed / cancelled / incomplete -> 200.",
                "Missing or expired -> <font face='Courier'>404 job_not_found</font>. Same error on "
                "purpose, so people cannot fish for whether an old id once existed.",
            ]
        )
    )

    out.append(p("Job states", "h2"))
    out.append(
        make_table(
            ["State", "Meaning", "Typical HTTP on GET"],
            [
                ["pending", "Job saved, OpenAI not yet attached.", "202"],
                ["in_progress", "OpenAI is working. We have their response id.", "202"],
                ["completed", "Webhook (or retrieve) filled in the result.", "200"],
                ["failed", "OpenAI reported failure.", "200"],
                ["cancelled", "OpenAI reported cancellation.", "200"],
                ["incomplete", "OpenAI stopped without a full result.", "200"],
                ["expired", "Treated like missing. Public contract is 404.", "404"],
            ],
            [1.3 * inch, 3.6 * inch, 1.6 * inch],
        )
    )
    out.append(Spacer(1, 10))

    out.append(p("9.3 Receive a signed webhook", "h2"))
    out.append(
        p(
            "Files: <font face='Courier'>app/api/webhooks.py</font> and "
            "<font face='Courier'>app/services/webhooks.py</font>."
        )
    )
    out.extend(
        bullets(
            [
                "Require the three headers: webhook-signature, webhook-timestamp, webhook-id.",
                "Read the raw body. Cap at 1 MiB -> 413 if larger.",
                "Verify the signature <b>before</b> trusting anything "
                "(<font face='Courier'>openai.webhooks.unwrap</font>).",
                "Unknown event types return <font face='Courier'>{\"received\": true}</font> and stop. "
                "Do not fail OpenAI’s delivery for events you do not use.",
                "Claim the event id in Redis with <font face='Courier'>SET NX</font> and a random owner token.",
                "Already processed -> 200, do nothing.",
                "Another worker is processing -> 503 so OpenAI retries.",
                "Look up the job by OpenAI response id.",
                "If the job is not there yet (webhook won the race) -> 503 so OpenAI retries.",
                "If the job is already terminal -> mark the event processed, do not overwrite.",
                "If the event is completed: retrieve the full response from OpenAI, then save text and usage.",
                "If retrieve does not yet show completed -> release the claim and 503.",
                "Finalize with a Lua script: only the owner token can finish; never overwrite a terminal job.",
            ]
        )
    )
    out.append(p("Events this wrapper cares about", "h2"))
    out.append(
        make_table(
            ["OpenAI event", "Job status written"],
            [
                ["response.completed", "completed (after retrieve)"],
                ["response.failed", "failed"],
                ["response.cancelled", "cancelled"],
                ["response.incomplete", "incomplete"],
            ],
            [2.6 * inch, 3.9 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(p("Why 503 instead of 200 when something is temporarily wrong", "h2"))
    out.append(
        p(
            "A 200 tells OpenAI “I got it, stop sending.” If Redis was down or the job was not stored "
            "yet, that event is lost. A 503 tells OpenAI “try again.” That is how you keep delivery "
            "honest without a queue of your own."
        )
    )
    out.append(p("Owner tokens — why they exist", "h2"))
    out.append(
        p(
            "A worker claims an event as <font face='Courier'>processing:&lt;token&gt;</font>. If that "
            "worker dies, the claim expires and another worker can take over. Lua scripts check the "
            "token before release, mark-processed, or finalize. An expired worker cannot clobber a "
            "newer worker’s claim."
        )
    )
    out.append(
        warn_box(
            "Interview trap: “Why no worker process?” Because OpenAI performs the model work. A "
            "second worker would only duplicate what webhooks already do, and you would still need "
            "Redis for shared state."
        )
    )

    # ----- 10 -----
    out.append(p("10. Stage 6 — Errors, health, and fail-closed", "h1"))
    out.append(
        p(
            "File: <font face='Courier'>app/errors.py</font>. Every error looks the same. Messages "
            "never include keys, prompts, raw OpenAI exceptions, or authorization headers."
        )
    )
    out.append(Preformatted('{\n  "error": {\n    "code": "rate_limit_exceeded",\n    "message": "Request limit exceeded.",\n    "correlation_id": "request-123"\n  }\n}', S["mono"]))
    out.append(
        make_table(
            ["HTTP", "Code", "When"],
            [
                ["400", "invalid_request / unsupported_model / invalid_correlation_id", "JSON is valid but violates this contract, or the model is not allowed, or the correlation header is malformed."],
                ["401", "authentication_failed / invalid_webhook_signature", "Bad wrapper key, or forged / unsigned webhook."],
                ["404", "job_not_found (or not_found)", "Unknown or expired job, or a missing route."],
                ["409", "idempotency_key_reused / idempotency_in_progress", "Same key, different body; or the first request is still running."],
                ["413", "request_too_large", "Webhook body over 1 MiB."],
                ["422", "validation_error", "Field type, presence, or size is wrong. Also missing idempotency key."],
                ["429", "rate_limit_exceeded", "This wrapper’s Redis counter said stop. Includes Retry-After."],
                ["500", "internal_error", "Unexpected bug. Correlation middleware catches leftovers."],
                ["503", "upstream_unavailable", "Redis down, OpenAI down, OpenAI 429, connection error, or a webhook that must be retried."],
                ["504", "upstream_timeout", "OpenAI did not answer before OPENAI_TIMEOUT_SECONDS."],
            ],
            [0.7 * inch, 2.4 * inch, 3.4 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(p("Live vs ready", "h2"))
    out.append(p("File: <font face='Courier'>app/api/health.py</font>."))
    out.extend(
        bullets(
            [
                "<b>Live</b> = the process and HTTP server are up. It does not ping Redis or OpenAI. "
                "A platform should not kill the process just because Redis blinked.",
                "<b>Ready</b> = Redis answers <font face='Courier'>PING</font>. If not, stop sending "
                "this instance work. It can recover when Redis returns.",
                "Ready does <b>not</b> call OpenAI on every probe. That would be slow, billable, and "
                "a self-inflicted outage during a provider incident.",
            ]
        )
    )
    out.append(
        callout(
            "Interview line: “Live is 200 and ready is 503 means the process is up and Redis is not. "
            "Stop sending it traffic. Do not kill it yet.”"
        )
    )

    # ----- 11 -----
    out.append(p("11. Stage 7 — Redis as the shared brain", "h1"))
    out.append(
        p(
            "Redis is required. Rate-limit counters, idempotency records, job state, and processed "
            "webhook events must be shared by all API instances and must survive a process restart. "
            "In-memory state cannot do that."
        )
    )
    out.append(
        make_table(
            ["Key prefix", "Purpose", "Dies after"],
            [
                [
                    "wrapper:rate-limit:{window}",
                    "Request counter for the current fixed window",
                    "The window length",
                ],
                [
                    "wrapper:idempotency:{sha256(key)}",
                    "Claim + saved result for one client key",
                    "Default 24 hours",
                ],
                [
                    "wrapper:job:{job_id}",
                    "The job JSON the client polls",
                    "Remaining job TTL",
                ],
                [
                    "wrapper:openai-response-job:{sha256(id)}",
                    "OpenAI response id -> wrapper job id",
                    "Same remaining job TTL",
                ],
                [
                    "wrapper:webhook:event:{sha256(event_id)}",
                    "Dedup + owner-token claim for one webhook",
                    "Processing TTL while working; 3 days once processed",
                ],
            ],
            [2.4 * inch, 2.3 * inch, 1.8 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(p("Four Redis patterns you must be able to name", "h2"))
    out.append(
        make_table(
            ["Pattern", "Where", "Plain English"],
            [
                [
                    "SET NX EX",
                    "Idempotency claim, webhook event claim",
                    "Create this key only if it does not exist, and auto-delete later.",
                ],
                [
                    "Pipeline / transaction",
                    "Rate limit INCR+EXPIRE, job + reverse index",
                    "Two commands as one unit so a crash cannot leave half a write.",
                ],
                [
                    "Lua script",
                    "Webhook release / mark / finalize",
                    "Only delete or update if I still own this token. Never overwrite a terminal job.",
                ],
                [
                    "TTL",
                    "Every key",
                    "Nothing lives forever. An expired job is a 404.",
                ],
            ],
            [1.5 * inch, 2.3 * inch, 2.7 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(
        p(
            "Hashes appear on idempotency keys, OpenAI response ids, and webhook event ids so Redis "
            "keys stay a predictable length and do not contain raw caller input."
        )
    )

    # ----- 12 -----
    out.append(p("12. Stage 8 — Tests as a second teacher", "h1"))
    out.append(
        p(
            "You do not need to memorize tests. Use them as stories. "
            "<font face='Courier'>tests/conftest.py</font> fakes Redis and OpenAI. The suite is "
            "designed so CI never spends money and never needs a real OpenAI key."
        )
    )
    out.append(
        make_table(
            ["Test file", "Story it tells"],
            [
                ["test_authentication.py", "No key / bad key never reaches OpenAI."],
                ["test_config.py", "Bad environment refuses to boot. Secrets stay out of errors."],
                ["test_health.py / test_readiness.py", "Live is not ready. Ready pings Redis."],
                ["test_rate_limiting.py / test_rate_limit_service.py", "Shared Redis limit. Health and webhooks exempt. Atomic window."],
                ["test_responses.py", "Sync happy path, allowlist, validation, extra fields rejected."],
                ["test_retry.py / test_upstream_errors.py", "What is retried vs translated into wrapper errors."],
                ["test_idempotency.py / test_idempotency_service.py", "Replay, conflict, in-progress, failed claim released."],
                ["test_background_responses.py", "202, job created, OpenAI called with background=True."],
                ["test_job_status.py / test_jobs_service.py", "Poll codes, unknown job, reverse index."],
                ["test_webhooks.py / test_webhook_service.py", "Bad signature, duplicate, unknown event, owner token."],
                ["test_openai_lifecycle.py", "Client is created and closed with the app lifespan."],
            ],
            [2.4 * inch, 4.1 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(
        p(
            "Study method: pick one test name, predict the status code and whether OpenAI is called, "
            "then read the test. If your prediction is wrong, you found a gap."
        )
    )

    # ----- 13 -----
    out.append(p("13. Stage 9 — Built vs still on the old roadmap", "h1"))
    out.append(
        p(
            "Be honest in interviews. Claiming Docker and structured logging when they are not in "
            "the repo is worse than saying what you would add next."
        )
    )
    out.append(p("Built and worth talking about", "h2"))
    out.extend(
        bullets(
            [
                "Config that fails closed at boot",
                "Bearer auth and correlation IDs",
                "Redis clients, live, and ready",
                "Shared fixed-window rate limit",
                "Synchronous OpenAI Responses API with a small contract",
                "Bounded jittered retries and error translation",
                "Idempotency with Redis claims and replay",
                "Background jobs, status polling, signed webhooks",
                "Consistent error shape",
                "Automated tests with fakes, no live spend",
            ]
        )
    )
    out.append(p("Not finished as originally planned", "h2"))
    out.extend(
        bullets(
            [
                "Rich structured JSON logs with named events (today: a simple line in correlation middleware).",
                "Docker / Docker Compose for API + Redis.",
                "A full root README and a portfolio demo script.",
            ]
        )
    )
    out.append(
        callout(
            "If asked “what would you add next?” say: structured logs with event names and correlation "
            "IDs, Docker Compose for local Redis + API, and per-client keys instead of one shared "
            "wrapper key."
        )
    )

    # ----- 14 -----
    out.append(p("14. File map", "h1"))
    out.append(
        make_table(
            ["File", "Job in one line"],
            [
                ["app/main.py", "Start, stop, wire routes, register middleware and error handlers."],
                ["app/config.py", "Read env, validate, refuse unsafe boot."],
                ["app/errors.py", "One error shape. Special cases for model, idempotency, job 404."],
                ["app/api/responses.py", "Sync create, background create, job poll."],
                ["app/api/webhooks.py", "Verify OpenAI events and update jobs."],
                ["app/api/health.py", "Live vs ready."],
                ["app/middleware/correlation.py", "Name-tag every request."],
                ["app/middleware/authentication.py", "Require the internal bearer key."],
                ["app/middleware/rate_limiting.py", "Shared Redis limit, with exemptions."],
                ["app/services/idempotency.py", "Claim, store, replay, delete."],
                ["app/services/retry.py", "Bounded jittered retries of transient errors."],
                ["app/services/jobs.py", "Redis job records and OpenAI-id reverse index."],
                ["app/services/webhooks.py", "Event claim and Lua finalize."],
                ["app/services/rate_limit.py", "Fixed-window INCR + EXPIRE NX."],
                ["app/services/responses.py", "Shrink the provider payload."],
                ["app/schemas/responses.py", "The public create request and sync response."],
                ["app/schemas/jobs.py", "Job states and the public job body."],
                ["app/clients/*", "SDK construction only. Routes do not build clients."],
            ],
            [2.3 * inch, 4.2 * inch],
        )
    )
    out.append(Spacer(1, 10))

    # ----- 15 -----
    out.append(p("15. Whiteboard scripts", "h1"))
    out.append(
        p(
            "Practice these out loud. Time yourself. Two minutes each is enough if you stay concrete."
        )
    )

    scripts = [
        (
            "Walk me through a successful sync request.",
            "Correlation stamps an ID. Auth checks the bearer key. Rate limit increments Redis. "
            "Pydantic validates the small body. The model is allowlisted. Idempotency SET NX claims "
            "the key. OpenAI is called through retry_async. The result is normalized, stored, and "
            "returned as 200 with the correlation header.",
        ),
        (
            "A client timed out and sent the same request again.",
            "Same Idempotency-Key and same request hash. The record is completed, so we replay the "
            "stored result. OpenAI is not called. No second bill.",
        ),
        (
            "They reused the key with a different prompt.",
            "The hash does not match. 409 idempotency_key_reused. The key is a fingerprint of one "
            "request, not a blank “do anything” token.",
        ),
        (
            "Two requests with the same key arrive at the same time.",
            "Only one SET NX wins. The loser sees an in_progress record and gets 409 "
            "idempotency_in_progress. At most one OpenAI create happens.",
        ),
        (
            "Why is there no Celery or worker?",
            "OpenAI runs the long job when we send background=True. We persist a Redis job, return "
            "202, and later update that job from a verified webhook. A worker would duplicate that.",
        ),
        (
            "The webhook arrives before we saved the job.",
            "Reverse lookup misses. We release the event claim and return 503. OpenAI retries. We "
            "do not ack early, because 200 would drop the event.",
        ),
        (
            "Why verify the webhook before parsing?",
            "The signature covers the raw body and delivery headers. A forged request must not "
            "choose a job, trigger an OpenAI retrieve, or change shared Redis state.",
        ),
        (
            "Live is 200 but ready is 503. What is wrong?",
            "The process is up. Redis is not answering PING. Stop sending this instance work. Do "
            "not kill the process yet; it can recover.",
        ),
        (
            "Why translate OpenAI errors instead of forwarding them?",
            "Callers get a stable code and a correlation ID. We hide credentials, raw exceptions, "
            "and provider-shaped payloads that would couple every client to OpenAI’s error format.",
        ),
        (
            "What happens after 24 hours?",
            "Job and idempotency TTLs expire. Polling an old job is 404. A new request with the "
            "same idempotency key is treated as new work. That is a cost/privacy trade-off, not an accident.",
        ),
    ]
    for title, body in scripts:
        out.append(p(title, "h3"))
        out.append(p(body))

    # ----- 16 -----
    out.append(p("16. Five-day study plan", "h1"))
    out.append(
        p(
            "Each day: about 40 minutes reading the listed files, then 20 minutes speaking the story "
            "as if an interviewer is in the room. Do not skip the speaking part."
        )
    )
    out.append(
        make_table(
            ["Day", "Goal", "You are done when"],
            [
                [
                    "1",
                    "Story + six endpoints + boot + middleware",
                    "You can draw the architecture from memory, including middleware order.",
                ],
                [
                    "2",
                    "Sync path + idempotency + retries",
                    "You can whiteboard Stage 4 without opening the file.",
                ],
                [
                    "3",
                    "Background + poll + webhooks",
                    "You can explain owner tokens, reverse lookup, and why 503 exists.",
                ],
                [
                    "4",
                    "Redis keys + error table + live/ready",
                    "You can list every Redis prefix and every status code.",
                ],
                [
                    "5",
                    "Tests + Q&A + “what I would add”",
                    "You can answer the questions in section 17 cold, and you do not oversell unfinished work.",
                ],
            ],
            [0.6 * inch, 2.4 * inch, 3.5 * inch],
        )
    )
    out.append(Spacer(1, 10))
    out.append(
        p(
            "If you only have one evening, do Day 2 and Day 3. Those two stories win the interview."
        )
    )

    # ----- 17 -----
    out.append(p("17. Interview questions and answers", "h1"))
    out.append(
        p(
            "These answers match the decisions in this repo. Learn them in your own words, not as a script."
        )
    )

    qa = [
        (
            "Why put a wrapper in front of OpenAI?",
            "To keep the OpenAI key in one place, give internal apps a small stable contract, and "
            "centralize auth, rate limits, retries, idempotency, and logs.",
        ),
        (
            "Why should a frontend never receive the OpenAI API key?",
            "Anything shipped to a browser or a mobile app can be extracted. A leaked key is an "
            "open bill. The frontend talks to your backend; only this service talks to OpenAI.",
        ),
        (
            "Why expose only a limited set of fields?",
            "A limited contract is easier to validate, document, test, and evolve. You add a field "
            "when there is a real internal use case instead of coupling every client to every "
            "upstream option.",
        ),
        (
            "Why reject unknown request fields?",
            "So callers cannot silently depend on behavior you have not documented or tested. Typos "
            "fail at the boundary instead of being ignored.",
        ),
        (
            "Why enforce a model allowlist?",
            "Cost, capability, and policy. Callers may only use configured models. The default "
            "must itself be on the list or the process will not start.",
        ),
        (
            "Why normalize provider responses?",
            "The provider object is large and can change. Returning a stable shape keeps clients "
            "decoupled and gives you one place to control what is exposed.",
        ),
        (
            "Why is Redis required?",
            "Rate-limit counters, idempotency records, job state, and processed webhook events must "
            "be shared across instances and survive a restart.",
        ),
        (
            "Why not an in-memory rate-limit counter?",
            "Each worker would see a different count. A restart would wipe history. Two instances "
            "would allow twice the traffic.",
        ),
        (
            "Why are health routes exempt from rate limiting?",
            "Probes must stay observable during traffic spikes. They should not consume the "
            "business request budget.",
        ),
        (
            "How should a caller handle 429?",
            "Read Retry-After, wait at least that long, then retry with backoff. Do not tight-loop.",
        ),
        (
            "What is idempotency?",
            "Doing the same intended action more than once has the same effect as doing it once. "
            "Here: the same key plus the same body returns the original result instead of creating "
            "another billable OpenAI request.",
        ),
        (
            "How does Redis idempotency prevent duplicate billing?",
            "Hash the validated request. SET NX an in_progress record before calling OpenAI. Only "
            "the claimant may create work. Later requests replay, conflict, or see in-progress.",
        ),
        (
            "What happens when the provider call fails?",
            "The in-progress record is deleted after the final failure so a later retry can claim "
            "the key. A permanent lock would punish the client for OpenAI being down.",
        ),
        (
            "What is the difference between retries and idempotency?",
            "Retries are the server trying OpenAI again after a blip. Idempotency is the client "
            "sending the same request again. You need both.",
        ),
        (
            "Which failures should be retried?",
            "Transient ones: connection errors, timeouts, provider 5xx, and provider 429 when a "
            "retry hint exists. Not auth, not validation, not unsupported models.",
        ),
        (
            "Why should authentication errors not be retried?",
            "They will fail the same way. Retrying only adds latency and can look like an attack.",
        ),
        (
            "What is exponential backoff? Why jitter?",
            "Each retry waits longer (0.1s, 0.2s, …). Jitter adds a small random amount so many "
            "instances do not retry in lockstep after an outage.",
        ),
        (
            "What is a correlation ID? How is it different from an idempotency key?",
            "A correlation ID traces one request across logs, errors, and jobs. An idempotency key "
            "prevents duplicate work. The first is for debugging. The second is for correctness and cost.",
        ),
        (
            "Do correlation IDs authorize a request?",
            "No. Bearer auth proves the caller has the internal key. A correlation ID only names the request.",
        ),
        (
            "What is background mode?",
            "The wrapper asks OpenAI to run the response asynchronously, returns 202 and a job id "
            "immediately, and later updates that job from a webhook.",
        ),
        (
            "Why use webhooks instead of polling OpenAI forever?",
            "Polling OpenAI from every status request would add load, latency, and cost. Redis is "
            "the source of truth for the client. Webhooks update Redis when OpenAI is done.",
        ),
        (
            "Why can webhook events be duplicated?",
            "Networks retry. OpenAI will resend if it is not sure you got the event. Dedup by event "
            "id in Redis makes that harmless.",
        ),
        (
            "How should out-of-order events be handled?",
            "Never overwrite a terminal job. The finalize Lua script writes the new status only if "
            "the job is not already completed, failed, cancelled, incomplete, or expired.",
        ),
        (
            "Why keep processed webhook event IDs?",
            "So a second delivery of the same event is a no-op across workers. The processed mark "
            "lasts three days, long enough to cover provider retries.",
        ),
        (
            "Why return an error instead of acknowledging a temporary webhook failure?",
            "Success means “stop sending.” A 503 preserves OpenAI’s retry mechanism.",
        ),
        (
            "Why store a wrapper job instead of returning only the OpenAI response id?",
            "The wrapper job keeps provider identifiers mostly internal and gives clients a stable "
            "status URL, expiry, correlation ID, and controlled state model.",
        ),
        (
            "Why isolate the OpenAI SDK behind a client adapter?",
            "Routes should own the wrapper contract, not SDK types. One place to construct the "
            "client, one place to fake it in tests.",
        ),
        (
            "Why avoid logging prompts and outputs by default?",
            "They can contain customer data. Correlation IDs plus event names are enough to debug "
            "most production issues.",
        ),
        (
            "How do mocked tests differ from live smoke tests?",
            "The default suite fakes OpenAI and Redis behavior and must stay free. A live smoke "
            "test would use a real key, cost money, and should never run automatically.",
        ),
        (
            "What would need to change for multiple internal clients?",
            "Per-client wrapper keys, per-client rate limits, and probably per-client allowlists "
            "and audit fields. Today there is one shared WRAPPER_API_KEY.",
        ),
        (
            "What would need to change for multi-region?",
            "Redis would need to be regional or replicated with a clear consistency story. "
            "Idempotency and webhook claims only work if all instances share the same keyspace.",
        ),
    ]
    for i, (q, a) in enumerate(qa, start=1):
        out.append(p(f"{i}. {q}", "h3"))
        out.append(p(a))

    # ----- 18 -----
    out.append(p("18. Words you must not mix up", "h1"))
    out.append(
        make_table(
            ["Word", "Means", "Does not mean"],
            [
                [
                    "Wrapper",
                    "Your internal service in front of OpenAI",
                    "A generic HTTP proxy that forwards everything",
                ],
                [
                    "Correlation ID",
                    "A name tag for tracing one request",
                    "A password or a permission",
                ],
                [
                    "Idempotency key",
                    "A client key that makes a retry return the original result",
                    "A request id you generate for logs",
                ],
                [
                    "Retry",
                    "This service calling OpenAI again after a transient failure",
                    "The client sending the request again",
                ],
                [
                    "Rate limit",
                    "This wrapper’s Redis counter for the internal app",
                    "OpenAI’s own rate limit (that becomes 503 here)",
                ],
                [
                    "Live",
                    "The process is running",
                    "The process can do useful work",
                ],
                [
                    "Ready",
                    "Required dependencies (Redis) answer",
                    "OpenAI is healthy right now",
                ],
                [
                    "TTL",
                    "Redis will delete the key after this many seconds",
                    "The client’s poll interval",
                ],
                [
                    "Background response",
                    "OpenAI finishes after the HTTP request returns 202",
                    "A local worker queue inside this repo",
                ],
                [
                    "Webhook",
                    "OpenAI calling you with a signed event",
                    "You polling OpenAI",
                ],
                [
                    "Fail closed",
                    "If Redis is down, refuse the request (503)",
                    "Skip the check and let traffic through",
                ],
                [
                    "Normalize",
                    "Return only the fields your contract promises",
                    "Return the raw OpenAI object",
                ],
            ],
            [1.4 * inch, 2.7 * inch, 2.4 * inch],
        )
    )
    out.append(Spacer(1, 14))
    out.append(p("Last page checklist", "h2"))
    out.extend(
        bullets(
            [
                "I can draw the architecture and name the six endpoints.",
                "I can say the middleware order and why it is that order.",
                "I can whiteboard a sync request including idempotency states.",
                "I can explain background create, poll codes, and webhook verify-then-claim.",
                "I can list the Redis key prefixes.",
                "I can map common failures to HTTP codes without looking.",
                "I can say what is not built yet without sounding defensive.",
            ]
        )
    )
    out.append(
        callout(
            "If you can do those seven things, you understand this project end to end. The files "
            "are only there to prove the story, not to replace it."
        )
    )
    return out


def main():
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.5 * inch,
        title="Production API Wrapper — Interview Study Guide",
        author="prod-api-wrapper",
        subject="Plain-English end-to-end understanding guide for interview preparation",
    )
    # Cover has no header; remaining pages do.
    def first_page(canvas, doc_):
        cover_page(canvas, doc_)

    def later(canvas, doc_):
        header_footer(canvas, doc_)

    # Cover is drawn on page 1 via onFirstPage; story starts on page 2.
    content = [Spacer(1, 7.4 * inch), PageBreak(), *story()]
    doc.build(content, onFirstPage=first_page, onLaterPages=later)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
