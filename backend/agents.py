"""The Campus Customs agent team: Boss, Inventory, Accounting, Facilities, Customer Service.

- Model:      gpt-6-luna through Portkey (PORTKEY_API_KEY from .env), the only model used,
              on the OpenAI Responses API with low reasoning effort.
- Prompts:    prompts/shop_rules.md (shared) + prompts/<agent>.md (one per agent).
- Data:       every read and write goes through the campus-customs MCP server
              (mcp_server/server.py). This backend never opens the database itself.
- Tools:      each agent sees only its own subset of MCP tools (TOOL_ACCESS), plus
              `delegate`, which lets any agent hand a task to any other agent.
- Limits:     limits.py (steps per ticket run / per agent, delegation depth, tokens),
              enforced here: tools are hidden on an agent's last allowed step so it has
              to answer, and any step past a limit is stopped before the model is called.
- Audit:      every agent-loop step is appended to output/audit_trail.json.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage, UsageLimits

import audit
from limits import AgentStepLimit, RunLimits, TicketStepLimit
from models import (
    AGENT_NAMES, AgentName, AgentReport, AuditEntry, DelegationResult, RunMode, TeamDeps, TeamResult, TeamRun,
)

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

BACKEND = Path(__file__).resolve().parent
ROOT = BACKEND.parent
PROMPTS = BACKEND / "prompts"
MCP_DIR = ROOT / "mcp_server"

# The only model this homework may use. Don't add a fallback.
MODEL_NAME = "gpt-6-luna"
REASONING_EFFORT = "low"        # enough for tool-driven ops work, and much cheaper than the default
OUTPUT_TOOL = "final_result"    # PydanticAI's structured-answer tool (not a real tool)

PROMPT_FILES: dict[AgentName, str] = {
    "Boss": "boss.md",
    "Inventory": "inventory.md",
    "Accounting": "accounting.md",
    "Facilities": "facilities.md",
    "Customer Service": "customer_service.md",
}

# Which MCP tools each agent can see. approve_request / reject_request are human-only
# and are never given to any agent.
HUMAN_ONLY_TOOLS = {"approve_request", "reject_request", "sync_ticket_status", "undo_decision"}
TOOL_ACCESS: dict[AgentName, set[str]] = {
    "Boss": {
        "list_tickets", "get_ticket", "get_financial_status", "quote_bulk_order", "list_approval_requests",
        "list_customer_drafts", "add_ticket_note", "update_ticket_status", "record_discount_decision",
    },
    "Inventory": {
        "get_ticket", "check_product_stock", "list_inventory", "get_product_pricing", "list_vendors",
        "plan_restock", "add_ticket_note",
    },
    "Accounting": {
        "get_ticket", "get_financial_status", "list_invoices", "list_vendors", "get_product_pricing",
        "quote_bulk_order", "plan_restock", "list_approval_requests", "list_payments", "request_payment",
        "request_purchase_order", "add_ticket_note",
    },
    "Facilities": {
        "get_ticket", "get_lease", "get_financial_status", "list_payments", "list_approval_requests",
        "add_ticket_note",
    },
    "Customer Service": {
        "get_ticket", "check_product_stock", "get_product_pricing", "quote_bulk_order", "list_customer_drafts",
        "draft_customer_message", "add_ticket_note",
    },
}
# Backend-only helper: sends an already-recorded discount decision to the inbox. Agents use
# record_discount_decision, which creates the discount approval itself.
BACKEND_ONLY_TOOLS = {"request_discount_approval"}
assert not any((HUMAN_ONLY_TOOLS | BACKEND_ONLY_TOOLS) & tools for tools in TOOL_ACCESS.values())

# Tools that change data. Any of them clears the repeat-call cache, since results may change.
WRITE_TOOLS = {
    "request_payment", "request_purchase_order", "draft_customer_message", "add_ticket_note",
    "update_ticket_status", "record_discount_decision", "approve_request", "reject_request", "sync_ticket_status",
    "request_discount_approval", "undo_decision",
}

# Never pass these to the MCP subprocess.
_SECRET_ENV = {"PORTKEY_API_KEY", "OPENAI_API_KEY"}


# ---------- Model and MCP connection ----------

def load_env() -> None:
    """Load .env from this homework folder, or the nearest parent (the course root)."""
    for folder in [ROOT, *ROOT.parents]:
        if (folder / ".env").exists():
            load_dotenv(folder / ".env")
            return


def current_limits() -> RunLimits:
    load_env()
    return RunLimits.from_env()


def build_model() -> Model:
    load_env()
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is not set (put it in .env).")
    client = AsyncOpenAI(
        api_key=key,
        base_url="https://api.portkey.ai/v1",
        default_headers={"x-portkey-api-key": key, "x-portkey-provider": "openai"},
    )
    # Responses API: through Portkey, gpt-6-luna only supports function tools there.
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def mcp_client(db_path: Path | None = None) -> Client:
    """A FastMCP client for the campus-customs server.

    Default: start mcp_server/server.py over stdio with its own .venv.
    CAMPUS_CUSTOMS_MCP_URL (e.g. http://127.0.0.1:8001/mcp) connects over HTTP instead.
    `db_path` points the server at another copy (used by tests).
    """
    url = os.getenv("CAMPUS_CUSTOMS_MCP_URL")
    if url and db_path is None:
        return Client(url)
    # mcp_server/.venv if it exists, otherwise the Python running this backend (one shared .venv works too)
    python = MCP_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        python = Path(sys.executable)
    env = {k: v for k, v in os.environ.items() if k not in _SECRET_ENV}
    env["FASTMCP_SHOW_SERVER_BANNER"] = "false"
    if db_path is not None:
        env["CAMPUS_CUSTOMS_DB"] = str(Path(db_path).resolve())
    return Client(StdioTransport(command=str(python), args=[str(MCP_DIR / "server.py")], env=env, cwd=str(MCP_DIR)))


# ---------- Loop protection ----------

def must_finish(deps: TeamDeps) -> str | None:
    """Why this agent has to give its final answer now (None = it may keep using tools).

    Called while a step is being prepared; that step is already reserved (counted).
    An agent on its last allowed step must answer. And when the team is nearly out of
    steps, every agent still in the delegation chain needs one step to report back,
    so the current agent wraps up while there's room for that.
    """
    run = deps.run
    used = run.steps_by_agent.get(deps.agent, 0)  # includes the step being prepared
    if used >= run.max_agent_steps:
        return f"this is your last allowed step ({used} of {run.max_agent_steps})"
    if run.max_steps - run.total_steps <= deps.depth:
        return f"the team is almost out of steps ({run.total_steps} of {run.max_steps} used)"
    return None


async def wrap_up_tools(ctx: RunContext[TeamDeps], tool_defs: list[ToolDefinition]) -> list[ToolDefinition]:
    """Hide every tool (MCP + delegate) when the agent must answer, so only the final answer is possible."""
    return [] if must_finish(ctx.deps) else tool_defs


async def dedupe_tool_calls(ctx: RunContext[TeamDeps], call_tool, name: str, tool_args: dict[str, Any]):
    """Don't repeat a read call with identical arguments while nothing has changed.

    Writes go through and clear the cache. A repeated read from the SAME agent gets a short
    note (it already has the result in its context); another agent gets the saved result
    without calling the MCP server again.
    """
    deps, run = ctx.deps, ctx.deps.run
    if name in WRITE_TOOLS:
        run.tool_cache.clear()
        run.seen_by.clear()
        return await call_tool(name, tool_args)
    key = f"{name}:{json.dumps(tool_args, sort_keys=True, default=str)}"
    if key in run.tool_cache:
        run.repeats_blocked += 1
        if deps.agent in run.seen_by[key]:
            _log(deps, "tool_repeat", tool=name, args=audit.short(tool_args, 150),
                 result="blocked: same agent, same arguments, nothing changed since")
            return {"repeat_blocked": True,
                    "note": f"You already called {name} with these exact arguments in this run and nothing has "
                            "changed since. Use that earlier result instead of calling it again."}
        run.seen_by[key].add(deps.agent)
        _log(deps, "tool_repeat", tool=name, args=audit.short(tool_args, 150),
             result="served from this run's cache (no new MCP call)")
        return run.tool_cache[key]
    result = await call_tool(name, tool_args)
    run.tool_cache[key] = result
    run.seen_by[key] = {deps.agent}
    return result


# ---------- Delegation ----------

async def delegate(ctx: RunContext[TeamDeps], to_agent: AgentName, task: str) -> DelegationResult:
    """Hand a task to another agent on the team and get their report back.

    Write `task` so it stands alone: the ticket number, what you already know
    (with numbers), and exactly what you need back. Any agent can delegate to
    any other agent, but not to itself, not back to an agent already working
    on this chain, and not deeper than the team's limit.
    """
    deps, run = ctx.deps, ctx.deps.run
    refusal = None
    if to_agent == deps.agent:
        refusal = "You can't delegate to yourself."
    elif to_agent in deps.chain:
        refusal = f"{to_agent} is already working on this chain ({' -> '.join(deps.chain)}); that would loop."
    elif deps.depth >= run.max_depth:
        refusal = f"Delegation depth limit ({run.max_depth}) reached. Finish with what you have."
    elif run.delegations >= run.max_delegations:
        refusal = f"This run already used all {run.max_delegations} delegations. Finish with what you have."
    elif run.steps_by_agent.get(to_agent, 0) >= run.max_agent_steps:
        refusal = f"{to_agent} already used all {run.max_agent_steps} of its steps in this run."
    if refusal:
        _log(deps, "delegate", to_agent=to_agent, args=audit.short(task, 160), result=f"REFUSED: {refusal}")
        return DelegationResult(ok=False, to_agent=to_agent, message=refusal)

    run.delegations += 1
    _log(deps, "delegate", to_agent=to_agent, args=audit.short(task, 300))
    child = TeamDeps(run=run, agent=to_agent, chain=[*deps.chain, to_agent])
    try:
        report = await run_agent(child, task, usage=ctx.usage, usage_limits=ctx.usage_limits)
    except (UsageLimitExceeded, TicketStepLimit):
        raise  # team-wide limits stop the whole run, not just this branch
    except AgentStepLimit as exc:
        msg = f"{to_agent} stopped at its step limit before finishing ({exc}). Work it saved through tools is kept."
        _log(deps, "delegation_result", to_agent=to_agent, result=f"LIMIT: {msg}")
        return DelegationResult(ok=False, to_agent=to_agent, message=msg)
    except Exception as exc:
        _log(deps, "delegation_result", to_agent=to_agent, result=f"ERROR: {type(exc).__name__}: {audit.short(str(exc), 150)}")
        return DelegationResult(ok=False, to_agent=to_agent, message=f"{to_agent} failed: {type(exc).__name__}")
    _log(deps, "delegation_result", to_agent=to_agent, result=audit.short(report.summary, 600))
    return DelegationResult(ok=True, to_agent=to_agent, report=report)


# ---------- Building the team ----------

def _instructions(name: AgentName) -> list[str]:
    shared = (PROMPTS / "shop_rules.md").read_text(encoding="utf-8")
    own = (PROMPTS / PROMPT_FILES[name]).read_text(encoding="utf-8")
    return [own, shared]


def build_team(model: Model | None = None, db_path: Path | None = None,
               limits: RunLimits | None = None) -> tuple[dict[AgentName, Agent], MCPToolset]:
    """Create the five agents sharing ONE MCP connection, each with its own filtered tool list."""
    model = model or build_model()
    limits = limits or current_limits()
    mcp = MCPToolset(mcp_client(db_path), max_retries=1, process_tool_call=dedupe_tool_calls)
    settings = OpenAIResponsesModelSettings(max_tokens=limits.max_output_tokens_per_call,
                                            openai_reasoning_effort=REASONING_EFFORT)
    team: dict[AgentName, Agent] = {}
    for name in AGENT_NAMES:
        allowed = frozenset(TOOL_ACCESS[name])
        agent = Agent(
            model,
            name=name,
            deps_type=TeamDeps,
            output_type=AgentReport,
            instructions=_instructions(name),
            toolsets=[
                mcp.filtered(lambda ctx, tool_def, allowed=allowed: tool_def.name in allowed).prepared(wrap_up_tools),
                FunctionToolset([Tool(delegate)]).prepared(wrap_up_tools),
            ],
            model_settings=settings,
            retries=1,
        )

        @agent.instructions
        def run_context(ctx: RunContext[TeamDeps]) -> str:
            d, r = ctx.deps, ctx.deps.run
            others = [a for a in AGENT_NAMES if a not in d.chain]
            can_delegate = d.depth < r.max_depth and r.delegations < r.max_delegations and others
            used = r.steps_by_agent.get(d.agent, 0)
            lines = [
                "## This run",
                f"You are the **{d.agent}** agent. Use `{d.agent}` as your name in tool fields "
                "like requested_by / author / written_by / updated_by / decided_by.",
                f"Delegation chain: {' -> '.join(d.chain)} (depth {d.depth} of {r.max_depth}).",
                (f"You may delegate to: {', '.join(others)}. Delegations used: {r.delegations}/{r.max_delegations}."
                 if can_delegate else "You can't delegate any further. Finish with your own tools."),
                f"Step budget: this is your step {used} of {r.max_agent_steps}; the team is on step "
                f"{r.total_steps} of {r.max_steps}. Each model call is a step. Batch independent tool calls "
                "into one step and don't repeat a call you already made.",
            ]
            why = must_finish(d)
            if why:
                lines.append(f"**Give your final answer now: {why}. Your tools are switched off for this step.** "
                             "Report what you found and what is still unfinished.")
            if r.ticket_id:
                lines.append(f"Ticket in focus: {r.ticket_id}.")
            if r.mode == "test":
                lines.append("This is a TEST run on a throwaway copy of the database.")
            return "\n".join(lines)

        team[name] = agent
    return team, mcp


# ---------- Running one agent loop (with audit) ----------

def _log(deps: TeamDeps, event: str, **fields) -> None:
    audit.append(AuditEntry(
        time=audit.now(), run_id=deps.run.run_id, mode=deps.run.mode, ticket_id=deps.run.ticket_id,
        agent=deps.agent, depth=deps.depth, event=event, **fields,
    ))


async def run_agent(
    deps: TeamDeps, task: str, usage: RunUsage | None = None, usage_limits: UsageLimits | None = None,
) -> AgentReport:
    """Run one agent's loop, logging every step. Usage and step counts are shared with the parent run."""
    run = deps.run
    agent = run.team[deps.agent]
    _log(deps, "run_start", args=audit.short(task, 300), model=MODEL_NAME)
    step = tokens_in = tokens_out = 0  # this agent's own numbers (usage itself is shared with the parent)
    try:
        async with agent.iter(task, deps=deps, usage=usage, usage_limits=usage_limits) as agent_run:
            async for node in agent_run:
                if Agent.is_model_request_node(node):
                    # The request carries the results of the tools called in the previous step.
                    for part in node.request.parts:
                        if isinstance(part, ToolReturnPart) and part.tool_name != OUTPUT_TOOL:
                            _log(deps, "tool_result", step=step, tool=part.tool_name, result=audit.short(part.content))
                        elif isinstance(part, RetryPromptPart) and part.tool_name:
                            _log(deps, "tool_retry", step=step, tool=part.tool_name,
                                 result=audit.short(part.model_response(), 200))
                    # Hard stops, checked BEFORE the model is called (so no tokens are spent).
                    # Check and reserve happen together with no await in between, so parallel
                    # delegations (e.g. two agents asking Inventory at once) can't both slip
                    # past the limit.
                    if run.total_steps >= run.max_steps:
                        raise TicketStepLimit(run.total_steps, run.max_steps)
                    used = run.steps_by_agent.get(deps.agent, 0)
                    if used >= run.max_agent_steps:
                        raise AgentStepLimit(deps.agent, used, run.max_agent_steps)
                    run.total_steps += 1
                    run.steps_by_agent[deps.agent] = used + 1
                elif Agent.is_call_tools_node(node):
                    step += 1
                    resp = node.model_response
                    calls = [p for p in resp.parts if isinstance(p, ToolCallPart)]
                    tokens_in += resp.usage.input_tokens
                    tokens_out += resp.usage.output_tokens
                    _log(deps, "model_response", step=step, finish_reason=resp.finish_reason,
                         input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                         result=f"{len(calls)} tool call(s): {', '.join(c.tool_name for c in calls) or 'none'} "
                                f"[agent step {run.steps_by_agent[deps.agent]}/{run.max_agent_steps}, "
                                f"team {run.total_steps}/{run.max_steps}]")
                    for call in calls:
                        if call.tool_name == OUTPUT_TOOL:
                            _log(deps, "final_answer", step=step, result=audit.short(call.args_as_dict().get("summary", ""), 600))
                        elif call.tool_name != "delegate":  # delegate logs itself
                            _log(deps, "tool_call", step=step, tool=call.tool_name, args=audit.short(call.args_as_dict(), 200))
            result = agent_run.result
    except (AgentStepLimit, TicketStepLimit) as exc:
        run.limit_stops.append(str(exc))
        _log(deps, "limit_stop", step=step, stop_reason=type(exc).__name__, result=str(exc))
        _log(deps, "run_end", step=step, stop_reason=f"limit: {exc}", input_tokens=tokens_in, output_tokens=tokens_out)
        raise
    except UsageLimitExceeded as exc:
        run.limit_stops.append(f"usage limit: {exc}")
        _log(deps, "limit_stop", step=step, stop_reason="UsageLimitExceeded", result=audit.short(str(exc), 200))
        _log(deps, "run_end", step=step, stop_reason=f"usage_limit: {audit.short(str(exc), 120)}")
        raise
    except Exception as exc:
        _log(deps, "run_end", step=step, stop_reason=f"error: {type(exc).__name__}: {audit.short(str(exc), 120)}")
        raise
    _log(deps, "run_end", step=step, stop_reason="final_answer", input_tokens=tokens_in, output_tokens=tokens_out)
    return result.output


REPLY_TASK = (
    "Ticket {ticket_id}: the team has finished its work on this ticket and the requester still needs a reply. "
    "Outcome so far: {outcome}\n"
    "Use get_ticket for the facts, then save ONE reply draft to the ticket's requester with draft_customer_message. "
    "If a decision is waiting on the owners (a pending approval), say our team has reviewed the request and passed "
    "its recommendation to the owners for a decision, and that we'll follow up once they decide."
)


async def _drafts_since(mcp: MCPToolset, ticket_id: int, since: str) -> list[dict]:
    res = await mcp.direct_call_tool("list_customer_drafts", {"ticket_id": ticket_id})
    return [d for d in res.get("drafts", []) if d["created_at"] >= since]


async def _ensure_customer_reply(mcp: MCPToolset, run: TeamRun, lead: AgentName, started: str, outcome: str,
                                 usage: RunUsage, usage_limits: UsageLimits) -> str:
    """Every ticket run ends with a Customer Service reply draft to the requester.

    If the team didn't save one, the backend gives Customer Service one short task to write it,
    inside the same run limits. Returns what happened, for the result and the audit trail.
    """
    if not run.ticket_id or lead == "Customer Service":
        return "not needed (Customer Service led this run)" if lead == "Customer Service" else "not needed"
    if await _drafts_since(mcp, run.ticket_id, started):
        return "drafted by the team"
    if run.max_steps - run.total_steps < 2 or run.steps_by_agent.get("Customer Service", 0) >= run.max_agent_steps:
        return "missing: not enough steps left in this run for the required customer reply"
    task = REPLY_TASK.format(ticket_id=run.ticket_id, outcome=outcome or "(no summary)")
    audit.append(AuditEntry(time=audit.now(), run_id=run.run_id, mode=run.mode, ticket_id=run.ticket_id,
                            agent="System", depth=0, event="delegate", to_agent="Customer Service",
                            args=audit.short("[Required customer reply: the team ended without one] " + task, 300)))
    deps = TeamDeps(run=run, agent="Customer Service", chain=["Customer Service"])
    try:
        report = await run_agent(deps, task, usage=usage, usage_limits=usage_limits)
        summary = report.summary
    except (AgentStepLimit, TicketStepLimit, UsageLimitExceeded) as exc:
        summary = f"LIMIT: {exc}"
    except Exception as exc:
        summary = f"ERROR: {type(exc).__name__}"
    audit.append(AuditEntry(time=audit.now(), run_id=run.run_id, mode=run.mode, ticket_id=run.ticket_id,
                            agent="System", depth=0, event="delegation_result", to_agent="Customer Service",
                            result=audit.short(summary, 400)))
    if await _drafts_since(mcp, run.ticket_id, started):
        return "drafted by the required reply step"
    return f"missing: Customer Service didn't save a draft ({audit.short(summary, 120)})"


async def _save_limit_progress(mcp: MCPToolset, run: TeamRun, stop: str) -> str:
    """When a run stops at a limit: work saved through tools stays, plus a System note on the ticket
    explaining what's unfinished. Returns that explanation."""
    pending: list[str] = []
    status = "unknown"
    if run.ticket_id:
        try:
            t = await mcp.direct_call_tool("get_ticket", {"ticket_id": run.ticket_id})
            status = t["ticket"]["status"]
            pending = [f"#{r['id']} {r['kind']} ${r['amount']:,.2f}" for r in t.get("approval_requests", [])
                       if r["status"] == "pending"]
        except Exception:  # explanation still goes to the API response and the audit trail
            pass
    text = (f"Run {run.run_id} stopped at an execution limit ({stop}; steps {run.total_steps}/{run.max_steps}). "
            f"Ticket status is still '{status}'. "
            + (f"Pending approvals: {', '.join(pending)}. " if pending else "No approval requests pending. ")
            + "The agents did not finish; a human must decide whether to run this ticket again.")
    if run.ticket_id:
        try:
            await mcp.direct_call_tool("add_ticket_note", {"ticket_id": run.ticket_id, "note": text, "author": "System"})
        except Exception:
            pass
    return text


async def run_team_task(
    agent_name: AgentName, task: str, ticket_id: int | None = None, mode: RunMode = "run",
    db_path: Path | None = None, model: Model | None = None, run_id: str | None = None,
    limits: RunLimits | None = None,
) -> TeamResult:
    """Start a top-level run with one agent (usually the Boss). Delegations happen inside it."""
    limits = limits or current_limits()
    team, mcp = build_team(model=model, db_path=db_path, limits=limits)
    run = TeamRun(run_id=run_id or uuid.uuid4().hex[:10], team=team, ticket_id=ticket_id, mode=mode,
                  max_delegations=limits.max_delegations_per_run, max_depth=limits.max_delegation_depth,
                  max_steps=limits.max_steps_per_ticket, max_agent_steps=limits.max_steps_per_agent)
    deps = TeamDeps(run=run, agent=agent_name, chain=[agent_name])
    usage = RunUsage()
    usage_limits = UsageLimits(request_limit=limits.max_steps_per_ticket,  # backup for the step counter
                               tool_calls_limit=limits.max_tool_calls_per_ticket,
                               total_tokens_limit=limits.max_tokens_per_ticket)
    output, error, stop, unresolved, reply = None, None, "final_answer", None, None
    started = audit.now()
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mcp)  # one MCP connection for the whole team run
        try:
            output = await run_agent(deps, task, usage=usage, usage_limits=usage_limits)
        except TicketStepLimit as exc:
            stop, error = "ticket_step_limit", str(exc)
        except AgentStepLimit as exc:
            stop, error = "agent_step_limit", str(exc)
        except UsageLimitExceeded as exc:
            stop, error = "usage_limit", str(exc)
        except Exception as exc:
            stop, error = "error", f"{type(exc).__name__}: {exc}"
        if stop in ("final_answer", "agent_step_limit"):
            try:
                reply = await _ensure_customer_reply(mcp, run, agent_name, started,
                                                     output.summary if output else (error or ""), usage, usage_limits)
            except Exception as exc:  # never lose the main result over the reply check
                reply = f"missing: reply check failed ({type(exc).__name__})"
        if stop in ("ticket_step_limit", "agent_step_limit", "usage_limit"):
            unresolved = await _save_limit_progress(mcp, run, stop)
    return TeamResult(
        run_id=run.run_id, agent=agent_name, stop_reason=stop, output=output, error=error,
        model_requests=usage.requests, tool_calls=usage.tool_calls, delegations=run.delegations,
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
        steps_by_agent=dict(run.steps_by_agent), repeats_blocked=run.repeats_blocked,
        limit_stops=list(run.limit_stops), limit_hit=bool(run.limit_stops), unresolved=unresolved,
        customer_reply=reply,
    )
