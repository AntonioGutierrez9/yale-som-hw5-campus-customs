"""Shared Pydantic models and dependency types for the Campus Customs agent team."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pydantic_ai import Agent

AgentName = Literal["Boss", "Inventory", "Accounting", "Facilities", "Customer Service"]
AGENT_NAMES: tuple[AgentName, ...] = ("Boss", "Inventory", "Accounting", "Facilities", "Customer Service")
TicketStatus = Literal["open", "in_progress", "waiting_on_approval", "waiting_on_vendor", "resolved"]
# Set only from human decisions on approval requests (dashboard "Update status" / approve / reject).
HumanTicketStatus = Literal["approved", "rejected", "partially_approved"]
RunMode = Literal["run", "test"]


# ---------- What every agent returns ----------

class AgentReport(BaseModel):
    """The structured answer every agent gives back (to a person or to the agent that delegated)."""

    agent: AgentName
    summary: str = Field(description="2-4 sentences: what you found and what you did.")
    findings: list[str] = Field(
        default_factory=list, description="Key facts from tools, with the actual numbers, dates, and IDs."
    )
    actions_taken: list[str] = Field(
        default_factory=list, description="Things you saved through tools (requests, drafts, notes, status changes)."
    )
    approval_request_ids: list[int] = Field(
        default_factory=list, description="IDs of approval requests you created (they wait for a human)."
    )
    draft_ids: list[int] = Field(default_factory=list, description="IDs of customer drafts you saved (never sent).")
    recommendation: str = Field(description="What should happen next, and who should do it.")
    needs_human: list[str] = Field(
        default_factory=list, description="Decisions or approvals only a human can make."
    )
    ticket_status: TicketStatus | None = Field(
        default=None, description="Boss only: the ticket's status after this work."
    )


# ---------- Dependencies shared through a team run ----------

@dataclass
class TeamRun:
    """State shared by every agent in one top-level run (including all delegations)."""

    run_id: str
    team: dict[AgentName, Agent[TeamDeps, AgentReport]]
    ticket_id: int | None = None
    mode: RunMode = "run"
    delegations: int = 0
    max_delegations: int = 6
    max_depth: int = 4
    max_steps: int = 25                    # model calls across the whole team in this run
    max_agent_steps: int = 5               # model calls per agent in this run
    total_steps: int = 0
    steps_by_agent: dict[str, int] = field(default_factory=dict)
    tool_cache: dict[str, Any] = field(default_factory=dict)       # read-tool results, cleared after any write
    seen_by: dict[str, set[str]] = field(default_factory=dict)     # which agents already got each cached result
    repeats_blocked: int = 0
    limit_stops: list[str] = field(default_factory=list)


@dataclass
class TeamDeps:
    """Per-agent dependencies: who is running and the delegation chain that led here."""

    run: TeamRun
    agent: AgentName
    chain: list[AgentName] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return len(self.chain) - 1


class DelegationResult(BaseModel):
    """What the delegate tool hands back to the agent that asked."""

    ok: bool
    to_agent: AgentName
    message: str = ""
    report: AgentReport | None = None


class TeamResult(BaseModel):
    """One finished top-level run, with token usage, for the CLI / API / tests."""

    run_id: str
    agent: AgentName
    stop_reason: str  # final_answer | ticket_step_limit | agent_step_limit | usage_limit | error
    output: AgentReport | None = None
    error: str | None = None
    model_requests: int = 0
    tool_calls: int = 0
    delegations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    steps_by_agent: dict[str, int] = Field(default_factory=dict)
    repeats_blocked: int = 0
    limit_stops: list[str] = Field(default_factory=list)   # every limit that stopped an agent or the run
    limit_hit: bool = False
    unresolved: str | None = None                          # what's left, when the run stopped at a limit
    customer_reply: str | None = None                      # how the requester's reply draft was produced


# ---------- Audit trail ----------

class AuditEntry(BaseModel):
    """One line in output/audit_trail.json: one step of an agent loop."""

    time: str
    run_id: str
    mode: RunMode
    ticket_id: int | None = None
    agent: AgentName | Literal["Human", "System"]  # Human = dashboard actions; System = backend maintenance
    depth: int
    step: int | None = None
    event: Literal[
        "run_start", "model_response", "tool_call", "tool_result", "tool_retry",
        "delegate", "delegation_result", "final_answer", "run_end",
        "human_approval", "human_rejection", "db_reset",
        "tool_repeat", "limit_stop", "human_continue", "status_sync", "approval_created", "human_undo",
    ]
    tool: str | None = None
    args: str | None = None
    result: str | None = None
    to_agent: AgentName | None = None
    finish_reason: str | None = None
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
