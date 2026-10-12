"""Test the running API (start it first: uvicorn main:app --reload --port 8000).

1. Reset, then check every read route against the database (read-only SQLite here, test only).
2. Approval guardrails: no header, agent/AI names, single names, confirm=false, unknown request.
3. One real agent run (ticket 102, gpt-6-luna). While it runs: status is busy, reset and a
   second run are refused, and activity events appear. Nothing is approved or paid.
4. Reset again, so the working copy is back to the original for the full run.

Run from this folder:  .venv/Scripts/python test_api.py [--no-agents]
"""

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = ROOT / "data" / "campus_customs.db"
WORKING = ROOT / "data" / "campus_customs_new.db"
HUMAN = {"X-Human-Approval": "true"}
results: list[dict] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    results.append({"test": name, "passed": bool(ok), **({"detail": detail} if detail != "" else {})})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n       {json.dumps(detail, default=str)[:300]}" if detail != "" else ""))


def db_rows(sql: str, *args) -> list[dict]:
    """Independent read of the working DB, only to verify what the API returned."""
    conn = sqlite3.connect(f"{WORKING.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def main(run_agents: bool) -> int:
    original_hash = sha(ORIGINAL)
    async with httpx.AsyncClient(base_url=BASE, timeout=600) as c:
        # ---------- 1. Reset + reads ----------
        r = await c.post("/api/reset", json={"confirm": True})
        check("POST /api/reset restores the working copy (hash = original)",
              r.status_code == 200 and r.json()["sha256"] == original_hash and sha(WORKING) == original_hash, r.json())
        r = await c.post("/api/reset", json={"confirm": False})
        check("POST /api/reset without confirm=true -> 422", r.status_code == 422, r.json())

        r = (await c.get("/api/health")).json()
        check("GET /api/health: MCP connected, model gpt-6-luna", r["mcp_connected"] and r["model"] == "gpt-6-luna", r)

        r = (await c.get("/api/tickets")).json()
        db = db_rows("SELECT id, status, requester FROM tickets ORDER BY id")
        api = [{"id": t["id"], "status": t["status"], "requester": t["requester"]} for t in r["tickets"]]
        check("GET /api/tickets: 101/102/103 with status matching the DB",
              sorted(api, key=lambda t: t["id"]) == db and [t["id"] for t in db] == [101, 102, 103], api)

        r = (await c.get("/api/tickets/101")).json()
        check("GET /api/tickets/101: tee S stock 0, invoice 501 blocks vendor",
              r["stock"]["qty_in_requested_size"] == db_rows(
                  "SELECT qty FROM inventory WHERE sku='CC-TEE-WHITE' AND size='S'")[0]["qty"] == 0
              and r["invoice"]["id"] == 501 and r["vendor"]["can_ship"] is False, r["stock"])
        r = await c.get("/api/tickets/999")
        check("GET /api/tickets/999 -> 404 with error shape",
              r.status_code == 404 and r.json()["error"]["code"] == "ticket_not_found", r.json())

        r = (await c.get("/api/cash")).json()
        bal = db_rows("SELECT balance FROM cash_accounts WHERE name='checking'")[0]["balance"]
        check("GET /api/cash: checking balance matches cash_accounts ($3,400), nothing pending",
              r["balance"] == bal == 3400 and r["pending_approvals_total"] == 0 and r["payments"] == [], r)

        r = (await c.get("/api/approvals")).json()
        check("GET /api/approvals: empty after reset", r["requests"] == [], r)

        r = await c.options("/api/tickets", headers={"Origin": "http://localhost:5173",
                                                     "Access-Control-Request-Method": "GET"})
        check("CORS allows the local React dev server", r.headers.get("access-control-allow-origin") == "http://localhost:5173",
              dict(r.headers))

        # ---------- 2. Approval guardrails (nothing gets paid) ----------
        good = {"approved_by": "Jane Doe", "confirm": True}
        r = await c.post("/api/approvals/1/approve", json=good)
        check("approve without X-Human-Approval header -> 403", r.status_code == 403, r.json())
        for name in ["Boss", "Accounting Agent", "Antonio", "gpt-6-luna", "AI Assistant", "System Auto"]:
            r = await c.post("/api/approvals/1/approve", json={"approved_by": name, "confirm": True}, headers=HUMAN)
            check(f"approve as {name!r} -> 422 (not a real human name)", r.status_code == 422, r.json()["error"]["message"])
        r = await c.post("/api/approvals/1/approve", json={"approved_by": "Jane Doe", "confirm": False}, headers=HUMAN)
        check("approve with confirm=false -> 422", r.status_code == 422, r.json())
        r = await c.post("/api/approvals/999/approve", json=good, headers=HUMAN)
        check("approve unknown request -> 409 from the MCP tool's checks",
              r.status_code == 409 and "not found" in r.json()["error"]["message"], r.json())

        # ---------- 3. Agent run (ticket 102) ----------
        if run_agents:
            before = (await c.get("/api/activity")).json()["next_since"]
            run_task = asyncio.create_task(c.post("/api/tickets/102/run"))
            await asyncio.sleep(4)
            s = (await c.get("/api/status")).json()
            check("while running: /api/status is busy on ticket 102", s["busy"] and s["ticket_id"] == 102, s)
            r = await c.post("/api/reset", json={"confirm": True})
            check("while running: reset refused (409 busy)", r.status_code == 409 and r.json()["error"]["code"] == "busy",
                  r.json()["error"]["message"])
            r = await c.post("/api/tickets/101/run")
            check("while running: a second run refused (409 busy)", r.status_code == 409, r.json()["error"]["message"])
            mid = (await c.get("/api/activity", params={"since": before, "run_id": s["run_id"]})).json()
            check("while running: activity already shows events for this run", mid["count"] > 0,
                  [e["text"][:90] for e in mid["events"][:4]])

            r = await run_task
            body = r.json()
            run = body.get("run", {})
            check("POST /api/tickets/102/run finished with a final answer",
                  r.status_code == 200 and run.get("stop_reason") == "final_answer",
                  {k: run.get(k) for k in ("run_id", "stop_reason", "model_requests", "tool_calls", "delegations",
                                           "input_tokens", "output_tokens")} if run else body)
            if run:
                print("\nBoss summary:", run["output"]["summary"])
                ev = (await c.get("/api/activity", params={"run_id": run["run_id"], "limit": 1000})).json()["events"]
                kinds = {e["event"] for e in ev}
                tools = sorted({e["tool"] for e in ev if e["event"] == "tool_call"})
                agents_seen = sorted({e["agent"] for e in ev})
                check("activity for the run has agents, delegations, MCP tools, and a final answer",
                      {"delegate", "tool_call", "final_answer", "run_end"} <= kinds and len(agents_seen) >= 2,
                      {"agents": agents_seen, "tools": tools, "events": len(ev)})
                for e in ev:
                    if e["event"] in ("delegate", "delegation_result", "final_answer", "run_end"):
                        print("  ", e["text"][:160])
                cash = (await c.get("/api/cash")).json()
                appr = (await c.get("/api/approvals")).json()["requests"]
                check("after the run: no money moved ($3,400, 0 payments)",
                      cash["balance"] == 3400 and cash["payments"] == [] and
                      db_rows("SELECT COUNT(*) n FROM payments")[0]["n"] == 0, cash)
                check("after the run: any requests are pending (waiting for a human)",
                      all(a["status"] == "pending" for a in appr),
                      [(a["id"], a["kind"], a["amount"], a["status"], a["requested_by"]) for a in appr])
                t = (await c.get("/api/tickets/102")).json()
                check("after the run: ticket 102 not marked resolved while approval is pending",
                      not (t["ticket"]["status"] == "resolved" and any(a["status"] == "pending" for a in appr)),
                      {"status": t["ticket"]["status"], "notes": len(t["notes"])})
                if appr:
                    r = await c.post(f"/api/approvals/{appr[0]['id']}/approve",
                                     json={"approved_by": "Boss", "confirm": True}, headers=HUMAN)
                    check("the real pending request can't be approved as 'Boss' (422); left pending",
                          r.status_code == 422, r.json()["error"]["message"])

            # ---------- 4. Reset for a clean full run ----------
            r = await c.post("/api/reset", json={"confirm": True})
            check("final reset: working copy = original again", r.status_code == 200 and sha(WORKING) == original_hash,
                  r.json())
            tickets = (await c.get("/api/tickets")).json()["tickets"]
            check("after reset: all tickets open, no approvals",
                  all(t["status"] == "open" and t["approval_requests"] == 0 for t in tickets),
                  [(t["id"], t["status"]) for t in tickets])

    check("original database never changed", sha(ORIGINAL) == original_hash, original_hash)
    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed")
    (ROOT / "output" / "api_tests.json").write_text(
        json.dumps({"passed": passed, "total": len(results), "results": results}, indent=2, default=str) + "\n",
        encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--no-agents", action="store_true", help="skip the live agent run")
    sys.exit(asyncio.run(main(not p.parse_args().no_agents)))
