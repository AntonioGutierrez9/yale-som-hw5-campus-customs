"""FastAPI backend for the Campus Customs dashboard.

Run from this folder:   uvicorn main:app --reload --port 8000
Interactive docs:       http://127.0.0.1:8000/docs

- Shop data: every read and write goes through the campus-customs MCP server
  (one connection kept open for the dashboard routes). This file never queries
  the database. The only direct file operation is the reset route, which copies
  the original database file over the working copy.
- Agents: POST /api/tickets/{id}/run starts the existing team (Boss first).
- Activity: read from output/audit_trail.json (append-only), so the dashboard can poll it.
- Approvals: the ONLY place the human-only approve/reject MCP tools are called.
  Agents never get those tools, and these routes require a real human name.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

import agents
import audit
from models import AuditEntry, TeamResult

log = logging.getLogger("campus_customs.api")

ROOT = agents.ROOT
ORIGINAL_DB = ROOT / "data" / "campus_customs.db"
WORKING_DB = ROOT / "data" / "campus_customs_new.db"
RUN_TIMEOUT_SECONDS = 420
RUN_TASK = (
    "Ticket {ticket_id} is on the board. Work it end to end as the Boss: find out what it needs, "
    "delegate to the right teammates, make the calls that are yours, and leave the ticket in the right "
    "status with a note. Payments, purchase orders, and discounts must stay pending for human approval. "
    "Before you finish, make sure Customer Service saves a reply draft to the requester."
)

agents.load_env()


# ---------- Errors: one shape for React ({"error": {"code", "message"}}) ----------

class ApiError(Exception):
    def __init__(self, http_status: int, code: str, message: str, **extra: Any):
        self.http_status, self.code, self.message, self.extra = http_status, code, message, extra


def error_body(code: str, message: str, **extra: Any) -> dict:
    return {"error": {"code": code, "message": message, **extra}}


# ---------- Busy state: one agent run (or reset) at a time ----------

class Busy:
    lock = asyncio.Lock()
    action: Literal["run", "reset"] | None = None
    ticket_id: int | None = None
    run_id: str | None = None
    started_at: str | None = None

    @classmethod
    def as_dict(cls) -> dict:
        return {"busy": cls.lock.locked(), "action": cls.action, "ticket_id": cls.ticket_id,
                "run_id": cls.run_id, "started_at": cls.started_at}


# ---------- MCP connection ----------

class Mcp:
    client = None

    @classmethod
    async def connect(cls) -> None:
        cls.client = agents.mcp_client()
        await cls.client.__aenter__()

    @classmethod
    async def close(cls) -> None:
        if cls.client is not None:
            try:
                await cls.client.__aexit__(None, None, None)
            finally:
                cls.client = None


async def mcp_call(tool: str, **args: Any) -> dict:
    """Call one MCP tool and return its structured result (reconnects once if the server died)."""
    for attempt in (1, 2):
        try:
            if Mcp.client is None:
                await Mcp.connect()
            result = await Mcp.client.call_tool(tool, args, raise_on_error=False)
            break
        except Exception as exc:
            await Mcp.close()
            if attempt == 2:
                raise ApiError(502, "mcp_unavailable", f"MCP server error on {tool}: {type(exc).__name__}") from exc
    if result.is_error:
        text = " ".join(getattr(c, "text", "") for c in result.content)[:300]
        raise ApiError(502, "mcp_tool_error", f"{tool} failed: {text}")
    return result.structured_content or {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await Mcp.connect()
    except Exception as exc:  # the API still starts; routes retry the connection
        log.error("MCP server not reachable at startup: %s", exc)
    yield
    await Mcp.close()


app = FastAPI(title="Campus Customs Multi-Agent API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",  # the local React dev server
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Human-Approval"],
)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError):
    return JSONResponse(error_body(exc.code, exc.message, **exc.extra), status_code=exc.http_status)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException):
    return JSONResponse(error_body("http_error", str(exc.detail)), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    problems = [f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
    return JSONResponse(error_body("invalid_request", "; ".join(problems)), status_code=422)


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse(error_body("server_error", f"{type(exc).__name__}"), status_code=500)


# ---------- Human identity (approvals) ----------

NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z'.\-]+( [A-Za-z][A-Za-z'.\-]+)+$")
NOT_HUMAN_WORDS = {
    "boss", "inventory", "accounting", "facilities", "customer", "service", "agent", "agents", "ai", "bot",
    "assistant", "system", "auto", "automatic", "model", "gpt", "luna", "llm", "claude", "pydantic", "mcp",
}


def human_name(value: str) -> str:
    """A real person's first and last name, never an agent / AI / system name."""
    name = " ".join(value.split())
    if not NAME_PATTERN.match(name) or len(name) > 80:
        raise ValueError("Enter your first and last name (letters only), e.g. 'Jane Doe'.")
    if NOT_HUMAN_WORDS & {w.lower().strip(".'-") for w in name.split()}:
        raise ValueError("Approvals must come from a person, not an agent, AI, or system.")
    allowed = [a.strip().lower() for a in os.getenv("HUMAN_APPROVERS", "").split(",") if a.strip()]
    if allowed and name.lower() not in allowed:
        raise ValueError("This name isn't on the HUMAN_APPROVERS list.")
    return name


def require_human_header(value: str | None) -> None:
    if value != "true":
        raise ApiError(403, "human_confirmation_required",
                       "Approvals are human-only: send the header X-Human-Approval: true from the dashboard.")


HumanName = Annotated[str, AfterValidator(human_name)]


class ApproveBody(BaseModel):
    approved_by: HumanName = Field(description="The approving person's first and last name.")
    confirm: Literal[True] = Field(description="Must be true: the person confirmed this payment.")
    note: str = Field(default="", max_length=300)


class RejectBody(BaseModel):
    rejected_by: HumanName
    reason: str = Field(min_length=3, max_length=300)
    confirm: Literal[True]


class RunBody(BaseModel):
    instructions: str | None = Field(default=None, max_length=500,
                                     description="Optional extra guidance from the human for the Boss.")
    continue_confirmed: bool = Field(default=False, description=(
        "The human's explicit permission to run this ticket again. Required when the ticket already "
        "has a run since the last reset (e.g. it stopped at a limit or is waiting on approvals)."))


class UndoBody(BaseModel):
    undone_by: HumanName
    reason: str = Field(min_length=3, max_length=300)
    confirm: Literal[True]


class ResetBody(BaseModel):
    confirm: Literal[True]


def log_human(event: str, **fields: Any) -> None:
    """Human actions also go in the audit trail, so the activity feed shows them."""
    audit.append(AuditEntry(time=audit.now(), run_id="human", mode="run", agent="Human", depth=0, event=event, **fields))


@app.get("/api/limits")
async def limits():
    """The execution limits the backend enforces on every agent run (configurable via env vars)."""
    return {**agents.current_limits().as_dict(), "model": agents.MODEL_NAME, "reasoning_effort": agents.REASONING_EFFORT}


# ---------- Activity (audit trail) ----------

def describe(e: dict) -> str:
    """One readable line per audit event, for the activity feed."""
    a, ev = e.get("agent", "?"), e.get("event")
    match ev:
        case "run_start":
            return f"{a} started: {e.get('args', '')}"
        case "model_response":
            return f"{a} (step {e.get('step')}): {e.get('result', '')}"
        case "tool_call":
            return f"{a} called {e.get('tool')} {e.get('args', '')}"
        case "tool_result":
            return f"{e.get('tool')} returned to {a}: {e.get('result', '')}"
        case "tool_retry":
            return f"{a} retried {e.get('tool')}: {e.get('result', '')}"
        case "delegate":
            r = e.get("result", "")
            return f"{a} → {e.get('to_agent')}: {e.get('args', '')}" + (f" [{r}]" if r else "")
        case "delegation_result":
            return f"{e.get('to_agent')} reported back to {a}: {e.get('result', '')}"
        case "final_answer":
            return f"{a} said: {e.get('result', '')}"
        case "run_end":
            return f"{a} finished ({e.get('stop_reason')})"
        case _:
            return f"{a}: {e.get('result') or e.get('args') or ev}"


def read_events() -> list[dict]:
    try:
        return json.loads(audit.AUDIT_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise ApiError(500, "audit_unreadable", f"Couldn't read the audit trail: {type(exc).__name__}") from exc


def last_reset_index(events: list[dict]) -> int:
    """Index just after the most recent database reset (0 if there wasn't one)."""
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("event") == "db_reset":
            return i + 1
    return 0


def summarize_run(run_id: str, evs: list[dict]) -> dict:
    """What each agent did in one run: tools, delegations, what it said, tokens, and how the run ended."""
    agents_out: dict[str, dict] = {}

    def slot(name: str) -> dict:
        return agents_out.setdefault(name, {
            "agent": name, "tool_calls": {}, "delegated_to": [], "delegated_from": [], "said": [],
            "model_steps": 0, "input_tokens": 0, "output_tokens": 0, "finished": False, "stop_reason": None,
        })

    refused = 0
    limit_stops: list[str] = []
    repeats = 0
    for e in evs:
        if e["agent"] == "System":  # the backend's required-reply step
            if e["event"] == "delegate":
                slot(e["to_agent"])["delegated_from"].append("System (required customer reply)")
            continue
        a, ev = slot(e["agent"]), e["event"]
        if ev == "tool_call":
            a["tool_calls"][e["tool"]] = a["tool_calls"].get(e["tool"], 0) + 1
        elif ev == "delegate":
            if str(e.get("result", "")).startswith("REFUSED"):
                refused += 1
            else:
                a["delegated_to"].append(e["to_agent"])
                slot(e["to_agent"])["delegated_from"].append(e["agent"])
        elif ev == "final_answer":
            a["said"].append(e.get("result", ""))
        elif ev == "model_response":
            a["model_steps"] += 1
            a["input_tokens"] += e.get("input_tokens") or 0
            a["output_tokens"] += e.get("output_tokens") or 0
        elif ev == "run_end":
            a["finished"], a["stop_reason"] = True, e.get("stop_reason")
        elif ev == "limit_stop":
            limit_stops.append(f"{e['agent']}: {e.get('result', '')}")
        elif ev == "tool_repeat":
            repeats += 1
    top = evs[0]
    top_end = next((e for e in reversed(evs) if e["event"] == "run_end" and e.get("depth") == 0), None)
    if top_end is None:
        state = "running" if Busy.run_id == run_id else "interrupted"
    elif top_end.get("stop_reason") == "final_answer":
        state = "completed"
    elif str(top_end.get("stop_reason", "")).startswith(("limit", "usage_limit")):
        state = "limit_stopped"
    else:
        state = "failed"
    top_said = slot(top["agent"])["said"]
    return {
        "run_id": run_id, "ticket_id": top.get("ticket_id"), "mode": top.get("mode"), "status": state,
        "started_at": top["time"], "ended_at": top_end["time"] if top_end else None,
        "stop_reason": top_end.get("stop_reason") if top_end else None,
        "lead_agent": top["agent"], "outcome": top_said[-1] if top_said else None,
        "delegations": sum(len(a["delegated_to"]) for a in agents_out.values()), "refused_delegations": refused,
        "input_tokens": sum(a["input_tokens"] for a in agents_out.values()),
        "output_tokens": sum(a["output_tokens"] for a in agents_out.values()),
        "model_steps": sum(a["model_steps"] for a in agents_out.values()),
        "limit_stops": limit_stops, "repeats_blocked": repeats,
        "agents": list(agents_out.values()), "first_event_id": evs[0]["id"], "last_event_id": evs[-1]["id"],
    }


def select_events(since: int | None, limit: int, run_id: str | None = None, ticket_id: int | None = None,
                  mode: str | None = None, since_reset: bool = False) -> dict:
    events = read_events()
    rows = [{"id": i, **e, "text": describe(e)} for i, e in enumerate(events)]
    if since_reset:
        rows = rows[last_reset_index(events):]
    if since is not None:
        rows = [r for r in rows if r["id"] >= since]
    if run_id:
        rows = [r for r in rows if r.get("run_id") == run_id]
    if ticket_id is not None:
        rows = [r for r in rows if r.get("ticket_id") == ticket_id]
    if mode:
        rows = [r for r in rows if r.get("mode") == mode]
    rows = rows[:limit] if since is not None else rows[-limit:]
    return {"events": rows, "count": len(rows), "next_since": len(events), "status": Busy.as_dict()}


# ---------- Routes ----------

@app.get("/api/health")
async def health():
    """Is the API up, and is the MCP server reachable?"""
    try:
        await mcp_call("list_tickets")
        mcp_ok = True
    except ApiError:
        mcp_ok = False
    return {"ok": True, "mcp_connected": mcp_ok, "model": agents.MODEL_NAME, "status": Busy.as_dict()}


@app.get("/api/status")
async def status():
    """Whether agents (or a reset) are running right now."""
    return Busy.as_dict()


@app.get("/api/tickets")
async def list_tickets():
    """The board: every ticket with its status and how much work is attached to it."""
    board = await mcp_call("list_tickets")
    details = await asyncio.gather(*(mcp_call("get_ticket", ticket_id=t["id"]) for t in board["tickets"]))
    tickets = []
    for t, d in zip(board["tickets"], details):
        reqs = d.get("approval_requests", [])
        tickets.append({
            **t,
            "description": d.get("ticket", {}).get("notes"),
            "is_resolved": t["status"] == "resolved",
            "pending_approvals": sum(r["status"] == "pending" for r in reqs),
            "approved_by_human": sum(r["status"] in ("paid", "approved") for r in reqs),
            "rejected_by_human": sum(r["status"] == "rejected" for r in reqs),
            "approval_requests": len(reqs),
            "drafts": len(d.get("drafts", [])),
            "notes": len(d.get("notes", [])),
        })
    return {"today": board["today"], "count": len(tickets), "tickets": tickets}


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: int):
    """One ticket with its stock, pricing, invoice/vendor, lease, notes, drafts, and approval requests."""
    data, drafts = await asyncio.gather(mcp_call("get_ticket", ticket_id=ticket_id),
                                        mcp_call("list_customer_drafts", ticket_id=ticket_id))
    if not data.get("ok"):
        raise ApiError(404, "ticket_not_found", data.get("message", f"Ticket {ticket_id} not found."))
    data["drafts"] = drafts["drafts"]  # full drafts (with body) so the human can review them
    return data


DRAFT_TASK = (
    "Ticket {ticket_id}: write the reply to this ticket's requester. Use get_ticket for the facts (status, notes, "
    "approval requests and their decisions, existing drafts). Save ONE draft with draft_customer_message. If a "
    "decision is still waiting on the owners, say our team has reviewed the request and passed its recommendation "
    "to the owners for a decision, and that we'll follow up once they decide."
)


@app.post("/api/tickets/{ticket_id}/draft-reply")
async def draft_reply(ticket_id: int):
    """Run ONLY Customer Service to write the requester's reply (much cheaper than rerunning the team).

    Clicking the dashboard button is the human's permission; it's recorded in the audit trail.
    """
    ticket = await mcp_call("get_ticket", ticket_id=ticket_id)
    if not ticket.get("ok"):
        raise ApiError(404, "ticket_not_found", ticket.get("message", f"Ticket {ticket_id} not found."))
    if Busy.lock.locked():
        raise ApiError(409, "busy", "Agents are already working (or a reset is running). Try again when it finishes.",
                       running=Busy.as_dict())
    log_human("human_continue", ticket_id=ticket_id,
              result=f"Human asked Customer Service to draft the reply for ticket {ticket_id}")
    return await _run_team(ticket_id, "Customer Service", DRAFT_TASK.format(ticket_id=ticket_id))


async def _run_team(ticket_id: int, lead: str, task: str) -> dict:
    run_id = uuid.uuid4().hex[:10]
    async with Busy.lock:
        Busy.action, Busy.ticket_id, Busy.run_id, Busy.started_at = "run", ticket_id, run_id, audit.now()
        try:
            result: TeamResult = await asyncio.wait_for(
                agents.run_team_task(lead, task, ticket_id=ticket_id, run_id=run_id), timeout=RUN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise ApiError(504, "run_timeout", f"The agent run took longer than {RUN_TIMEOUT_SECONDS}s and was stopped.",
                           run_id=run_id) from exc
        finally:
            Busy.action = Busy.ticket_id = Busy.run_id = Busy.started_at = None
    after = await mcp_call("get_ticket", ticket_id=ticket_id)
    return {"run": result.model_dump(), "ticket": after, "events": select_events(None, 500, run_id=run_id)["events"]}


@app.post("/api/tickets/{ticket_id}/run")
async def run_ticket(ticket_id: int, body: RunBody | None = None):
    """Run the agent team on one ticket (the Boss starts and delegates). Waits for the result."""
    ticket = await mcp_call("get_ticket", ticket_id=ticket_id)
    if not ticket.get("ok"):
        raise ApiError(404, "ticket_not_found", ticket.get("message", f"Ticket {ticket_id} not found."))
    if Busy.lock.locked():
        raise ApiError(409, "busy", "Agents are already working (or a reset is running). Try again when it finishes.",
                       running=Busy.as_dict())
    previous = [r for r in (await runs(ticket_id=ticket_id, limit=100, since_reset=True, mode="run"))["runs"]]
    if previous and not (body and body.continue_confirmed):
        last = previous[0]
        raise ApiError(409, "needs_permission",
                       f"Ticket {ticket_id} already ran {len(previous)} time(s) since the last reset (last run "
                       f"{last['run_id']}: {last['status']}, {last['stop_reason'] or 'no stop reason'}). Running it again "
                       "uses a new step budget, so it needs your explicit permission.",
                       previous_runs=len(previous), last_run=last["run_id"], last_status=last["status"],
                       last_stop_reason=last["stop_reason"], limits=agents.current_limits().as_dict())
    if previous:
        log_human("human_continue", ticket_id=ticket_id,
                  result=f"Human allowed another run on ticket {ticket_id} (run #{len(previous) + 1} since reset)")
    task = RUN_TASK.format(ticket_id=ticket_id)
    if body and body.instructions:
        task += f"\n\nExtra guidance from the human manager: {body.instructions.strip()}"
    return await _run_team(ticket_id, "Boss", task)


@app.get("/api/activity")
async def activity(
    since: int | None = Query(None, ge=0, description="Return events with id >= since (use next_since to poll)."),
    limit: int = Query(100, ge=1, le=1000),
    run_id: str | None = None,
    ticket_id: int | None = None,
    mode: Literal["run", "test"] | None = None,
    since_reset: bool = Query(False, description="Only events after the most recent database reset."),
):
    """Recent agent events (newest last): who acted, what they said, delegations, and MCP tools used."""
    return select_events(since, limit, run_id=run_id, ticket_id=ticket_id, mode=mode, since_reset=since_reset)


@app.get("/api/approvals")
async def list_approvals(status: Literal["pending", "paid", "rejected"] | None = None):
    """Payment and purchase-order requests the agents prepared, with cash context.

    Each request also gets a readable `purpose`, the vendor name, whether the vendor is
    blocked by an unpaid invoice, and the projected checking balance if it's approved.
    """
    data, vendors, fin, board = await asyncio.gather(
        mcp_call("list_approval_requests", **({"status": status} if status else {})),
        mcp_call("list_vendors"), mcp_call("get_financial_status"), mcp_call("list_tickets"),
    )
    requesters = {t["id"]: t["requester"] for t in board["tickets"]}
    by_vendor = {v["vendor_id"]: v for v in vendors["vendors"]}
    leases = {l["lease_id"]: l for l in fin["rent_obligations"]}
    balance = data["checking_balance"]
    for r in data["requests"]:
        v = by_vendor.get(r.get("vendor_id"))
        r["vendor_name"] = v["name"] if v else None
        r["moves_cash"] = r["kind"] != "discount"
        if r["kind"] == "discount":
            r["purpose"] = (f"{r['discount_pct']:g}% discount for {requesters.get(r['ticket_id'], 'the customer')} "
                            f"on {r['qty']} × {r['sku']} size {r['size']}")
            r["quote"] = await mcp_call("quote_bulk_order", sku=r["sku"], size=r["size"], qty=r["qty"],
                                        discount_pct=r["discount_pct"])
        elif r["kind"] == "invoice":
            r["purpose"] = f"Pay invoice #{r['ref_id']} to {r['vendor_name']}"
        elif r["kind"] == "rent":
            l = leases.get(r["ref_id"])
            r["purpose"] = f"Rent for {l['space_name']} ({l['landlord']})" if l else f"Rent for lease #{r['ref_id']}"
        else:
            r["purpose"] = f"Restock {r['qty']} × {r['sku']} size {r['size']} from {r['vendor_name']}"
        blocked = r["kind"] == "purchase_order" and v is not None and not v["can_ship"]
        r["vendor_blocked"] = blocked
        r["blocking_invoices"] = [i["invoice_id"] for i in v["blocking_invoices"]] if blocked else []
        if r["status"] == "pending":
            cash_out = r["amount"] if r["moves_cash"] else 0  # a discount moves no cash
            r["projected_balance"] = round(balance - cash_out, 2)
            r["sufficient_cash"] = cash_out <= balance
    return data


@app.get("/api/attention")
async def attention(low_stock_at: int = Query(3, ge=0, le=50)):
    """Things a manager should look at now, from real data: overdue invoices, low stock,
    blocked vendors, rent coming due, and pending approvals."""
    invoices, stock, vendors, fin, reqs = await asyncio.gather(
        mcp_call("list_invoices", status="open"), mcp_call("list_inventory", max_qty=low_stock_at),
        mcp_call("list_vendors"), mcp_call("get_financial_status"), mcp_call("list_approval_requests", status="pending"),
    )
    items: list[dict] = []
    for i in invoices["invoices"]:
        if i["days_overdue"] > 0:
            items.append({"kind": "overdue_invoice", "severity": "high",
                          "title": f"Invoice #{i['id']} is {i['days_overdue']} days overdue",
                          "detail": f"${i['amount']:,.2f} to {i['vendor_name']} (due {i['due_date']}): {i['description']}"})
    for r in stock["rows"]:
        items.append({"kind": "low_inventory", "severity": "high" if r["qty"] == 0 else "medium",
                      "title": f"{r['name']} size {r['size']}: {'out of stock' if r['qty'] == 0 else f'only {r['qty']} left'}",
                      "detail": f"{r['sku']} · {r['location']}"})
    for v in vendors["vendors"]:
        if not v["can_ship"]:
            ids = ", ".join(f"#{i['invoice_id']}" for i in v["blocking_invoices"])
            items.append({"kind": "blocked_vendor", "severity": "high", "title": f"{v['name']} can't ship",
                          "detail": f"Unpaid invoice {ids} blocks new orders ({v['specialty']}, {v['lead_days']}-day lead time)."})
    for l in fin["rent_obligations"]:
        if l["days_until_due"] <= 7:
            items.append({"kind": "rent_due", "severity": "high" if l["days_until_due"] <= 3 else "medium",
                          "title": (f"Rent overdue by {-l['days_until_due']} days" if l["is_overdue"]
                                    else f"Rent due in {l['days_until_due']} days"),
                          "detail": f"${l['monthly_rent']:,.2f} to {l['landlord']} for {l['space_name']}, due {l['next_due']}"})
    for r in reqs["requests"]:
        what = (f"{r['discount_pct']:g}% customer discount (${r['amount']:,.2f} off list)" if r["kind"] == "discount"
                else f"${r['amount']:,.2f}")
        items.append({"kind": "pending_approval", "severity": "medium", "ticket_id": r["ticket_id"],
                      "title": f"Approval #{r['id']} waiting: {what}",
                      "detail": f"{r['kind'].replace('_', ' ')} requested by {r['requested_by']}"})
    if reqs["pending_total"] > reqs["checking_balance"]:
        items.append({"kind": "cash_shortfall", "severity": "high", "title": "Pending requests exceed cash",
                      "detail": f"${reqs['pending_total']:,.2f} pending vs ${reqs['checking_balance']:,.2f} in checking"})
    order = {"high": 0, "medium": 1}
    items.sort(key=lambda x: order[x["severity"]])
    counts: dict[str, int] = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    return {"today": fin["today"], "count": len(items), "counts": counts, "items": items}


@app.get("/api/runs")
async def runs(ticket_id: int | None = None, limit: int = Query(10, ge=1, le=100), since_reset: bool = True,  # noqa
               mode: Literal["run", "test"] | None = "run"):
    """Agent runs (newest first) with what each agent contributed and the final outcome, from the audit trail."""
    events = read_events()
    start = last_reset_index(events) if since_reset else 0
    grouped: dict[str, list[dict]] = {}
    for i, e in enumerate(events[start:], start=start):
        if e.get("run_id") in ("human", "system") or e.get("agent") == "Human" or (mode and e.get("mode") != mode):
            continue
        if ticket_id is not None and e.get("ticket_id") != ticket_id:
            continue
        grouped.setdefault(e["run_id"], []).append({"id": i, **e})
    out = [summarize_run(run_id, evs) for run_id, evs in grouped.items()]
    out.sort(key=lambda r: r["first_event_id"], reverse=True)
    return {"runs": out[:limit], "count": len(out)}


@app.post("/api/approvals/{request_id}/approve")
async def approve(request_id: int, body: ApproveBody, x_human_approval: str | None = Header(None)):
    """HUMAN ONLY: approve a pending request. This is what actually pays (through the MCP server's checks)."""
    require_human_header(x_human_approval)
    result = await mcp_call("approve_request", request_id=request_id, approved_by=body.approved_by, note=body.note)
    if not result.get("ok"):
        log_human("human_approval", args=f"request #{request_id} by {body.approved_by}",
                  result=f"REFUSED: {result.get('message')}")
        raise ApiError(409, "approval_refused", result.get("message", "Approval refused."), request_id=request_id)
    summary = (result.get("effect", "") if result.get("kind") == "discount" else
               f"paid ${result['amount']:,.2f}; {result.get('effect', '')}; checking now ${result['checking_balance']:,.2f}")
    log_human("human_approval", args=f"request #{request_id} by {body.approved_by}", result=audit.short(summary, 250))
    synced = await sync_status(result.get("ticket_id"), body.approved_by)
    return {**result, "approved_by": body.approved_by, "ticket_status": synced}


@app.post("/api/approvals/{request_id}/reject")
async def reject(request_id: int, body: RejectBody, x_human_approval: str | None = Header(None)):
    """HUMAN ONLY: reject a pending request. No money moves."""
    require_human_header(x_human_approval)
    result = await mcp_call("reject_request", request_id=request_id, rejected_by=body.rejected_by, reason=body.reason)
    if not result.get("ok"):
        raise ApiError(409, "rejection_refused", result.get("message", "Rejection refused."), request_id=request_id)
    log_human("human_rejection", args=f"request #{request_id} by {body.rejected_by}", result=audit.short(body.reason, 200))
    synced = await sync_status(result.get("ticket_id"), body.rejected_by)
    return {**result, "rejected_by": body.rejected_by, "ticket_status": synced}


async def sync_status(ticket_id: int | None, who: str) -> dict | None:
    """Apply the human decisions on a ticket's approval requests to its status (no agents run)."""
    if ticket_id is None:
        return None
    res = await mcp_call("sync_ticket_status", ticket_id=ticket_id, updated_by=who)
    if res.get("ok") and res.get("changed"):
        log_human("status_sync", ticket_id=ticket_id,
                  result=f"Ticket {ticket_id}: {res['old_status']} -> {res['new_status']}. {res['reason']}")
    return res


@app.post("/api/tickets/{ticket_id}/sync-status")
async def sync_ticket_status(ticket_id: int):
    """Update a ticket's status from human approval decisions, without rerunning the agents.

    pending request(s) -> waiting_on_approval; all approved -> approved; all rejected -> rejected;
    a mix -> partially_approved. Tickets with no approval requests (or already resolved) don't change.
    """
    if Busy.lock.locked() and Busy.ticket_id == ticket_id:
        raise ApiError(409, "busy", f"Agents are working on ticket {ticket_id}; update its status after the run.")
    res = await sync_status(ticket_id, "Dashboard user")
    if not res.get("ok"):
        raise ApiError(404, "ticket_not_found", res.get("message", f"Ticket {ticket_id} not found."))
    return res


@app.post("/api/approvals/{request_id}/undo")
async def undo(request_id: int, body: UndoBody, x_human_approval: str | None = Header(None)):
    """HUMAN ONLY: take back a decision so the request is pending again.

    Each request has exactly one decision at a time; to change it you undo it first.
    Undoing a payment reverses it (money back to checking, a reversal row in payments).
    """
    require_human_header(x_human_approval)
    result = await mcp_call("undo_decision", request_id=request_id, undone_by=body.undone_by, reason=body.reason)
    if not result.get("ok"):
        raise ApiError(409, "undo_refused", result.get("message", "Undo refused."), request_id=request_id)
    log_human("human_undo", ticket_id=result.get("ticket_id"), args=f"request #{request_id} by {body.undone_by}",
              result=audit.short(f"{result['old_status']} -> pending. {result['effect']} Reason: {body.reason}", 300))
    synced = await sync_status(result.get("ticket_id"), body.undone_by)
    return {**result, "undone_by": body.undone_by, "ticket_status": synced}


@app.get("/api/cash")
async def cash():
    """Checking balance (from cash_accounts), what's promised to pending requests, and payments so far."""
    fin, reqs, pays = await asyncio.gather(
        mcp_call("get_financial_status"), mcp_call("list_approval_requests", status="pending"), mcp_call("list_payments"),
    )
    checking = next((a for a in fin["cash_accounts"] if a["name"] == "checking"), None)
    if checking is None:
        raise ApiError(500, "no_checking_account", "cash_accounts has no 'checking' row.")
    return {
        "today": fin["today"],
        "account": "checking",
        "balance": checking["balance"],
        "as_of": checking["date"],
        "pending_approvals_total": reqs["pending_total"],
        "available_after_pending": round(checking["balance"] - reqs["pending_total"], 2),
        "open_invoices_total": fin["total_open_invoices"],
        "rent_due_total": fin["total_rent_due"],
        "payments": pays["payments"],
        "total_paid": pays["total_paid"],          # net of reversals
        "total_reversed": pays.get("total_reversed", 0),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@app.post("/api/reset")
async def reset(body: ResetBody):
    """Restore the working copy from the original database. Refused while agents are running."""
    if Busy.lock.locked():
        raise ApiError(409, "busy", "Can't reset while agents are working. Wait for the run to finish.",
                       running=Busy.as_dict())
    if ORIGINAL_DB.resolve() == WORKING_DB.resolve():
        raise ApiError(500, "bad_config", "The working database path points at the original.")
    if not ORIGINAL_DB.exists():
        raise ApiError(500, "original_missing", "data/campus_customs.db is missing; can't reset.")
    async with Busy.lock:
        Busy.action, Busy.started_at = "reset", audit.now()
        try:
            original_hash = sha256(ORIGINAL_DB)
            # Copy INTO the working file (never the other way). The original is only ever read.
            shutil.copyfile(ORIGINAL_DB, WORKING_DB)
            for extra in ("-journal", "-wal", "-shm"):
                Path(f"{WORKING_DB}{extra}").unlink(missing_ok=True)
            working_hash = sha256(WORKING_DB)
        finally:
            Busy.action = Busy.started_at = None
    if working_hash != original_hash or sha256(ORIGINAL_DB) != original_hash:
        raise ApiError(500, "reset_failed", "The working copy doesn't match the original after reset.")
    log_human("db_reset", result="campus_customs_new.db restored from campus_customs.db")
    return {"ok": True, "working_db": "data/campus_customs_new.db", "restored_from": "data/campus_customs.db",
            "sha256": working_hash, "matches_original": True}
