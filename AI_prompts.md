# Homework 5 — AI Prompt Log

This file records the prompts used while completing Homework 5.

## Logging rule

Update this file after every prompt related to a problem, as the work happens.

- Start each problem with a heading in the form `## Problem N — Title`.
- **Initial prompt:** the first prompt for the problem, verbatim.
- **Follow-up prompts:** every later prompt for the same problem, verbatim and in order (Follow-up 1, Follow-up 2, …). If none were needed, write "No follow-up prompt was used for this problem."
- **What was missing:** one sentence under each follow-up summarizing what the earlier prompts for that problem did not cover.
- Keep the problems in the order they were worked on.

### Template

```markdown
## Problem N — Title

### Initial prompt

<exact prompt>

### Follow-up prompts

#### Follow-up 1

<exact prompt>

**What was missing:** <one sentence>
```

---

## Problem 2 — Study the campus customs database

### Initial prompt

I want you to open data/campus_customs.db and inspect every table and its fields.

1. Create an exact copy of the original database named data/campus_customs_new.db. Keep the original untouched, we will use the new copy throughout the rest of the homework.
2. Study the three open tickets in the database. Understand what each ticket is asking for, which tables are involved, and how the information connects across tables. Don't resolve the tickets yet.
3. Create output/harness.md. For every table, include:
   * Table name
   * All fields/columns
   * One short explanation of why that table matters for our agents
4. Add a short section summarizing the three open tickets and the tables each one will likely involve.

Use the actual database schema and data rather than making assumptions.
Keep the harness clear, concise, and in my normal writing style. We will continue updating this same file in later problems.

### Follow-up prompts

No follow-up prompt was used for this problem.

## Problem 3 — Build the MCP server

### Initial prompt

I want you to create an MCP server in mcp_server/ using FastMCP, connected to data/campus_customs_new.db.
Based on the three tickets we studied, create these three read-only tools:
1. check_product_stock(sku, size)
Look up the product's name, SKU, size, available quantity, and location from the inventory table.
This will help with Ticket 101, where the requested Bulldog Tee size S is out of stock, and Ticket 103, where the customer wants more hoodies than we currently have.
2. get_financial_status()
Retrieve the checking account balance, open invoices (including vendor information), and upcoming rent obligations using cash_accounts, invoices, vendors, and leases.
This will help Ticket 102 determine whether rent can be paid and Ticket 101 identify the unpaid vendor invoice blocking restocking.
3. get_product_pricing(sku)
Retrieve the unit cost, list price, and available inventory by size using pricing and inventory.
This will help Ticket 103 evaluate the requested bulk hoodie discount, including the product margin and inventory shortage.
Use the actual database fields and return clear, structured results. Do not invent information or modify any records yet.
You do not need to connect or run the MCP server in this problem.
Documentation
Update output/harness.md with a Problem 3 section listing each tool, the exact tables it reads, the tickets it supports (101, 102, or 103), and one specific sentence explaining why it helps resolve those tickets.
Also create mcp_server/README.md explaining the server's purpose, its working database, and the three available tools.
Keep both documents short and in my normal writing style.

### Follow-up prompts

No follow-up prompt was used for this problem.

## Problem 4 — Add the MCP server to vibe coder and test each tool

### Initial prompt

I want you to connect the FastMCP server we created to this vibe coding environment so you can call its tools directly.

1. Configure the MCP connection and save the configuration in .mcp.json at the project root (or the equivalent configuration file for this environment). Make sure it connects to our existing MCP server and uses data/campus_customs_new.db.
2. Once connected, actually call and test all three tools:
   * check_product_stock — check CC-TEE-WHITE, size S, for Ticket 101.
   * get_financial_status — check the cash balance, unpaid invoices, and rent obligations for Tickets 101 and 102.
   * get_product_pricing — check the navy hoodie involved in Ticket 103, using its actual SKU from the database.
3. Create output/mcp_smoke.json containing one test record for each tool, including:
   * The exact prompt I asked you to test
   * The tool name
   * The actual tool output

Verify that every returned value matches data/campus_customs_new.db. Do not invent or manually fabricate tool responses.
If the connection or a tool fails, fix it and rerun the test.
Keep the existing MCP tools and database unchanged unless a correction is necessary.

### Follow-up prompts

No follow-up prompt was used for this problem.

## Problem 5 — Build the agent team and grow the MCP tools

### Initial prompt

I want you to build the multi-agent team using PydanticAI, based on the MCP server and database tools we created.
AGENT TEAM
Create five agents under backend/, each with its own detailed system prompt in backend/prompts/:

* Boss: Reviews tickets, delegates work, coordinates agents, and makes final decisions.
* Inventory: Checks stock by SKU/size, identifies shortages, evaluates vendors and lead times, and plans restocking.
* Accounting: Reviews cash, invoices, margins, and financial obligations. Prepares payments and purchase orders for human approval.
* Facilities: Handles rent, leases, due dates, and other shop-related obligations.
* Customer Service: Prepares accurate customer responses and updates without actually sending messages.

Write specific prompts covering each agent's responsibilities, tools, decision-making rules, and limitations. Use the actual tickets and business rules we studied rather than generic descriptions.
AGENT CONNECTIONS
Use PydanticAI so all five agents can delegate tasks to one another, not just through the Boss.
Create shared Pydantic models and dependency types in backend/models.py.
Use PORTKEY_API_KEY and only gpt-6-luna through Portkey for every agent.
MCP TOOLS
All shop information and database operations must go through the existing MCP server.
Expand its tools as needed to handle Tickets 101, 102, and 103, including inventory, vendors, unpaid invoices, cash, rent, pricing, ticket information and other possible inquiries that might come up.
Use the actual database schema. Do not create a separate database-access layer in the backend that bypasses MCP. Make sure tools enforce important rules, especially human approval before payments, sufficient cash, and vendor restrictions.
AUDIT TRAIL
As the agents run, append their activity to output/audit_trail.json, record enough information to understand each agent-loop step, including timestamp, agent, action/tool, short inputs/results, delegation, and stop reason. Never overwrite previous entries or log secrets.
DOCUMENTATION
Update output/harness.md with:

* Each agent's responsibilities
* Every MCP tool, the tables it uses, and which tickets it supports
* Safety guardrails for customers, money, approvals, and database changes
* Agent-loop/delegation limits, token-saving measures, and model configuration

Also update mcp_server/README.md to reflect all available tools.
VERIFICATION
Check that all five agents initialize correctly, can access MCP tools, and can delegate to one another.
Test a few representative interactions without executing unapproved payments or completing the full ticket-resolution run yet.
Show me the five agents, the tools added, how delegation works, and the tests performed.

### Follow-up prompts

No follow-up prompt was used for this problem.

## Problem 6 — Plan the three tickets

### Initial prompt

I want you to create output/desk_tickets.html, a clean, standalone HTML page with five functional tabs: Ticket 101, Ticket 102, Ticket 103, Cash, and Reflection.
For each ticket, add an Expected section using the plans below. Do not change these plans or invent different delegations. Leave an empty Actual section for later.
Leave Cash and Reflection marked "Coming later."
Ticket 101 - Out-of-Stock Bulldog Tee
Situation: Tauhid Zaman ordered one Classic Bulldog Tee (CC-TEE-WHITE), size S, but inventory is zero. Bulldog Print Co has an unpaid $840 invoice (#501) and a five-day lead time.
Boss should contact Inventory first, because the main problem is fulfilling an out-of-stock order.
Expected delegations:

1. Boss → Inventory: Use get_ticket, list_inventory, and list_vendors to confirm the shortage and identify the vendor.
2. Inventory → Accounting: Ask Accounting to investigate invoice #501 and available cash using list_invoices, list_approval_requests, and get_ticket.
3. Accounting → Boss: Recommend whether to create request_payment for invoice #501, considering the upcoming rent. Payment must remain pending human approval.
4. Inventory: Use plan_restock to estimate the cost, lead time, and feasibility. If appropriate, use request_purchase_order, recognizing that the vendor may remain blocked until the invoice is paid.
5. Boss → Customer Service: Use draft_customer_message to explain the shortage and that restocking is being evaluated, without promising a confirmed delivery date.
6. Boss: Use add_ticket_note and update_ticket_status to document progress. Do not mark the ticket resolved while required approvals are pending.

Expected outcome: A documented stock shortage, appropriate approval requests if feasible, and an honest customer draft. No unapproved payments or promises.
Ticket 102 - Rent Notice
Situation: Elm City Properties requests $2,400 rent, due September 2, 2026. The shop has $3,400 in checking.
Boss should contact Facilities first, because this is a lease obligation.
Expected delegations:

1. Boss → Facilities: Use get_ticket and get_lease to confirm the landlord, amount, and due date.
2. Facilities → Accounting: Ask Accounting to review cash and competing obligations using get_ticket, list_invoices, and list_approval_requests.
3. Accounting → Facilities/Boss: Confirm that paying rent would leave $1,000 before other payments, and flag the $840 outstanding vendor invoice.
4. Accounting: Use request_payment to prepare the $2,400 rent payment for human approval.
5. Facilities → Boss: Recommend prioritizing the rent payment before its due date.
6. Boss: Document the decision with add_ticket_note and update the ticket status appropriately using update_ticket_status.

Expected outcome: A rent payment request awaiting human approval. No money moves until a person uses approve_request.
Ticket 103 - Yale AI Club Bulk Hoodie Request
Situation: Yale AI Club wants 20 medium navy hoodies (CC-HOOD-NAVY), but only 8 are available. Unit cost is $22 and list price is $58.
Boss should contact Inventory first, because the requested quantity exceeds available stock.
Expected delegations:

1. Boss → Inventory: Use get_ticket and list_inventory to confirm the 12-unit shortage.
2. Inventory: Use list_vendors and plan_restock to evaluate supplier availability, lead time, and replenishment cost.
3. Inventory → Accounting: Ask Accounting to review restocking affordability and profitability using quote_bulk_order, list_invoices, and list_approval_requests.
4. Accounting → Boss: Report the financial implications. The regular unit margin is $36 (62.1% of selling price), and 12 additional units would cost approximately $264 at the recorded unit cost, before additional charges. Evaluate discounts without going below cost.
5. Boss: Make the final discount decision and use record_discount_decision to save it. Only the Boss should call this tool.
6. If restocking is feasible, Inventory/Accounting should use request_purchase_order to prepare the purchase for human approval.
7. Boss → Customer Service: Use draft_customer_message to prepare an accurate response explaining stock availability, the discount decision, and any pending restocking.
8. Boss: Use add_ticket_note and update_ticket_status to record progress without marking unresolved obligations complete.

Expected outcome: A documented discount decision, restocking plan or approval request if feasible, and a customer draft. No below-cost discount or unapproved purchase.
HTML REQUIREMENTS
Make the page polished, readable, and easy to compare later with actual agent behavior.
Use clear headings, delegation sequences, and MCP tool names. Keep the Expected content above intact, but format it naturally.
The HTML must work when double-clicked, without external dependencies.
Do not run the agents, execute payments, or fill in the Actual sections yet.

### Follow-up prompts

#### Follow-up 1

No, keep it as you have it, that will be better to see the difference of what i expected and what the actual agents will do.

**What was missing:** The initial prompt didn't say whether to change the agents' tool access to match the plan (Inventory calling request_purchase_order), so I chose to keep the current setup to compare expected and actual behavior.

## Problem 7 — Backend routes

### Initial prompt

I want you to create backend/main.py using FastAPI so the React dashboard we will build later can communicate with our multi-agent system.
Add API routes that:

1. List tickets: Return the three tickets (101, 102, 103), including their current status (open/resolved).
2. Run agents: Accept a ticket ID and run the existing multi-agent team on that ticket, returning the result.
3. Agent activity: Return recent agent events, including which agent acted, what it said, delegations, and MCP tools used, so the dashboard can refresh.
4. Human approvals: Allow a human to approve a pending payment or purchase order. Use the existing human-only MCP approval tool, enforce its safety checks, and update the database accordingly. Agents must never be able to approve requests themselves.
5. Cash balance: Return the current checking balance from cash_accounts.
6. Reset database: Restore campus_customs_new.db from the original campus_customs.db so we can start a fresh run.

Reuse the existing agents and MCP tools. Do not create another database-access layer that bypasses MCP for normal shop operations.
Make the API responses structured and easy for React to use. Include appropriate error handling and CORS for the local frontend.
Make sure the approval route is explicitly restricted to human-initiated actions, not accessible as an agent tool. Require a real human identity for the approver rather than accepting an AI-generated approval.
The reset route should only affect the working database, never the original, and should not run while agents are processing tickets.
Testing
Start the backend from backend/ using:
uvicorn main:app --reload --port 8000
Test the routes and confirm they return correct database information. Test the agent-run route without approving any payments, and confirm agent events are available.
Update output/harness.md with a short section listing each API route, its URL, and what it does.

### Follow-up prompts

No follow-up prompt was used for this problem.

## Problem 8 — Agent dashboard

### Initial prompt

I want you to build a React + Vite + TypeScript dashboard in frontend/, connected to our existing FastAPI backend.
I want a creative and polished Campus Customs operations control center where I can manage tickets, watch the five agents collaborate in real time, and approve important decisions.
1. Core Dashboard Features

* Ticket board: Display Tickets 101, 102, and 103 with their descriptions, current statuses, and buttons to run the multi-agent team.
* Live agent activity: Show which agent is working, its messages, delegations, and MCP tool calls. Refresh automatically while agents are running.
* Agent summaries: After each run, show what each agent contributed and the final outcome.
* Ticket status: Reflect the real backend status. Do not automatically resolve tickets with pending approvals or unfinished work.
* Human approvals: Display pending payment and purchase-order requests with Approve buttons connected to the backend. Require confirmation.
* Cash balance: Show the checking balance prominently and refresh it after approved payments.
* Loading and error states: Clearly communicate running, completed, failed, and pending actions.

2. Additional Creative Features
Agent Collaboration Map
Create a visual map showing the five agents and their connections. Highlight active agents and animate the connection when one agent delegates to another. Use actual backend events.
Smart Approval Inbox
Each approval card should show its amount, purpose, related ticket, current checking balance, and projected balance after approval. Warn if cash is insufficient.
Ticket Timeline
Show a chronological timeline of each ticket's investigation, agent activity, tool calls, decisions, and pending approvals.
Attention-Needed Panel
Highlight overdue invoices, low inventory, blocked vendors, upcoming rent deadlines, and pending approvals using real database information.
Reset and Rerun
Add a Reset button with confirmation that restores the working database from the original. Prevent resetting while an agent run is active.
3. Hansome Dan Agent Avatars
Create five matching illustrated bulldog avatars inspired by Hansome Dan, Yale's mascot.
Each bulldog should have an accessory representing its responsibilities:

* Boss: Yale-blue tie and clipboard.
* Inventory: Warehouse vest and package.
* Accounting: Glasses and calculator.
* Facilities: Hard hat and wrench.
* Customer Service: Headset and friendly expression.

Keep the avatars consistent in illustration style, proportions, and Yale-inspired colors.
Use them throughout the dashboard, particularly in the collaboration map, activity feed, and agent summaries.
Animated Tail Wagging
The bulldogs should react to real agent activity:

* Idle: Stationary bulldog.
* Active: Bulldog smoothly wags its tail.
* Delegating: Tail wags while an animated arrow moves toward the receiving agent.
* Finished: Tail stops and the bulldog returns to its idle pose.

Animate the tail rather than the entire bulldog when possible. Keep the animation playful but professional, lightweight, and respectful of reduced-motion settings.
Do not simulate agent activity just to trigger animations.
4. Custom Yale Cursor
Replace the standard mouse pointer with a slightly larger capital Y inspired by Yale's logo.

* Use Yale blue (#00356B).
* Make the Y crisp and recognizable.
* Keep an accurate clickable hotspot.
* Preserve text-selection behavior and accessibility.
* Use the normal cursor as a fallback where appropriate.

5. Overall Design
Use Yale/Campus Customs branding with a modern, professional operations-dashboard feel.
I want the dashboard to look like a real business control center while incorporating creative Yale elements.
Use clean typography, Yale navy, white, complementary colors, clear status indicators, organized panels, and subtle transitions.
Make the layout responsive and easy to navigate. The ticket board, live agent activity, approvals, and cash balance should be the main elements.
Prioritize functionality and usability over unnecessary effects.
6. Implementation and Testing
Use real FastAPI data, not hardcoded results or simulated agent activity.
Extend the backend only where necessary.
Connect to http://localhost:8000 and configure CORS for the Vite frontend.
Run the frontend with npm run dev.
Test ticket selection, agent runs, live activity, delegations, tail animations, approvals, cash balance updates, reset functionality, navigation, and responsive behavior.
Make sure previous functionality continues working.
7. Create output/design.md
Create output/design.md using the exact text below. Do not ask AI to write or expand this explanation. You can make minor formatting adjustments, but keep the wording and meaning the same.
Campus Customs Operations Dashboard – Design Notes
Overall Design
For the dashboard, I wanted to create something that feels like a real operations center rather than just a page displaying information. My goal was to make it easy for someone managing Campus Customs to understand what is happening with each ticket, which agents are working, and what decisions still require human intervention.
I chose a design inspired by Yale's branding, using Yale blue as the main color, complemented by white and neutral tones. I wanted the interface to look professional and organized while still having some personality.
Dashboard Layout
I organized the dashboard around the information I think would be most useful for someone running the business.
The ticket board gives a quick overview of the three open tickets and their current statuses. The live activity section shows what the agents are doing, while the approval inbox makes it easy to identify decisions that require human action. I also included the checking balance because the business has limited cash, and financial decisions affect what the agents can recommend.
I wanted to avoid having the user navigate through several pages just to understand the current situation.
Hansome Dan Agent Avatars
Since Campus Customs is a Yale-related business, I thought it would be interesting to use Hansome Dan, Yale's bulldog mascot, to represent the five agents.
Each agent has a different accessory that reflects its responsibilities. The Boss has a tie and clipboard, Inventory has a warehouse vest and package, Accounting has glasses and a calculator, Facilities has a hard hat and wrench, and Customer Service has a headset.
I chose to keep the bulldogs in the same illustration style so they look like members of the same team, while their accessories make it easy to recognize their different roles.
Agent Animations and Collaboration Map
One of my favorite ideas was making the bulldogs wag their tails when their agents are working.
When an agent is idle, its bulldog stays still. When it starts working, its tail begins moving. When one agent delegates to another, the connection between them is highlighted, making the collaboration visible.
I wanted this to be more than a decorative animation. By connecting it to real agent activity, someone looking at the dashboard can immediately see which agents are working and how tasks move between them.
The collaboration map also helps demonstrate that the agents work as a team rather than as five independent chatbots.
Custom Yale Cursor
I also wanted to add a small detail that makes the dashboard feel more connected to Yale, so I chose a custom mouse cursor shaped like a capital Y in Yale blue.
The cursor is slightly larger than normal to make it more visible, but I wanted to keep it simple enough that it does not interfere with using the dashboard.
Approval Inbox and Financial Information
I think one of the most important parts of this assignment is understanding that the agents can recommend actions, but certain decisions still require human approval.
For that reason, I wanted the approval inbox to be very visible. Each request shows why the payment or purchase is needed, how much it costs, and how it would affect the checking balance.
Showing the projected balance is particularly useful because Campus Customs has limited cash and needs to prioritize expenses.
Ticket Timeline and Alerts
I added a timeline to make it easier to follow how each ticket progresses. Instead of only showing the final result, it displays the actions and decisions that led to that outcome.
I also wanted an attention-needed section that highlights issues such as unpaid invoices, inventory shortages, upcoming rent payments, and pending approvals.
These features help the user focus on the most important problems without having to read every agent message.
Reset and Rerun
I included the ability to reset the working database because I wanted to be able to test the agents multiple times under the same initial conditions.
This makes it easier to compare how the system handles different tickets and verify that the agents are following the required approval process.
Final Thoughts
Overall, I wanted the dashboard to balance functionality and creativity. The most important information should be easy to find, the approval process should be clear, and the agent activity should be transparent.
The Hansome Dan avatars and animations add a Yale identity to the project, but I also wanted them to serve a purpose by helping the user understand what the agents are doing.
My goal was to create something that would be enjoyable to use while still being practical for managing the operations of a small business.

### Follow-up prompts

No follow-up prompt was used for this problem.

## Problem 9 — Resolve the tickets

### Initial prompt

I want you to make a full run of the multi-agent system across Tickets 101, 102, and 103. I want to complete the assignment while minimizing token consumption and maintaining accurate financial records.
1. Token Limits and Loop Protection
Before running any agents, review the existing agent execution logic and add safeguards to prevent unnecessary token usage.

* Use only `gpt-6-luna` through Portkey for every agent, as required.
* Limit each ticket to a maximum of 25 total agent execution steps, shared across all five agents, including delegations.
* Limit each individual agent to 5 execution steps per ticket.
* Limit delegation depth to 4 levels and prevent circular delegation.
* Set a reasonable token/output limit per model call.
* Prevent repeated tool calls with identical arguments when the information has not changed.
* Avoid unnecessary agent discussions or repeated analysis.
* Stop when the ticket is resolved, genuinely blocked, or reaches its execution limit.
* If a limit is reached, save the progress, explain what remains unresolved, and stop safely instead of continuing.
* ive a prompt to the Human if they wish to continue running the agents and only continue running the agents if you have permision from the human.

These limits should be configurable and enforced by the backend, not just mentioned in the agents' prompts.
Do not automatically restart failed or incomplete runs, and do not increase the limits without asking me.
Keep enough flexibility for the agents to collaborate meaningfully, but prioritize efficient execution.
2. Reset the Database and Record Starting Cash
Before the full run:

1. Reset `data/campus_customs_new.db` from the original `data/campus_customs.db`.
2. Confirm the reset was successful.
3. Read and record the starting checking balance directly from `cash_accounts`.
4. Confirm that no previous approvals, payments, or test-run changes remain in the working database.

Do not modify the original database.
3. Run All Three Tickets
Run Tickets 101, 102, and 103 through the actual multi-agent system using the dashboard.
The goal is to resolve all three tickets, following the real business constraints and human approval requirements.

* Allow agents to delegate work and use the existing MCP tools.
* Do not bypass vendor restrictions, inventory constraints, or cash limits.
* All payments and purchase orders must receive real human approval through the existing approval workflow.
* Never have agents approve their own requests.
* Do not invent approvals, transactions, customer messages, or successful outcomes.
* Never send real emails or contact vendors.

If an approval is required, pause and let me approve or reject it through the dashboard before continuing.
If a ticket cannot be resolved, record the actual reason and leave its status accurate. Do not force a resolved status just to complete the assignment.
Run the tickets efficiently, respecting the execution limits.
4. Update output/desk_tickets.html
Open the existing `output/desk_tickets.html` from Problem 6.
Keep its five tabs:

* Ticket 101
* Ticket 102
* Ticket 103
* Cash
* Reflection

For each ticket, preserve the original Expected section and fill in the Actual section using the real execution logs.
Include:

* Which agents worked
* What each agent contributed
* Which agents delegated to others
* Which MCP tools were used
* Important decisions and approval requests
* Final ticket status and outcome
* Differences between Expected and Actual

Do not invent activity that is missing from the logs.
Redesign the HTML to Match the Frontend
Update the visual design of `desk_tickets.html` so it looks like an extension of the React dashboard.
Use the same:

* Yale-blue color palette and typography
* Cards, tabs, spacing, and status indicators
* Hansome Dan agent avatars and their role-specific accessories
* Agent colors and visual identities
* Ticket timeline styling
* Financial information and approval styling

If practical, reuse the same local visual assets from the frontend.
Make the Expected vs. Actual comparison easy to read, preferably using side-by-side sections on desktop and stacked sections on smaller screens.
Include the Hansome Dan avatars beside each agent's contributions.
The HTML must remain a standalone file that can be opened by double-clicking, without requiring the React server, backend, internet access, or external dependencies. Embed any assets necessary for this.
Keep the existing information from Problem 6 rather than recreating or losing it.
5. Complete the Cash Tab
Fill the Cash tab with an accurate financial reconciliation based on the working database.
Include:

* Starting checking balance immediately after reset
* Cash movements attributable to each ticket
* Payment or purchase description
* Amount paid
* Human approval associated with the transaction
* Checking balance after each payment
* Ending checking balance

Make it easy to understand which ticket caused each cash movement and why.
Use a table with a running balance and a clear summary.
Important: Only approved and executed payments should reduce cash. Pending or rejected requests must not be treated as payments.
Verify that:
Starting cash − actual cash outflows = ending cash
The ending balance must match `cash_accounts` in `data/campus_customs_new.db` exactly.
If the numbers do not reconcile, investigate and fix the underlying issue before reporting completion. Do not adjust figures just to make them match.
6. Save the Required Outputs
output/resolved_tickets.json
For each ticket, include:

* Ticket ID
* Final status
* Short outcome
* Each agent's contribution
* Delegations and important tools used
* Human approvals, including amounts and outcomes

Use actual execution data.
output/resolved_board.html
Create a standalone HTML page that I can double-click to open.
Include a screenshot of the React dashboard for each ticket (101, 102, and 103) showing its final state.
Use real screenshots captured from the running frontend, not recreated or simulated images.
Embed the screenshots directly in the HTML so the page works offline.
If any ticket remains unresolved, show its actual final state and explain why rather than presenting a false resolved screenshot.
output/audit_trail.json
Append the actual runs, including timestamps, agents, tool calls, delegations, approvals, outcomes, and any execution-limit stops.
Preserve the existing audit trail rather than replacing it.
output/harness.md
Finish the documentation so it covers:

* Database tables and their purpose
* MCP tools
* Five agents and their responsibilities
* Agent delegation structure
* FastAPI routes
* React dashboard
* Human approval and financial safety rules
* Token limits, loop protection, and stopping conditions

Keep the documentation clear and concise.
7. Final Verification
Before finishing:

1. Verify the final status of all three tickets against the working database.
2. Confirm that every recorded payment had human approval.
3. Reconcile the checking balance with the database.
4. Confirm the Actual sections match the audit trail.
5. Open and verify both standalone HTML files.
6. Confirm the three dashboard screenshots are embedded correctly.
7. Check that the agent execution limits were respected.
8. Report the actual number of model calls and token usage if available.

Give me a short final summary showing each ticket's status, starting cash, total cash spent, ending cash, approvals completed, and any unresolved issues.
Do not claim that a ticket is resolved or that a test passed unless it was actually verified.

### Follow-up prompts

#### Follow-up 1

I approved request #1, run tickets 102 and 103

**What was missing:** The initial prompt left the human approval step open, so this follow-up records that I approved request #1 (invoice 501) in the dashboard and told the agents to continue with Tickets 102 and 103.

#### Follow-up 2

I approved request #2.

**What was missing:** The earlier prompts did not cover the rent decision, so this follow-up records that I approved request #2 ($2,400 rent for Ticket 102) in the dashboard.

#### Follow-up 3

I want you to update the backend and the frontend so that when a human approves or rejects something, it updates on the frontend and shows that ticket either as approved or rejected if there was an action taken by a human, but show as pending if there has not been any action taken by a human. put and update button on the frontend so that the status of a ticket can update without rerunning the whole thing.

**What was missing:** The earlier prompts had no way to reflect a human approval or rejection in the ticket status without rerunning the agents, so tickets stayed on "waiting on approval" after I had already decided.

#### Follow-up 4

For ticket #103, the conclusion is that they are waiting on approval from a human but there was no approval sent to the approval inbox, can you fix it so that there can also be a different type of approval? in this case the approval should about the discount it is giving to a customer

**What was missing:** The approval workflow only covered payments and purchase orders, so the Boss's discount decision for Ticket 103 never reached the approval inbox even though the ticket said it was waiting on a human.

#### Follow-up 5

Can you update it so that when i make a decision I can choose to go back on that decision? also dont let me make more than one decision per ticket

**What was missing:** Human decisions were final and could not be reversed, and the rule for how many decisions are allowed was not defined (I then chose one decision per approval request, which must be undone before it can be changed).

#### Follow-up 6

Rerun it all tickets so that we use that data for the problem 9 outputs

**What was missing:** The earlier runs happened before the discount approvals, status sync, and undo features existed, so I asked for a fresh full run (reset first, then Tickets 101, 102, and 103) to produce the Problem 9 outputs from consistent data.

#### Follow-up 7

I approved request #1, run ticket 102

**What was missing:** The full run paused for the invoice 501 decision, so this follow-up records my approval of request #1 and tells the agents to continue with Ticket 102.

#### Follow-up 8

I approved request #2, run ticket 103

**What was missing:** The full run paused for the rent decision, so this follow-up records my approval of request #2 and tells the agents to continue with Ticket 103.

#### Follow-up 9

The agent collaboration map is not updating as i change tickets, it should display the collaboration of the agents in the ticket selected as well as the live agent activity

**What was missing:** The map and activity feed always showed the most recent run on any ticket, so selecting a different ticket did not show that ticket's own agent collaboration.

#### Follow-up 10

Can you update it so that each ticket has a draft written by customer service? I think all customers should have a reply independently if there is a decision to be made. please change it so that the customers have a reply even if it says that they are waiting for a reply but state that the agents have let know the decision to the owners

**What was missing:** Customer Service replies depended on the Boss delegating to it, so Tickets 102 and 103 ended without any reply to the requester, even when the decision was waiting on the owners.

#### Follow-up 11

go ahead with the problem 9 outputs

**What was missing:** The full run and the human decisions were finished, so this follow-up told the agent to produce the Problem 9 reports from that data.

#### Follow-up 12

help me do an analysis of what i expected the agents to do and what they actually did for each of the tickets

**What was missing:** The reports listed the Expected and Actual activity side by side, but did not explain step by step how well each plan was followed or why the agents behaved differently.

## Problem 10 — Reflection

### Initial prompt

Open output/desk_tickets.html and fill in the Reflection tab using the text I have written below. Do not generate a different reflection.
Keep the existing Yale-themed design and preserve the Expected, Actual, and Cash tabs. Do not rerun agents or modify the database.
Reflection – Campus Customs Multi-Agent System
1. How would I evaluate the agents' performance?
Ticket 101 – Inventory shortage
I think the agents were good at identifying the problem but inefficient at solving it. They correctly identified that the size S white tee was out of stock and that Bulldog Print Co. would not ship until its $840 invoice was paid. Accounting requested the payment, which I approved, but the tee was never restocked.
The biggest problem was the repeated delegation between Inventory and Accounting. Both reached their five-step limits without making much additional progress. The agents understood the situation, but their collaboration became unnecessarily complicated.
Ticket 102 – Rent payment
This was the most successful ticket from an execution perspective. Facilities verified the lease, Accounting prepared the $2,400 payment request, and I approved it.
I found it interesting how the sequence of tickets affected the decisions. After paying the $840 supplier invoice in Ticket 101, the business had $2,560 available. Paying rent reduced that balance to $160.
The agents handled the payment correctly and respected the approval process, although the ticket itself was never formally resolved.
Ticket 103 – Bulk hoodie order
I think the agents made reasonable financial decisions. They identified that only eight of the 20 requested hoodies were available, evaluated different discounts, and recommended 15% off.
I approved the discount, resulting in a $986 order value and a 55.4% gross margin. However, restocking the missing 12 hoodies would cost $264, and the business only had $160.
The agents correctly avoided an unaffordable purchase order. However, the Boss reached its execution limit before updating the ticket status, and Customer Service drafted the response before the discount was approved.
Overall, the financial analysis was good, but the workflow remained incomplete.
2. How did Actual compare with Expected?
Ticket 101: My original plan was sequential, with the Boss delegating to Inventory and Inventory consulting Accounting. Instead, the Boss assigned work to Inventory and Accounting simultaneously. This created overlapping work, and the two agents eventually exhausted their execution limits. The invoice was paid, but the restock was never ordered. Only two of my six planned steps were fully matched.
Ticket 102: This was relatively close to my plan, matching four of six steps. The Boss delegated directly to Facilities and Accounting rather than having Facilities delegate to Accounting. Accounting requested the payment, which I approved. Customer Service also drafted a landlord response, which I had not originally included.
Ticket 103: This followed my plan most closely, matching six of eight steps. Inventory identified the shortage, Accounting evaluated discounts and margins, and the Boss recorded the discount decision. The restock was correctly avoided because cash was insufficient. However, the customer draft was prepared before approval, and the Boss did not update the final status.
One important difference across all three tickets was that the Boss delegated tasks in parallel rather than following the sequence I had planned. I think this can make the system faster, but it also creates the risk of agents duplicating work.
Another interesting difference was that the agents sometimes chose more efficient tools than I had expected. For example, get_ticket already returned inventory, invoice, and lease information, so separate calls to list_inventory or list_invoices were not always necessary.
3. What would have been simpler with one agent?
I think Tickets 101 and 102 could have been handled more efficiently by a single agent with access to all the MCP tools.
In Ticket 101, one agent could have checked inventory, identified the unpaid invoice, evaluated the cash balance, and requested payment without repeated delegations.
Ticket 102 was even more straightforward: verify rent, check available cash, request approval, and record the payment.
Having specialized agents was more valuable for Ticket 103 because the decision involved inventory, pricing, profitability, and customer communication.
If I redesigned the system, I would use a hybrid approach: one main agent handles simple tasks and delegates only when specialized analysis is necessary.
I would also make sure the system resumes after human approvals. In this run, the agents stopped when approval was needed, but they did not automatically continue afterward. This left all three tickets without a final resolved status.
4. Three new problems the existing agents could solve
   1. Another product shortage: If a customer orders an unavailable sweatshirt size, Inventory could use list_inventory, list_vendors, and plan_restock to evaluate replenishment. Accounting could check affordability, and Customer Service could draft a response.
   2. Another bulk discount request: If a student organization wants 35 T-shirts at a discount, Accounting could use quote_bulk_order to compare profitability, Inventory could verify availability, and the Boss could use record_discount_decision to record the decision.
   3. Prioritizing competing payments: If several invoices become due around the rent payment, Accounting and Facilities could use list_invoices, get_lease, and list_approval_requests to evaluate obligations and recommend a payment priority based on available cash.
5. Three problems the agents could not solve with the existing tools
   1. Forecasting sales and cash flow: The system tracks expenses but not incoming revenue. This limited Ticket 103 because the agents could not consider future cash inflows. I would add a Sales agent with record_sale, list_sales, and forecast_cash_flow tools.
   2. Finding alternative suppliers: Ticket 101 showed how dependent the business was on Bulldog Print Co. I would add a Procurement agent with search_suppliers, request_supplier_quote, and compare_supplier_options tools to evaluate alternative prices, delivery times, and payment terms.
   3. Predicting inventory needs: The agents identified the 12-hoodie shortage but could not anticipate it. I would add an Inventory Planning agent with analyze_sales_history, forecast_product_demand, and recommend_reorder_levels tools to make purchasing more proactive.
6. Final Reflection
What surprised me most was that having more agents did not necessarily make the process more efficient. The Boss assigned tasks in parallel, which could save time, but sometimes created overlapping work and unnecessary delegation.
I also realized that the tools available to an agent can matter more than the number of agents involved. Some tools already returned enough information to make additional calls unnecessary.
From a financial perspective, I found the relationship between profitability and liquidity particularly interesting. Ticket 103 was profitable even after the discount, but the business could not afford the inventory needed to fulfill it. A profitable opportunity is not necessarily executable if the cash is unavailable.
I also think the execution limits were an important lesson. They prevented unnecessary token consumption in Ticket 101, but they also stopped the Boss from completing the final status update in Ticket 103. Finding the right balance between efficiency and completeness is important.
Although none of the tickets reached a resolved status, the system respected its safety rules: payments required human approval, no purchase orders were placed without sufficient cash, and no customer messages were actually sent.
If I improved the system, I would focus on more selective delegation, resuming workflows after human approvals, and making sure the agents complete the final administrative steps.
Overall, I think the assignment showed that multi-agent systems can support real business decisions, but they still require clear responsibilities, financial controls, and human oversight.

Implementation
Insert this reflection into the Reflection tab of output/desk_tickets.html.
Keep the writing exactly as provided unless a factual correction is necessary based on the actual logs.
Match the existing Yale branding, typography, spacing, and card styling. Make the sections easy to navigate and read.
Preserve all other tabs and their information. Do not rerun agents or modify the database.

### Follow-up prompts

No follow-up prompt was used for this problem.

## Problem 11 — Submit to GitHub

### Initial prompt

[attached screenshot: the required hw5/ file tree — AI_prompts.md, requirements.txt, .env.example, .gitignore, .mcp.json, README.md, data/ (campus_customs.db, campus_customs_new.db), mcp_server/ (server.py, README.md), frontend/, backend/ (main.py, models.py, prompts/ with boss.md, inventory.md, accounting.md, facilities.md, customer_service.md), output/ (harness.md, mcp_smoke.json, desk_tickets.html, design.md, resolved_tickets.json, resolved_board.html, audit_trail.json, github_url.txt)]

I want you to prepare my entire Campus Customs project for submission and push it to a public GitHub repository so the graders can clone and run it.
Do not submit anything to Canvas. Just give me the final GitHub URL, and I will submit it myself.
1. Repository Structure
Make sure the repository follows the structure in the picture.
Include all other source files needed to run the frontend, backend, and MCP server, even if they are not explicitly listed above.
Do not remove any required files or previous homework deliverables.
2. Security and Configuration
Before pushing:

* Make sure the real .env is excluded from Git.
* Include .env.example with placeholder values for PORTKEY_API_KEY and any other required configuration.
* Check that API keys, credentials, and other secrets are not exposed in source code, logs, configuration files, or Git history.
* Verify that .mcp.json does not contain credentials or machine-specific absolute paths.
* Exclude unnecessary files such as node_modules/, virtual environments, caches, and temporary files.
* Include both database files in data/, as explicitly required by the assignment.
* Preserve the working database and its actual final results.

3. README.md
Create a clear README explaining:

1. What the Campus Customs multi-agent system does.
2. The five agents and their responsibilities.
3. How to install the Python dependencies from requirements.txt.
4. How to configure .env using .env.example.
5. How to install the frontend dependencies.
6. How to start the MCP server.
7. How to start the FastAPI backend using uvicorn main:app --reload --port 8000 from backend/.
8. How to start the React dashboard using npm run dev from frontend/.
9. How to reset data/campus_customs_new.db by copying the original database when a clean run is needed.
10. How to run all three tickets and handle human approvals through the dashboard.
11. Where to find the output files and documentation.

Use commands that actually work with the existing project. Keep the instructions straightforward so the graders can reproduce the system.
4. Final Checks
Before publishing:

* Verify the required folder structure and files.
* Confirm the frontend and backend can start.
* Confirm the MCP server configuration is correct.
* Check that the standalone HTML deliverables work.
* Make sure AI_prompts.md includes the prompts used for the assignment.
* Confirm the two database files are included.
* Make sure the reflection and all required output files are present.
* Verify that no real secrets will be committed.

Do not rerun the agents or reset the database during these checks. I want to preserve the results from Problems 9 and 10 and avoid unnecessary token consumption.
5. Publish to GitHub
Create a public GitHub repository for Homework 5 and push the complete project.
Use a clear repository name, such as yale-som-hw5-campus-customs.
After publishing:

1. Verify that the repository is public and accessible.
2. Confirm the required files are visible on GitHub.
3. Save the repository URL in output/github_url.txt.
4. Commit and push that file as well.
5. Give me the exact repository URL so I can submit it to Canvas myself.

If GitHub authentication or permission is needed, ask me to complete that step rather than attempting to bypass it.
Do not submit anything to Canvas.
When finished, give me the GitHub URL and a brief confirmation that the repository is public, the required files are included, and no secrets were exposed.

### Follow-up prompts

No follow-up prompt was used for this problem.
