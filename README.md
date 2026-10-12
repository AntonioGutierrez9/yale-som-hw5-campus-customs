# Campus Customs — Multi-Agent Operations (Homework 5)

**Campus Customs** is a small Yale merch shop run by a team of five AI agents. Open tickets (a customer order, a rent notice, a bulk-discount request) land on a board. The agents investigate them, delegate work to each other, and prepare payments, purchase orders, discounts, and customer replies. **A human approves every money and discount decision** in a React dashboard.

```
React dashboard (frontend/, :5175)  ──REST──►  FastAPI backend (backend/, :8000)  ──MCP──►  MCP server (mcp_server/)  ──►  data/campus_customs_new.db
                                                 5 PydanticAI agents, gpt-6-luna via Portkey      the only code that touches the DB
```

The data in this repo is the **real final state** after the full run (Problem 9). The database, audit trail, and reports all match it. Read the reports before running anything new.

## 1. The five agents

| Agent | Responsibilities |
|---|---|
| **Boss** | Reads each ticket, decides who works on it, delegates, makes the final calls (discount level, payment priority), sets the ticket status, and makes sure the requester gets a reply |
| **Inventory** | Checks stock by SKU and size, finds shortfalls, picks the vendor, and plans restocks (cost, lead time, arrival date) |
| **Accounting** | Watches cash, invoices, and margins. Prepares payment and purchase-order requests **for human approval** |
| **Facilities** | Handles the lease: rent amount, due date, landlord. Passes the rent payment to Accounting |
| **Customer Service** | Writes one honest reply draft per requester. Drafts are never sent, and it only quotes discounts a human approved |

- Any agent can delegate to any other agent.
- Limits are enforced by the backend: 25 steps per ticket run, 5 per agent, delegation depth 4, and 2,000 output tokens per call.
- Every step is logged to `output/audit_trail.json`.

## 2. Install

You need Python 3.12+ (tested on 3.14), Node.js 20+ (tested on 24), and a Portkey API key.

**Python dependencies** (one virtual environment at the repo root):

```bash
python -m venv .venv
```

Activate it. On Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

On macOS / Linux:

```bash
source .venv/bin/activate
```

Then install:

```bash
pip install -r requirements.txt
```

**Configure `.env`** by copying the example and adding your key:

```bash
cp .env.example .env
```

On Windows: `copy .env.example .env`. Then open `.env` and set `PORTKEY_API_KEY=...`. The other values are optional.

**Frontend dependencies:**

```bash
cd frontend
npm install
```

## 3. Start the system

Keep the root `.venv` activated in every Python terminal.

**MCP server.** You don't need to start it yourself: the backend launches `mcp_server/server.py` automatically over stdio and keeps one connection open. To run it on its own (for example, to inspect its tools):

```bash
python mcp_server/server.py          # stdio
python mcp_server/server.py --http   # http://127.0.0.1:8001/mcp
```

`.mcp.json` registers the same server as `campus-customs` for MCP-aware coding tools. It runs `python mcp_server/server.py` from the repo root, so start the tool with the `.venv` activated.

**FastAPI backend** (terminal 1):

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Check it at http://localhost:8000/api/health (it should show `"mcp_connected": true`). The interactive docs are at http://localhost:8000/docs.

**React dashboard** (terminal 2):

```bash
cd frontend
npm run dev
```

Open http://localhost:5175. The dashboard talks to `http://localhost:8000`; change that with `VITE_API_URL` in `frontend/.env` (see `frontend/.env.example`).

## 4. Reset the working database (for a clean run)

`data/campus_customs.db` is the original and is never written. `data/campus_customs_new.db` is the working copy that the agents and approvals change. To start over, use one of these:

- **In the dashboard**, click **Reset database** in the top bar and confirm. It's refused while agents are running.
- **Or by copying the file**, with the backend stopped. From the repo root:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

On Windows: `copy /Y data\campus_customs.db data\campus_customs_new.db`

> ⚠️ Resetting replaces the committed final results from Problem 9. If you only want to look at them, don't reset. Running agents costs Portkey tokens (about 50–80k per ticket).

## 5. Run the three tickets and handle approvals

1. **Reset** (step 4) and check that checking shows **$3,400.00** and all three tickets are **Open**.
2. On the **Ticket board**, click **Run agents** on **Ticket 101**. Watch the **Agent collaboration map** (tails wag while an agent works, and an arrow moves on each delegation) and the **Live agent activity** feed.
3. When the run ends, its request appears in the **Approval inbox**: for 101, paying overdue invoice #501 ($840). Click **Approve…** (or **Reject**), type your **first and last name**, tick the confirmation box, and submit. Approving executes the payment and updates the checking balance and the ticket status. Agents can never approve anything.
4. Repeat for **Ticket 102** (rent, $2,400) and **Ticket 103** (bulk hoodies: a **customer discount** approval, which moves no cash).
5. Useful controls:
   - **Undo** a decision under "Your decisions", which reverses a payment or withdraws an approval.
   - **Update status** syncs a ticket's status from your decisions.
   - **Draft reply** has only Customer Service write the requester's reply.
   - **Run again** asks for your permission before rerunning a ticket.
6. The **Ticket detail** panel shows each ticket's timeline, per-agent summaries, and the drafts and notes. **Attention needed** lists overdue invoices, low stock, blocked vendors, and rent deadlines.

Optional offline checks (no AI calls, run on a throwaway copy of the database):

```bash
python mcp_server/test_server.py
cd backend
python test_team.py
python test_sync.py
```

`backend/test_api.py` **resets the working database**, so don't run it if you want to keep the results.

## 6. Outputs and documentation

| File | What it is |
|---|---|
| `output/harness.md` | The full technical reference: database, all 25 MCP tools, agents, delegation, API routes, dashboard, approval and financial safety rules, limits, tests |
| `output/desk_tickets.html` | Standalone page (double-click it): Expected vs Actual for tickets 101–103, the **Cash** reconciliation, and the **Reflection** |
| `output/resolved_board.html` | Standalone page with real screenshots of the dashboard showing each ticket's final state |
| `output/resolved_tickets.json` | Per ticket: final status, outcome, each agent's contribution, delegations, tools, human approvals, replies, plus cash and token usage |
| `output/audit_trail.json` | Append-only log of every agent step, human approval, limit stop, and reset |
| `output/mcp_smoke.json` | Problem 4 smoke test of the MCP tools |
| `output/design.md` | Dashboard design notes |
| `output/final_verification.json` | The 26 checks run on the final reports (statuses, approvals, cash, limits, screenshots) |
| `output/github_url.txt` | This repository's URL |
| `mcp_server/README.md` | The MCP server and its tools |
| `AI_prompts.md` | Every prompt used for this assignment, by problem |

Other files:
- `output/screenshots/` holds the PNGs embedded in `resolved_board.html`.
- `output/archive/desk_tickets_problem6.html` is the original Problem 6 plan page.
- `output/full_run_start*.json` are the starting snapshots recorded before each full-run attempt.
- `backend/build_reports.py` rebuilds the reports from the data (with the backend running).

**Final results (Problem 9):** all three tickets are **Approved** by the human but **not resolved**. Checking went **$3,400 → $160** ($840 invoice + $2,400 rent). The 15% discount moved no cash. See the Reflection tab for the analysis.
