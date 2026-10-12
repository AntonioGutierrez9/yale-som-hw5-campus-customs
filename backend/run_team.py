"""Give one agent a task from the command line (it can delegate to the rest of the team).

Works on the working database (data/campus_customs_new.db) through the MCP server.
Agents can only *request* payments; nothing is paid until a human approves it.

Examples (from this folder):
  .venv/Scripts/python run_team.py --agent Inventory --ticket 101 "Is the size S tee in stock?"
  .venv/Scripts/python run_team.py --agent Boss --ticket 103 "Review this ticket and plan next steps."
  .venv/Scripts/python run_team.py --db ../output/scratch.db --agent Accounting "What do we owe?"
"""

import argparse
import asyncio
import json
from pathlib import Path

from agents import run_team_task
from models import AGENT_NAMES

parser = argparse.ArgumentParser(description="Run the Campus Customs agent team")
parser.add_argument("task", help="What you want the agent to do")
parser.add_argument("--agent", default="Boss", choices=AGENT_NAMES, help="Who starts (default: Boss)")
parser.add_argument("--ticket", type=int, help="Ticket in focus (101, 102, 103)")
parser.add_argument("--db", type=Path, help="Use another database copy instead of the working copy")
args = parser.parse_args()

result = asyncio.run(run_team_task(args.agent, args.task, ticket_id=args.ticket, db_path=args.db,
                                   mode="test" if args.db else "run"))
print(json.dumps(result.model_dump(exclude_none=True), indent=2, ensure_ascii=False))
