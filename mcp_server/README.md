# Campus Customs MCP Server

This FastMCP server is the **only** way the Campus Customs agent team (and later the dashboard) reads or changes shop data. Agents check stock, money, rent, and pricing, and record their work. Money only moves when a human approves a request.

## Working database

The server uses `../data/campus_customs_new.db`, the working copy. It **refuses to open the original** `data/campus_customs.db`, so we can always reset by copying the original over the working copy. Tests can point it at another copy with the `CAMPUS_CUSTOMS_DB` environment variable.

- Read tools open the database in SQLite **read-only mode**.
- Write tools run in one transaction each and roll back if any check fails.
- "Today" always comes from `desk.date_today` (2026-08-31), not the real calendar.
- The server adds three tables to the working copy if they're missing: `approval_requests` (payments, purchase orders, and customer discounts waiting for a human), `customer_drafts`, and `ticket_notes`. The original 9 tables keep their schema.

## Tools (25)

### Read

| Tool | Reads | Returns |
|---|---|---|
| `list_tickets(status?)` | `tickets` | The board, optionally filtered by status |
| `get_ticket(ticket_id)` | `tickets` + everything linked | The ticket plus its stock and shortfall, pricing, invoice and vendor (can it ship?), lease (days until due), notes, drafts, and approval requests |
| `check_product_stock(sku, size)` | `inventory` | Name, qty, `in_stock`, and location; if the size doesn't exist, the sizes that do |
| `list_inventory(max_qty?)` | `inventory` | All stock, or only rows at or below `max_qty` (0 = out of stock) |
| `get_product_pricing(sku)` | `pricing`, `inventory` | Cost, list price, margin $ and %, and stock by size |
| `quote_bulk_order(sku, size, qty, discount_pct)` | `pricing`, `inventory` | Discounted unit price, total, cost, margin, a below-cost flag, and the shortfall |
| `list_vendors()` | `vendors`, `invoices` | Specialty, lead days, `can_ship`, blocking invoices, and earliest arrival |
| `plan_restock(sku, size, qty, vendor_id)` | `inventory`, `pricing`, `vendors`, `invoices`, `cash_accounts`, `approval_requests` | Cost, whether the vendor is blocked, arrival date, and cash left after pending requests and this order |
| `get_financial_status()` | `desk`, `cash_accounts`, `invoices`, `vendors`, `leases` | Cash, open invoices (days overdue), rent (days until due), and cash left if everything were paid |
| `list_invoices(status?)` | `invoices`, `vendors` | Invoices with vendor name and days overdue |
| `get_lease(lease_id)` | `leases`, `payments` | Rent, next due date, days until due, and past rent payments |
| `list_payments()` | `payments` | Every payment made, with who approved it |
| `list_approval_requests(status?)` | `approval_requests`, `cash_accounts` | Pending, paid, and rejected requests, plus the cash left if everything pending were paid |
| `list_customer_drafts(ticket_id?)` | `customer_drafts` | Saved drafts (never sent) |

### Agent write tools (no money moves)

| Tool | What it does | Rules it enforces |
|---|---|---|
| `request_payment(kind, ref_id, requested_by, reason, ticket_id?)` | Saves a **pending** request to pay an invoice or rent | Amount comes from the database. The invoice must be open; rent must be due within 30 days. No duplicates. |
| `request_purchase_order(vendor_id, sku, size, qty, requested_by, reason, ticket_id?)` | Saves a **pending** restock PO | Amount = unit_cost × qty. Must be a SKU/size we stock. A vendor with an open invoice gets the request flagged as blocked. No duplicates. |
| `draft_customer_message(ticket_id, subject, body, written_by)` | Saves a draft to the ticket's requester | The recipient is taken from the ticket. Status `draft`. Never sent. |
| `add_ticket_note(ticket_id, note, author)` | Adds a working note | The ticket must exist. |
| `update_ticket_status(ticket_id, status, note, updated_by)` | Changes ticket status and logs why | Can't set `resolved` while approvals are pending. |
| `record_discount_decision(ticket_id, discount_pct, rationale, decided_by)` | Records the Boss's discount and creates a **pending discount approval** for a human | Boss only. Never below unit cost. No cash moves. |

### Human-only tools (never given to agents)

| Tool | What it does | Rules it enforces |
|---|---|---|
| `approve_request(request_id, approved_by, note?)` | **Pays** (or, for a discount, approves it with no cash movement): adds a `payments` row, lowers checking, and marks the invoice paid or moves the lease's `next_due` forward a month | The approver must be a person, not an agent name. The request must be pending. Cash must cover it (no negative balances). The invoice must still be open. For a PO, the vendor can't have an open unpaid invoice. |
| `reject_request(request_id, rejected_by, reason)` | Rejects a pending request | The rejecter must be a person's name. |
| `undo_decision(request_id, undone_by, reason)` | Takes back a decision so the request is pending again. A paid request is **reversed**: a `reversal` row (negative amount) is added, money goes back to checking, and the invoice reopens or the rent due date moves back | Human name required. Refused if a later payment depends on it. One decision per request: undo before deciding again. |
| `sync_ticket_status(ticket_id, updated_by)` | Sets the ticket status from human decisions: pending → `waiting_on_approval`, all approved → `approved`, all rejected → `rejected`, mix → `partially_approved` | Human only. No-request and resolved tickets are left alone. |

### Backend-only tool

| Tool | What it does |
|---|---|
| `request_discount_approval(ticket_id, discount_pct, requested_by, reason)` | Sends an already-recorded discount decision to the approval inbox (used once in Problem 9 for a decision made before discount approvals existed). |

SKUs and sizes aren't case-sensitive. Agent-name fields only accept `Boss`, `Inventory`, `Accounting`, `Facilities`, or `Customer Service`.

## How to run

From this folder, using its own `.venv`:

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python server.py          # stdio (the backend starts it this way)
.venv/Scripts/python server.py --http   # http://127.0.0.1:8001/mcp
.venv/Scripts/python test_server.py     # 48 guardrail tests on a throwaway copy
```

Port 8001 keeps port 8000 free for the FastAPI backend. The server is also registered as `campus-customs` in `.mcp.json`.
