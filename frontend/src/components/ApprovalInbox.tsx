import { useState } from 'react'
import { ApiError, clock, humanNameError, money } from '../api'
import type { ApprovalRequest, Approvals, Cash } from '../types'
import { AgentAvatar } from './AgentAvatar'
import { Modal } from './Modal'

const KIND_LABEL = { invoice: 'Vendor invoice', rent: 'Rent payment', purchase_order: 'Purchase order', discount: 'Customer discount' } as const

function blockers(r: ApprovalRequest, balance: number): string[] {
  const out: string[] = []
  if (r.kind === 'discount') return out  // no cash moves, so cash can't block it
  if (r.amount > balance) out.push(`Not enough cash: ${money(r.amount)} needed, ${money(balance)} in checking.`)
  if (r.vendor_blocked)
    out.push(`${r.vendor_name} won't ship while invoice ${r.blocking_invoices?.map((i) => `#${i}`).join(', ')} is unpaid. Approve that first.`)
  return out
}

function ApprovalCard({ r, balance, onDecide }: { r: ApprovalRequest; balance: number; onDecide: (r: ApprovalRequest, mode: 'approve' | 'reject') => void }) {
  const projected = balance - (r.kind === 'discount' ? 0 : r.amount)
  const issues = blockers(r, balance)
  return (
    <article className={`appr ${issues.length ? 'appr--blocked' : ''}`} aria-label={`Approval request ${r.id}`}>
      <div className="appr-top">
        <span className={`kind kind-${r.kind}`}>{KIND_LABEL[r.kind]}</span>
        <span className="appr-id">#{r.id}</span>
        {r.ticket_id && <span className="appr-ticket">Ticket {r.ticket_id}</span>}
      </div>
      {r.kind === 'discount' ? (
        <>
          <div className="appr-amount">{r.discount_pct}% off <span className="appr-amount-sub">−{money(r.amount)} vs list price</span></div>
          <p className="appr-purpose">{r.purpose}</p>
          {r.quote && (
            <div className="appr-balance appr-quote" aria-label="Discounted order">
              <div><span>Unit price</span><strong>{money(r.quote.unit_price)}</strong><small>list {money(r.quote.list_price)}</small></div>
              <div><span>Order total</span><strong>{money(r.quote.order_total)}</strong><small>{r.qty} units</small></div>
              <div><span>Margin</span><strong className={r.quote.margin_pct < 50 ? 'warn' : ''}>{r.quote.margin_pct}%</strong><small>{money(r.quote.gross_margin)}</small></div>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="appr-amount">{money(r.amount)}</div>
          <p className="appr-purpose">{r.purpose}</p>
        </>
      )}
      {r.reason && <p className="appr-reason">“{r.reason}”</p>}
      <div className="appr-who">
        <AgentAvatar actor={r.requested_by} size={22} /> Requested by {r.requested_by} · {clock(r.requested_at)}
      </div>
      {r.kind === 'discount' ? (
        <p className="appr-note">No cash moves. Checking stays at {money(balance)}; approving lets Customer Service quote this price.</p>
      ) : (
        <div className="appr-balance" aria-label="Checking balance before and after approval">
          <div><span>Checking now</span><strong>{money(balance)}</strong></div>
          <div className="appr-arrow" aria-hidden="true">→</div>
          <div><span>After approval</span><strong className={projected < 0 ? 'bad' : projected < 500 ? 'warn' : ''}>{money(projected)}</strong></div>
        </div>
      )}
      {issues.map((m) => <p key={m} className="appr-warn" role="note">⚠ {m}</p>)}
      <div className="appr-actions">
        <button className="btn btn-ghost" onClick={() => onDecide(r, 'reject')}>Reject</button>
        <button className="btn btn-approve" onClick={() => onDecide(r, 'approve')} disabled={issues.length > 0}
          title={issues.length ? issues.join(' ') : 'Review and approve this payment'}>
          Approve…
        </button>
      </div>
    </article>
  )
}

type Mode = 'approve' | 'reject' | 'undo'

/** What undoing a decision will do, in plain words. */
function undoEffect(r: ApprovalRequest): string {
  if (r.status === 'paid') return `reverses the payment: ${money(r.amount)} goes back to checking` +
    (r.kind === 'invoice' ? ` and invoice #${r.ref_id} becomes unpaid again` : r.kind === 'rent' ? ' and the rent due date moves back a month' : '')
  if (r.status === 'approved') return `withdraws the ${r.discount_pct}% discount approval`
  return 'withdraws the rejection'
}

export function ApprovalInbox({ approvals, cash, onApprove, onReject, onUndo }: {
  approvals: Approvals | null
  cash: Cash | null
  onApprove: (id: number, name: string) => Promise<void>
  onReject: (id: number, name: string, reason: string) => Promise<void>
  onUndo: (id: number, name: string, reason: string) => Promise<void>
}) {
  const [open, setOpen] = useState<{ r: ApprovalRequest; mode: Mode } | null>(null)
  const [name, setName] = useState(() => localStorage.getItem('cc-approver') ?? '')
  const [confirmed, setConfirmed] = useState(false)
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const balance = cash?.balance ?? approvals?.checking_balance ?? 0
  const pending = approvals?.requests.filter((r) => r.status === 'pending') ?? []
  const decided = approvals?.requests.filter((r) => r.status !== 'pending').reverse() ?? []

  const start = (r: ApprovalRequest, mode: Mode) => {
    setOpen({ r, mode })
    setConfirmed(false)
    setReason('')
    setError(null)
  }
  const nameError = name ? humanNameError(name) : null

  const submit = async () => {
    if (!open) return
    setSubmitting(true)
    setError(null)
    try {
      localStorage.setItem('cc-approver', name.trim())
      if (open.mode === 'approve') await onApprove(open.r.id, name.trim())
      else if (open.mode === 'undo') await onUndo(open.r.id, name.trim(), reason.trim())
      else await onReject(open.r.id, name.trim(), reason.trim())
      setOpen(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  const r = open?.r
  const canSubmit = !!r && !submitting && !humanNameError(name) &&
    (open?.mode === 'approve' ? confirmed && blockers(r, balance).length === 0
      : open?.mode === 'undo' ? confirmed && reason.trim().length >= 3
      : reason.trim().length >= 3)

  return (
    <section className="panel inbox-panel" id="approvals" aria-labelledby="inbox-title">
      <header className="panel-head">
        <div>
          <h2 id="inbox-title">Approval inbox {pending.length > 0 && <span className="count-pill">{pending.length}</span>}</h2>
          <p className="panel-sub">
            {approvals ? (pending.length
              ? `${money(approvals.pending_total)} pending · ${money(approvals.cash_left_if_all_pending_paid)} left if all approved`
              : 'Nothing waiting for a human') : 'Loading…'}
          </p>
        </div>
      </header>

      {approvals && approvals.pending_total > balance && (
        <p className="banner banner-bad" role="alert">Pending requests ({money(approvals.pending_total)}) are more than the cash in checking ({money(balance)}). Decide what comes first.</p>
      )}

      <div className="inbox">
        {pending.length === 0 && (
          <div className="empty">
            <strong>No pending approvals.</strong>
            <span>When agents prepare a payment or purchase order, it waits here for you. Agents can't approve anything.</span>
          </div>
        )}
        {pending.map((p) => <ApprovalCard key={p.id} r={p} balance={balance} onDecide={start} />)}
      </div>

      {decided.length > 0 && (
        <details className="decided" open>
          <summary>Your decisions ({decided.length}) · one per request; undo to change it</summary>
          <ul>
            {decided.map((d) => (
              <li key={d.id} className="decision">
                <span className={`badge ${d.status === 'paid' || d.status === 'approved' ? 'b-good' : 'b-bad'}`}>{d.status}</span>
                <span className="decision-text">
                  <strong>#{d.id}</strong> {d.purpose} · {d.kind === 'discount' ? `${d.discount_pct}% (−${money(d.amount)})` : money(d.amount)}
                  {d.ticket_id ? ` · ticket ${d.ticket_id}` : ''} · by {d.decided_by}
                </span>
                <button className="btn btn-ghost btn-xs" onClick={() => start(d, 'undo')} title={`Undo: ${undoEffect(d)}`}>Undo</button>
              </li>
            ))}
          </ul>
        </details>
      )}

      <Modal open={!!open} onClose={() => !submitting && setOpen(null)}
        title={open?.mode === 'approve' ? `Approve request #${r?.id}` : open?.mode === 'undo' ? `Undo your decision on #${r?.id}` : `Reject request #${r?.id}`} labelledBy="approve-title">
        {r && (
          <form className="approve-form" onSubmit={(e) => { e.preventDefault(); if (canSubmit) submit() }}>
            <dl className="kv">
              <div><dt>What</dt><dd>{r.purpose}</dd></div>
              {r.kind === 'discount'
                ? <div><dt>Discount</dt><dd className="big">{r.discount_pct}% (−{money(r.amount)})</dd></div>
                : <div><dt>Amount</dt><dd className="big">{money(r.amount)}</dd></div>}
              {r.kind === 'discount' && r.quote && (
                <div><dt>Customer pays</dt><dd>{money(r.quote.order_total)} ({money(r.quote.unit_price)}/unit, margin {r.quote.margin_pct}%)</dd></div>
              )}
              <div><dt>Ticket</dt><dd>{r.ticket_id ? `#${r.ticket_id}` : '—'}</dd></div>
              <div><dt>Requested by</dt><dd>{r.requested_by} (agent)</dd></div>
              {open?.mode === 'undo' && (
                <div><dt>Current decision</dt><dd>{r.status} by {r.decided_by}</dd></div>
              )}
              {open?.mode === 'approve' && r.kind !== 'discount' && (
                <div><dt>Checking</dt><dd>{money(balance)} → <strong className={balance - r.amount < 0 ? 'bad' : ''}>{money(balance - r.amount)}</strong></dd></div>
              )}
              {open?.mode === 'approve' && r.kind === 'discount' && (
                <div><dt>Checking</dt><dd>{money(balance)} (no cash moves)</dd></div>
              )}
            </dl>
            {open?.mode === 'approve' && blockers(r, balance).map((m) => <p key={m} className="appr-warn">⚠ {m}</p>)}

            <label className="field">
              <span>Your full name (human approver)</span>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="First Last" autoComplete="name" required
                aria-invalid={!!nameError} aria-describedby="name-help" />
              <small id="name-help" className={nameError ? 'bad' : 'muted'}>{nameError ?? 'Recorded as approved_by on the payment.'}</small>
            </label>

            {open?.mode === 'undo' ? (
              <>
                <label className="field">
                  <span>Why are you undoing it?</span>
                  <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="e.g. Approved by mistake" />
                </label>
                <label className="check check-warn">
                  <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                  <span>I want to undo this decision. This {undoEffect(r)}, and request #{r.id} goes back to pending.</span>
                </label>
              </>
            ) : open?.mode === 'approve' ? (
              <label className="check">
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                {r.kind === 'discount'
                  ? <span>I reviewed this request and approve a <strong>{r.discount_pct}% discount</strong> for this customer.</span>
                  : <span>I reviewed this request and approve paying <strong>{money(r.amount)}</strong> from checking.</span>}
              </label>
            ) : (
              <label className="field">
                <span>Reason for rejecting</span>
                <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="e.g. Pay rent first; revisit next week" />
              </label>
            )}

            {error && <p className="banner banner-bad" role="alert">{error}</p>}
            <div className="modal-actions">
              <button type="button" className="btn btn-ghost" onClick={() => setOpen(null)} disabled={submitting}>Cancel</button>
              <button type="submit" className={`btn ${open?.mode === 'approve' ? 'btn-approve' : 'btn-danger'}`} disabled={!canSubmit}>
                {submitting ? 'Working…' : open?.mode === 'undo' ? 'Undo decision' : open?.mode === 'approve'
                  ? (r.kind === 'discount' ? `Approve ${r.discount_pct}% discount` : `Approve & pay ${money(r.amount)}`)
                  : 'Reject request'}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </section>
  )
}
