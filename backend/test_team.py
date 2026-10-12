"""Verify the agent team without touching the working database.

Part A (offline, default): scripted stand-in models, no AI calls, no tokens.
  - all five agents initialize and connect to the MCP server
  - each agent sees exactly its own MCP tools + delegate (no human-only tools)
  - an agent can call an MCP tool and get real data back
  - every agent can delegate to every other agent (all 20 directions)
  - loop, depth, and per-run delegation limits refuse correctly
Part B (--live): a few real gpt-6-luna interactions, logged to output/audit_trail.json
  with mode "test". Then checks no money moved.

Both parts run on a throwaway copy of the ORIGINAL database.

Run from this folder:
  .venv/Scripts/python test_team.py           # Part A only
  .venv/Scripts/python test_team.py --live    # Part A + Part B
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import tempfile
from contextlib import ExitStack
from itertools import permutations
from pathlib import Path

from fastmcp import Client
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage, UsageLimits

import agents
import audit
from limits import AgentStepLimit, TicketStepLimit
from models import AGENT_NAMES, AgentName, TeamDeps, TeamRun

ROOT = Path(__file__).resolve().parent.parent
results: list[dict] = []


def check(part: str, name: str, ok: bool, detail: object = "") -> None:
    results.append({"part": part, "test": name, "passed": bool(ok),
                    **({"detail": audit.short(detail, 400)} if detail != "" else {})})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n       {audit.short(detail, 300)}" if detail != "" else ""))


def fresh_db() -> Path:
    path = Path(tempfile.mkdtemp()) / "campus_customs_test.db"
    shutil.copy(ROOT / "data" / "campus_customs.db", path)
    return path


# ---------- Scripted stand-in model (offline) ----------

def scripted(name: AgentName, calls: list[tuple[str, dict]], seen: dict | None = None,
             stubborn: bool = False) -> FunctionModel:
    """Make one tool call per step from `calls`, then give a final report.

    A well-behaved model answers as soon as no tools are offered (the backend hides them on
    an agent's last allowed step). A `stubborn` one keeps calling tools anyway, to test the hard stop.
    """

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen[name] = sorted(t.name for t in info.function_tools)
        done = sum(isinstance(m, ModelResponse) for m in messages)
        if done < len(calls) and (info.function_tools or stubborn):
            tool, args = calls[done]
            return ModelResponse(parts=[ToolCallPart(tool, args)])
        returns = [p.content for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]
        summary = f"{name} done. Last tool result: {audit.short(returns[-1], 150)}" if returns else f"{name} done."
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "agent": name, "summary": summary, "recommendation": "n/a (offline test)"})])

    return FunctionModel(fn)


def tool_returns(messages: list[ModelMessage], tool: str) -> list:
    return [p.content for m in messages for p in getattr(m, "parts", [])
            if isinstance(p, ToolReturnPart) and p.tool_name == tool]


def refusals(run_id: str) -> list[dict]:
    """Refused delegations recorded in the (offline) audit file for one run."""
    entries = json.loads(audit.AUDIT_PATH.read_text(encoding="utf-8"))
    return [e for e in entries if e["run_id"] == run_id and str(e.get("result", "")).startswith("REFUSED")]


async def run_scripted(team, scripts: dict[AgentName, FunctionModel], first: AgentName, task: str, max_delegations=6,
                       run_id: str = "offline", max_depth: int = 4):
    """Run `first` with scripted models for every agent; return its messages and the run state."""
    run = TeamRun(run_id=run_id, team=team, mode="test", max_delegations=max_delegations, max_depth=max_depth)
    deps = TeamDeps(run=run, agent=first, chain=[first])
    with ExitStack() as stack:
        for name, model in scripts.items():
            stack.enter_context(team[name].override(model=model))
        async with team[first].iter(task, deps=deps, usage=RunUsage(),
                                    usage_limits=UsageLimits(request_limit=50)) as agent_run:
            async for _ in agent_run:
                pass
    return agent_run.all_messages(), run


def audit_events(run_id: str) -> list[dict]:
    return [e for e in json.loads(audit.AUDIT_PATH.read_text(encoding="utf-8")) if e["run_id"] == run_id]


async def run_limited(team, scripts: dict[AgentName, FunctionModel], first: AgentName, run_id: str,
                      max_steps: int = 25, max_agent_steps: int = 5):
    """Run through agents.run_agent (where the step limits live). Returns (output or the exception, run)."""
    run = TeamRun(run_id=run_id, team=team, mode="test", max_depth=4, max_steps=max_steps, max_agent_steps=max_agent_steps)
    deps = TeamDeps(run=run, agent=first, chain=[first])
    with ExitStack() as stack:
        for name, model in scripts.items():
            stack.enter_context(team[name].override(model=model))
        try:
            out = await agents.run_agent(deps, "limit test", usage=RunUsage(), usage_limits=UsageLimits(request_limit=50))
        except Exception as exc:  # the limit exceptions are what we're testing
            out = exc
    return out, run


async def part_a() -> None:
    print("\n=== Part A: offline checks (scripted models, no AI calls) ===")
    db = fresh_db()
    real_audit = audit.AUDIT_PATH
    audit.AUDIT_PATH = db.parent / "audit_offline.json"  # keep stand-in runs out of the real audit trail
    try:
        # The MCP server itself
        async with agents.mcp_client(db) as c:
            server_tools = {t.name for t in await c.list_tools()}
        check("A", f"MCP server reachable over stdio with {len(server_tools)} tools", len(server_tools) == 25,
              sorted(server_tools))

        team, mcp = agents.build_team(model=scripted("Boss", []), db_path=db)
        check("A", "five agents built", sorted(team) == sorted(AGENT_NAMES), list(team))

        async with mcp:
            # 1. Each agent sees exactly its tools
            seen: dict = {}
            for name in AGENT_NAMES:
                await run_scripted(team, {name: scripted(name, [], seen)}, name, "Say hi.")
                expected = sorted(agents.TOOL_ACCESS[name] | {"delegate"})
                check("A", f"{name}: sees its {len(expected) - 1} MCP tools + delegate, no human-only tools",
                      seen[name] == expected and not (set(seen[name]) & agents.HUMAN_ONLY_TOOLS), seen[name])

            # 2. An agent calls an MCP tool and gets real data
            msgs, _ = await run_scripted(
                team, {"Inventory": scripted("Inventory", [("check_product_stock", {"sku": "CC-TEE-WHITE", "size": "S"})])},
                "Inventory", "Check the tee.")
            got = tool_returns(msgs, "check_product_stock")
            check("A", "Inventory -> MCP check_product_stock returns real data (tee S qty 0)",
                  got and got[0].get("qty_available") == 0, got)

            # 3. Every agent can delegate to every other agent
            ok_pairs = []
            for a, b in permutations(AGENT_NAMES, 2):
                scripts = {a: scripted(a, [("delegate", {"to_agent": b, "task": f"Test from {a}"})]), b: scripted(b, [])}
                msgs, run = await run_scripted(team, scripts, a, "Delegate test.")
                r = tool_returns(msgs, "delegate")
                if r and r[0].ok and r[0].report.agent == b:
                    ok_pairs.append(f"{a}->{b}")
            check("A", f"full connectivity: {len(ok_pairs)}/20 delegation directions work", len(ok_pairs) == 20, ok_pairs)

            # 4. Loop and depth limits
            scripts = {
                "Boss": scripted("Boss", [("delegate", {"to_agent": "Inventory", "task": "check stock"})]),
                "Inventory": scripted("Inventory", [("delegate", {"to_agent": "Boss", "task": "loop back?"}),
                                                    ("delegate", {"to_agent": "Accounting", "task": "cost it"})]),
                "Accounting": scripted("Accounting", [("delegate", {"to_agent": "Facilities", "task": "too deep?"})]),
            }
            msgs, run = await run_scripted(team, scripts, "Boss", "Chain test.", run_id="offline-chain", max_depth=2)
            boss_got = tool_returns(msgs, "delegate")[0]
            refused = {(e["agent"], e["to_agent"]): e["result"] for e in refusals("offline-chain")}
            check("A", "Boss -> Inventory -> Accounting chain works (depth 2)",
                  boss_got.ok and run.delegations == 2, f"delegations used: {run.delegations}")
            check("A", "Inventory -> Boss refused (already in chain: no loops)",
                  "would loop" in refused.get(("Inventory", "Boss"), ""), refused.get(("Inventory", "Boss")))
            check("A", "Accounting -> Facilities refused at depth 2 (depth limit enforced; test set to 2)",
                  "depth limit" in refused.get(("Accounting", "Facilities"), ""), refused.get(("Accounting", "Facilities")))

            # 5. Per-run delegation cap
            many = [("delegate", {"to_agent": b, "task": "x"}) for b in ["Inventory", "Accounting", "Facilities",
                    "Customer Service", "Inventory", "Accounting", "Facilities"]]
            scripts = {"Boss": scripted("Boss", many), **{n: scripted(n, []) for n in AGENT_NAMES if n != "Boss"}}
            msgs, run = await run_scripted(team, scripts, "Boss", "Cap test.")
            r = tool_returns(msgs, "delegate")
            check("A", "7th delegation refused (cap of 6 per run)",
                  [x.ok for x in r] == [True] * 6 + [False] and run.delegations == 6, [x.message or "ok" for x in r])

            # 6. Depth 4 (the real setting): a five-agent chain works; the fifth can't loop back
            chain = ["Boss", "Inventory", "Accounting", "Facilities", "Customer Service"]
            scripts = {a: scripted(a, [("delegate", {"to_agent": b, "task": "pass it on"})]) for a, b in zip(chain, chain[1:])}
            scripts["Customer Service"] = scripted("Customer Service", [("delegate", {"to_agent": "Boss", "task": "back?"})])
            msgs, run = await run_scripted(team, scripts, "Boss", "Depth test.", run_id="offline-depth4")
            refused = {(e["agent"], e["to_agent"]): e["result"] for e in refusals("offline-depth4")}
            check("A", "depth 4: Boss > Inventory > Accounting > Facilities > Customer Service works; CS > Boss refused (loop)",
                  run.delegations == 4 and "would loop" in refused.get(("Customer Service", "Boss"), ""),
                  {"delegations": run.delegations, "refused": list(refused.values())})

            # 7. Per-agent limit (5): tools are hidden on the 5th step, so the agent has to answer
            many_reads = [("check_product_stock", {"sku": "CC-TEE-WHITE", "size": z}) for z in ["S", "M", "L", "XL", "S2", "S3"]]
            out, run = await run_limited(team, {"Inventory": scripted("Inventory", many_reads)}, "Inventory", "lim-agent")
            check("A", "agent limit: Inventory forced to answer on step 5 (4 tool steps + final), no 6th call",
                  not isinstance(out, Exception) and run.steps_by_agent.get("Inventory") == 5,
                  {"steps": run.steps_by_agent, "out": type(out).__name__})

            # 8. Hard stop: a model that ignores the hidden tools is stopped before a 6th model call
            out, run = await run_limited(team, {"Inventory": scripted("Inventory", many_reads, stubborn=True)}, "Inventory", "lim-hard")
            check("A", "agent limit hard stop: stubborn agent stopped by AgentStepLimit at 5 steps",
                  isinstance(out, AgentStepLimit) and run.steps_by_agent.get("Inventory") == 5 and bool(run.limit_stops),
                  {"steps": run.steps_by_agent, "out": repr(out)})

            # 9. Team limit (set to 4 for the test): wrap-up leaves room for each agent in the chain to answer
            s9 = {"Boss": scripted("Boss", [("delegate", {"to_agent": "Inventory", "task": "check"})] * 3),
                  "Inventory": scripted("Inventory", many_reads)}
            out, run = await run_limited(team, s9, "Boss", "lim-team", max_steps=4)
            check("A", "team limit 4: Boss > Inventory wraps up gracefully within 4 steps",
                  not isinstance(out, Exception) and run.total_steps <= 4, {"total": run.total_steps, "by_agent": run.steps_by_agent})
            s9s = {"Boss": scripted("Boss", [("delegate", {"to_agent": "Inventory", "task": "check"})] * 3, stubborn=True),
                   "Inventory": scripted("Inventory", many_reads, stubborn=True)}
            out, run = await run_limited(team, s9s, "Boss", "lim-team-hard", max_steps=4)
            check("A", "team limit hard stop: stubborn team stopped without exceeding 4 steps",
                  isinstance(out, (TicketStepLimit, AgentStepLimit)) and run.total_steps <= 4,
                  {"total": run.total_steps, "out": repr(out)})

            # 9b. Parallel delegations: Boss asks Accounting and Customer Service at once, and both ask
            # Inventory. Inventory's 5-step budget must hold across the two concurrent copies.
            def boss_parallel(messages, info):
                if not any(isinstance(m, ModelResponse) for m in messages) and info.function_tools:
                    return ModelResponse(parts=[
                        ToolCallPart("delegate", {"to_agent": "Accounting", "task": "ask Inventory"}),
                        ToolCallPart("delegate", {"to_agent": "Customer Service", "task": "ask Inventory"})])
                return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                         {"agent": "Boss", "summary": "done", "recommendation": "n/a"})])
            reads = [("check_product_stock", {"sku": "CC-HOOD-NAVY", "size": z}) for z in ["S", "M", "L", "XL", "S1", "S2", "S3"]]
            s9p = {"Boss": FunctionModel(boss_parallel),
                   "Accounting": scripted("Accounting", [("delegate", {"to_agent": "Inventory", "task": "stock?"})]),
                   "Customer Service": scripted("Customer Service", [("delegate", {"to_agent": "Inventory", "task": "stock?"})]),
                   "Inventory": scripted("Inventory", reads, stubborn=True)}
            out, run = await run_limited(team, s9p, "Boss", "lim-parallel")
            check("A", "parallel delegations: Inventory never exceeds 5 steps even with two copies running at once",
                  run.steps_by_agent.get("Inventory", 0) <= 5 and run.total_steps <= 25,
                  {"by_agent": run.steps_by_agent, "total": run.total_steps, "stops": run.limit_stops})

            # 10. Repeated identical tool calls
            dup = [("check_product_stock", {"sku": "CC-TEE-WHITE", "size": "S"})] * 2 + [
                ("delegate", {"to_agent": "Customer Service", "task": "check the tee"})]
            s10 = {"Inventory": scripted("Inventory", dup),
                   "Customer Service": scripted("Customer Service", [("check_product_stock", {"sku": "CC-TEE-WHITE", "size": "S"})])}
            out, run = await run_limited(team, s10, "Inventory", "dedupe")
            reps = [e["result"] for e in audit_events("dedupe") if e["event"] == "tool_repeat"]
            check("A", "repeat call blocked for the same agent; another agent gets the cached result (no new MCP call)",
                  len(reps) == 2 and reps[0].startswith("blocked") and reps[1].startswith("served"), reps)
            s11 = {"Inventory": scripted("Inventory", [("get_ticket", {"ticket_id": 101}),
                   ("add_ticket_note", {"ticket_id": 101, "note": "test", "author": "Inventory"}),
                   ("get_ticket", {"ticket_id": 101})])}
            out, run = await run_limited(team, s11, "Inventory", "dedupe-write")
            reps = [e for e in audit_events("dedupe-write") if e["event"] == "tool_repeat"]
            check("A", "after a write, the same read runs again for real (cache cleared)", reps == [], reps)

            # 11. Every ticket run ends with a Customer Service reply draft
            def by_agent(boss_delegates: bool):
                def fn(messages, info):
                    m = re.search(r"You are the \*\*(.+?)\*\* agent", info.instructions or "")
                    name = m.group(1) if m else "Boss"
                    done = sum(isinstance(x, ModelResponse) for x in messages)
                    if name == "Boss" and boss_delegates and done == 0 and info.function_tools:
                        return ModelResponse(parts=[ToolCallPart("delegate", {"to_agent": "Customer Service", "task": "reply"})])
                    if name == "Customer Service" and done == 0 and info.function_tools:
                        return ModelResponse(parts=[ToolCallPart("draft_customer_message", {
                            "ticket_id": 102, "subject": "Rent notice received", "body": "Test reply.",
                            "written_by": "Customer Service"})])
                    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                             {"agent": name, "summary": f"{name} done", "recommendation": "n/a"})])
                return FunctionModel(fn)

            res = await agents.run_team_task("Boss", "test", ticket_id=102, mode="test", db_path=db,
                                             model=by_agent(False), run_id="reply-required")
            sys_steps = [e for e in audit_events("reply-required") if e["agent"] == "System"]
            check("A", "Boss skips Customer Service -> backend adds the required reply step and a draft is saved",
                  res.customer_reply == "drafted by the required reply step" and len(sys_steps) == 2,
                  {"reply": res.customer_reply, "system_events": [e["event"] for e in sys_steps]})
            res = await agents.run_team_task("Boss", "test", ticket_id=102, mode="test", db_path=db,
                                             model=by_agent(True), run_id="reply-by-team")
            check("A", "Boss delegates to Customer Service -> 'drafted by the team', no extra step",
                  res.customer_reply == "drafted by the team"
                  and not [e for e in audit_events("reply-by-team") if e["agent"] == "System"], res.customer_reply)
    finally:
        audit.AUDIT_PATH = real_audit


# ---------- Part B: live gpt-6-luna ----------

LIVE_TESTS: list[tuple[AgentName, int, str, str]] = [
    ("Inventory", 101,
     "Ticket 101: Is the Classic Bulldog Tee (CC-TEE-WHITE) size S in stock? If not, which vendor can restock it, "
     "is that vendor able to ship right now, and what's the earliest arrival? Don't delegate; just report.",
     "single agent + MCP tools"),
    ("Facilities", 102,
     "Ticket 102: Confirm the rent amount and due date for lease 1, then have Accounting check whether cash covers it "
     "and prepare the payment for human approval if appropriate.",
     "peer delegation Facilities -> Accounting (not through the Boss)"),
    ("Customer Service", 101,
     "Ticket 101: Tauhid Zaman is asking when the size S tee will be available. Ask Inventory what the restock "
     "situation is, then save a draft reply. Don't promise a firm date.",
     "peer delegation Customer Service -> Inventory, then a saved draft"),
]


async def part_b() -> None:
    print(f"\n=== Part B: live interactions ({agents.MODEL_NAME} via Portkey, throwaway DB) ===")
    db = fresh_db()
    total_in = total_out = 0
    for agent_name, ticket, task, what in LIVE_TESTS:
        res = await agents.run_team_task(agent_name, task, ticket_id=ticket, mode="test", db_path=db)
        total_in += res.input_tokens
        total_out += res.output_tokens
        o = res.output
        detail = {
            "run_id": res.run_id, "stop": res.stop_reason, "requests": res.model_requests, "tool_calls": res.tool_calls,
            "delegations": res.delegations, "tokens_in": res.input_tokens, "tokens_out": res.output_tokens,
            "summary": o.summary if o else res.error,
            "approval_request_ids": o.approval_request_ids if o else None, "draft_ids": o.draft_ids if o else None,
        }
        print(json.dumps(detail, indent=2, ensure_ascii=False))
        need_delegation = "delegation" in what
        check("B", f"{agent_name} on ticket {ticket}: {what}",
              res.stop_reason == "final_answer" and o is not None and (res.delegations >= 1 if need_delegation else True),
              detail)

    # Nothing was paid: check through the MCP server, like everything else
    async with agents.mcp_client(db) as c:
        fin = (await c.call_tool("get_financial_status", {})).structured_content
        pays = (await c.call_tool("list_payments", {})).structured_content
        reqs = (await c.call_tool("list_approval_requests", {})).structured_content
        drafts = (await c.call_tool("list_customer_drafts", {})).structured_content
    check("B", "no money moved: checking still $3,400 and 0 payments",
          fin["total_cash"] == 3400 and pays["count"] == 0, {"cash": fin["total_cash"], "payments": pays["count"]})
    check("B", "any approval requests are still pending (waiting for a human)",
          all(r["status"] == "pending" for r in reqs["requests"]),
          [(r["id"], r["kind"], r["amount"], r["status"]) for r in reqs["requests"]])
    check("B", "drafts are saved as drafts (never sent)",
          all(d["status"] == "draft" for d in drafts["drafts"]),
          [(d["id"], d["recipient"], d["subject"]) for d in drafts["drafts"]])
    print(f"\nLive token total: {total_in:,} in / {total_out:,} out")
    results.append({"part": "B", "test": "token usage", "passed": True,
                    "detail": f"{total_in} input / {total_out} output tokens across {len(LIVE_TESTS)} runs"})


async def main(live: bool) -> int:
    await part_a()
    if live:
        await part_b()
    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed")
    # Offline and live results go to separate files, so an offline rerun never replaces live evidence.
    for part, name in (("A", "agent_team_tests_offline.json"), ("B", "agent_team_tests_live.json")):
        rows = [r for r in results if r["part"] == part]
        if rows:
            out = ROOT / "output" / name
            out.write_text(json.dumps({"model": agents.MODEL_NAME, "passed": sum(r["passed"] for r in rows),
                                       "total": len(rows), "results": rows}, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            print(f"Results saved to {out.relative_to(ROOT)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help=f"also run real {agents.MODEL_NAME} interactions")
    sys.exit(asyncio.run(main(parser.parse_args().live)))
