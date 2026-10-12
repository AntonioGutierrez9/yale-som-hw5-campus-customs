# Campus Customs Multi-Agent Operations — Harness

Campus Customs is run by five AI agents (Boss, Inventory, Accounting, Facilities, Customer Service) that work tickets on a board. They read and change shop data only through an **MCP server**. A **FastAPI backend** runs them, and a **React dashboard** lets a human watch them and make every money decision. This file describes the final system (end of Problem 9).

```
React dashboard (frontend/, Vite, :5175)
   │  REST + polling
   ▼
FastAPI backend (backend/main.py, :8000) ── agents.py: 5 PydanticAI agents, gpt-6-luna via Portkey
   │  one MCP connection (stdio)                └─ every agent step ──► output/audit_trail.json (append-only)
   ▼
MCP server (mcp_server/server.py, FastMCP) ── the ONLY code that touches the database
   ▼
data/campus_customs_new.db (working copy)      data/campus_customs.db (original, never written)
```

## How to run

| Part | Command (from that folder, each with its own `.venv`) |
|---|---|
| Backend (starts the MCP server itself) | `uvicorn main:app --reload --port 8000` in `backend/` |
| Dashboard | `npm install` then `npm run dev` in `frontend/` → http://localhost:5175 |
| MCP server alone | `python server.py` (stdio) or `python server.py --http` (port 8001) in `mcp_server/` |
| Reset the working DB | the dashboard's **Reset database** button, or `POST /api/reset` |
| Rebuild the Problem 9 reports | `python build_reports.py` in `backend/` (with the API running) |

`PORTKEY_API_KEY` is read from `.env`, which is never committed. With `--reload`, don't edit backend files while agents are running: the folder is in OneDrive, and the file watcher can restart the server late.

## 1. Database

The original 9 tables keep their schema. The MCP server adds 3 tables to the **working copy only**, created automatically after a reset.

| Table | Purpose for the agents |
|---|---|
| `desk` | `date_today` = the shop's "today" (2026-08-31). Used for every overdue / due-soon check |
| `tickets` | The board: type, requester, linked SKU/size/qty, lease or invoice, status |
| `inventory` | Stock per SKU **and size** (e.g. tee size S = 0, hoodie M = 8) |
| `pricing` | Unit cost and list price, for margins, discounts, and restock cost |
| `vendors` | Specialty and lead days. Bulldog Print Co = apparel, 5 days |
| `leases` | Rent amount and `next_due` (Chapel Street shop, $2,400) |
| `cash_accounts` | `checking` balance ($3,400 at start). Only goes down; no revenue is modeled |
| `payments` | Every executed payment, with `approved_by` (a human). Undone payments get a `reversal` row with a negative amount |
| `invoices` | Vendor bills. An open invoice blocks that vendor from shipping |
| `approval_requests` *(added)* | Payments, purchase orders, and **discounts** waiting for or decided by a human. Statuses: `pending`, `paid`, `approved` (discount), `rejected`. `discount_pct` is set for discounts |
| `customer_drafts` *(added)* | Reply drafts to each ticket's requester. Always `draft`; nothing is ever sent |
| `ticket_notes` *(added)* | Working notes from agents, the System, and humans (decisions, status changes, undos) |

## 2. MCP tools (25)

| Group | Tools | Notes |
|---|---|---|
| Read (14) | `list_tickets`, `get_ticket`, `check_product_stock`, `list_inventory`, `get_product_pricing`, `quote_bulk_order`, `list_vendors`, `plan_restock`, `get_financial_status`, `list_invoices`, `get_lease`, `list_payments`, `list_approval_requests`, `list_customer_drafts` | Open SQLite read-only. `get_ticket` bundles a ticket's stock, pricing, invoice/vendor, lease, notes, drafts, and requests in one call |
| Agent writes (6) | `request_payment`, `request_purchase_order`, `record_discount_decision` (Boss only), `draft_customer_message`, `add_ticket_note`, `update_ticket_status` | Never move money. Requests and discounts are created **pending**. Amounts always come from the DB |
| Human only (4) | `approve_request`, `reject_request`, `undo_decision`, `sync_ticket_status` | Never given to an agent; called only by the dashboard routes |
| Backend only (1) | `request_discount_approval` | Sends an already-recorded Boss discount decision to the inbox |

Main tables per ticket: **101** `inventory`, `vendors`, `invoices`, `cash_accounts`, `payments` · **102** `leases`, `cash_accounts`, `payments` · **103** `inventory`, `pricing`, `vendors`, `cash_accounts`, `approval_requests`. Every ticket also uses `tickets`, `ticket_notes`, and `customer_drafts`.

## 3. The five agents

| Agent | Responsibilities | MCP tools |
|---|---|---|
| **Boss** | Triage, delegate, final calls (discount level, payment priority), ticket status, make sure the requester gets a reply | list/get tickets, financial status, quote, approvals, drafts, notes, status, `record_discount_decision` |
| **Inventory** | Stock by SKU/size, shortfalls, vendor choice, lead times, restock plans | get_ticket, stock, inventory, pricing, vendors, `plan_restock`, notes |
| **Accounting** | Cash, invoices, margins. Prepares payment and purchase-order requests for human approval | get_ticket, financial status, invoices, vendors, pricing, quote, plan_restock, approvals, payments, `request_payment`, `request_purchase_order`, notes |
| **Facilities** | Lease, rent amount and due date. Hands rent payment to Accounting | get_ticket, `get_lease`, financial status, payments, approvals, notes |
| **Customer Service** | One honest reply draft per ticket requester (customers and landlord), never sent. Quotes only human-approved discounts | get_ticket, stock, pricing, quote, drafts, `draft_customer_message`, notes |

Prompts: `backend/prompts/<agent>.md`, plus `shop_rules.md`, which every agent gets (business rules, team roster, step budget, and the every-ticket-gets-a-reply rule).

## 4. Delegation structure

- **Full connectivity:** any agent can call `delegate(to_agent, task)` on any other agent and gets that agent's structured report back. Several delegations can run in parallel.
- **Refused by the backend:** delegating to yourself, delegating back into the current chain (no A → B → A), going deeper than **4** levels, more than **6** delegations per run, or delegating to an agent that has used all of its steps.
- **Required reply:** if a Boss-led run ends without a Customer Service draft, the backend (logged as `System`) gives Customer Service one short task to write it, inside the same limits.
- The dashboard's **Draft reply** button runs only Customer Service for a ticket.

## 5. FastAPI routes (`backend/main.py`)

| Method | URL | What it does |
|---|---|---|
| GET | `/api/health`, `/api/status`, `/api/limits` | Health and MCP connection; busy state; the enforced limits and model |
| GET | `/api/tickets`, `/api/tickets/{id}` | Board with status and human-decision counts; one ticket with everything linked (full drafts) |
| POST | `/api/tickets/{id}/run` | Run the team on a ticket (Boss first). A second run since the last reset needs `continue_confirmed: true` (the human's permission) |
| POST | `/api/tickets/{id}/draft-reply` | Run only Customer Service to write the requester's reply |
| POST | `/api/tickets/{id}/sync-status` | Set the status from human decisions: pending → Pending approval; all approved → Approved; all rejected → Rejected; a mix → Partly approved |
| GET | `/api/activity`, `/api/runs` | Audit events with readable text (filters: since, run, ticket, since_reset); per-run, per-agent summaries |
| GET | `/api/approvals`, `/api/attention`, `/api/cash` | Requests with purpose and projected balance; overdue/low-stock/blocked/rent/pending alerts; checking and payments |
| POST | `/api/approvals/{id}/approve` · `/reject` · `/undo` | **Human only:** header `X-Human-Approval: true`, a real first and last name, and `confirm: true`. Then the MCP tool's own checks run |
| POST | `/api/reset` | Copy the original DB over the working copy and check the hash. Refused while agents run |

Errors always come back as `{"error": {"code", "message"}}`. CORS allows the local Vite server.

## 6. React dashboard (`frontend/`)

- **Main panels:** ticket board (status, human decision, **Run** / **Update status** / **Draft reply**), approval inbox (cards with amount or discount, purpose, balance now → after; your decisions with **Undo**), the checking balance in the header, and live activity (1.2 s polling while agents run, filters, **this ticket / all tickets**).
- **Collaboration map:** the five Handsome Dan bulldogs. It follows the live run, otherwise the selected ticket's last run. Real events drive the states: working (tail wags), delegating (arrow moves to the receiver), done.
- **Other panels:** ticket timeline, per-agent summaries, drafts and notes, and attention-needed.
- **Details:** confirm dialogs for approve, reject, undo, rerun, and reset. Yale "Y" cursor. Respects reduced-motion settings. Responsive at 375, 768, and 1440 px. Design notes are in `output/design.md`.

## 7. Human approval and financial safety rules

- **Agents can only request.** Payments, purchase orders, and discounts start as `pending`. Only `approve_request` (human only) executes them.
- **One decision per request.** Changing it requires `undo_decision`: a rejection or discount goes back to pending, and a payment is **reversed** (money back to checking, a reversal row, invoice reopened, or rent due date moved back). An undo is refused if a later payment depends on it.
- **Approval checks run in one transaction:** a real human name (agent, AI, and system names refused), still pending, **enough cash (never negative)**, the invoice still open, and **no purchase order to a vendor with an open invoice**.
- **Amounts come from the DB.** Discounts never go below unit cost and move no cash. Pending discounts aren't counted as cash.
- **Ticket statuses:** agents can't set Approved or Rejected (only human decisions can), and can't set Resolved while requests are pending.
- **Customers:** drafts go only to the ticket's requester, are never sent, and don't mention cash, invoices, margins, or AI.
- **The original DB is never opened by the server.** Reset only writes the working copy.

## 8. Token limits, loop protection, stopping conditions

These are configurable in `backend/limits.py` (environment variables `CC_*`) and enforced in code, not just in prompts.

| Limit | Value |
|---|---|
| Model | `gpt-6-luna` only, Portkey, Responses API (Chat Completions refused tools for this model), reasoning effort low |
| Steps (model calls) per ticket run | 25 for the whole team, delegations included |
| Steps per agent per run | 5 |
| Delegation depth / delegations per run | 4 / 6 |
| Output tokens per call / tokens per run / tool calls per run | 2,000 / 200,000 / 50 |

- **Graceful finish:** on an agent's last step, or when the team only has room left to wrap up the chain, its tools are hidden, so it has to give its final answer.
- **Hard stop:** each step is checked and reserved *before* the model is called, in one atomic action (this also covers parallel delegations). A step past a limit is stopped, and the stop is logged as `limit_stop`.
- **Repeated tool calls:** an identical read call isn't sent to the MCP server again until something is written. The same agent gets a "you already have this" note; another agent gets the saved result.
- **Stopping:** a run stops when the Boss answers (resolved, or blocked waiting on a human), or at a limit. At a limit, the work saved through tools is kept, a System note lists what's unfinished, and the dashboard asks the human before any rerun. Nothing restarts automatically.

## 9. Audit trail (`output/audit_trail.json`)

The trail is append-only: only the closing `]` is ever rewritten. Each entry has the time, run, mode, ticket, agent, depth, step, and event. The events are:

- `run_start`, `model_response` (tokens, step counters), `tool_call`, `tool_result`, `tool_repeat`
- `delegate` / `delegation_result`, `final_answer`, `limit_stop`, `run_end`
- Human and System events: `human_approval`, `human_rejection`, `human_undo`, `human_continue`, `status_sync`, `approval_created`, `db_reset`

Inputs and results are shortened, and secrets are redacted.

## 10. Problem 9 result (final full run)

The final run started after the reset at 11:51:43 PM on Oct 11 (03:51:43 UTC on Oct 12). Runs were `fef52e4662` (101), `fed70d372e` (102), and `84b19a1831` (103). Details are in `output/desk_tickets.html`, `output/resolved_tickets.json`, and `output/resolved_board.html`.

| Ticket | Final status | Human decision | Cash | Still open |
|---|---|---|---|---|
| 101 tee | Approved (not resolved) | #1 invoice 501 paid | −$840.00 | Tee size S still 0. The restock order was never requested |
| 102 rent | Approved (not resolved) | #2 rent paid | −$2,400.00 | Nothing operational; no agent marked it Resolved |
| 103 hoodies | Approved (not resolved) | #3 15% discount approved | $0.00 | 12 hoodies short; the $264 restock is unfunded |

- **Cash:** $3,400.00 − $3,240.00 = **$160.00**, which equals `cash_accounts`. Both payments were approved by Antonio Gutierrez.
- **Limits held:** 19, 16, and 16 of 25 team steps, with no agent over 5 steps.
- **Usage:** the final run made **51 model calls** using **192,312 input and 9,091 output tokens**. All Problem 9 runs, earlier attempts included, made 181 calls using 681,885 input and 30,110 output tokens.
- **Verification:** `output/final_verification.json`, 26/26 checks passed.

## 11. Tests

| Suite | What it covers | Last result |
|---|---|---|
| `mcp_server/test_server.py` | Every tool and guardrail (approvals, cash, vendor block, discounts, sync, undo), on a throwaway DB | 48/48 |
| `backend/test_team.py` | Tool lists, all 20 delegation directions, loops, depth, per-agent and team limits (graceful and hard stop, parallel), repeat blocking, required reply. No AI calls | 23/23 |
| `backend/test_sync.py` | Status sync, undo, one decision per request, through the real routes, on a throwaway DB | 17/17 |
| `backend/test_api.py` | Routes against the running server, plus one live run | 31/31 (Problem 7). Not rerun in Problem 9, because it resets the working DB |
| `backend/build_reports.py` | Cross-checks the reports against the DB, audit trail, and screenshots | 26/26 |
