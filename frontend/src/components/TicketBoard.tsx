import { AGENTS } from '../agents'
import { statusLabel } from '../api'
import type { AgentLive } from '../hooks/agentStates'
import { useState } from 'react'
import type { AgentName, Status, Ticket, TicketList } from '../types'
import { Bulldog } from './Bulldog'

const TYPE_LABEL: Record<string, string> = {
  customer_order: 'Customer order',
  rent_notice: 'Rent notice',
  price_override: 'Price override',
}

function itemLine(t: Ticket) {
  if (t.sku) return `${t.qty ?? 1} × ${t.sku} · size ${t.size}`
  if (t.lease_id) return `Lease #${t.lease_id}`
  return null
}

function humanDecision(t: Ticket): { label: string; cls: string } {
  if (t.pending_approvals) return { label: `${t.pending_approvals} pending human decision${t.pending_approvals === 1 ? '' : 's'}`, cls: 'hd-pending' }
  if (t.approved_by_human && t.rejected_by_human) return { label: `Human: ${t.approved_by_human} approved · ${t.rejected_by_human} rejected`, cls: 'hd-mixed' }
  if (t.approved_by_human) return { label: `Human approved ${t.approved_by_human} request${t.approved_by_human === 1 ? '' : 's'}`, cls: 'hd-approved' }
  if (t.rejected_by_human) return { label: `Human rejected ${t.rejected_by_human} request${t.rejected_by_human === 1 ? '' : 's'}`, cls: 'hd-rejected' }
  return { label: 'No approval requests', cls: 'hd-none' }
}

export function TicketBoard({ tickets, status, selected, onSelect, onRun, onSync, onDraft, runningTicket, live }: {
  tickets: TicketList | null
  status: Status | null
  selected: number | null
  onSelect: (id: number) => void
  onRun: (id: number) => void
  onSync: (id: number) => Promise<void>
  onDraft: (id: number) => Promise<void>
  runningTicket: number | null
  live: Record<AgentName, AgentLive>
}) {
  const busy = !!status?.busy
  const [syncing, setSyncing] = useState<number | null>(null)
  const sync = async (id: number) => {
    setSyncing(id)
    try { await onSync(id) } finally { setSyncing(null) }
  }
  return (
    <section className="panel board-panel" id="tickets" aria-labelledby="board-title">
      <header className="panel-head">
        <div>
          <h2 id="board-title">Ticket board</h2>
          <p className="panel-sub">{tickets ? `${tickets.count} tickets · shop date ${tickets.today}` : 'Loading tickets…'}</p>
        </div>
      </header>

      <div className="board">
        {!tickets && [0, 1, 2].map((i) => <div key={i} className="ticket skeleton" aria-hidden="true" />)}
        {tickets?.tickets.map((t) => {
          const isRunning = (busy && status?.ticket_id === t.id && status.action === 'run') || runningTicket === t.id
          const working = isRunning ? AGENTS.filter((a) => live[a].state === 'working' || live[a].state === 'delegating') : []
          return (
            <article
              key={t.id}
              className={`ticket ${selected === t.id ? 'is-selected' : ''} ${isRunning ? 'is-running' : ''}`}
              aria-label={`Ticket ${t.id}`}
            >
              <button className="ticket-select" onClick={() => onSelect(t.id)} aria-pressed={selected === t.id}>
                <div className="ticket-top">
                  <span className="ticket-id">#{t.id}</span>
                  <span className="ticket-type">{TYPE_LABEL[t.type] ?? t.type}</span>
                  <span className={`status status-${t.status}`}>{statusLabel[t.status] ?? t.status}</span>
                </div>
                <h3>{t.subject}</h3>
                <p className="ticket-desc">{t.description}</p>
                <dl className="ticket-meta">
                  <div><dt>From</dt><dd>{t.requester}</dd></div>
                  {itemLine(t) && <div><dt>Item</dt><dd className="mono">{itemLine(t)}</dd></div>}
                  {t.invoice_id && <div><dt>Invoice</dt><dd>#{t.invoice_id}</dd></div>}
                </dl>
                <div className={`human-decision ${humanDecision(t).cls}`}>{humanDecision(t).label}</div>
                <div className="ticket-counts">
                  <span className={t.pending_approvals ? 'warn' : ''}>{t.pending_approvals} pending approval{t.pending_approvals === 1 ? '' : 's'}</span>
                  <span>{t.drafts} draft{t.drafts === 1 ? '' : 's'}</span>
                  <span>{t.notes} note{t.notes === 1 ? '' : 's'}</span>
                </div>
              </button>

              <div className="ticket-foot">
                {isRunning ? (
                  <div className="ticket-running" role="status">
                    <span className="spinner" aria-hidden="true" />
                    <span>Agents working…</span>
                    <span className="mini-dogs">
                      {working.map((a) => <Bulldog key={a} agent={a} size={28} state={live[a].state} />)}
                    </span>
                  </div>
                ) : (
                  <>
                    <span className="ticket-created">Opened {new Date(t.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</span>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => sync(t.id)}
                      disabled={syncing !== null || (busy && status?.ticket_id === t.id)}
                      title="Update this ticket's status from the human approve/reject decisions (no agents run)"
                    >
                      {syncing === t.id ? 'Updating…' : 'Update status'}
                    </button>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => onDraft(t.id)}
                      disabled={busy || runningTicket !== null}
                      title="Have Customer Service write the requester's reply draft (runs only Customer Service; never sent)"
                    >
                      {t.drafts ? 'New reply' : 'Draft reply'}
                    </button>
                    <button
                      className="btn btn-primary"
                      onClick={() => onRun(t.id)}
                      disabled={busy || runningTicket !== null}
                      title={busy ? 'Agents are busy; wait for the current run to finish.' : 'Run the five-agent team on this ticket'}
                    >
                      {t.notes || t.approval_requests ? 'Run again' : 'Run agents'}
                    </button>
                  </>
                )}
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
