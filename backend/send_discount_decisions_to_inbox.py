"""One-time fix: send discount decisions recorded BEFORE discount approvals existed to the approval inbox.

For each ticket with a Boss "DISCOUNT DECISION" note but no discount approval request, create a
pending discount approval through the MCP server (request_discount_approval), using the
percentage the Boss actually recorded. Nothing is approved here: a human still decides in the
dashboard. The action is logged in the audit trail as a System event.

Run from this folder (backend running or not):  .venv/Scripts/python send_discount_decisions_to_inbox.py
"""

import asyncio
import re

import agents
import audit
from models import AuditEntry

DECISION = re.compile(r"^DISCOUNT DECISION(?: \(pending[^)]*\))?: ([\d.]+)% off")


async def main() -> None:
    async with agents.mcp_client() as c:
        call = lambda tool, **a: c.call_tool(tool, a)  # noqa: E731
        board = (await call("list_tickets")).structured_content
        for t in board["tickets"]:
            detail = (await call("get_ticket", ticket_id=t["id"])).structured_content
            if any(r["kind"] == "discount" for r in detail["approval_requests"]):
                continue
            decisions = [(n, DECISION.match(n["note"])) for n in detail["notes"] if n["author"] == "Boss"]
            decisions = [(n, m) for n, m in decisions if m]
            if not decisions:
                continue
            note, m = decisions[-1]  # the Boss's latest decision
            pct = float(m.group(1))
            reason = (f"From the Boss's discount decision recorded {note['created_at']} (made before discount "
                      f"approvals existed): {note['note'][:220]}")
            res = (await call("request_discount_approval", ticket_id=t["id"], discount_pct=pct,
                              requested_by="Boss", reason=reason)).structured_content
            print(f"ticket {t['id']}: {res}")
            if res.get("ok"):
                audit.append(AuditEntry(
                    time=audit.now(), run_id="system", mode="run", ticket_id=t["id"], agent="System", depth=0,
                    event="approval_created",
                    result=f"Discount approval #{res['approval_request_id']} ({pct:g}%, ${res['discount_value']:,.2f} off) "
                           f"sent to the inbox from the Boss's recorded decision; waiting for a human.",
                ))


if __name__ == "__main__":
    asyncio.run(main())
