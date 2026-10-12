"""Campus Customs MCP server — Homework 5.

The only way the agent team (and later the dashboard) reads or changes shop data.
It works on the working database data/campus_customs_new.db and refuses to open
the original data/campus_customs.db, so we can always reset from it.

Tools come in three groups:
- Read tools: open the database read-only.
- Agent write tools: record work (approval requests, drafts, notes, ticket status,
  discount decisions). None of them move money.
- Human-only tools: approve_request / reject_request. Approving is the only way a
  payment happens. The backend never gives these two tools to an agent.

Run from this folder (stdio):  python server.py
Run (HTTP):                    python server.py --http
HTTP URL:                      http://127.0.0.1:8001/mcp
Use another copy (tests):      set CAMPUS_CUSTOMS_DB=path/to/copy.db
"""

from __future__ import annotations

import argparse
import calendar
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ORIGINAL_DB = ROOT / "data" / "campus_customs.db"
DB_PATH = Path(os.getenv("CAMPUS_CUSTOMS_DB", ROOT / "data" / "campus_customs_new.db")).resolve()

mcp = FastMCP("campus-customs")

AgentName = Literal["Boss", "Inventory", "Accounting", "Facilities", "Customer Service"]
AGENT_NAMES = {"boss", "inventory", "accounting", "facilities", "customer service"}
# Approvers must be a person, not an agent or a generic system name.
NOT_A_HUMAN = AGENT_NAMES | {"customer_service", "agent", "ai", "assistant", "system", "bot", "auto", ""}
# Statuses agents can set. "approved" / "rejected" / "partially_approved" come only from human decisions
# (sync_ticket_status), so an agent can never mark its own request as approved.
AgentTicketStatus = Literal["open", "in_progress", "waiting_on_approval", "waiting_on_vendor", "resolved"]
TicketStatus = Literal["open", "in_progress", "waiting_on_approval", "waiting_on_vendor", "resolved",
                       "approved", "rejected", "partially_approved"]
MAX_ORDER_QTY = 500

# Tables this server adds to the working copy (the original 9 tables are never altered).
EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER,
    kind TEXT NOT NULL,              -- invoice | rent | purchase_order | discount
    ref_id INTEGER,                  -- invoices.id or leases.id (NULL for purchase_order)
    vendor_id INTEGER,
    sku TEXT,
    size TEXT,
    qty INTEGER,
    amount REAL NOT NULL,            -- computed from the database, never typed by an agent
                                     -- (for a discount: the $ off list price; no cash moves)
    reason TEXT,
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | paid | approved (discount) | rejected
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT,
    payment_id INTEGER,
    discount_pct REAL                -- only for kind = discount
);
CREATE TABLE IF NOT EXISTS customer_drafts (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    recipient TEXT NOT NULL,         -- always the ticket's requester
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    written_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'      -- drafts stay on the board; nothing is sent
);
CREATE TABLE IF NOT EXISTS ticket_notes (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    author TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


# ---------- Database helpers ----------

class ClosingConnection(sqlite3.Connection):
    """A connection that also closes at the end of a `with` block (plain sqlite3 only commits),
    so no file handle stays open on the working database (matters for the reset route on Windows)."""

    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


def _check_path() -> None:
    if DB_PATH == ORIGINAL_DB.resolve():
        raise PermissionError("Refusing to use the original campus_customs.db. Point at a copy.")
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Working database not found at {DB_PATH}. "
            "Copy data/campus_customs.db to data/campus_customs_new.db first."
        )


def _ensure_schema() -> None:
    """Add our three extra tables if they're missing (e.g. right after a reset)."""
    with sqlite3.connect(DB_PATH, factory=ClosingConnection) as conn:
        conn.executescript(EXTRA_SCHEMA)
        # Older working copies were created before discount approvals existed.
        if "discount_pct" not in {r[1] for r in conn.execute("PRAGMA table_info(approval_requests)")}:
            conn.execute("ALTER TABLE approval_requests ADD COLUMN discount_pct REAL")


def connect() -> sqlite3.Connection:
    """Open the working database read-only, so read tools can never change a record."""
    _check_path()
    _ensure_schema()
    conn = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    return conn


def connect_write() -> sqlite3.Connection:
    """Open for writing inside one transaction (BEGIN IMMEDIATE locks out other writers)."""
    _check_path()
    _ensure_schema()
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN IMMEDIATE")
    return conn


def shop_today(conn: sqlite3.Connection) -> str:
    """The shop's "today" comes from desk.date_today, not the real calendar."""
    return conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()["date_today"]


def now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Sort sizes the way people read them (S, M, L, XL), not alphabetically.
SIZE_ORDER = "CASE size WHEN 'S' THEN 1 WHEN 'M' THEN 2 WHEN 'L' THEN 3 WHEN 'XL' THEN 4 ELSE 5 END"


def days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def add_days(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def add_month(day: str) -> str:
    d = date.fromisoformat(day)
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def sub_month(day: str) -> str:
    d = date.fromisoformat(day)
    y, m = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def checking_balance(conn: sqlite3.Connection) -> float:
    return conn.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()["balance"]


def pending_total(conn: sqlite3.Connection) -> float:
    return conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM approval_requests WHERE status = 'pending' AND kind != 'discount'"
    ).fetchone()["t"]


def open_invoices_for(conn: sqlite3.Connection, vendor_id: int) -> list[dict]:
    return [
        dict(r) for r in conn.execute(
            "SELECT id AS invoice_id, amount, due_date, description FROM invoices "
            "WHERE vendor_id = ? AND status = 'open' ORDER BY due_date",
            (vendor_id,),
        )
    ]


def vendor_summary(conn: sqlite3.Connection, v: sqlite3.Row, today: str) -> dict:
    blocking = open_invoices_for(conn, v["id"])
    return {
        "vendor_id": v["id"],
        "name": v["name"],
        "specialty": v["specialty"],
        "lead_days": v["lead_days"],
        "can_ship": not blocking,
        "blocking_invoices": blocking,
        "earliest_arrival_if_ordered_today": add_days(today, v["lead_days"]) if not blocking else None,
    }


def fail(message: str, **extra) -> dict:
    return {"ok": False, "message": message, **extra}


# ---------- Read tools: tickets ----------

@mcp.tool
def list_tickets(status: TicketStatus | None = None) -> dict:
    """List tickets on the board (all, or only one status), oldest first.

    Each row has id, type, requester, subject, sku/size/qty, linked lease_id or
    invoice_id, and status. Use get_ticket for the full picture of one ticket.
    """
    with connect() as conn:
        today = shop_today(conn)
        sql = ("SELECT id, type, requester, subject, sku, size, qty, lease_id, invoice_id, status, created_at "
               "FROM tickets")
        rows = conn.execute(sql + (" WHERE status = ?" if status else "") + " ORDER BY created_at",
                            (status,) if status else ()).fetchall()
    return {"today": today, "count": len(rows), "tickets": [dict(r) for r in rows]}


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """Get one ticket with everything linked to it, in one call.

    Includes the ticket row, plus (when the ticket has them) the stock for its
    SKU/size, the SKU's pricing, the linked invoice with its vendor and whether
    that vendor can ship, the linked lease with days until rent is due, and any
    notes, customer drafts, and approval requests already made for this ticket.
    """
    with connect() as conn:
        today = shop_today(conn)
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return fail(f"Ticket {ticket_id} not found.")
        out: dict = {"ok": True, "today": today, "ticket": dict(t)}
        if t["sku"]:
            stock = conn.execute(
                f"SELECT size, qty, location FROM inventory WHERE sku = ? ORDER BY {SIZE_ORDER}", (t["sku"],)
            ).fetchall()
            here = next((r for r in stock if r["size"] == t["size"]), None)
            out["stock"] = {
                "requested_size": t["size"],
                "qty_in_requested_size": here["qty"] if here else None,
                "shortfall": max((t["qty"] or 0) - (here["qty"] if here else 0), 0),
                "all_sizes": [dict(r) for r in stock],
            }
            p = conn.execute("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (t["sku"],)).fetchone()
            out["pricing"] = dict(p) if p else None
        if t["invoice_id"]:
            i = conn.execute("SELECT * FROM invoices WHERE id = ?", (t["invoice_id"],)).fetchone()
            if i:
                v = conn.execute("SELECT * FROM vendors WHERE id = ?", (i["vendor_id"],)).fetchone()
                out["invoice"] = {**dict(i), "days_overdue": max(days_between(i["due_date"], today), 0)}
                out["vendor"] = vendor_summary(conn, v, today)
        if t["lease_id"]:
            l = conn.execute("SELECT * FROM leases WHERE id = ?", (t["lease_id"],)).fetchone()
            if l:
                out["lease"] = {**dict(l), "days_until_due": days_between(today, l["next_due"])}
        out["notes"] = [dict(r) for r in conn.execute(
            "SELECT author, note, created_at FROM ticket_notes WHERE ticket_id = ? ORDER BY id", (ticket_id,))]
        out["drafts"] = [dict(r) for r in conn.execute(
            "SELECT id, recipient, subject, written_by, status FROM customer_drafts WHERE ticket_id = ? ORDER BY id",
            (ticket_id,))]
        out["approval_requests"] = [dict(r) for r in conn.execute(
            "SELECT id, kind, ref_id, vendor_id, sku, size, qty, amount, status, requested_by, requested_at, "
            "decided_by, decided_at, discount_pct FROM approval_requests WHERE ticket_id = ? ORDER BY id", (ticket_id,))]
    return out


# ---------- Read tools: inventory, pricing, vendors ----------

@mcp.tool
def check_product_stock(sku: str, size: str) -> dict:
    """Check how many units of one SKU in one size are in stock.

    Returns the product name, SKU, size, available quantity, and shelf
    location from the inventory table. Sizes are S, M, L, XL, or OS (one size).
    If the SKU/size isn't found, `found` is false and `sizes_on_file` lists the
    sizes that do exist for that SKU.
    """
    sku, size = sku.strip().upper(), size.strip().upper()
    with connect() as conn:
        row = conn.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
            (sku, size),
        ).fetchone()
        if row is None:
            sizes = [
                r["size"]
                for r in conn.execute(
                    f"SELECT size FROM inventory WHERE sku = ? ORDER BY {SIZE_ORDER}", (sku,)
                )
            ]
            return {
                "found": False,
                "sku": sku,
                "size": size,
                "sizes_on_file": sizes,
                "message": (
                    f"No inventory row for {sku} size {size}."
                    if sizes
                    else f"SKU {sku} is not in inventory."
                ),
            }
    return {
        "found": True,
        "sku": row["sku"],
        "name": row["name"],
        "size": row["size"],
        "qty_available": row["qty"],
        "in_stock": row["qty"] > 0,
        "location": row["location"],
    }


@mcp.tool
def list_inventory(max_qty: int | None = None) -> dict:
    """List stock for every SKU and size, or only rows at or below `max_qty`.

    Use max_qty=0 to find everything that's out of stock.
    """
    with connect() as conn:
        sql = "SELECT sku, name, size, qty, location FROM inventory"
        rows = conn.execute(
            sql + (" WHERE qty <= ?" if max_qty is not None else "") + f" ORDER BY sku, {SIZE_ORDER}",
            (max_qty,) if max_qty is not None else (),
        ).fetchall()
    return {"count": len(rows), "rows": [dict(r) for r in rows]}


@mcp.tool
def get_product_pricing(sku: str) -> dict:
    """Get cost, list price, margin, and stock by size for one SKU.

    Reads the pricing table (unit_cost, list_price) and the inventory table
    (qty per size). Margin is list price minus unit cost, per unit and as a
    percent of list price. Useful before agreeing to a discount.
    """
    sku = sku.strip().upper()
    with connect() as conn:
        price = conn.execute(
            "SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)
        ).fetchone()
        stock = conn.execute(
            f"SELECT name, size, qty, location FROM inventory WHERE sku = ? ORDER BY {SIZE_ORDER}",
            (sku,),
        ).fetchall()

    if price is None:
        return {"found": False, "sku": sku, "message": f"SKU {sku} has no pricing on file."}

    unit_cost, list_price = price["unit_cost"], price["list_price"]
    margin = list_price - unit_cost
    return {
        "found": True,
        "sku": sku,
        "name": stock[0]["name"] if stock else None,
        "unit_cost": unit_cost,
        "list_price": list_price,
        "margin_per_unit": round(margin, 2),
        "margin_pct": round(margin / list_price * 100, 1) if list_price else None,
        "inventory_by_size": [
            {"size": r["size"], "qty": r["qty"], "location": r["location"]} for r in stock
        ],
        "total_qty": sum(r["qty"] for r in stock),
    }


@mcp.tool
def quote_bulk_order(sku: str, size: str, qty: int, discount_pct: float = 0) -> dict:
    """Price a bulk order at a given discount, without saving anything.

    Shows the discounted unit price, order total, cost, gross margin ($ and %),
    whether the price would be below cost, and how many units are in stock in
    that size (and the shortfall). Try a few discounts to compare.
    """
    sku, size = sku.strip().upper(), size.strip().upper()
    if not 0 <= discount_pct < 100:
        return fail("discount_pct must be between 0 and 99.")
    if not 0 < qty <= MAX_ORDER_QTY:
        return fail(f"qty must be between 1 and {MAX_ORDER_QTY}.")
    with connect() as conn:
        p = conn.execute("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)).fetchone()
        s = conn.execute("SELECT qty FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone()
    if p is None:
        return fail(f"SKU {sku} has no pricing on file.")
    unit_price = round(p["list_price"] * (1 - discount_pct / 100), 2)
    total, cost = round(unit_price * qty, 2), round(p["unit_cost"] * qty, 2)
    in_stock = s["qty"] if s else 0
    return {
        "ok": True,
        "sku": sku, "size": size, "qty": qty, "discount_pct": discount_pct,
        "list_price": p["list_price"], "unit_cost": p["unit_cost"],
        "unit_price": unit_price,
        "order_total": total,
        "order_cost": cost,
        "gross_margin": round(total - cost, 2),
        "margin_pct": round((total - cost) / total * 100, 1) if total else None,
        "below_cost": unit_price < p["unit_cost"],
        "in_stock_this_size": in_stock,
        "shortfall": max(qty - in_stock, 0),
    }


@mcp.tool
def list_vendors() -> dict:
    """List every vendor with specialty, lead time, and whether they can ship now.

    A vendor can't ship new product while it has an open unpaid invoice, so
    `can_ship` is false and `blocking_invoices` lists them. Arrival dates
    count lead_days from the shop's today.
    """
    with connect() as conn:
        today = shop_today(conn)
        vendors = [vendor_summary(conn, v, today) for v in conn.execute("SELECT * FROM vendors ORDER BY id")]
    return {"today": today, "vendors": vendors}


@mcp.tool
def plan_restock(sku: str, size: str, qty: int, vendor_id: int) -> dict:
    """Plan a restock (read-only): cost, vendor status, arrival date, and cash impact.

    Cost is pricing.unit_cost x qty. Shows if the vendor is blocked by an open
    invoice, the earliest arrival (today + lead_days, only once unblocked),
    current stock, checking balance, cash already promised to pending approval
    requests, and what would be left after this order too.
    """
    sku, size = sku.strip().upper(), size.strip().upper()
    if not 0 < qty <= MAX_ORDER_QTY:
        return fail(f"qty must be between 1 and {MAX_ORDER_QTY}.")
    with connect() as conn:
        today = shop_today(conn)
        inv = conn.execute("SELECT name, qty FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone()
        p = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
        v = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if inv is None or p is None:
            return fail(f"No inventory/pricing for {sku} size {size}.")
        if v is None:
            return fail(f"Vendor {vendor_id} not found.")
        vendor = vendor_summary(conn, v, today)
        cash, pending = checking_balance(conn), pending_total(conn)
    cost = round(p["unit_cost"] * qty, 2)
    blocked_total = sum(i["amount"] for i in vendor["blocking_invoices"])
    return {
        "ok": True,
        "sku": sku, "name": inv["name"], "size": size, "qty": qty,
        "current_stock": inv["qty"],
        "order_cost": cost,
        "vendor": vendor,
        "earliest_arrival_after_unblocking": add_days(today, v["lead_days"]),
        "checking_balance": cash,
        "pending_approvals_total": pending,
        "cash_left_after_pending_and_this_order": round(cash - pending - cost, 2),
        "affordable_after_pending": cash - pending - cost >= 0,
        "note": (f"Blocked: pay {len(vendor['blocking_invoices'])} open invoice(s) "
                 f"(${blocked_total:,.2f}) to this vendor first." if not vendor["can_ship"] else "Vendor can ship."),
    }


# ---------- Read tools: money, rent, approvals, drafts ----------

@mcp.tool
def get_financial_status() -> dict:
    """Get the shop's cash position and what it owes.

    Returns the shop's "today" (desk.date_today), every cash account balance,
    all open vendor invoices with vendor details and days overdue, and rent
    for every lease with days until due. Totals show what cash would be left
    if every open invoice and rent were paid. This tool does not pay anything.
    """
    with connect() as conn:
        today = shop_today(conn)
        accounts = [
            dict(r) for r in conn.execute("SELECT name, balance, date FROM cash_accounts")
        ]
        invoice_rows = conn.execute(
            """
            SELECT i.id AS invoice_id, i.amount, i.due_date, i.status, i.description,
                   v.id AS vendor_id, v.name AS vendor_name, v.specialty, v.lead_days
            FROM invoices i
            JOIN vendors v ON v.id = i.vendor_id
            WHERE i.status = 'open'
            ORDER BY i.due_date
            """
        ).fetchall()
        lease_rows = conn.execute(
            """
            SELECT id AS lease_id, space_name, landlord, monthly_rent, next_due, notes
            FROM leases
            ORDER BY next_due
            """
        ).fetchall()

    open_invoices = []
    for r in invoice_rows:
        late = days_between(r["due_date"], today)
        open_invoices.append({
            **dict(r),
            "is_overdue": late > 0,
            "days_overdue": max(late, 0),
            "blocks_vendor_shipping": True,  # vendors won't ship with an open unpaid invoice
        })

    rent = []
    for r in lease_rows:
        until = days_between(today, r["next_due"])
        rent.append({**dict(r), "days_until_due": until, "is_overdue": until < 0})

    total_cash = sum(a["balance"] for a in accounts)
    total_invoices = sum(i["amount"] for i in open_invoices)
    total_rent = sum(r["monthly_rent"] for r in rent)
    return {
        "today": today,
        "cash_accounts": accounts,
        "total_cash": total_cash,
        "open_invoices": open_invoices,
        "total_open_invoices": total_invoices,
        "rent_obligations": rent,
        "total_rent_due": total_rent,
        "cash_left_if_all_paid": total_cash - total_invoices - total_rent,
    }


@mcp.tool
def list_invoices(status: Literal["open", "paid"] | None = None) -> dict:
    """List vendor invoices (all, open, or paid) with vendor name and days overdue."""
    with connect() as conn:
        today = shop_today(conn)
        rows = conn.execute(
            "SELECT i.*, v.name AS vendor_name FROM invoices i JOIN vendors v ON v.id = i.vendor_id"
            + (" WHERE i.status = ?" if status else "") + " ORDER BY i.due_date",
            (status,) if status else (),
        ).fetchall()
    return {"today": today, "invoices": [
        {**dict(r), "days_overdue": max(days_between(r["due_date"], today), 0) if r["status"] == "open" else 0}
        for r in rows
    ]}


@mcp.tool
def get_lease(lease_id: int) -> dict:
    """Get one lease: space, landlord, monthly rent, next due date, days until due, and past rent payments."""
    with connect() as conn:
        today = shop_today(conn)
        l = conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
        if l is None:
            return fail(f"Lease {lease_id} not found.")
        paid = [dict(r) for r in conn.execute(
            "SELECT id, amount, paid_at, approved_by FROM payments WHERE kind = 'rent' AND ref_id = ? ORDER BY id",
            (lease_id,))]
    until = days_between(today, l["next_due"])
    return {"ok": True, "today": today, **dict(l), "days_until_due": until, "is_overdue": until < 0,
            "rent_payments": paid}


@mcp.tool
def list_payments() -> dict:
    """List every payment (each approved by a human), including reversals of undone payments.

    A reversal is kind='reversal' with a negative amount and ref_id = the payment it reverses.
    total_paid is the net cash that left checking.
    """
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM payments ORDER BY id")]
    reversed_ids = {r["ref_id"] for r in rows if r["kind"] == "reversal"}
    for r in rows:
        r["reversed"] = r["id"] in reversed_ids
    return {"count": len(rows), "total_paid": round(sum(r["amount"] for r in rows), 2),
            "total_reversed": round(-sum(r["amount"] for r in rows if r["kind"] == "reversal"), 2), "payments": rows}


@mcp.tool
def list_approval_requests(status: Literal["pending", "paid", "approved", "rejected"] | None = None) -> dict:
    """List payment and purchase-order requests waiting for (or decided by) a human.

    Also shows the checking balance and how much cash the pending requests add up to.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM approval_requests" + (" WHERE status = ?" if status else "") + " ORDER BY id",
            (status,) if status else (),
        ).fetchall()
        cash, pending = checking_balance(conn), pending_total(conn)
    return {"checking_balance": cash, "pending_total": pending, "cash_left_if_all_pending_paid": cash - pending,
            "requests": [dict(r) for r in rows]}


@mcp.tool
def list_customer_drafts(ticket_id: int | None = None) -> dict:
    """List customer message drafts (all, or for one ticket). Drafts are never sent."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM customer_drafts" + (" WHERE ticket_id = ?" if ticket_id else "") + " ORDER BY id",
            (ticket_id,) if ticket_id else (),
        ).fetchall()
    return {"drafts": [dict(r) for r in rows]}


# ---------- Agent write tools (no money moves) ----------

@mcp.tool
def request_payment(
    kind: Literal["invoice", "rent"], ref_id: int, requested_by: AgentName, reason: str,
    ticket_id: int | None = None,
) -> dict:
    """Ask a human to approve paying a vendor invoice or rent. Does NOT pay.

    kind="invoice": ref_id is invoices.id (must be open). kind="rent": ref_id is
    leases.id (rent must be due within 30 days). The amount is taken from the
    database. Refuses duplicates. The request waits as 'pending' until a human
    approves it on the dashboard.
    """
    conn = connect_write()
    try:
        today = shop_today(conn)
        if kind == "invoice":
            row = conn.execute("SELECT * FROM invoices WHERE id = ?", (ref_id,)).fetchone()
            if row is None:
                return fail(f"Invoice {ref_id} not found.")
            if row["status"] != "open":
                return fail(f"Invoice {ref_id} is already {row['status']}.")
            amount, vendor_id = row["amount"], row["vendor_id"]
        else:
            row = conn.execute("SELECT * FROM leases WHERE id = ?", (ref_id,)).fetchone()
            if row is None:
                return fail(f"Lease {ref_id} not found.")
            if days_between(today, row["next_due"]) > 30:
                return fail(f"Rent for lease {ref_id} isn't due until {row['next_due']}; it looks paid for this period.")
            amount, vendor_id = row["monthly_rent"], None
        dup = conn.execute(
            "SELECT id FROM approval_requests WHERE kind = ? AND ref_id = ? AND status = 'pending'", (kind, ref_id)
        ).fetchone()
        if dup:
            return fail(f"Request #{dup['id']} for this {kind} is already pending.", request_id=dup["id"])
        cur = conn.execute(
            "INSERT INTO approval_requests (ticket_id, kind, ref_id, vendor_id, amount, reason, requested_by, requested_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, kind, ref_id, vendor_id, amount, reason.strip()[:500], requested_by, now_stamp()),
        )
        cash, pending = checking_balance(conn), pending_total(conn)
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {
        "ok": True, "request_id": cur.lastrowid, "status": "pending", "kind": kind, "ref_id": ref_id,
        "amount": amount, "checking_balance": cash, "pending_total": pending,
        "warning": None if cash - pending >= 0 else "Pending requests now add up to more than the cash on hand.",
        "message": f"Request #{cur.lastrowid} is waiting for human approval. No money has moved.",
    }


@mcp.tool
def request_purchase_order(
    vendor_id: int, sku: str, size: str, qty: int, requested_by: AgentName, reason: str,
    ticket_id: int | None = None,
) -> dict:
    """Ask a human to approve a restock purchase order. Does NOT order or pay.

    The amount is pricing.unit_cost x qty. If the vendor has an open unpaid
    invoice, the request is still saved but flagged as blocked: it can't be
    approved until that invoice is paid.
    """
    sku, size = sku.strip().upper(), size.strip().upper()
    if not 0 < qty <= MAX_ORDER_QTY:
        return fail(f"qty must be between 1 and {MAX_ORDER_QTY}.")
    conn = connect_write()
    try:
        today = shop_today(conn)
        v = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if v is None:
            return fail(f"Vendor {vendor_id} not found.")
        if conn.execute("SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone() is None:
            return fail(f"{sku} size {size} isn't a product we stock.")
        p = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if p is None:
            return fail(f"SKU {sku} has no pricing on file.")
        dup = conn.execute(
            "SELECT id FROM approval_requests WHERE kind = 'purchase_order' AND vendor_id = ? AND sku = ? "
            "AND size = ? AND status = 'pending'", (vendor_id, sku, size)
        ).fetchone()
        if dup:
            return fail(f"Purchase order request #{dup['id']} for {sku} {size} is already pending.", request_id=dup["id"])
        amount = round(p["unit_cost"] * qty, 2)
        cur = conn.execute(
            "INSERT INTO approval_requests (ticket_id, kind, vendor_id, sku, size, qty, amount, reason, requested_by, "
            "requested_at) VALUES (?, 'purchase_order', ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, vendor_id, sku, size, qty, amount, reason.strip()[:500], requested_by, now_stamp()),
        )
        vendor = vendor_summary(conn, v, today)
        cash, pending = checking_balance(conn), pending_total(conn)
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {
        "ok": True, "request_id": cur.lastrowid, "status": "pending", "amount": amount,
        "vendor": v["name"], "lead_days": v["lead_days"],
        "blocked_until_paid": [i["invoice_id"] for i in vendor["blocking_invoices"]],
        "checking_balance": cash, "pending_total": pending,
        "message": (f"PO request #{cur.lastrowid} saved for human approval. "
                    + ("It can't be approved until the vendor's open invoice(s) are paid. " if not vendor["can_ship"] else "")
                    + "No money has moved."),
    }


@mcp.tool
def draft_customer_message(ticket_id: int, subject: str, body: str, written_by: AgentName) -> dict:
    """Save a draft message to the ticket's requester. Nothing is ever sent.

    The recipient is always the ticket's requester (taken from the database).
    The draft stays on the board for a human to review.
    """
    if not subject.strip() or not body.strip():
        return fail("Subject and body are required.")
    conn = connect_write()
    try:
        t = conn.execute("SELECT requester FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return fail(f"Ticket {ticket_id} not found.")
        cur = conn.execute(
            "INSERT INTO customer_drafts (ticket_id, recipient, subject, body, written_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticket_id, t["requester"], subject.strip()[:200], body.strip()[:4000], written_by, now_stamp()),
        )
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {"ok": True, "draft_id": cur.lastrowid, "recipient": t["requester"], "status": "draft",
            "message": "Draft saved on the board. It has NOT been sent."}


@mcp.tool
def add_ticket_note(ticket_id: int, note: str, author: AgentName | Literal["System"]) -> dict:
    """Add a short working note to a ticket (findings, plans, hand-offs).

    Agents use their own name. "System" is reserved for the backend's notes when a run
    stops at an execution limit.
    """
    if not note.strip():
        return fail("Note is empty.")
    conn = connect_write()
    try:
        if conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return fail(f"Ticket {ticket_id} not found.")
        cur = conn.execute(
            "INSERT INTO ticket_notes (ticket_id, author, note, created_at) VALUES (?, ?, ?, ?)",
            (ticket_id, author, note.strip()[:1000], now_stamp()),
        )
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {"ok": True, "note_id": cur.lastrowid}


@mcp.tool
def update_ticket_status(ticket_id: int, status: AgentTicketStatus, note: str, updated_by: AgentName) -> dict:
    """Change a ticket's status and record why (as a ticket note).

    A ticket can't be marked 'resolved' while it still has pending approval
    requests; use 'waiting_on_approval' instead.
    """
    conn = connect_write()
    try:
        t = conn.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return fail(f"Ticket {ticket_id} not found.")
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM approval_requests WHERE ticket_id = ? AND status = 'pending'", (ticket_id,)
        ).fetchone()["n"]
        if status == "resolved" and pending:
            return fail(f"Ticket {ticket_id} has {pending} pending approval request(s); it can't be resolved yet.")
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
        conn.execute(
            "INSERT INTO ticket_notes (ticket_id, author, note, created_at) VALUES (?, ?, ?, ?)",
            (ticket_id, updated_by, f"Status {t['status']} -> {status}. {note.strip()[:800]}", now_stamp()),
        )
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {"ok": True, "ticket_id": ticket_id, "old_status": t["status"], "new_status": status}


def _discount_request(conn: sqlite3.Connection, t: sqlite3.Row, p: sqlite3.Row, discount_pct: float,
                      requested_by: str, reason: str) -> dict:
    """Create a pending 'discount' approval request (no cash moves when approved)."""
    dup = conn.execute(
        "SELECT id FROM approval_requests WHERE ticket_id = ? AND kind = 'discount' AND status = 'pending'", (t["id"],)
    ).fetchone()
    if dup:
        return fail(f"Discount approval #{dup['id']} for ticket {t['id']} is already waiting for a human.",
                    request_id=dup["id"])
    qty = t["qty"] or 0
    unit_price = round(p["list_price"] * (1 - discount_pct / 100), 2)
    discount_value = round((p["list_price"] - unit_price) * qty, 2)
    cur = conn.execute(
        "INSERT INTO approval_requests (ticket_id, kind, sku, size, qty, amount, reason, requested_by, requested_at, "
        "discount_pct) VALUES (?, 'discount', ?, ?, ?, ?, ?, ?, ?, ?)",
        (t["id"], t["sku"], t["size"], qty, discount_value, reason.strip()[:500], requested_by, now_stamp(), discount_pct),
    )
    return {"ok": True, "request_id": cur.lastrowid, "discount_value": discount_value}


@mcp.tool
def record_discount_decision(ticket_id: int, discount_pct: float, rationale: str, decided_by: AgentName) -> dict:
    """Record the Boss's discount decision for a price-override ticket and send it to a human for approval.

    Uses the ticket's SKU and qty. Refuses any discount that would price the item below
    unit cost. Saves the decision as a ticket note AND creates a pending 'discount'
    approval request; the discount only counts once a human approves it. No cash moves.
    """
    if decided_by != "Boss":
        return fail("Only the Boss can make the final discount decision.")
    if not 0 <= discount_pct < 100:
        return fail("discount_pct must be between 0 and 99.")
    conn = connect_write()
    try:
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None or not t["sku"]:
            return fail(f"Ticket {ticket_id} not found or has no SKU.")
        p = conn.execute("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (t["sku"],)).fetchone()
        unit_price = round(p["list_price"] * (1 - discount_pct / 100), 2)
        if unit_price < p["unit_cost"]:
            return fail(f"${unit_price} is below the ${p['unit_cost']} unit cost. Not allowed.")
        qty = t["qty"] or 0
        total, cost = round(unit_price * qty, 2), round(p["unit_cost"] * qty, 2)
        margin_pct = round((total - cost) / total * 100, 1) if total else None
        req = _discount_request(conn, t, p, discount_pct, decided_by, rationale)
        if not req["ok"]:
            return req
        note = (f"DISCOUNT DECISION (pending human approval #{req['request_id']}): {discount_pct:g}% off {t['sku']} "
                f"-> ${unit_price}/unit, {qty} units = ${total:,.2f} (margin {margin_pct}%). {rationale.strip()[:600]}")
        conn.execute(
            "INSERT INTO ticket_notes (ticket_id, author, note, created_at) VALUES (?, ?, ?, ?)",
            (ticket_id, decided_by, note, now_stamp()),
        )
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {"ok": True, "ticket_id": ticket_id, "discount_pct": discount_pct, "unit_price": unit_price,
            "order_total": total, "margin_pct": margin_pct, "approval_request_id": req["request_id"],
            "status": "pending human approval",
            "message": f"Discount sent to the approval inbox as request #{req['request_id']}. "
                       "Don't quote it to the customer until a human approves it."}


@mcp.tool
def request_discount_approval(ticket_id: int, discount_pct: float, requested_by: AgentName, reason: str) -> dict:
    """Create a pending discount approval for a ticket without writing a new decision note.

    Used by the backend to send an already-recorded discount decision to the inbox.
    Same checks as record_discount_decision (never below unit cost, one pending discount per ticket).
    """
    if not 0 <= discount_pct < 100:
        return fail("discount_pct must be between 0 and 99.")
    conn = connect_write()
    try:
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None or not t["sku"]:
            return fail(f"Ticket {ticket_id} not found or has no SKU.")
        p = conn.execute("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (t["sku"],)).fetchone()
        if round(p["list_price"] * (1 - discount_pct / 100), 2) < p["unit_cost"]:
            return fail("That discount would price the item below unit cost. Not allowed.")
        req = _discount_request(conn, t, p, discount_pct, requested_by, reason)
        if not req["ok"]:
            return req
        conn.execute(
            "INSERT INTO ticket_notes (ticket_id, author, note, created_at) VALUES (?, ?, ?, ?)",
            (ticket_id, "System", f"Discount approval #{req['request_id']} ({discount_pct:g}%) sent to the human "
                                  f"approval inbox. {reason.strip()[:300]}", now_stamp()),
        )
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {"ok": True, "ticket_id": ticket_id, "approval_request_id": req["request_id"],
            "discount_pct": discount_pct, "discount_value": req["discount_value"], "status": "pending"}


# ---------- Human-only tools (never given to agents) ----------

@mcp.tool
def approve_request(request_id: int, approved_by: str, note: str = "") -> dict:
    """HUMAN ONLY: approve a pending request and make the payment.

    Checks, in one transaction: the request is still pending, the approver is a
    person (not an agent), there's enough cash in checking (no negative
    balances), an invoice is still open, and for purchase orders the vendor has
    no open unpaid invoice. Then it adds a payments row, lowers the checking
    balance, and updates what was paid (invoice -> paid, lease next_due +1 month).
    """
    who = approved_by.strip()
    if who.lower() in NOT_A_HUMAN:
        return fail("Payments need a human approver's name; agents can't approve.")
    conn = connect_write()
    try:
        today = shop_today(conn)
        r = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        if r is None:
            return fail(f"Request {request_id} not found.")
        if r["status"] != "pending":
            return fail(f"Request {request_id} is already {r['status']}.")
        if r["kind"] == "discount":
            effect = (f"{r['discount_pct']:g}% discount approved for ticket {r['ticket_id']} "
                      f"(${r['amount']:,.2f} off list price). No cash moved.")
            conn.execute(
                "UPDATE approval_requests SET status = 'approved', decided_by = ?, decided_at = ?, decision_note = ? "
                "WHERE id = ?", (who, now_stamp(), (note.strip() + " " + effect).strip()[:500], request_id))
            conn.execute(
                "INSERT INTO ticket_notes (ticket_id, author, note, created_at) VALUES (?, ?, ?, ?)",
                (r["ticket_id"], "Human", f"DISCOUNT APPROVED by {who}: {effect}", now_stamp()))
            balance = checking_balance(conn)
            conn.execute("COMMIT")
            return {"ok": True, "request_id": request_id, "ticket_id": r["ticket_id"], "kind": "discount",
                    "payment_id": None, "amount": r["amount"], "discount_pct": r["discount_pct"],
                    "checking_balance": balance, "effect": effect}
        cash = checking_balance(conn)
        if r["amount"] > cash:
            return fail(f"Not enough cash: ${r['amount']:,.2f} needed, ${cash:,.2f} in checking. Payment refused.")
        if r["kind"] == "invoice":
            inv = conn.execute("SELECT status FROM invoices WHERE id = ?", (r["ref_id"],)).fetchone()
            if inv is None or inv["status"] != "open":
                return fail(f"Invoice {r['ref_id']} is no longer open.")
        if r["kind"] == "purchase_order":
            blocking = open_invoices_for(conn, r["vendor_id"])
            if blocking:
                ids = ", ".join(str(i["invoice_id"]) for i in blocking)
                return fail(f"Vendor still has open invoice(s) {ids}; they won't ship. Pay those first.")

        pay = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
            "VALUES (?, ?, ?, 'checking', ?, ?)",
            (r["kind"], r["ref_id"] if r["kind"] != "purchase_order" else r["id"], r["amount"], today, who),
        )
        conn.execute("UPDATE cash_accounts SET balance = balance - ?, date = ? WHERE name = 'checking'",
                     (r["amount"], today))
        effect = ""
        if r["kind"] == "invoice":
            conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (r["ref_id"],))
            effect = f"Invoice {r['ref_id']} marked paid."
        elif r["kind"] == "rent":
            due = conn.execute("SELECT next_due FROM leases WHERE id = ?", (r["ref_id"],)).fetchone()["next_due"]
            conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (add_month(due), r["ref_id"]))
            effect = f"Lease {r['ref_id']} next_due moved {due} -> {add_month(due)}."
        else:
            lead = conn.execute("SELECT lead_days FROM vendors WHERE id = ?", (r["vendor_id"],)).fetchone()["lead_days"]
            effect = f"PO placed; expected arrival {add_days(today, lead)}."
        conn.execute(
            "UPDATE approval_requests SET status = 'paid', decided_by = ?, decided_at = ?, decision_note = ?, "
            "payment_id = ? WHERE id = ?",
            (who, now_stamp(), (note.strip() + " " + effect).strip()[:500], pay.lastrowid, request_id),
        )
        new_balance = checking_balance(conn)
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {"ok": True, "request_id": request_id, "ticket_id": r["ticket_id"], "payment_id": pay.lastrowid,
            "amount": r["amount"], "checking_balance": new_balance, "effect": effect}


@mcp.tool
def reject_request(request_id: int, rejected_by: str, reason: str) -> dict:
    """HUMAN ONLY: reject a pending request. No money moves."""
    who = rejected_by.strip()
    if who.lower() in NOT_A_HUMAN:
        return fail("Rejections need a human's name.")
    conn = connect_write()
    try:
        r = conn.execute("SELECT status, ticket_id FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        if r is None:
            return fail(f"Request {request_id} not found.")
        if r["status"] != "pending":
            return fail(f"Request {request_id} is already {r['status']}.")
        conn.execute(
            "UPDATE approval_requests SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? "
            "WHERE id = ?", (who, now_stamp(), reason.strip()[:500], request_id),
        )
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {"ok": True, "request_id": request_id, "ticket_id": r["ticket_id"], "status": "rejected"}


@mcp.tool
def sync_ticket_status(ticket_id: int, updated_by: str) -> dict:
    """HUMAN ONLY: set a ticket's status from the human decisions on its approval requests. No agents run.

    Rules: any request still pending -> waiting_on_approval (pending a human); every request
    paid -> approved; every request rejected -> rejected; some paid and some rejected ->
    partially_approved. A ticket with no approval requests, or one already resolved, is left as is.
    """
    who = updated_by.strip()
    if who.lower() in NOT_A_HUMAN:
        return fail("Only a human (the dashboard) can sync a ticket's status from approvals.")
    conn = connect_write()
    try:
        t = conn.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return fail(f"Ticket {ticket_id} not found.")
        reqs = [r["status"] for r in conn.execute(
            "SELECT status FROM approval_requests WHERE ticket_id = ?", (ticket_id,))]
        counts = {k: reqs.count(k) for k in ("pending", "paid", "rejected")}
        counts["paid"] += reqs.count("approved")  # discount approvals (no payment) count as approved
        old = t["status"]
        if old == "resolved":
            new, reason = old, "Ticket is already resolved; left unchanged."
        elif not reqs:
            new, reason = old, "No approval requests on this ticket, so there is no human decision to apply."
        elif counts["pending"]:
            new, reason = "waiting_on_approval", f"{counts['pending']} request(s) still waiting for a human decision."
        elif counts["paid"] and not counts["rejected"]:
            new, reason = "approved", f"All {counts['paid']} request(s) approved by a human."
        elif counts["rejected"] and not counts["paid"]:
            new, reason = "rejected", f"All {counts['rejected']} request(s) rejected by a human."
        else:
            new, reason = "partially_approved", f"{counts['paid']} approved and {counts['rejected']} rejected by a human."
        if new != old:
            conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (new, ticket_id))
            conn.execute(
                "INSERT INTO ticket_notes (ticket_id, author, note, created_at) VALUES (?, ?, ?, ?)",
                (ticket_id, "Human", f"Status {old} -> {new} (synced from approvals by {who[:60]}). {reason}", now_stamp()),
            )
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {"ok": True, "ticket_id": ticket_id, "old_status": old, "new_status": new, "changed": new != old,
            "approved": counts["paid"], "rejected": counts["rejected"], "pending": counts["pending"], "reason": reason}


@mcp.tool
def undo_decision(request_id: int, undone_by: str, reason: str) -> dict:
    """HUMAN ONLY: take back a human decision so the request is pending again (then decide again).

    - rejected -> pending.
    - approved discount -> pending (no cash was involved).
    - paid -> the payment is reversed: a 'reversal' row (negative amount) is added to payments,
      the money goes back to checking, and what was paid is restored (invoice -> open,
      lease next_due back one month). Refused if a later payment depends on it (e.g. a paid
      PO to the same vendor after this invoice, or a later rent payment).
    """
    who = undone_by.strip()
    if who.lower() in NOT_A_HUMAN:
        return fail("Only a human can undo a decision.")
    if len(reason.strip()) < 3:
        return fail("Give a short reason for undoing the decision.")
    conn = connect_write()
    try:
        today = shop_today(conn)
        r = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        if r is None:
            return fail(f"Request {request_id} not found.")
        if r["status"] == "pending":
            return fail(f"Request {request_id} hasn't been decided yet; there's nothing to undo.")
        old = r["status"]
        effect = ""
        reversal_id = None
        if old == "paid":
            pay = conn.execute("SELECT * FROM payments WHERE id = ?", (r["payment_id"],)).fetchone()
            if pay is None:
                return fail(f"Payment for request {request_id} not found; can't reverse it.")
            if conn.execute("SELECT 1 FROM payments WHERE kind = 'reversal' AND ref_id = ?", (pay["id"],)).fetchone():
                return fail(f"Payment #{pay['id']} was already reversed.")
            if r["kind"] == "invoice":
                later_po = conn.execute(
                    "SELECT id FROM approval_requests WHERE kind = 'purchase_order' AND vendor_id = ? AND status = 'paid' "
                    "AND payment_id > ?", (r["vendor_id"], pay["id"])).fetchone()  # paid after this invoice
                if later_po:
                    return fail(f"Purchase order #{later_po['id']} to the same vendor was paid after this invoice "
                                "(it relied on the invoice being paid). Undo that one first.")
                conn.execute("UPDATE invoices SET status = 'open' WHERE id = ?", (r["ref_id"],))
                effect = f"Invoice {r['ref_id']} is open (unpaid) again."
            elif r["kind"] == "rent":
                later = conn.execute(
                    "SELECT id FROM payments WHERE kind = 'rent' AND ref_id = ? AND id > ? AND id NOT IN "
                    "(SELECT ref_id FROM payments WHERE kind = 'reversal')", (r["ref_id"], pay["id"])).fetchone()
                if later:
                    return fail(f"A later rent payment (#{later['id']}) exists. Undo that one first.")
                due = conn.execute("SELECT next_due FROM leases WHERE id = ?", (r["ref_id"],)).fetchone()["next_due"]
                conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (sub_month(due), r["ref_id"]))
                effect = f"Lease {r['ref_id']} next_due moved back {due} -> {sub_month(due)}."
            else:
                effect = "Purchase order cancelled (no stock had been received)."
            cur = conn.execute(
                "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
                "VALUES ('reversal', ?, ?, 'checking', ?, ?)", (pay["id"], -pay["amount"], today, who))
            reversal_id = cur.lastrowid
            conn.execute("UPDATE cash_accounts SET balance = balance + ?, date = ? WHERE name = 'checking'",
                         (pay["amount"], today))
            effect = f"Payment #{pay['id']} reversed: ${pay['amount']:,.2f} back to checking. " + effect
        elif old == "approved":
            effect = f"{r['discount_pct']:g}% discount approval withdrawn; the discount is not approved anymore."
        else:
            effect = "Rejection withdrawn."
        history = (f"Was {old} by {r['decided_by']} at {r['decided_at']}; undone by {who} at {now_stamp()}: "
                   f"{reason.strip()[:200]}")
        conn.execute(
            "UPDATE approval_requests SET status = 'pending', decided_by = NULL, decided_at = NULL, payment_id = NULL, "
            "decision_note = ? WHERE id = ?", (history[:500], request_id))
        conn.execute(
            "INSERT INTO ticket_notes (ticket_id, author, note, created_at) VALUES (?, ?, ?, ?)",
            (r["ticket_id"], "Human", f"DECISION UNDONE on request #{request_id} ({r['kind']}, was {old}) by {who}. "
                                      f"{effect} Reason: {reason.strip()[:200]}", now_stamp()))
        balance = checking_balance(conn)
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
    return {"ok": True, "request_id": request_id, "ticket_id": r["ticket_id"], "kind": r["kind"],
            "old_status": old, "new_status": "pending", "reversal_payment_id": reversal_id,
            "checking_balance": balance, "effect": effect}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Campus Customs MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve Streamable HTTP on port 8001 (keeps FastAPI free on 8000)",
    )
    args = parser.parse_args()
    if args.http:
        mcp.run(transport="http", host="127.0.0.1", port=8001)
    else:
        mcp.run()
