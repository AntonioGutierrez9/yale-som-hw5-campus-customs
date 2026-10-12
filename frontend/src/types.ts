// Shapes returned by the FastAPI backend (backend/main.py).

export type AgentName = 'Boss' | 'Inventory' | 'Accounting' | 'Facilities' | 'Customer Service'
export type Actor = AgentName | 'Human' | 'System'
export type TicketStatus = 'open' | 'in_progress' | 'waiting_on_approval' | 'waiting_on_vendor' | 'resolved'
  | 'approved' | 'rejected' | 'partially_approved'  // these three come only from human decisions

export interface Status {
  busy: boolean
  action: 'run' | 'reset' | null
  ticket_id: number | null
  run_id: string | null
  started_at: string | null
}

export interface Ticket {
  id: number
  type: string
  requester: string
  subject: string
  description: string | null
  sku: string | null
  size: string | null
  qty: number | null
  lease_id: number | null
  invoice_id: number | null
  status: TicketStatus
  created_at: string
  is_resolved: boolean
  pending_approvals: number
  approved_by_human: number
  rejected_by_human: number
  approval_requests: number
  drafts: number
  notes: number
}

export interface TicketList {
  today: string
  count: number
  tickets: Ticket[]
}

export interface Note {
  author: string
  note: string
  created_at: string
}

export interface Draft {
  id: number
  ticket_id: number
  recipient: string
  subject: string
  body: string
  written_by: string
  created_at: string
  status: string
}

export interface ApprovalRequest {
  id: number
  ticket_id: number | null
  kind: 'invoice' | 'rent' | 'purchase_order' | 'discount'
  ref_id: number | null
  vendor_id: number | null
  sku: string | null
  size: string | null
  qty: number | null
  amount: number
  reason: string | null
  requested_by: string
  requested_at: string
  status: 'pending' | 'paid' | 'approved' | 'rejected'  // approved = a discount (no cash moved)
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
  payment_id: number | null
  discount_pct?: number | null
  // added by /api/approvals
  moves_cash?: boolean
  quote?: { unit_price: number; list_price: number; order_total: number; gross_margin: number; margin_pct: number; in_stock_this_size: number; shortfall: number }
  purpose?: string
  vendor_name?: string | null
  vendor_blocked?: boolean
  blocking_invoices?: number[]
  projected_balance?: number
  sufficient_cash?: boolean
}

export interface Approvals {
  checking_balance: number
  pending_total: number
  cash_left_if_all_pending_paid: number
  requests: ApprovalRequest[]
}

export interface TicketDetail {
  ok: boolean
  today: string
  ticket: Ticket & { notes: string | null }
  stock?: {
    requested_size: string
    qty_in_requested_size: number | null
    shortfall: number
    all_sizes: { size: string; qty: number; location: string }[]
  }
  pricing?: { unit_cost: number; list_price: number } | null
  invoice?: { id: number; amount: number; due_date: string; status: string; description: string; days_overdue: number }
  vendor?: { vendor_id: number; name: string; lead_days: number; can_ship: boolean }
  lease?: { id: number; space_name: string; landlord: string; monthly_rent: number; next_due: string; days_until_due: number }
  notes: Note[]
  drafts: Draft[]
  approval_requests: ApprovalRequest[]
}

export interface Payment {
  id: number
  kind: string
  ref_id: number | null
  amount: number
  account: string
  paid_at: string
  approved_by: string
  reversed?: boolean  // a later 'reversal' row undid this payment
}

export interface Cash {
  today: string
  account: string
  balance: number
  as_of: string
  pending_approvals_total: number
  available_after_pending: number
  open_invoices_total: number
  rent_due_total: number
  payments: Payment[]
  total_paid: number  // net of reversals
  total_reversed: number
}

export type AuditEventKind =
  | 'run_start' | 'model_response' | 'tool_call' | 'tool_result' | 'tool_retry'
  | 'delegate' | 'delegation_result' | 'final_answer' | 'run_end'
  | 'human_approval' | 'human_rejection' | 'db_reset'
  | 'tool_repeat' | 'limit_stop' | 'human_continue' | 'status_sync' | 'approval_created' | 'human_undo'

export interface AuditEvent {
  id: number
  time: string
  run_id: string
  mode: 'run' | 'test'
  ticket_id?: number | null
  agent: Actor
  depth: number
  step?: number
  event: AuditEventKind
  tool?: string
  args?: string
  result?: string
  to_agent?: AgentName
  finish_reason?: string
  stop_reason?: string
  input_tokens?: number
  output_tokens?: number
  model?: string
  text: string
}

export interface Activity {
  events: AuditEvent[]
  count: number
  next_since: number
  status: Status
}

export interface AttentionItem {
  kind: 'overdue_invoice' | 'low_inventory' | 'blocked_vendor' | 'rent_due' | 'pending_approval' | 'cash_shortfall'
  severity: 'high' | 'medium'
  title: string
  detail: string
  ticket_id?: number | null
}

export interface Attention {
  today: string
  count: number
  counts: Record<string, number>
  items: AttentionItem[]
}

export interface AgentContribution {
  agent: AgentName
  tool_calls: Record<string, number>
  delegated_to: AgentName[]
  delegated_from: AgentName[]
  said: string[]
  model_steps: number
  input_tokens: number
  output_tokens: number
  finished: boolean
  stop_reason: string | null
}

export interface SyncResult {
  ok: boolean
  ticket_id: number
  old_status: TicketStatus
  new_status: TicketStatus
  changed: boolean
  approved: number
  rejected: number
  pending: number
  reason: string
}

export interface Limits {
  max_steps_per_ticket: number
  max_steps_per_agent: number
  max_delegation_depth: number
  max_delegations_per_run: number
  max_output_tokens_per_call: number
  max_tokens_per_ticket: number
  max_tool_calls_per_ticket: number
  model: string
  reasoning_effort: string
}

export interface RunSummary {
  run_id: string
  ticket_id: number | null
  mode: string
  status: 'running' | 'completed' | 'failed' | 'interrupted' | 'limit_stopped'
  model_steps: number
  limit_stops: string[]
  repeats_blocked: number
  started_at: string
  ended_at: string | null
  stop_reason: string | null
  lead_agent: AgentName
  outcome: string | null
  delegations: number
  refused_delegations: number
  input_tokens: number
  output_tokens: number
  agents: AgentContribution[]
  first_event_id: number
  last_event_id: number
}

export interface AgentReport {
  agent: AgentName
  summary: string
  findings: string[]
  actions_taken: string[]
  approval_request_ids: number[]
  draft_ids: number[]
  recommendation: string
  needs_human: string[]
  ticket_status: TicketStatus | null
}

export interface RunResult {
  run: {
    run_id: string
    agent: AgentName
    stop_reason: string
    output: AgentReport | null
    error: string | null
    model_requests: number
    tool_calls: number
    delegations: number
    input_tokens: number
    output_tokens: number
    steps_by_agent: Record<string, number>
    repeats_blocked: number
    limit_stops: string[]
    limit_hit: boolean
    unresolved: string | null
    customer_reply: string | null
  }
  ticket: TicketDetail
  events: AuditEvent[]
}
