// Small typed client for the FastAPI backend. Every call is real data; nothing is simulated.
import type {
  Activity, Approvals, Attention, Cash, Limits, RunResult, RunSummary, Status, SyncResult, TicketDetail, TicketList,
} from './types'

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || 'http://localhost:8000'

/** Errors from the backend come as {"error": {"code", "message"}}. */
export class ApiError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError(0, 'offline', `Can't reach the backend at ${API_URL}. Is uvicorn running?`)
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const err = body?.error
    throw new ApiError(res.status, err?.code ?? 'http_error', err?.message ?? `Request failed (${res.status})`)
  }
  return body as T
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  status: () => request<Status>('/api/status'),
  tickets: () => request<TicketList>('/api/tickets'),
  ticket: (id: number) => request<TicketDetail>(`/api/tickets/${id}`),
  run: (id: number, continueConfirmed = false) =>
    request<RunResult>(`/api/tickets/${id}/run`, { method: 'POST', body: JSON.stringify({ continue_confirmed: continueConfirmed }) }),
  limits: () => request<Limits>('/api/limits'),
  draftReply: (id: number) => request<RunResult>(`/api/tickets/${id}/draft-reply`, { method: 'POST', body: '{}' }),
  syncStatus: (id: number) => request<SyncResult>(`/api/tickets/${id}/sync-status`, { method: 'POST', body: '{}' }),
  activity: (p: { since?: number; limit?: number; ticket_id?: number; run_id?: string; since_reset?: boolean }) =>
    request<Activity>(`/api/activity${qs({ mode: 'run', ...p })}`),
  runs: (ticket_id?: number) => request<{ runs: RunSummary[]; count: number }>(`/api/runs${qs({ ticket_id, limit: 5 })}`),
  approvals: () => request<Approvals>('/api/approvals'),
  approve: (id: number, approved_by: string, note = '') =>
    request<{ ok: boolean; kind?: string; amount: number; checking_balance: number; effect: string }>(`/api/approvals/${id}/approve`, {
      method: 'POST',
      headers: { 'X-Human-Approval': 'true' },
      body: JSON.stringify({ approved_by, confirm: true, note }),
    }),
  reject: (id: number, rejected_by: string, reason: string) =>
    request<{ ok: boolean }>(`/api/approvals/${id}/reject`, {
      method: 'POST',
      headers: { 'X-Human-Approval': 'true' },
      body: JSON.stringify({ rejected_by, reason, confirm: true }),
    }),
  undo: (id: number, undone_by: string, reason: string) =>
    request<{ ok: boolean; kind: string; old_status: string; effect: string; checking_balance: number }>(`/api/approvals/${id}/undo`, {
      method: 'POST',
      headers: { 'X-Human-Approval': 'true' },
      body: JSON.stringify({ undone_by, reason, confirm: true }),
    }),
  cash: () => request<Cash>('/api/cash'),
  attention: () => request<Attention>('/api/attention'),
  reset: () => request<{ ok: boolean; sha256: string }>('/api/reset', { method: 'POST', body: JSON.stringify({ confirm: true }) }),
}

// ---------- formatting helpers ----------

export const money = (n: number | null | undefined) =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export const statusLabel: Record<string, string> = {
  open: 'Open',
  in_progress: 'In progress',
  waiting_on_approval: 'Pending approval',
  waiting_on_vendor: 'Waiting on vendor',
  resolved: 'Resolved',
  approved: 'Approved',
  rejected: 'Rejected',
  partially_approved: 'Partly approved',
}

/** Same rule as the backend: a person's first and last name, not an agent/AI/system name. */
const NOT_HUMAN = new Set(['boss', 'inventory', 'accounting', 'facilities', 'customer', 'service', 'agent', 'agents',
  'ai', 'bot', 'assistant', 'system', 'auto', 'automatic', 'model', 'gpt', 'luna', 'llm', 'claude', 'pydantic', 'mcp'])
export function humanNameError(name: string): string | null {
  const clean = name.trim().replace(/\s+/g, ' ')
  if (!/^[A-Za-z][A-Za-z'.-]+( [A-Za-z][A-Za-z'.-]+)+$/.test(clean)) return 'Enter your first and last name.'
  if (clean.split(' ').some((w) => NOT_HUMAN.has(w.toLowerCase().replace(/[.'-]/g, ''))))
    return 'Approvals must come from a person, not an agent or AI.'
  return null
}
