"""Execution limits for one agent run on a ticket. Enforced by the backend (agents.py / main.py).

Every value can be changed with an environment variable (e.g. in .env) without touching code.
Don't raise them without the manager's OK.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class RunLimits:
    max_steps_per_ticket: int = 25        # model calls across all five agents in one run, delegations included
    max_steps_per_agent: int = 5          # model calls by one agent in one run (all its delegations combined)
    max_delegation_depth: int = 4         # Boss -> A -> B -> C -> D at most
    max_delegations_per_run: int = 6      # delegate calls in one run
    max_output_tokens_per_call: int = 2_000
    max_tokens_per_ticket: int = 200_000  # input + output tokens in one run (hard stop)
    max_tool_calls_per_ticket: int = 50

    @classmethod
    def from_env(cls) -> RunLimits:
        d = cls()
        return cls(
            max_steps_per_ticket=_int("CC_MAX_STEPS_PER_TICKET", d.max_steps_per_ticket),
            max_steps_per_agent=_int("CC_MAX_STEPS_PER_AGENT", d.max_steps_per_agent),
            max_delegation_depth=_int("CC_MAX_DELEGATION_DEPTH", d.max_delegation_depth),
            max_delegations_per_run=_int("CC_MAX_DELEGATIONS_PER_RUN", d.max_delegations_per_run),
            max_output_tokens_per_call=_int("CC_MAX_OUTPUT_TOKENS_PER_CALL", d.max_output_tokens_per_call),
            max_tokens_per_ticket=_int("CC_MAX_TOKENS_PER_TICKET", d.max_tokens_per_ticket),
            max_tool_calls_per_ticket=_int("CC_MAX_TOOL_CALLS_PER_TICKET", d.max_tool_calls_per_ticket),
        )

    def as_dict(self) -> dict:
        return asdict(self)


class AgentStepLimit(Exception):
    """One agent used all of its steps for this run."""

    def __init__(self, agent: str, used: int, limit: int):
        super().__init__(f"{agent} reached its {limit}-step limit ({used} used).")
        self.agent, self.used, self.limit = agent, used, limit


class TicketStepLimit(Exception):
    """The whole team used all of the steps for this ticket run."""

    def __init__(self, used: int, limit: int):
        super().__init__(f"The team reached the {limit}-step limit for this ticket ({used} used).")
        self.used, self.limit = used, limit
