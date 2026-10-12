"""Problem 10: put the manager's reflection into the Reflection tab of output/desk_tickets.html.

Only the Reflection section and its CSS change; every other tab is left byte-for-byte as it was.
No agents run and the database isn't touched.

Run from this folder:  .venv/Scripts/python insert_reflection.py
"""

import json
import re
from pathlib import Path

from reflection_html import CSS, render, visible_text

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "output"
page = OUT / "desk_tickets.html"
md = (HERE / "report_assets" / "reflection.md").read_text(encoding="utf-8")
bulldogs = json.loads((HERE / "report_assets" / "bulldogs.json").read_text(encoding="utf-8"))
SLUG = {"Boss": "boss", "Inventory": "inventory", "Accounting": "accounting", "Facilities": "facilities",
        "Customer Service": "cs"}


def dog(name: str, size: int = 40) -> str:  # same markup as build_reports.dog (uses the page's <symbol> defs)
    return (f'<span class="av" style="width:{size}px;height:{size}px" title="{name}">'
            f'<svg class="dog" viewBox="0 0 120 120" role="img" aria-label="{name} bulldog"><use href="#dog-{SLUG[name]}"/></svg></span>')


html_text = page.read_text(encoding="utf-8")
pattern = re.compile(r'<section class="panel-tab" id="panel-reflection".*?</section>', re.S)
assert len(pattern.findall(html_text)) == 1, "expected exactly one Reflection section"
before_other = pattern.sub("", html_text).replace(CSS, "")

section = render(md, dog)
new = pattern.sub(lambda _: section, html_text)
if CSS not in new:
    new = new.replace("</style>", CSS + "</style>", 1)

# ---- checks ----
after_other = pattern.sub("", new).replace(CSS, "")
assert after_other == before_other, "something outside the Reflection tab changed"
text = visible_text(section)
missing = []
for ln in md.splitlines():
    ln = ln.strip()
    if not ln:
        continue
    ln = re.sub(r"^\d\. ", "", ln)  # section/list numbers are shown as badges
    if " ".join(ln.split()) not in text:
        missing.append(ln[:80])
assert not missing, f"text not found verbatim: {missing}"

page.write_text(new, encoding="utf-8")
lines = len([ln for ln in md.splitlines() if ln.strip()])
print(f"Reflection inserted: {lines} lines of the manager's text, all found verbatim; other tabs unchanged.")
