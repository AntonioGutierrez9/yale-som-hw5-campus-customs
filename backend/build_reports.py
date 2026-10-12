"""Build the Problem 9 reports from the REAL run data. Nothing here is invented.

Data sources
- The running FastAPI backend (http://127.0.0.1:8000): tickets, runs, activity, approvals, cash.
- output/audit_trail.json: every agent step since the last reset (the final full run).
- data/campus_customs_new.db, read-only: independent cross-checks (payments, cash, statuses).
- output/archive/desk_tickets_problem6.html: the Expected plans, copied word for word.
- output/screenshots/dashboard_ticket_*.png: real screenshots of the React dashboard.

Outputs
- output/resolved_tickets.json
- output/desk_tickets.html   (Expected vs Actual, Cash reconciliation; standalone)
- output/resolved_board.html (embedded dashboard screenshots; standalone)
- output/final_verification.json

Run from this folder with the API running:  .venv/Scripts/python build_reports.py
"""

from __future__ import annotations

import base64
import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
API = "http://127.0.0.1:8000"
TICKETS = (101, 102, 103)
PROBLEM9_FIRST_RESET = "2026-10-12T02:39:15+00:00"  # first reset after Problem 9 started
AGENTS = ["Boss", "Inventory", "Accounting", "Facilities", "Customer Service"]
COLOR = {"Boss": "#00356B", "Inventory": "#C2410C", "Accounting": "#0F766E", "Facilities": "#A16207",
         "Customer Service": "#7C3AED", "System": "#475569", "Human": "#475569"}
SLUG = {"Boss": "boss", "Inventory": "inventory", "Accounting": "accounting", "Facilities": "facilities",
        "Customer Service": "cs"}
E = html.escape


def get(path: str, **params):
    r = httpx.get(API + path, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def money(x: float) -> str:
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def local(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone().strftime("%b %d, %I:%M:%S %p").replace(" 0", " ")


# ======================================================================================
# 1. Collect the real data
# ======================================================================================

start = json.loads((OUT / "full_run_start.json").read_text(encoding="utf-8"))
audit = json.loads((OUT / "audit_trail.json").read_text(encoding="utf-8"))
reset_idx = start["reset_audit_index"]
final_events = audit[reset_idx:]
starting_cash = next(a["balance"] for a in start["starting_cash"] if a["name"] == "checking")

limits = get("/api/limits")
cash = get("/api/cash")
approvals = get("/api/approvals")["requests"]
board = {t["id"]: t for t in get("/api/tickets")["tickets"]}
details = {t: get(f"/api/tickets/{t}") for t in TICKETS}
runs = {t: list(reversed(get("/api/runs", ticket_id=t, limit=20)["runs"])) for t in TICKETS}  # oldest first
activity = {t: get("/api/activity", ticket_id=t, since_reset="true", limit=1000)["events"] for t in TICKETS}

db = sqlite3.connect(f"{(ROOT / 'data' / 'campus_customs_new.db').as_uri()}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
q = lambda sql, *a: [dict(r) for r in db.execute(sql, a)]  # noqa: E731
db_payments = q("SELECT * FROM payments ORDER BY id")
db_cash = q("SELECT balance FROM cash_accounts WHERE name = 'checking'")[0]["balance"]
db_requests = q("SELECT * FROM approval_requests ORDER BY id")
db_tickets = {r["id"]: r["status"] for r in q("SELECT id, status FROM tickets")}
db_drafts = q("SELECT * FROM customer_drafts ORDER BY id")

bulldogs = json.loads((Path(__file__).resolve().parent / "report_assets" / "bulldogs.json").read_text(encoding="utf-8"))
font_b64 = base64.b64encode((ROOT / "frontend/node_modules/@fontsource-variable/inter/files/"
                             "inter-latin-wght-normal.woff2").read_bytes()).decode()

# ======================================================================================
# 2. The Expected plans (Problem 6), copied verbatim
# ======================================================================================

p6 = (OUT / "archive" / "desk_tickets_problem6.html").read_text(encoding="utf-8")


def p6_panel(pid: str) -> str:
    return re.search(rf'<section class="panel" id="panel-{pid}".*?</section>', p6, re.S).group(0)


def plan(t: int) -> dict:
    s = p6_panel(str(t))
    title = re.search(r"<h2>(.*?)</h2>", s).group(1)
    situation = re.search(r"<h3>Situation</h3>\s*(<p>.*?</p>)", s, re.S).group(1)
    first = re.search(r'<h3>First contact</h3>\s*(<div class="route">.*?</div>)\s*(<p>.*?</p>)', s, re.S)
    steps = re.search(r'<ol class="steps">.*?</ol>', s, re.S).group(0)
    outcome = re.search(r'<div class="outcome">.*?</div>', s, re.S).group(0)
    tools = sorted(set(re.findall(r'<code class="tool">(\w+)</code>', steps)))
    edges, report_backs = set(), set()
    for route in re.findall(r'<div class="route">(.*?)</div>', steps, re.S):
        toks = re.findall(r'<span class="agent \w+">([^<]+)</span>|<span class="(arrow|slash)">', route)
        groups, cur, arrow_seen = [], [], False
        for name, sep in toks:
            if name:
                cur.append(name)
            elif sep == "arrow":
                groups.append(cur)
                cur, arrow_seen = [], True
        groups.append(cur)
        if arrow_seen and len(groups) == 2:
            for a in groups[0]:
                for b in groups[1]:
                    (report_backs if b == "Boss" and a != "Boss" else edges).add((a, b))
    return {"title": title, "situation": situation, "first_route": first.group(1), "first_text": first.group(2),
            "steps": steps, "outcome": outcome, "tools": tools, "edges": sorted(edges), "report_backs": sorted(report_backs)}


PLANS = {t: plan(t) for t in TICKETS}

# ======================================================================================
# 3. What actually happened (from the logs) + my reading of the differences
# ======================================================================================


def full_run(t: int) -> dict:
    """The Boss-led run of the final full run (first run on the ticket after the reset)."""
    return next(r for r in runs[t] if r["lead_agent"] == "Boss")


def delegations(t: int, run_id: str) -> list[dict]:
    out = []
    for e in activity[t]:
        if e["run_id"] == run_id and e["event"] == "delegate":
            out.append({"time": e["time"], "from": e["agent"], "to": e.get("to_agent"),
                        "task": e.get("args", ""), "refused": str(e.get("result", "")).startswith("REFUSED")})
    return out


def limit_stops(t: int, run_id: str) -> list[dict]:
    return [{"time": e["time"], "agent": e["agent"], "detail": e.get("result", "")}
            for e in activity[t] if e["run_id"] == run_id and e["event"] == "limit_stop"]


# Written from the audit trail and ticket notes of the final run (see the run ids in each tab).
ANALYSIS = {
    101: {
        "differences": [
            "Order of work: the plan had Boss → Inventory first and then Inventory → Accounting. In the run, the Boss sent "
            "Inventory and Accounting their tasks at the same moment (both delegations at 11:51:56 PM), so Accounting "
            "started before Inventory reported.",
            "Accounting filed the invoice payment request itself (request #1, $840, at 11:52:01 PM) instead of only "
            "recommending it to the Boss. It stayed pending until the human approved it.",
            "Inventory and Accounting also asked each other for input (Accounting → Inventory and Inventory → Accounting). "
            "A third call into each of them was stopped by the 5-steps-per-agent limit before any model call was made, "
            "so the limit held (Inventory 5/5, Accounting 5/5).",
            "Inventory used get_ticket and plan_restock rather than list_inventory and list_vendors (Accounting ran "
            "list_vendors). get_ticket already bundles the stock for the ticket's SKU.",
            "No purchase order: Inventory recommended a 4-tee restock ($32) but Bulldog Print Co was blocked by unpaid "
            "invoice 501 during the run. Inventory has no request_purchase_order tool (kept that way on purpose to show "
            "this difference) and Accounting didn't file one while the vendor was blocked.",
            "The Boss's report back from Accounting/Inventory came as their returned reports, not as new delegations.",
        ],
        "outcome": ("Human approved request #1, so invoice 501 is paid ($840) and Bulldog Print Co can ship again. "
                    "Status is Approved (a human decision status), not Resolved."),
        "unresolved": [
            "Tauhid's size S tee is still out of stock (0). The 4-tee restock order was never requested, because the "
            "vendor was still blocked during the run and no further run was made after the invoice was paid.",
            "Customer reply draft #1 was written before the approval, so it says the decision is with the owners.",
        ],
    },
    102: {
        "differences": [
            "Order of work: the plan had Boss → Facilities → Accounting. In the run, the Boss delegated to Facilities and "
            "Accounting at the same moment (11:53:41 PM); Facilities only checked the lease (get_lease, 2 steps) and did "
            "not delegate to Accounting.",
            "Accounting used get_financial_status instead of list_invoices; it shows open invoices and cash in one call. "
            "Because ticket 101 ran first and its invoice was already paid, Accounting saw $2,560 in checking and $0 "
            "pending (not $3,400 and the $840 invoice the plan expected), so paying rent would leave $160, not $1,000.",
            "Accounting filed the rent request (#2, $2,400) exactly as planned; it waited for the human.",
            "Extra step not in the plan: the Boss also asked Customer Service for a reply to the landlord (draft #2), "
            "following the every-ticket-gets-a-reply rule added during Problem 9.",
        ],
        "outcome": ("Human approved request #2: rent paid ($2,400) and the lease's next due date moved to 2026-10-02. "
                    "Status is Approved, not Resolved."),
        "unresolved": [
            "Nothing operational is left (rent is paid), but no agent ran afterwards to mark the ticket Resolved.",
            "Reply draft #2 was written before the approval, so it says the payment is pending the owners' decision.",
        ],
    },
    103: {
        "differences": [
            "The plan's Boss → Inventory and Inventory → Accounting both happened; the Boss also delegated to Accounting "
            "directly at the same moment (11:55:08 PM).",
            "Inventory used get_ticket, list_vendors and plan_restock (no list_inventory); Accounting used quote_bulk_order "
            "four times (0%, 10%, 15%, 20%) plus get_financial_status, but not list_invoices.",
            "The Boss recorded a 15% discount with record_discount_decision. With the discount-approval workflow added in "
            "Problem 9, this created approval #3 in the human inbox instead of being final on its own.",
            "No purchase order: the 12-hoodie restock costs $264 but only $160 was left after rent, so Inventory and "
            "Accounting reported it unaffordable ($104 short). The plan said to request one only if feasible.",
            "The Boss used all 5 of its steps and never called update_ticket_status, so the ticket stayed Open until the "
            "human's approval synced it to Approved.",
        ],
        "outcome": ("Human approved discount #3 (15%: $49.30 per hoodie, $986 for 20, margin 55.4%; no cash moved). "
                    "Status is Approved, not Resolved."),
        "unresolved": [
            "Only 8 of the 20 size-M hoodies are in stock; the 12-unit restock ($264) is unfunded with $160 in checking.",
            "Reply draft #3 was written before the approval, so it says the discount is pending the owners' decision.",
        ],
    },
}

# ======================================================================================
# 4. Per-ticket records
# ======================================================================================

records = []
for t in TICKETS:
    r = full_run(t)
    det = details[t]
    reqs = [a for a in approvals if a["ticket_id"] == t]
    dels = delegations(t, r["run_id"])
    tools_used = sorted({tool for a in r["agents"] for tool in a["tool_calls"]})
    actual_edges = sorted({(d["from"], d["to"]) for d in dels if not d["refused"] and d["from"] in AGENTS})
    pl = PLANS[t]
    extra_runs = [x for x in runs[t] if x["run_id"] != r["run_id"]]
    records.append({
        "ticket_id": t,
        "subject": board[t]["subject"],
        "requester": board[t]["requester"],
        "final_status": db_tickets[t],
        "resolved": db_tickets[t] == "resolved",
        "outcome": ANALYSIS[t]["outcome"],
        "boss_final_answer": r["outcome"],
        "unresolved": ANALYSIS[t]["unresolved"],
        "run": {k: r[k] for k in ("run_id", "status", "started_at", "ended_at", "stop_reason", "model_steps",
                                  "delegations", "refused_delegations", "repeats_blocked", "limit_stops",
                                  "input_tokens", "output_tokens")},
        "other_runs_since_reset": [{k: x[k] for k in ("run_id", "lead_agent", "status", "model_steps",
                                                      "input_tokens", "output_tokens")} for x in extra_runs],
        "agents": [{
            "agent": a["agent"], "model_steps": a["model_steps"], "delegated_from": a["delegated_from"],
            "delegated_to": a["delegated_to"], "mcp_tools": a["tool_calls"], "contribution": (a["said"] or [""])[-1],
            "input_tokens": a["input_tokens"], "output_tokens": a["output_tokens"],
        } for a in r["agents"]],
        "delegations": [{k: d[k] for k in ("time", "from", "to", "refused")} | {"task": d["task"][:300]} for d in dels],
        "mcp_tools_used": tools_used,
        "expected_vs_actual": {
            "planned_tools_not_used": sorted(set(pl["tools"]) - set(tools_used)),
            "tools_used_not_in_plan": sorted(set(tools_used) - set(pl["tools"])),
            "planned_delegations_not_seen": [f"{a} -> {b}" for a, b in pl["edges"] if (a, b) not in actual_edges],
            "delegations_not_in_plan": [f"{a} -> {b}" for a, b in actual_edges if (a, b) not in pl["edges"]],
            "planned_report_backs": [f"{a} -> {b} (comes back as the delegate's returned report)" for a, b in pl["report_backs"]],
            "key_differences": ANALYSIS[t]["differences"],
        },
        "human_approvals": [{
            "request_id": a["id"], "kind": a["kind"], "purpose": a.get("purpose"), "amount": a["amount"],
            "discount_pct": a.get("discount_pct"), "requested_by": a["requested_by"], "requested_at": a["requested_at"],
            "decision": a["status"], "decided_by": a["decided_by"], "decided_at": a["decided_at"],
            "cash_effect": (0.0 if a["kind"] == "discount" else -a["amount"]) if a["status"] == "paid" else 0.0,
        } for a in reqs],
        "customer_reply_drafts": [{k: d[k] for k in ("id", "recipient", "subject", "body", "written_by", "created_at", "status")}
                                  for d in det["drafts"]],
    })

# ======================================================================================
# 5. Cash reconciliation (payments table = the only cash movements)
# ======================================================================================

by_payment = {a["payment_id"]: a for a in db_requests if a["payment_id"]}
ledger, bal = [], starting_cash
for p in db_payments:
    req = by_payment.get(p["id"])
    if p["kind"] == "reversal":
        orig = next(x for x in db_payments if x["id"] == p["ref_id"])
        desc, ticket = f"Reversal of payment #{p['ref_id']} ({orig['kind']})", None
    else:
        desc = req["purpose"] if req and req.get("purpose") else f"{p['kind']} payment"
        ticket = req["ticket_id"] if req else None
        req_full = next((a for a in approvals if req and a["id"] == req["id"]), None)
        desc = (req_full or {}).get("purpose") or desc
    bal = round(bal - p["amount"], 2)
    ledger.append({"payment_id": p["id"], "kind": p["kind"], "ticket_id": ticket, "description": desc,
                   "amount": p["amount"], "paid_at_shop_date": p["paid_at"], "approved_by": p["approved_by"],
                   "approval_request": req["id"] if req else None, "approved_at": req["decided_at"] if req else None,
                   "balance_after": bal})
total_out = round(sum(p["amount"] for p in db_payments), 2)
ending = round(starting_cash - total_out, 2)
non_cash = [a for a in approvals if a["kind"] == "discount"]
pending = [a for a in approvals if a["status"] == "pending"]
rejected = [a for a in approvals if a["status"] == "rejected"]
reconciles = ending == db_cash == cash["balance"]

# ======================================================================================
# 6. Tokens, model calls, limits
# ======================================================================================

final_runs = [full_run(t) for t in TICKETS]
other_runs = [x for t in TICKETS for x in runs[t] if x["run_id"] != full_run(t)["run_id"]]
final_totals = {"model_calls": sum(r["model_steps"] for r in final_runs),
                "input_tokens": sum(r["input_tokens"] for r in final_runs),
                "output_tokens": sum(r["output_tokens"] for r in final_runs)}
all_since_reset = {"model_calls": sum(r["model_steps"] for t in TICKETS for r in runs[t]),
                   "input_tokens": sum(r["input_tokens"] for t in TICKETS for r in runs[t]),
                   "output_tokens": sum(r["output_tokens"] for t in TICKETS for r in runs[t])}
p9_responses = [e for e in audit if e.get("event") == "model_response" and e.get("mode") == "run"
                and e["time"] >= PROBLEM9_FIRST_RESET]
p9_totals = {"model_calls": len(p9_responses),
             "input_tokens": sum(e.get("input_tokens") or 0 for e in p9_responses),
             "output_tokens": sum(e.get("output_tokens") or 0 for e in p9_responses),
             "runs": len({e["run_id"] for e in p9_responses})}
max_out = max((e.get("output_tokens") or 0) for e in final_events if e.get("event") == "model_response")
max_depth = max((e.get("depth") or 0) for e in final_events if e.get("agent") in AGENTS)
limit_checks = []
for r in final_runs:
    worst = max(a["model_steps"] for a in r["agents"])
    limit_checks.append({"run_id": r["run_id"], "ticket_id": r["ticket_id"],
                         "team_steps": f"{r['model_steps']}/{limits['max_steps_per_ticket']}",
                         "max_agent_steps": f"{worst}/{limits['max_steps_per_agent']}",
                         "ok": r["model_steps"] <= limits["max_steps_per_ticket"] and worst <= limits["max_steps_per_agent"]})

# ======================================================================================
# 7. Verification
# ======================================================================================

checks = []


def check(name: str, ok: bool, detail=""):
    checks.append({"check": name, "passed": bool(ok), "detail": detail})


for t in TICKETS:
    check(f"ticket {t} status from the API matches the database", board[t]["status"] == db_tickets[t],
          {"api": board[t]["status"], "db": db_tickets[t]})
    check(f"ticket {t} is NOT reported as resolved unless the database says so",
          next(r for r in records if r["ticket_id"] == t)["resolved"] == (db_tickets[t] == "resolved"), db_tickets[t])
    check(f"ticket {t} has a Customer Service reply draft", any(d["ticket_id"] == t for d in db_drafts),
          [d["id"] for d in db_drafts if d["ticket_id"] == t])
for p in db_payments:
    req = by_payment.get(p["id"]) if p["kind"] != "reversal" else None
    human = p["approved_by"] and p["approved_by"].lower() not in {a.lower() for a in AGENTS}
    check(f"payment #{p['id']} was approved by a human through an approval request",
          bool(human) and (p["kind"] == "reversal" or (req is not None and req["status"] == "paid" and req["decided_by"] == p["approved_by"])),
          {"approved_by": p["approved_by"], "request": req and req["id"]})
check("starting cash − payments = ending cash = cash_accounts (DB) = /api/cash", reconciles,
      {"start": starting_cash, "out": total_out, "computed_end": ending, "db": db_cash, "api": cash["balance"]})
check("no pending or rejected request was counted as a payment",
      all(by_payment.get(p["id"], {}).get("status", "paid") == "paid" for p in db_payments if p["kind"] != "reversal"), "")
check("discount approvals moved no cash", all(a["payment_id"] is None for a in db_requests if a["kind"] == "discount"), "")
for lc in limit_checks:
    check(f"run {lc['run_id']} (ticket {lc['ticket_id']}) stayed within step limits", lc["ok"], lc)
check(f"delegation depth stayed within {limits['max_delegation_depth']}", max_depth <= limits["max_delegation_depth"], max_depth)
check(f"every model call stayed within {limits['max_output_tokens_per_call']} output tokens",
      max_out <= limits["max_output_tokens_per_call"], max_out)
check("only gpt-6-luna was used (model field of every run_start in the final run)",
      {e.get("model") for e in final_events if e.get("event") == "run_start"} <= {"gpt-6-luna"},
      sorted({e.get("model") for e in final_events if e.get("event") == "run_start"}))
for t in TICKETS:
    check(f"Actual section for {t} is built from the audit trail run {full_run(t)['run_id']}",
          any(e["run_id"] == full_run(t)["run_id"] for e in final_events), full_run(t)["run_id"])
shots = {t: OUT / "screenshots" / f"dashboard_ticket_{t}.png" for t in TICKETS}
for t, pth in shots.items():
    check(f"dashboard screenshot for ticket {t} exists and is a PNG",
          pth.exists() and pth.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", str(pth.relative_to(ROOT)))

# ======================================================================================
# 8. HTML helpers
# ======================================================================================

SYMBOLS = "".join(
    re.sub(r'^<svg class="dog" viewBox="0 0 120 120" role="img" aria-label="[^"]*">', f'<symbol id="dog-{SLUG[n]}" viewBox="0 0 120 120">', s)
    .replace("</svg>", "</symbol>")
    for n, s in bulldogs.items()
)


def dog(name: str, size: int = 40) -> str:
    if name in SLUG:
        return (f'<span class="av" style="width:{size}px;height:{size}px" title="{E(name)}">'
                f'<svg class="dog" viewBox="0 0 120 120" role="img" aria-label="{E(name)} bulldog"><use href="#dog-{SLUG[name]}"/></svg></span>')
    return f'<span class="av av-sys" style="width:{size}px;height:{size}px" title="{E(name)}">⚙</span>'


def chip(name: str) -> str:
    return f'<span class="agent" style="--c:{COLOR.get(name, "#475569")}">{dog(name, 20)}{E(name)}</span>'


CSS = """
@font-face { font-family: 'Inter Variable'; src: url(data:font/woff2;base64,%FONT%) format('woff2'); font-weight: 100 900; }
:root { --yale:#00356b; --yale-2:#286dc0; --yale-3:#63aaff; --ink:#0b1f3a; --bg:#f2f5f9; --panel:#fff; --line:#e1e7ef; --line-2:#cfd8e3;
  --text:#13233a; --muted:#5a6a80; --good:#15803d; --good-bg:#dcfce7; --warn:#b45309; --warn-bg:#fef3c7; --bad:#b91c1c; --bad-bg:#fee2e2;
  --deleg-bg:#dbeafe; --radius:14px; --shadow:0 1px 2px rgba(11,31,58,.06),0 6px 18px rgba(11,31,58,.06);
  font-family:'Inter Variable','Segoe UI',system-ui,sans-serif; color:var(--text); background:var(--bg); line-height:1.5; }
* { box-sizing:border-box } body { margin:0 } h1,h2,h3,h4 { margin:0; line-height:1.25 } p { margin:0 }
code,.mono { font-family:'Cascadia Code',Consolas,Menlo,monospace } .muted { color:var(--muted) } .small { font-size:13px }
.topbar { background:var(--yale); color:#fff; position:sticky; top:0; z-index:5; box-shadow:0 2px 12px rgba(0,20,50,.25) }
.topbar-inner { max-width:1360px; margin:0 auto; padding:12px 20px; display:flex; gap:18px; align-items:center; flex-wrap:wrap }
.brand { display:flex; gap:12px; align-items:center; margin-right:auto } .brand svg { width:40px; height:40px }
.brand strong { display:block; font-family:Georgia,serif; font-size:22px } .brand small { display:block; font-size:12px; letter-spacing:.14em; text-transform:uppercase; color:#b9d3f5 }
.tabs { max-width:1360px; margin:0 auto; padding:0 20px 8px; display:flex; gap:4px; flex-wrap:wrap }
.tab { appearance:none; border:0; background:transparent; color:#d6e4f7; font:inherit; font-weight:650; font-size:14px; padding:7px 14px; border-radius:9px; cursor:pointer }
.tab:hover { background:rgba(255,255,255,.12); color:#fff } .tab[aria-selected=true] { background:#fff; color:var(--yale) }
.tab:focus-visible { outline:3px solid var(--yale-3); outline-offset:2px }
main { max-width:1360px; margin:0 auto; padding:20px; display:grid; gap:18px } section.panel-tab[hidden] { display:none }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow); padding:16px 18px; display:grid; gap:12px; align-content:start }
.panel h3 { font-size:13px; letter-spacing:.09em; text-transform:uppercase; color:var(--muted); display:flex; gap:8px; align-items:center }
.head { display:flex; align-items:center; gap:10px; flex-wrap:wrap } .head h2 { font-size:24px; color:var(--ink) }
.tid { font-weight:800; color:var(--yale); font-size:15px; background:#eef4ff; padding:3px 10px; border-radius:8px }
.status { display:inline-block; font-size:12px; font-weight:700; padding:2px 9px; border-radius:999px; background:#e2e8f0; color:#334155 }
.status-approved,.status-resolved { background:var(--good-bg); color:var(--good) } .status-rejected { background:var(--bad-bg); color:var(--bad) }
.status-waiting_on_approval { background:var(--warn-bg); color:var(--warn) }
.badge { display:inline-block; font-size:11px; font-weight:700; padding:1px 7px; border-radius:6px; text-transform:uppercase; letter-spacing:.03em }
.b-good { background:var(--good-bg); color:var(--good) } .b-warn { background:var(--warn-bg); color:var(--warn) } .b-bad { background:var(--bad-bg); color:var(--bad) } .b-deleg { background:var(--deleg-bg); color:var(--yale) } .b-muted { background:#f1f5f9; color:#64748b }
.chips { display:flex; flex-wrap:wrap; gap:6px } .meta { font-size:13px; color:var(--muted); background:#fff; border:1px solid var(--line); padding:2px 10px; border-radius:999px } .meta b { color:var(--text) }
code.tool { font-size:12px; background:#eef4ff; color:#0b3b75; border:1px solid #d3e3fb; padding:0 6px; border-radius:6px; white-space:nowrap }
.av { display:inline-grid; place-items:center; border-radius:50%; background:#eef3fa; border:1px solid var(--line); flex:none; overflow:visible; vertical-align:middle }
.av .dog { width:112%; height:112%; margin-top:-6% } .av-sys { background:#e2e8f0; color:#475569; font-size:12px }
.agent { --c:#475569; display:inline-flex; align-items:center; gap:5px; padding:1px 9px 1px 2px; border-radius:999px; font-weight:650; font-size:13px; color:var(--c);
  border:1px solid color-mix(in srgb,var(--c) 40%,transparent); background:color-mix(in srgb,var(--c) 10%,#fff); white-space:nowrap }
.agent.boss{--c:#00356B}.agent.inventory{--c:#C2410C}.agent.accounting{--c:#0F766E}.agent.facilities{--c:#A16207}.agent.cs{--c:#7C3AED}
.arrow { color:var(--muted); font-weight:800; margin:0 2px } .slash { color:var(--muted) }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; align-items:start } .grid3 { display:grid; grid-template-columns:repeat(3,1fr); gap:14px }
@media (max-width:1000px) { .grid2,.grid3 { grid-template-columns:1fr } }
.col-label { font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; padding:3px 10px; border-radius:6px }
.col-exp { color:var(--good); background:rgba(21,128,61,.1) } .col-act { color:var(--yale); background:var(--deleg-bg) }
ol.steps { list-style:none; margin:0; padding:0; counter-reset:step } ol.steps li { position:relative; padding:0 0 14px 44px; counter-increment:step }
ol.steps li::before { content:counter(step); position:absolute; left:0; top:0; width:30px; height:30px; border-radius:50%; display:grid; place-items:center; font-weight:700; font-size:13px; background:#eef2f7; border:1px solid var(--line-2) }
ol.steps li::after { content:''; position:absolute; left:15px; top:32px; bottom:2px; width:2px; background:var(--line) } ol.steps li:last-child::after { display:none }
.route { display:flex; align-items:center; flex-wrap:wrap; gap:4px; margin:2px 0 6px } .step-text { font-size:14px }
.outcome { margin-top:6px; padding:12px 14px; border-radius:12px; background:rgba(21,128,61,.06); border:1px solid rgba(21,128,61,.25) } .outcome strong { color:var(--good) }
.final { border-left:4px solid var(--good); background:#f6fbf8; border-radius:12px; padding:12px 14px; display:grid; gap:6px }
.final.unres { border-left-color:var(--warn); background:#fffaf0 }
.contrib { border:1px solid var(--line); border-top:4px solid var(--c); border-radius:12px; padding:12px; display:grid; gap:8px; background:#fff }
.contrib header { display:flex; gap:10px; align-items:center } .contrib h4 { font-size:15px } .quote { font-style:italic; color:#1e293b; font-size:13.5px }
.deleg { display:grid; grid-template-columns:auto 1fr; gap:4px 10px; padding:8px 10px; border:1px solid var(--line); border-radius:10px; background:#fbfcfe }
.deleg .who { display:flex; align-items:center; gap:4px; flex-wrap:wrap } .deleg p { grid-column:1/-1; font-size:13px; color:var(--muted) }
.appr { border:1px solid var(--line); border-left:4px solid var(--good); border-radius:12px; padding:12px 14px; display:grid; gap:6px; background:linear-gradient(180deg,#fff,#fbfcfe) }
.appr .amt { font-size:24px; font-weight:800; color:var(--ink) } .appr.disc { border-left-color:#7c3aed }
.draft { border:1px solid var(--line); border-radius:12px; padding:12px 14px; background:#fbfcfe; display:grid; gap:6px }
.draft pre { white-space:pre-wrap; font-family:inherit; font-size:14px; margin:0; background:#fff; border:1px solid var(--line); border-radius:8px; padding:10px 12px }
.diff li { margin-bottom:6px; font-size:14px } .diff ul { margin:6px 0 0; padding-left:18px }
.tl { list-style:none; margin:0; padding:0 } .tl li { display:grid; grid-template-columns:auto auto 1fr; gap:8px; align-items:start; padding:6px 0; border-bottom:1px dashed var(--line); font-size:13px }
.tl time { color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap }
details > summary { cursor:pointer; font-weight:650 }
.tiles { display:grid; grid-template-columns:repeat(4,1fr); gap:14px } @media (max-width:900px) { .tiles { grid-template-columns:1fr 1fr } }
.tile { background:#fff; border:1px solid var(--line); border-radius:14px; padding:14px 16px; box-shadow:var(--shadow) } .tile span { font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted) }
.tile strong { display:block; font-size:28px; font-weight:800; color:var(--ink); font-variant-numeric:tabular-nums } .tile.navy { background:var(--yale); color:#fff } .tile.navy span { color:#b9d3f5 } .tile.navy strong { color:#fff }
table { width:100%; border-collapse:collapse; font-size:14px } th,td { text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); vertical-align:top }
th { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); background:#f7f9fc } td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }
tr.total td { font-weight:800; background:#f4f7fb } .ok { color:var(--good); font-weight:800 } .neg { color:var(--bad) }
.later { text-align:center; padding:60px 20px } .later .badge { font-size:13px; padding:5px 12px; margin-bottom:10px }
.foot { max-width:1360px; margin:0 auto; padding:0 20px 28px; font-size:12.5px; color:var(--muted) }
.shot { border:1px solid var(--line-2); border-radius:12px; width:100%; height:auto; display:block; box-shadow:var(--shadow) }
@media print { .topbar { position:static } section.panel-tab[hidden] { display:block } }
@media (max-width:600px) { main { padding:12px; grid-template-columns:minmax(0,1fr) } .panel-tab, .panel { min-width:0 } .tiles { grid-template-columns:1fr } .tile strong { font-size:22px } .panel table { display:block; overflow-x:auto; white-space:nowrap } .tiles { grid-template-columns:minmax(0,1fr) } .tile { min-width:0; overflow-wrap:anywhere } .panel h3 { flex-wrap:wrap } .panel h3, .panel p { overflow-wrap:anywhere; min-width:0 } }
""".replace("%FONT%", font_b64)

TAB_JS = """
<script>
(function(){var tabs=[].slice.call(document.querySelectorAll('[role=tab]'));var ids=tabs.map(function(t){return t.dataset.tab});
function show(id,f){if(ids.indexOf(id)<0)id=ids[0];tabs.forEach(function(t){var on=t.dataset.tab===id;t.setAttribute('aria-selected',on);t.tabIndex=on?0:-1;
document.getElementById('panel-'+t.dataset.tab).hidden=!on;if(on&&f)t.focus()});if(location.hash!=='#'+id)history.replaceState(null,'','#'+id)}
tabs.forEach(function(t,i){t.addEventListener('click',function(){show(t.dataset.tab)});t.addEventListener('keydown',function(e){var n=null;
if(e.key==='ArrowRight')n=(i+1)%tabs.length;if(e.key==='ArrowLeft')n=(i-1+tabs.length)%tabs.length;if(n!==null){e.preventDefault();show(tabs[n].dataset.tab,true)}})});
window.addEventListener('hashchange',function(){show(location.hash.slice(1))});show(location.hash.slice(1));})();
</script>"""

BRAND_Y = ('<svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#fff"/>'
           '<path d="M5 6h9v2.4h-2l5 7.4 5-7.4h-2V6h8v2.4h-1.8L19 17.6V24h2.5v2.5H10.5V24H13v-6.4L6.8 8.4H5z" fill="#00356B"/></svg>')
STATUS_LABEL = {"approved": "Approved", "rejected": "Rejected", "partially_approved": "Partly approved",
                "waiting_on_approval": "Pending approval", "resolved": "Resolved", "open": "Open", "in_progress": "In progress"}


def page(title: str, subtitle: str, tabs: list[tuple[str, str]], panels: str, foot: str) -> str:
    tab_html = "".join(f'<button class="tab" role="tab" data-tab="{i}" aria-controls="panel-{i}">{E(lbl)}</button>' for i, lbl in tabs)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title><style>{CSS}</style></head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>{SYMBOLS}</defs></svg>
<header class="topbar"><div class="topbar-inner"><div class="brand">{BRAND_Y}<span><strong>Campus Customs</strong><small>{E(subtitle)}</small></span></div>
<div class="tile navy" style="padding:6px 14px;box-shadow:none;border-color:rgba(255,255,255,.2)"><span>Checking balance (DB)</span><strong style="font-size:24px">{money(db_cash)}</strong></div></div>
<nav class="tabs" role="tablist" aria-label="Sections">{tab_html}</nav></header>
<main>{panels}</main>
<footer class="foot">{foot}</footer>{TAB_JS}</body></html>"""


# ======================================================================================
# 9. desk_tickets.html
# ======================================================================================

def recolor_plan(html_snippet: str) -> str:
    """Give the Problem 6 agent badges the same bulldogs/colors as the dashboard (text unchanged)."""
    def sub(m):
        cls, name = m.group(1), m.group(2)
        return f'<span class="agent {cls}">{dog(name, 20)}{name}</span>'
    return re.sub(r'<span class="agent (\w+)">([^<]+)</span>', sub, html_snippet)


def ticket_panel(rec: dict) -> str:
    t = rec["ticket_id"]
    pl, an, run = PLANS[t], ANALYSIS[t], rec["run"]
    dels = rec["delegations"]
    stops = limit_stops(t, run["run_id"])
    ex = rec["expected_vs_actual"]
    contribs = "".join(f"""
      <article class="contrib" style="--c:{COLOR[a['agent']]}">
        <header>{dog(a['agent'], 52)}<div><h4>{E(a['agent'])}</h4>
          <p class="muted small">{a['model_steps']}/{limits['max_steps_per_agent']} steps ·
          {'asked by ' + E(', '.join(dict.fromkeys(a['delegated_from']))) if a['delegated_from'] else 'led the run'}
          {(' · delegated to ' + E(', '.join(a['delegated_to']))) if a['delegated_to'] else ''}</p></div></header>
        <p class="quote">“{E(a['contribution'])}”</p>
        <div class="chips">{''.join(f'<code class="tool">{E(k)}{" ×" + str(v) if v > 1 else ""}</code>' for k, v in a['mcp_tools'].items()) or '<span class="muted small">no MCP tools</span>'}</div>
      </article>""" for a in rec["agents"])
    deleg_html = "".join(f"""
      <div class="deleg"><span class="badge {'b-bad' if d['refused'] else 'b-deleg'}">{'refused' if d['refused'] else 'delegate'}</span>
        <div class="who">{chip(d['from'])}<span class="arrow">→</span>{chip(d['to'])}<span class="muted small" style="margin-left:auto">{E(local(d['time']))}</span></div>
        <p>{E(d['task'][:260])}{'…' if len(d['task']) > 260 else ''}</p></div>""" for d in dels)
    stop_html = "".join(f'<li><b>{E(s["agent"])}</b>: {E(s["detail"])} <span class="muted">(stopped before a model call; {E(local(s["time"]))})</span></li>' for s in stops)
    appr_html = "".join(f"""
      <div class="appr {'disc' if a['kind'] == 'discount' else ''}">
        <div class="head"><span class="badge b-muted">{E(a['kind'].replace('_', ' '))}</span><b>#{a['request_id']}</b>
          <span class="badge {'b-good' if a['decision'] in ('paid', 'approved') else 'b-bad' if a['decision'] == 'rejected' else 'b-warn'}">{E(a['decision'])}</span></div>
        <div class="amt">{(str(int(a['discount_pct'])) + '% off · −' + money(a['amount'])) if a['kind'] == 'discount' else money(a['amount'])}</div>
        <p>{E(a['purpose'] or '')}</p>
        <p class="small muted">Requested by {E(a['requested_by'])} (agent) · {E(local(a['requested_at']))}<br>
        Human decision: <b>{E(a['decision'])}</b> by <b>{E(a['decided_by'] or '—')}</b>{' · ' + E(local(a['decided_at'])) if a['decided_at'] else ''}<br>
        Cash effect: <b>{money(a['cash_effect']) if a['cash_effect'] else '$0.00 (no cash moved)'}</b></p></div>""" for a in rec["human_approvals"]) or '<p class="muted">No approval requests.</p>'
    drafts_html = "".join(f"""
      <div class="draft"><div class="head"><span class="badge b-muted">Draft #{d['id']} · never sent</span>
        <span class="small muted">to <b>{E(d['recipient'])}</b> · by {E(d['written_by'])} · {E(local(d['created_at']))}</span></div>
        <h4>{E(d['subject'])}</h4><pre>{E(d['body'])}</pre></div>""" for d in rec["customer_reply_drafts"])
    timeline = [e for e in activity[t] if e["run_id"] == run["run_id"] and e["event"] in
                ("run_start", "delegate", "tool_call", "final_answer", "limit_stop", "run_end") and not (e["event"] in ("run_start", "run_end") and e["depth"] > 0)]
    human_tl = [e for e in activity[t] if e["agent"] == "Human"]
    tl_html = "".join(f'<li><time>{E(local(e["time"]))}</time>{dog(e["agent"], 22)}<span>{E(e["text"][:240])}</span></li>'
                      for e in sorted(timeline + human_tl, key=lambda x: x["time"]))
    other = "".join(f'<li>{E(o["run_id"])} led by {E(o["lead_agent"])} ({E(o["status"])}, {o["model_steps"]} steps)</li>' for o in rec["other_runs_since_reset"])
    return f"""
<section class="panel-tab" id="panel-{t}" role="tabpanel" aria-label="Ticket {t}" hidden>
  <div class="panel">
    <div class="head"><span class="tid">TICKET {t}</span><h2>{pl['title']}</h2>
      <span class="status status-{E(rec['final_status'])}">{E(STATUS_LABEL.get(rec['final_status'], rec['final_status']))}</span>
      <span class="badge {'b-good' if rec['resolved'] else 'b-warn'}">{'resolved' if rec['resolved'] else 'not resolved'}</span></div>
    <div class="chips"><span class="meta">Requester <b>{E(rec['requester'])}</b></span><span class="meta">Run <b class="mono">{E(run['run_id'])}</b></span>
      <span class="meta">Started <b>{E(local(run['started_at']))}</b></span>
      <span class="meta">Steps <b>{run['model_steps']}/{limits['max_steps_per_ticket']}</b></span>
      <span class="meta">Delegations <b>{run['delegations']}</b></span><span class="meta">Repeat calls blocked <b>{run['repeats_blocked']}</b></span>
      <span class="meta">Tokens <b>{run['input_tokens']:,} in / {run['output_tokens']:,} out</b></span><span class="meta">Model <b>{E(limits['model'])}</b></span></div>
  </div>

  <div class="grid2">
    <div class="panel"><h3>Situation <span class="muted" style="text-transform:none;letter-spacing:0">(Problem 6)</span></h3>{pl['situation']}
      <h3>First contact</h3>{recolor_plan(pl['first_route'])}{pl['first_text']}</div>
    <div class="panel"><h3>Final status &amp; outcome</h3>
      <div class="final {'unres' if not rec['resolved'] else ''}"><p><b>{E(STATUS_LABEL.get(rec['final_status'], rec['final_status']))}</b> — {E(rec['outcome'])}</p>
        <p class="small"><b>Boss's final answer:</b> <span class="quote">“{E(rec['boss_final_answer'] or '')}”</span></p></div>
      <div><b class="small">Still unresolved</b><ul class="small">{''.join(f'<li>{E(u)}</li>' for u in rec['unresolved'])}</ul></div>
    </div>
  </div>

  <div class="grid2">
    <div class="panel"><h3><span class="col-label col-exp">Expected</span> Delegations (Problem 6 plan, unchanged)</h3>
      {recolor_plan(pl['steps'])}{pl['outcome']}
      <div class="chips"><span class="muted small">Planned MCP tools:</span>{''.join(f'<code class="tool">{E(x)}</code>' for x in pl['tools'])}</div>
    </div>
    <div class="panel"><h3><span class="col-label col-act">Actual</span> From the audit trail</h3>
      <b class="small">Delegations, in order</b>{deleg_html or '<p class="muted">No delegations.</p>'}
      {'<b class="small">Execution-limit stops</b><ul class="small">' + stop_html + '</ul>' if stop_html else '<p class="small muted">No execution-limit stops.</p>'}
      <b class="small">Approval requests &amp; human decisions</b>{appr_html}
      <b class="small">Customer reply</b>{drafts_html or '<p class="muted">No draft.</p>'}
      <div class="chips"><span class="muted small">MCP tools used:</span>{''.join(f'<code class="tool">{E(x)}</code>' for x in rec['mcp_tools_used'])}</div>
    </div>
  </div>

  <div class="panel"><h3>What each agent contributed</h3><div class="grid3" style="grid-template-columns:repeat(auto-fill,minmax(280px,1fr))">{contribs}</div></div>

  <div class="panel diff"><h3>Differences between Expected and Actual</h3>
    <ul>{''.join(f'<li>{E(x)}</li>' for x in ex['key_differences'])}</ul>
    <div class="grid2">
      <div><b class="small">MCP tools</b><ul class="small">
        <li>Planned but not used: {', '.join(f'<code class="tool">{E(x)}</code>' for x in ex['planned_tools_not_used']) or 'none'}</li>
        <li>Used but not in the plan: {', '.join(f'<code class="tool">{E(x)}</code>' for x in ex['tools_used_not_in_plan']) or 'none'}</li></ul></div>
      <div><b class="small">Delegations</b><ul class="small">
        <li>Planned but not seen: {E(', '.join(ex['planned_delegations_not_seen']) or 'none')}</li>
        <li>Happened but not planned: {E(', '.join(ex['delegations_not_in_plan']) or 'none')}</li>
        <li>Planned report-backs: {E('; '.join(ex['planned_report_backs']) or 'none')}</li></ul></div>
    </div>
  </div>

  <div class="panel"><details><summary>Timeline of the run and the human's actions ({len(timeline) + len(human_tl)} events)</summary>
    <ol class="tl">{tl_html}</ol>
    {('<p class="small muted" style="margin-top:8px">Other runs on this ticket since the reset: <ul class="small">' + other + '</ul></p>') if other else ''}</details></div>
</section>"""


def cash_panel() -> str:
    rows = "".join(f"""<tr><td>{i + 1}</td><td>{E(local(next(a['decided_at'] for a in approvals if a['id'] == l['approval_request'])) if l['approval_request'] else l['paid_at_shop_date'])}</td>
      <td>{('#' + str(l['ticket_id'])) if l['ticket_id'] else '—'}</td><td>{E(l['description'])}<br><span class="small muted">payment #{l['payment_id']} · {E(l['kind'])} · shop date {E(l['paid_at_shop_date'])}</span></td>
      <td>request #{l['approval_request']}<br><span class="small">approved by <b>{E(l['approved_by'])}</b> (human)</span></td>
      <td class="num neg">−{money(l['amount'])}</td><td class="num">{money(l['balance_after'])}</td></tr>""" for i, l in enumerate(ledger))
    per_ticket = "".join(f"<tr><td>#{t}</td><td>{E(board[t]['subject'])}</td><td class='num'>{money(-sum(l['amount'] for l in ledger if l['ticket_id'] == t)) if any(l['ticket_id'] == t for l in ledger) else '$0.00'}</td>"
                         f"<td>{E('; '.join((a['purpose'] or '') + ' (' + a['status'] + ')' for a in approvals if a['ticket_id'] == t))}</td></tr>" for t in TICKETS)
    return f"""
<section class="panel-tab" id="panel-cash" role="tabpanel" aria-label="Cash" hidden>
  <div class="tiles">
    <div class="tile"><span>Starting balance (after reset)</span><strong>{money(starting_cash)}</strong><span class="small" style="text-transform:none;letter-spacing:0">reset {E(local(start['reset_event_time']))}</span></div>
    <div class="tile"><span>Cash out (executed payments)</span><strong class="neg">−{money(total_out)}</strong><span class="small" style="text-transform:none;letter-spacing:0">{len(db_payments)} payments, all human-approved</span></div>
    <div class="tile navy"><span>Ending balance</span><strong>{money(ending)}</strong></div>
    <div class="tile"><span>Matches cash_accounts?</span><strong class="{'ok' if reconciles else 'neg'}">{'Yes ✓' if reconciles else 'NO ✗'}</strong><span class="small" style="text-transform:none;letter-spacing:0">DB {money(db_cash)} · API {money(cash['balance'])}</span></div>
  </div>
  <div class="panel"><h3>Reconciliation · {money(starting_cash)} − {money(total_out)} = {money(ending)} <span class="{'ok' if reconciles else 'neg'}">{'✓ equals checking in campus_customs_new.db' if reconciles else '✗ does not match'}</span></h3>
    <table><thead><tr><th>#</th><th>Approved at</th><th>Ticket</th><th>Payment / purchase</th><th>Human approval</th><th class="num">Amount</th><th class="num">Checking after</th></tr></thead>
    <tbody><tr><td>—</td><td>{E(local(start['reset_event_time']))}</td><td>—</td><td>Starting checking balance right after the reset (cash_accounts)</td><td>—</td><td class="num">—</td><td class="num">{money(starting_cash)}</td></tr>
    {rows}
    <tr class="total"><td></td><td></td><td></td><td>Ending checking balance</td><td></td><td class="num neg">−{money(total_out)}</td><td class="num">{money(ending)}</td></tr></tbody></table>
    <p class="small muted">Only rows in the <code>payments</code> table move cash. Each one was executed by the human-only approval tool after a person approved it.</p>
  </div>
  <div class="grid2">
    <div class="panel"><h3>Cash movement by ticket</h3>
      <table><thead><tr><th>Ticket</th><th>Subject</th><th class="num">Cash</th><th>Requests (status)</th></tr></thead><tbody>{per_ticket}</tbody></table></div>
    <div class="panel"><h3>Not counted as cash</h3><ul class="small">
      <li><b>Discount approvals:</b> {E('; '.join(f"#{a['id']} {a['purpose']} — {a['status']} (affects what the customer pays, no cash moved)" for a in non_cash)) or 'none'}</li>
      <li><b>Pending requests:</b> {E(', '.join(f"#{a['id']}" for a in pending)) or 'none'}</li>
      <li><b>Rejected requests:</b> {E(', '.join(f"#{a['id']}" for a in rejected)) or 'none'}</li>
      <li><b>Reversals (undone payments):</b> {len([p for p in db_payments if p['kind'] == 'reversal'])}</li>
      <li><b>Revenue:</b> none modeled in this homework, so cash only goes out.</li></ul></div>
  </div>
</section>"""


# Problem 10: the manager's own reflection (report_assets/reflection.md), reproduced exactly.
from reflection_html import CSS as REFLECTION_CSS, render as render_reflection  # noqa: E402
later = render_reflection((Path(__file__).resolve().parent / "report_assets" / "reflection.md").read_text(encoding="utf-8"), dog)
CSS += REFLECTION_CSS

desk = page(
    "Campus Customs · Desk Tickets (Expected vs Actual)", "Desk tickets · Expected vs Actual",
    [("101", "Ticket 101"), ("102", "Ticket 102"), ("103", "Ticket 103"), ("cash", "Cash"), ("reflection", "Reflection")],
    "".join(ticket_panel(r) for r in records) + cash_panel() + later,
    f"Built {E(datetime.now().astimezone().strftime('%b %d %Y, %I:%M %p'))} from the real run data: audit trail entries since the reset at "
    f"{E(local(start['reset_event_time']))} (runs {', '.join(r['run']['run_id'] for r in records)}), the API, and read-only checks of "
    "data/campus_customs_new.db. Expected sections are copied unchanged from the Problem 6 page (output/archive/desk_tickets_problem6.html).",
)
(OUT / "desk_tickets.html").write_text(desk, encoding="utf-8")

# ======================================================================================
# 10. resolved_board.html (real screenshots, embedded)
# ======================================================================================

def board_panel(rec: dict) -> str:
    t = rec["ticket_id"]
    shot = shots[t]
    b64 = base64.b64encode(shot.read_bytes()).decode()
    taken = datetime.fromtimestamp(shot.stat().st_mtime).astimezone().strftime("%b %d, %I:%M %p")
    return f"""
<section class="panel-tab" id="panel-{t}" role="tabpanel" aria-label="Ticket {t}" hidden>
  <div class="panel"><div class="head"><span class="tid">TICKET {t}</span><h2>{E(board[t]['subject'])}</h2>
    <span class="status status-{E(rec['final_status'])}">{E(STATUS_LABEL.get(rec['final_status'], rec['final_status']))}</span>
    <span class="badge {'b-good' if rec['resolved'] else 'b-warn'}">{'resolved' if rec['resolved'] else 'not resolved'}</span></div>
    <div class="final unres"><p><b>Actual final state:</b> {E(rec['outcome'])}</p>
      <p class="small"><b>Why it isn't shown as resolved:</b></p><ul class="small">{''.join(f'<li>{E(u)}</li>' for u in rec['unresolved'])}</ul></div>
  </div>
  <div class="panel"><h3>Real screenshot of the React dashboard · ticket {t} selected</h3>
    <img class="shot" alt="Screenshot of the Campus Customs React dashboard with ticket {t} selected, showing its final state" src="data:image/png;base64,{b64}">
    <p class="small muted">Captured {E(taken)} from the running frontend (http://localhost:5175/?ticket={t}) with headless Microsoft Edge at 1440 px wide. Not edited or recreated.</p>
  </div>
</section>"""


summary_rows = "".join(
    f"<tr><td>#{r['ticket_id']}</td><td>{E(r['subject'])}</td><td><span class='status status-{E(r['final_status'])}'>{E(STATUS_LABEL.get(r['final_status'], r['final_status']))}</span></td>"
    f"<td>{'yes' if r['resolved'] else 'no'}</td><td>{E('; '.join(f'#{a['request_id']} {a['kind']} {a['decision']} by {a['decided_by']}' for a in r['human_approvals']))}</td>"
    f"<td class='num'>{money(sum(a['cash_effect'] for a in r['human_approvals']))}</td></tr>" for r in records)
overview = f"""
<section class="panel-tab" id="panel-overview" role="tabpanel" aria-label="Overview" hidden>
  <div class="tiles">
    <div class="tile"><span>Starting cash</span><strong>{money(starting_cash)}</strong></div>
    <div class="tile"><span>Cash spent</span><strong class="neg">−{money(total_out)}</strong></div>
    <div class="tile navy"><span>Ending cash</span><strong>{money(ending)}</strong></div>
    <div class="tile"><span>Human decisions</span><strong>{len([a for a in approvals if a['status'] != 'pending'])}</strong></div>
  </div>
  <div class="panel"><h3>Final state of the board</h3>
    <table><thead><tr><th>Ticket</th><th>Subject</th><th>Status</th><th>Resolved?</th><th>Human approvals</th><th class="num">Cash</th></tr></thead><tbody>{summary_rows}</tbody></table>
    <p class="small muted">No ticket was marked Resolved by the agents. "Approved" is set only from human approval decisions. See each ticket's tab for the real dashboard screenshot and what remains open.</p></div>
</section>"""
board_html = page(
    "Campus Customs · Resolved Board", "Resolved board · final state",
    [("overview", "Overview"), ("101", "Ticket 101"), ("102", "Ticket 102"), ("103", "Ticket 103")],
    overview + "".join(board_panel(r) for r in records),
    "Screenshots are real captures of the React dashboard, embedded as PNG so this page works offline.",
)
(OUT / "resolved_board.html").write_text(board_html, encoding="utf-8")

# ======================================================================================
# 11. JSON outputs
# ======================================================================================

resolved = {
    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "final_full_run": {"reset_at": start["reset_event_time"], "run_ids": [r["run"]["run_id"] for r in records]},
    "model": limits["model"], "limits": {k: v for k, v in limits.items() if k.startswith("max_")},
    "cash": {"starting_checking": starting_cash, "total_paid": total_out, "ending_checking": ending,
             "matches_cash_accounts": reconciles, "ledger": ledger},
    "usage": {"final_full_run": final_totals, "all_runs_since_reset_incl_reply_and_reruns": all_since_reset,
              "all_problem9_runs_incl_earlier_attempts": p9_totals},
    "tickets": records,
}
(OUT / "resolved_tickets.json").write_text(json.dumps(resolved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
verification = {"generated_at": resolved["generated_at"], "passed": sum(c["passed"] for c in checks), "total": len(checks),
                "checks": checks, "usage": resolved["usage"], "limit_checks": limit_checks,
                "max_output_tokens_in_a_call": max_out, "max_delegation_depth": max_depth}
(OUT / "final_verification.json").write_text(json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print(f"desk_tickets.html {len(desk):,} chars · resolved_board.html {len(board_html):,} chars")
print(f"verification: {verification['passed']}/{verification['total']} passed")
for c in checks:
    if not c["passed"]:
        print("  FAIL:", c["check"], c["detail"])
print("usage:", json.dumps(resolved["usage"]))
