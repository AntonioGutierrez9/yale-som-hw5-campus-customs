"""Guardrail tests for the MCP server — no AI calls, no changes to the working database.

Copies the ORIGINAL database to a temp file, points the server at it with
CAMPUS_CUSTOMS_DB, and calls every tool through FastMCP's in-memory client.
Payments here are approved by a pretend human on the throwaway copy only.

Run from this folder:  .venv/Scripts/python test_server.py
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
tmp = Path(tempfile.mkdtemp()) / "campus_customs_test.db"
shutil.copy(HERE.parent / "data" / "campus_customs.db", tmp)
os.environ["CAMPUS_CUSTOMS_DB"] = str(tmp)

from fastmcp import Client  # noqa: E402
from server import mcp  # noqa: E402

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if not ok else ""))


async def main() -> None:
    async with Client(mcp) as c:
        async def call(tool: str, **args):
            return (await c.call_tool(tool, args, raise_on_error=False)).structured_content

        names = {t.name for t in await c.list_tools()}
        check("25 tools registered", len(names) == 25, sorted(names))

        # Reads
        t = await call("get_ticket", ticket_id=101)
        check("get_ticket 101: tee S stock 0, invoice 501 blocks Bulldog Print Co",
              t["stock"]["qty_in_requested_size"] == 0 and t["vendor"]["can_ship"] is False
              and t["invoice"]["days_overdue"] == 3, t)
        t = await call("get_ticket", ticket_id=103)
        check("get_ticket 103: 12 short in M", t["stock"]["shortfall"] == 12, t["stock"])
        t = await call("get_ticket", ticket_id=102)
        check("get_ticket 102: rent due in 2 days", t["lease"]["days_until_due"] == 2, t.get("lease"))
        q = await call("quote_bulk_order", sku="CC-HOOD-NAVY", size="M", qty=20, discount_pct=15)
        check("quote 20 hoodies at 15% = $986.00, 55.4% margin",
              q["order_total"] == 986.0 and q["margin_pct"] == 55.4 and q["shortfall"] == 12, q)
        q = await call("quote_bulk_order", sku="CC-HOOD-NAVY", size="M", qty=20, discount_pct=70)
        check("quote flags a below-cost discount", q["below_cost"] is True, q)
        v = await call("list_vendors")
        check("list_vendors: only vendor 1 blocked",
              [x["can_ship"] for x in v["vendors"]] == [False, True, True], v)
        r = await call("plan_restock", sku="CC-HOOD-NAVY", size="M", qty=12, vendor_id=1)
        check("plan_restock 12 hoodies: $264, blocked", r["order_cost"] == 264 and not r["vendor"]["can_ship"], r)

        # Agent write tools
        r1 = await call("request_payment", kind="invoice", ref_id=501, requested_by="Accounting",
                        reason="Overdue; blocks tee restock", ticket_id=101)
        check("request_payment invoice 501 -> pending, amount from DB", r1["ok"] and r1["amount"] == 840, r1)
        dup = await call("request_payment", kind="invoice", ref_id=501, requested_by="Accounting", reason="again")
        check("duplicate payment request refused", dup["ok"] is False, dup)
        fin = await call("get_financial_status")
        check("requesting moved no money (still $3,400)", fin["total_cash"] == 3400, fin["total_cash"])
        r2 = await call("request_payment", kind="rent", ref_id=1, requested_by="Facilities",
                        reason="Rent due 9/02", ticket_id=102)
        check("request_payment rent -> pending $2,400", r2["ok"] and r2["amount"] == 2400, r2)
        po = await call("request_purchase_order", vendor_id=1, sku="CC-HOOD-NAVY", size="M", qty=12,
                        requested_by="Inventory", reason="Ticket 103 shortfall", ticket_id=103)
        check("PO request saved but flagged blocked by invoice 501", po["ok"] and po["blocked_until_paid"] == [501], po)
        bad = await call("request_purchase_order", vendor_id=1, sku="CC-HOOD-NAVY", size="XXL", qty=1,
                         requested_by="Inventory", reason="x")
        check("PO for a size we don't stock refused", bad["ok"] is False, bad)
        d = await call("draft_customer_message", ticket_id=101, subject="Your tee", body="Hi Tauhid...",
                       written_by="Customer Service")
        check("draft goes to ticket requester, status draft", d["recipient"] == "Tauhid Zaman" and d["status"] == "draft", d)
        s = await call("update_ticket_status", ticket_id=101, status="resolved", note="done", updated_by="Boss")
        check("can't resolve a ticket with a pending approval", s["ok"] is False, s)
        s = await call("record_discount_decision", ticket_id=103, discount_pct=15, rationale="bulk", decided_by="Accounting")
        check("only the Boss can decide a discount", s["ok"] is False, s)
        s = await call("record_discount_decision", ticket_id=103, discount_pct=65, rationale="x", decided_by="Boss")
        check("discount below cost refused", s["ok"] is False, s)
        s = await call("record_discount_decision", ticket_id=103, discount_pct=15, rationale="bulk", decided_by="Boss")
        check("Boss 15% discount recorded and sent to the inbox as a pending discount approval",
              s["ok"] and s["unit_price"] == 49.3 and s["approval_request_id"], s)
        disc_id = s["approval_request_id"]
        lr = await call("list_approval_requests", status="pending")
        cash_pending = sum(r["amount"] for r in lr["requests"] if r["kind"] != "discount")
        check("pending discount isn't counted as cash (pending_total = payments/POs only)",
              lr["pending_total"] == cash_pending and any(r["kind"] == "discount" for r in lr["requests"]), lr["pending_total"])
        s = await call("request_discount_approval", ticket_id=103, discount_pct=10, requested_by="Boss", reason="dup")
        check("a second pending discount for the same ticket is refused", s["ok"] is False, s)
        s = await call("add_ticket_note", ticket_id=999, note="x", author="Boss")
        check("note on missing ticket refused", s["ok"] is False, s)

        # Human-only approvals
        a = await call("approve_request", request_id=r1["request_id"], approved_by="Accounting")
        check("an agent name can't approve", a["ok"] is False, a)
        a = await call("approve_request", request_id=po["request_id"], approved_by="Test Human")
        check("PO approval refused while vendor has open invoice", a["ok"] is False and "501" in a["message"], a)
        a = await call("approve_request", request_id=r1["request_id"], approved_by="Test Human")
        check("human approves invoice 501 -> paid, cash $2,560", a["ok"] and a["checking_balance"] == 2560, a)
        inv = await call("list_invoices", status="open")
        check("invoice 501 no longer open", inv["invoices"] == [], inv)
        a = await call("approve_request", request_id=r1["request_id"], approved_by="Test Human")
        check("same request can't be paid twice", a["ok"] is False, a)
        a = await call("approve_request", request_id=r2["request_id"], approved_by="Test Human")
        check("rent paid -> cash $160, next_due 2026-10-02",
              a["ok"] and a["checking_balance"] == 160 and "2026-10-02" in a["effect"], a)
        a = await call("approve_request", request_id=po["request_id"], approved_by="Test Human")
        check("PO $264 refused: not enough cash ($160)", a["ok"] is False and "Not enough cash" in a["message"], a)
        fin = await call("get_financial_status")
        check("balance never negative", fin["total_cash"] == 160, fin["total_cash"])
        pays = await call("list_payments")
        check("payments table has 2 rows with approver", pays["count"] == 2
              and all(p["approved_by"] == "Test Human" for p in pays["payments"]), pays)
        r = await call("request_payment", kind="rent", ref_id=1, requested_by="Facilities", reason="again")
        check("rent can't be re-requested once paid for the period", r["ok"] is False, r)
        rj = await call("reject_request", request_id=po["request_id"], rejected_by="Test Human", reason="no cash")
        check("human can reject a request", rj["ok"] and rj["status"] == "rejected", rj)

        # Status sync from human decisions (no agents)
        sy = await call("sync_ticket_status", ticket_id=102, updated_by="Boss")
        check("sync refuses an agent name", sy["ok"] is False, sy)
        sy = await call("sync_ticket_status", ticket_id=102, updated_by="Test Human")
        check("ticket 102: rent paid -> approved", sy["new_status"] == "approved" and sy["approved"] == 1, sy)
        sy = await call("sync_ticket_status", ticket_id=103, updated_by="Test Human")
        check("ticket 103: discount still pending -> pending (waiting_on_approval)",
              sy["new_status"] == "waiting_on_approval" and sy["pending"] == 1, sy)
        before = (await call("get_financial_status"))["total_cash"]
        a = await call("approve_request", request_id=disc_id, approved_by="Test Human")
        after = (await call("get_financial_status"))["total_cash"]
        check("approving the discount moves no cash and records no payment",
              a["ok"] and a["kind"] == "discount" and a["payment_id"] is None and before == after, a)
        sy = await call("sync_ticket_status", ticket_id=103, updated_by="Test Human")
        check("ticket 103: discount approved + PO rejected -> partially_approved", sy["new_status"] == "partially_approved", sy)

        # Undo decisions (one decision per request; undo puts it back to pending)
        again = await call("approve_request", request_id=disc_id, approved_by="Test Human")
        check("a decided request can't be decided again", again["ok"] is False, again)
        u = await call("undo_decision", request_id=disc_id, undone_by="Accounting", reason="agent tries")
        check("undo refuses an agent name", u["ok"] is False, u)
        u = await call("undo_decision", request_id=disc_id, undone_by="Test Human", reason="changed my mind")
        check("undo discount approval -> pending, no cash change", u["ok"] and u["new_status"] == "pending"
              and u["reversal_payment_id"] is None, u)
        u = await call("undo_decision", request_id=po["request_id"], undone_by="Test Human", reason="reconsider")
        check("undo a rejection -> pending", u["ok"] and u["old_status"] == "rejected", u)
        cash0 = (await call("get_financial_status"))["total_cash"]
        due0 = (await call("get_lease", lease_id=1))["next_due"]
        u = await call("undo_decision", request_id=r2["request_id"], undone_by="Test Human", reason="wrong amount")
        fin = await call("get_financial_status")
        lease = await call("get_lease", lease_id=1)
        pays = await call("list_payments")
        check("undo rent payment: $2,400 back to checking, lease due moves back, reversal row added",
              u["ok"] and fin["total_cash"] == cash0 + 2400 and lease["next_due"] == "2026-09-02" and due0 == "2026-10-02"
              and any(p["kind"] == "reversal" and p["amount"] == -2400 for p in pays["payments"]), u)
        check("payments total is net of reversals", pays["total_paid"] == 840 and pays["total_reversed"] == 2400, pays["total_paid"])
        u = await call("undo_decision", request_id=r2["request_id"], undone_by="Test Human", reason="again")
        check("can't undo a pending request", u["ok"] is False, u)
        a = await call("approve_request", request_id=r2["request_id"], approved_by="Test Human")
        check("after undo, the request can be decided again (rent paid again)", a["ok"], a)
        sy = await call("sync_ticket_status", ticket_id=101, updated_by="Test Human")
        check("ticket 101: invoice paid -> approved", sy["new_status"] == "approved", sy)
        r3 = await call("request_payment", kind="invoice", ref_id=501, requested_by="Accounting", reason="x")
        check("agents can't set 'approved' themselves (not an agent status)",
              (await c.call_tool("update_ticket_status", {"ticket_id": 101, "status": "approved", "note": "x",
                                                          "updated_by": "Boss"}, raise_on_error=False)).is_error, "")


asyncio.run(main())
passed = sum(ok for _, ok in results)
print(f"\n{passed}/{len(results)} passed (throwaway copy: {tmp})")
sys.exit(0 if passed == len(results) else 1)
