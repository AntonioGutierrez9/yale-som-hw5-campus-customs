"""Render the manager's reflection (report_assets/reflection.md) as the Reflection tab of desk_tickets.html.

The text is the human's own writing: it's escaped and laid out, never rewritten.
Structure of the source file:
- line 1: title
- "N. Heading" at the start of a line: a section
- "Ticket 10x – Subtitle": a ticket sub-card (section 1)
- "   N. Lead: text" (indented): a numbered item (sections 4 and 5)
- any other line: a paragraph
"""

from __future__ import annotations

import html
import re

E = html.escape
AGENTS = ["Boss", "Inventory", "Accounting", "Facilities", "Customer Service"]
SECTION = re.compile(r"^(\d)\. (.+)$")
ITEM = re.compile(r"^\s+(\d)\. (.+)$")
TICKET_HEAD = re.compile(r"^Ticket (10\d) – (.+)$")
TICKET_LEAD = re.compile(r"^(Ticket 10\d:)\s(.+)$")

CSS = """
.refl-hero { background:linear-gradient(135deg,#00356b,#0b4c8c); color:#fff; border-radius:16px; padding:22px 24px; display:grid; gap:6px; box-shadow:var(--shadow) }
.refl-hero h2 { font-family:Georgia,'Times New Roman',serif; font-size:28px; color:#fff } .refl-hero p { color:#d6e4f7; font-size:14px }
.refl-nav { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px }
.refl-nav button { appearance:none; border:1px solid rgba(255,255,255,.35); background:rgba(255,255,255,.08); color:#fff; font:inherit; font-size:13px; font-weight:650; padding:5px 11px; border-radius:999px; cursor:pointer }
.refl-nav button:hover { background:rgba(255,255,255,.2) } .refl-nav button:focus-visible { outline:3px solid #63aaff; outline-offset:2px }
.refl-sec { scroll-margin-top:130px } .refl-sec > .panel { gap:14px }
.refl-head { display:flex; align-items:center; gap:12px } .refl-head h3 { font-size:19px; letter-spacing:0; text-transform:none; color:var(--ink) }
.refl-num { width:34px; height:34px; border-radius:50%; background:var(--yale); color:#fff; display:grid; place-items:center; font-weight:800; flex:none }
.refl p { font-size:15px; line-height:1.65; max-width:78ch } .refl-body { display:grid; gap:10px }
.refl-tickets { display:grid; grid-template-columns:repeat(3,1fr); gap:14px } @media (max-width:1000px) { .refl-tickets { grid-template-columns:1fr } }
.refl-ticket { border:1px solid var(--line); border-top:4px solid var(--yale-2); border-radius:12px; padding:14px; display:grid; gap:10px; align-content:start; background:#fbfcfe }
.refl-ticket h4 { font-size:16px; display:flex; gap:8px; align-items:center; flex-wrap:wrap } .refl-ticket p { font-size:14.5px }
.refl-compare { display:grid; gap:10px } .refl-compare .row { border-left:4px solid var(--yale-2); background:#f7f9fc; border-radius:10px; padding:10px 14px }
.refl-items { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:repeat(3,1fr); gap:14px } @media (max-width:1000px) { .refl-items { grid-template-columns:1fr } }
.refl-items li { border:1px solid var(--line); border-radius:12px; padding:14px; display:grid; gap:8px; align-content:start; background:#fff; border-top:4px solid var(--good) }
.refl-items.cannot li { border-top-color:var(--warn) } .refl-items .n { width:26px; height:26px; border-radius:50%; display:grid; place-items:center; font-weight:800; font-size:13px; background:var(--good-bg); color:var(--good) }
.refl-items.cannot .n { background:var(--warn-bg); color:var(--warn) } .refl-items .lead { font-weight:750; color:var(--ink) } .refl-items p { font-size:14.5px }
.refl-final { border-left:5px solid var(--yale); background:linear-gradient(180deg,#fff,#f6f9fd) }
.refl-tag { font-size:12px; font-weight:700; color:var(--muted) }
"""


def _agents_in(text: str, dog) -> str:
    found = [a for a in AGENTS if re.search(rf"\b{re.escape(a)}\b", text)]
    if not found:
        return ""
    return '<div class="chips"><span class="refl-tag">Agents involved:</span>' + "".join(
        f'<span class="agent" style="--c:var(--yale)">{dog(a, 20)}{E(a)}</span>' for a in found) + "</div>"


def render(md: str, dog) -> str:
    lines = [ln.rstrip() for ln in md.splitlines() if ln.strip()]
    title, body = lines[0], lines[1:]
    sections: list[dict] = []
    for ln in body:
        m = SECTION.match(ln)
        if m:
            sections.append({"n": m.group(1), "title": m.group(2), "lines": []})
        else:
            sections[-1]["lines"].append(ln)

    out = []
    for s in sections:
        n, lines_ = s["n"], s["lines"]
        if n == "1":  # per-ticket evaluation cards
            cards, cur = [], None
            for ln in lines_:
                m = TICKET_HEAD.match(ln)
                if m:
                    cur = {"id": m.group(1), "sub": m.group(2), "paras": []}
                    cards.append(cur)
                else:
                    cur["paras"].append(ln)
            inner = '<div class="refl-tickets">' + "".join(
                f'<article class="refl-ticket"><h4>Ticket {c["id"]} – {E(c["sub"])}</h4>'
                + "".join(f"<p>{E(p)}</p>" for p in c["paras"]) + "</article>" for c in cards) + "</div>"
        elif n == "2":  # ticket-by-ticket comparison, then general observations
            rows, paras = [], []
            for ln in lines_:
                m = TICKET_LEAD.match(ln)
                (rows if m else paras).append(
                    f'<div class="row"><p><b>{E(m.group(1))}</b> {E(m.group(2))}</p></div>' if m else f"<p>{E(ln)}</p>")
            inner = '<div class="refl-compare">' + "".join(rows) + "</div>" + "".join(paras)
        elif n in ("4", "5"):
            items = []
            for ln in lines_:
                m = ITEM.match(ln)
                if not m:
                    items.append(f"<li><p>{E(ln.strip())}</p></li>")
                    continue
                lead, _, rest = m.group(2).partition(": ")
                agents = _agents_in(rest, dog) if n == "4" else ""
                items.append(f'<li><span class="n">{m.group(1)}</span><p><span class="lead">{E(lead)}:</span> {E(rest)}</p>{agents}</li>')
            inner = f'<ol class="refl-items {"cannot" if n == "5" else ""}">' + "".join(items) + "</ol>"
        else:
            inner = "".join(f"<p>{E(ln)}</p>" for ln in lines_)
        extra = " refl-final" if n == "6" else ""
        out.append(f"""
  <div class="refl-sec" id="refl-{n}"><div class="panel refl{extra}">
    <div class="refl-head"><span class="refl-num">{n}</span><h3>{E(s['title'])}</h3></div>
    <div class="refl-body">{inner}</div></div></div>""")

    nav = "".join(f'<button type="button" data-refl="refl-{s["n"]}">{s["n"]}. {E(s["title"])}</button>' for s in sections)
    return f"""<section class="panel-tab" id="panel-reflection" role="tabpanel" aria-label="Reflection" hidden>
  <div class="refl-hero"><h2>{E(title)}</h2>
    <p>Written by the human manager after the final full run. Reproduced exactly as written.</p>
    <nav class="refl-nav" aria-label="Reflection sections">{nav}</nav></div>
  {''.join(out)}
  <script>
  document.querySelectorAll('[data-refl]').forEach(function (b) {{
    b.addEventListener('click', function () {{ document.getElementById(b.dataset.refl).scrollIntoView({{ block: 'start' }}); }});
  }});
  </script>
</section>"""


def visible_text(section_html: str) -> str:
    """Plain text of the rendered section (for checking nothing was changed)."""
    t = re.sub(r"<script.*?</script>", " ", section_html, flags=re.S)
    t = re.sub(r"<nav.*?</nav>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(html.unescape(t).split())
