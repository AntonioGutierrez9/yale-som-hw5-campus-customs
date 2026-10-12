import { useMemo, useState } from 'react'
import { ActivityFeed } from './components/ActivityFeed'
import { ApprovalInbox } from './components/ApprovalInbox'
import { AttentionPanel } from './components/AttentionPanel'
import { CollaborationMap } from './components/CollaborationMap'
import { Header } from './components/Header'
import { Modal } from './components/Modal'
import { TicketBoard } from './components/TicketBoard'
import { TicketDetailPanel } from './components/TicketDetailPanel'
import { clock } from './api'
import { deriveAgentStates, focusRunId, runEdges } from './hooks/agentStates'
import { useDashboard } from './hooks/useDashboard'

export default function App() {
  const d = useDashboard()
  // ?ticket=103 opens the dashboard with that ticket selected (handy for sharing and screenshots)
  const [selected, setSelected] = useState<number | null>(() => Number(new URLSearchParams(location.search).get('ticket')) || 101)

  // The map follows the live run; otherwise the selected ticket's most recent run.
  const runId = useMemo(() => focusRunId(d.events, d.status, selected), [d.events, d.status, selected])
  const live = useMemo(() => deriveAgentStates(d.events, d.status, runId), [d.events, d.status, runId])
  const edges = useMemo(() => runEdges(d.events, runId), [d.events, runId])
  const runLabel = useMemo(() => {
    if (d.status?.busy && d.status.action === 'run') return `Live · ticket ${d.status.ticket_id} · run ${d.status.run_id}`
    const start = d.events.find((e) => e.run_id === runId && e.event === 'run_start')
    return start
      ? `Ticket ${selected} · last run ${runId} at ${clock(start.time)} · Done = took part (tails still)`
      : `Ticket ${selected} · no runs since the last reset`
  }, [d.status, d.events, runId, selected])

  const select = (id: number) => {
    setSelected(id)
    document.getElementById('timeline')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  const run = async (id: number, continueConfirmed = false) => {
    setSelected(id)
    await d.runTicket(id, continueConfirmed)
  }

  return (
    <>
      <a className="skip" href="#tickets">Skip to tickets</a>
      <Header cash={d.cash} status={d.status} offline={d.offline} onReset={d.reset} />

      <main className="grid">
        <div className="area-board">
          <TicketBoard tickets={d.tickets} status={d.status} selected={selected} onSelect={setSelected} onRun={run}
            onSync={d.syncTicket} onDraft={(id) => { setSelected(id); return d.draftReply(id) }} runningTicket={d.runningTicket} live={live} />
        </div>
        <div className="area-inbox">
          <ApprovalInbox approvals={d.approvals} cash={d.cash} onApprove={d.approve} onReject={d.reject} onUndo={d.undo} />
        </div>
        <div className="area-map">
          <CollaborationMap live={live} edges={edges} status={d.status} runLabel={runLabel} limits={d.limits} />
        </div>
        <div className="area-feed">
          <ActivityFeed events={d.events} status={d.status} live={live} ticketId={selected} />
        </div>
        <div className="area-detail">
          <TicketDetailPanel ticketId={selected} status={d.status} version={d.version} onRun={run} limits={d.limits} />
        </div>
        <div className="area-attention">
          <AttentionPanel attention={d.attention} onTicket={select} />
        </div>
      </main>

      <footer className="foot">
        Campus Customs · five gpt-6-luna agents via MCP · payments only move after a human approves · data from the live FastAPI backend
      </footer>

      <Modal open={!!d.permissionAsk} onClose={() => d.setPermissionAsk(null)} title={`Run ticket ${d.permissionAsk?.ticket} again?`} labelledBy="continue-title">
        <p>{d.permissionAsk?.message}</p>
        {d.limits && (
          <p className="muted small">The new run gets the same limits: {d.limits.max_steps_per_ticket} steps for the team, {d.limits.max_steps_per_agent} per agent, delegation depth {d.limits.max_delegation_depth}. Your permission is recorded in the audit trail.</p>
        )}
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={() => d.setPermissionAsk(null)}>Not now</button>
          <button className="btn btn-primary" onClick={() => d.permissionAsk && run(d.permissionAsk.ticket, true)}>Yes, run it again</button>
        </div>
      </Modal>

      <div className="toasts" aria-live="polite">
        {d.toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`} role={t.kind === 'error' ? 'alert' : 'status'}>
            <div>
              <strong>{t.title}</strong>
              {t.body && <p>{t.body}</p>}
            </div>
            <button className="icon-btn" onClick={() => d.dismissToast(t.id)} aria-label="Dismiss">×</button>
          </div>
        ))}
      </div>
    </>
  )
}
