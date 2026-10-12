import { useEffect, useRef, useState } from 'react'
import { money } from '../api'
import type { Cash, Status } from '../types'
import { Modal } from './Modal'

const NAV = [
  ['#tickets', 'Tickets'],
  ['#approvals', 'Approvals'],
  ['#map', 'Agent map'],
  ['#activity', 'Activity'],
  ['#timeline', 'Timeline'],
  ['#attention', 'Attention'],
]

export function Header({ cash, status, offline, onReset }: {
  cash: Cash | null
  status: Status | null
  offline: string | null
  onReset: () => Promise<void>
}) {
  const [confirm, setConfirm] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState(false)
  const last = useRef<number | null>(null)

  // Flash the balance when it changes (e.g. after an approved payment).
  useEffect(() => {
    if (cash == null) return
    if (last.current !== null && last.current !== cash.balance) {
      setFlash(true)
      const t = window.setTimeout(() => setFlash(false), 1600)
      last.current = cash.balance
      return () => window.clearTimeout(t)
    }
    last.current = cash.balance
  }, [cash])

  const busy = !!status?.busy
  const doReset = async () => {
    setResetting(true)
    setError(null)
    try {
      await onReset()
      setConfirm(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setResetting(false)
    }
  }

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <a className="brand" href="#tickets" aria-label="Campus Customs operations">
          <svg className="brand-y" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#fff" />
            <path d="M5 6h9v2.4h-2l5 7.4 5-7.4h-2V6h8v2.4h-1.8L19 17.6V24h2.5v2.5H10.5V24H13v-6.4L6.8 8.4H5z" fill="#00356B" />
          </svg>
          <span>
            <strong>Campus Customs</strong>
            <small>Operations Control Center</small>
          </span>
        </a>

        <div className={`run-state ${offline ? 'is-off' : busy ? 'is-busy' : 'is-idle'}`} role="status" aria-live="polite">
          <span className="dot" aria-hidden="true" />
          {offline ? 'Backend offline' : busy
            ? status?.action === 'reset' ? 'Resetting database…' : `Agents working on #${status?.ticket_id}`
            : 'Agents idle'}
        </div>

        <div className={`cash ${flash ? 'cash--flash' : ''}`} aria-live="polite">
          <span className="cash-label">Checking balance</span>
          <span className="cash-value">{cash ? money(cash.balance) : '—'}</span>
          <span className="cash-sub">
            {cash ? <>Pending {money(cash.pending_approvals_total)} · after pending <b className={cash.available_after_pending < 0 ? 'bad' : ''}>{money(cash.available_after_pending)}</b></> : 'Loading…'}
          </span>
        </div>

        <button className="btn btn-outline-light" onClick={() => setConfirm(true)} disabled={busy}
          title={busy ? 'Can’t reset while agents are running' : 'Restore the working database from the original'}>
          Reset database
        </button>
      </div>

      <nav className="subnav" aria-label="Sections">
        {NAV.map(([href, label]) => <a key={href} href={href}>{label}</a>)}
        {cash && <span className="subnav-date">Shop date {cash.today}</span>}
      </nav>

      {offline && <div className="banner banner-bad banner-top" role="alert">{offline} Start it from backend/ with <code>uvicorn main:app --reload --port 8000</code>.</div>}

      <Modal open={confirm} onClose={() => !resetting && setConfirm(false)} title="Reset the working database?" labelledBy="reset-title">
        <p>This copies <code>data/campus_customs.db</code> over <code>data/campus_customs_new.db</code>. All approval requests, drafts, notes, payments, and ticket statuses from earlier runs are cleared. The original file is never changed, and the audit trail keeps its history.</p>
        {busy && <p className="banner banner-bad">Agents are running. Wait for them to finish.</p>}
        {error && <p className="banner banner-bad" role="alert">{error}</p>}
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={() => setConfirm(false)} disabled={resetting}>Cancel</button>
          <button className="btn btn-danger" onClick={doReset} disabled={resetting || busy}>{resetting ? 'Resetting…' : 'Yes, reset'}</button>
        </div>
      </Modal>
    </header>
  )
}
