"""Test the human-decision status sync through the real API routes, on a throwaway database.

Uses FastAPI's TestClient in-process, with the MCP server pointed at a temp copy
(CAMPUS_CUSTOMS_DB) and the audit trail redirected to a temp file, so neither the
working database nor output/audit_trail.json is touched. No AI calls.

Run from this folder:  .venv/Scripts/python test_sync.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
db = tmp / "campus_customs_sync_test.db"
shutil.copy(ROOT / "data" / "campus_customs.db", db)
os.environ["CAMPUS_CUSTOMS_DB"] = str(db)

import audit  # noqa: E402
audit.AUDIT_PATH = tmp / "audit_sync_test.json"
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

HUMAN = {"X-Human-Approval": "true"}
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n       {detail}" if not ok else ""))


with TestClient(main.app) as c:
    import asyncio  # noqa: F401  (TestClient runs the app's event loop for us)

    def mcp(tool, **args):
        return c.portal.call(lambda: main.mcp_call(tool, **args))

    status = lambda t: next(x for x in c.get("/api/tickets").json()["tickets"] if x["id"] == t)

    # Agents (here: direct MCP calls) create requests
    r1 = mcp("request_payment", kind="invoice", ref_id=501, requested_by="Accounting", reason="test", ticket_id=101)
    r2 = mcp("request_payment", kind="rent", ref_id=1, requested_by="Accounting", reason="test", ticket_id=102)
    mcp("update_ticket_status", ticket_id=101, status="waiting_on_approval", note="test", updated_by="Boss")
    t = status(101)
    check("before any human action: ticket 101 shows pending (1 pending decision)",
          t["status"] == "waiting_on_approval" and t["pending_approvals"] == 1, t)

    res = c.post(f"/api/approvals/{r1['request_id']}/approve", json={"approved_by": "Jane Doe", "confirm": True}, headers=HUMAN).json()
    check("approve -> ticket 101 auto-synced to approved", res["ticket_status"]["new_status"] == "approved", res)
    t = status(101)
    check("ticket list shows 101 approved with 1 human approval",
          t["status"] == "approved" and t["approved_by_human"] == 1 and t["pending_approvals"] == 0, t)

    res = c.post(f"/api/approvals/{r2['request_id']}/reject",
                 json={"rejected_by": "Jane Doe", "reason": "testing reject", "confirm": True}, headers=HUMAN).json()
    check("reject -> ticket 102 auto-synced to rejected", res["ticket_status"]["new_status"] == "rejected", res)
    t = status(102)
    check("ticket list shows 102 rejected with 1 human rejection", t["status"] == "rejected" and t["rejected_by_human"] == 1, t)

    # Mixed decisions on one ticket
    p1 = mcp("request_purchase_order", vendor_id=1, sku="CC-HOOD-NAVY", size="M", qty=2, requested_by="Accounting", reason="t", ticket_id=103)
    p2 = mcp("request_purchase_order", vendor_id=1, sku="CC-HOOD-NAVY", size="L", qty=2, requested_by="Accounting", reason="t", ticket_id=103)
    res = c.post("/api/tickets/103/sync-status").json()
    check("Update button with requests still pending -> 103 shows pending", res["new_status"] == "waiting_on_approval", res)
    c.post(f"/api/approvals/{p1['request_id']}/approve", json={"approved_by": "Jane Doe", "confirm": True}, headers=HUMAN)
    res = c.post(f"/api/approvals/{p2['request_id']}/reject",
                 json={"rejected_by": "Jane Doe", "reason": "only need M", "confirm": True}, headers=HUMAN).json()
    check("one approved + one rejected -> 103 partially_approved", res["ticket_status"]["new_status"] == "partially_approved", res)

    res = c.post("/api/tickets/999/sync-status")
    check("Update on a missing ticket -> 404", res.status_code == 404, res.json())

    # Undo
    res = c.post(f"/api/approvals/{p1['request_id']}/undo", json={"undone_by": "Jane Doe", "reason": "test", "confirm": True})
    check("undo without the human header -> 403", res.status_code == 403, res.json())
    res = c.post(f"/api/approvals/{p1['request_id']}/undo", json={"undone_by": "AI Assistant", "reason": "test", "confirm": True}, headers=HUMAN)
    check("undo as an AI name -> 422", res.status_code == 422, res.json())
    cash0 = c.get("/api/cash").json()["balance"]
    res = c.post(f"/api/approvals/{p1['request_id']}/undo", json={"undone_by": "Jane Doe", "reason": "test undo", "confirm": True}, headers=HUMAN)
    body = res.json()
    cash = c.get("/api/cash").json()
    check("undo a paid PO -> pending, $44 back to checking, ticket 103 back to pending",
          res.status_code == 200 and body["new_status"] == "pending" and cash["balance"] == cash0 + 44
          and body["ticket_status"]["new_status"] == "waiting_on_approval", body)
    check("cash route shows the reversal (net total paid)", cash["total_reversed"] == 44, cash["total_reversed"])
    res = c.post(f"/api/approvals/{p1['request_id']}/approve", json={"approved_by": "Jane Doe", "confirm": True}, headers=HUMAN)
    check("after undo the request can be decided again", res.status_code == 200, res.json())
    res = c.post(f"/api/approvals/{p1['request_id']}/approve", json={"approved_by": "Jane Doe", "confirm": True}, headers=HUMAN)
    check("but only one decision at a time (second approve -> 409)", res.status_code == 409, res.json())
    res = c.post(f"/api/approvals/{r1['request_id']}/undo", json={"undone_by": "Jane Doe", "reason": "test", "confirm": True}, headers=HUMAN)
    check("can't undo the invoice while a later PO to the same vendor is paid -> 409",
          res.status_code == 409 and "Undo that one first" in res.json()["error"]["message"], res.json())

    events = [e["event"] for e in main.read_events()]
    check("status changes logged as human status_sync events (temp audit file)", events.count("status_sync") >= 3, events)

check("real working database untouched by this test",
      "campus_customs_sync_test" in os.environ["CAMPUS_CUSTOMS_DB"], os.environ["CAMPUS_CUSTOMS_DB"])
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
