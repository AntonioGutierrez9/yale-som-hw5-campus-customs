import { useEffect, useMemo, useState } from 'react'
import { AGENT_META, isAgent } from '../agents'
import { api, clock, money, statusLabel } from '../api'
import type { AgentContribution, AuditEvent, Limits, RunSummary, Status, TicketDetail } from '../types'
import { AgentAvatar } from './AgentAvatar'

type Tab = 'timeline' | 'summary' | 'drafts'

interface TimelineItem {
  key: string
  time: string
  actor: string
  kind: 'run' | 'delegation' | 'tool' | 'said' | 'decision' | 'approval' | 'draft' | 'note' | 'end'
  title: string
  body?: string
  pending?: boolean
}

function buildTimeline(detail: TicketDetail | null, events: AuditEvent[]): TimelineItem[] {
  const items: TimelineItem[] = []
  for (const e of events) {
    if (!isAgent(e.agent)) continue
    const base = { key: `e${e.id}`, time: e.time, actor: e.agent }
    switch (e.event) {
      case 'run_start':
        if (e.depth === 0) items.push({ ...base, kind: 'run', title: `${e.agent} started a run`, body: e.args })
        break
      case 'delegate':
        items.push({
          ...base, kind: 'delegation',
          title: (e.result ?? '').startsWith('REFUSED') ? `${e.agent} → ${e.to_agent} (refused)` : `${e.agent} delegated to ${e.to_agent}`,
          body: e.args,
        })
        break
      case 'tool_call':
        items.push({ ...base, kind: 'tool', title: `${e.agent} used ${e.tool}`, body: e.args !== '{}' ? e.args : undefined })
        break
      case 'final_answer':
        items.push({ ...base, kind: 'said', title: `${e.agent} concluded`, body: e.result })
        break
      case 'run_end':
        if (e.depth === 0) items.push({ ...base, kind: 'end', title: `Run finished (${e.stop_reason})` })
        break
    }
  }
  if (detail) {
    detail.notes.forEach((n, i) => {
      const decision = /^DISCOUNT DECISION|^Status /.test(n.note)
      items.push({ key: `n${i}`, time: n.created_at, actor: n.author, kind: decision ? 'decision' : 'note',
        title: decision ? `${n.author} decision` : `${n.author} added a note`, body: n.note })
    })
    detail.approval_requests.forEach((r) => {
      items.push({ key: `a${r.id}`, time: (r as { requested_at?: string }).requested_at ?? '', actor: r.requested_by, kind: 'approval',
        title: `Approval #${r.id} requested: ${r.kind.replace('_', ' ')} ${money(r.amount)}`,
        body: r.status === 'pending' ? 'Waiting for a human.' : `Now ${r.status}.`, pending: r.status === 'pending' })
    })
    detail.drafts.forEach((d) => {
      items.push({ key: `d${d.id}`, time: d.created_at, actor: d.written_by, kind: 'draft',
        title: `Draft #${d.id} saved for ${d.recipient}`, body: d.subject })
    })
  }
  return items.filter((i) => i.time).sort((a, b) => a.time.localeCompare(b.time))
}

const KIND_ICON: Record<TimelineItem['kind'], string> = {
  run: '▶', delegation: '⇢', tool: '⚙', said: '💬', decision: '⚖', approval: '✋', draft: '✉', note: '📝', end: '■',
}

function Contribution({ c }: { c: AgentContribution }) {
  const tools = Object.entries(c.tool_calls)
  return (
    <article className="contrib" style={{ ['--agent' as string]: AGENT_META[c.agent]?.color }}>
      <header>
        <AgentAvatar actor={c.agent} size={52} />
        <div>
          <h4>{c.agent}</h4>
          <p className="muted small">
            {c.delegated_from.length ? `Asked by ${[...new Set(c.delegated_from)].join(', ')}` : 'Led the run'}
            {c.delegated_to.length ? ` · delegated to ${c.delegated_to.join(', ')}` : ''}
          </p>
        </div>
      </header>
      {c.said.map((s, i) => <p key={i} className="quote">“{s}”</p>)}
      {!c.said.length && <p className="muted small">{c.finished ? 'No summary recorded.' : 'Still working…'}</p>}
      <div className="chips">
        {tools.map(([t, n]) => <code key={t} className="tool">{t}{n > 1 ? ` ×${n}` : ''}</code>)}
        {!tools.length && <span className="muted small">No MCP tools used</span>}
      </div>
      <p className="muted tiny">{c.model_steps} model steps · {c.input_tokens.toLocaleString()} in / {c.output_tokens.toLocaleString()} out tokens</p>
    </article>
  )
}

export function TicketDetailPanel({ ticketId, status, version, onRun, limits }: {
  ticketId: number | null
  status: Status | null
  version: number
  onRun: (id: number) => void
  limits: Limits | null
}) {
  const [tab, setTab] = useState<Tab>('timeline')
  const [detail, setDetail] = useState<TicketDetail | null>(null)
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const runningHere = !!status?.busy && status.ticket_id === ticketId

  useEffect(() => {
    if (ticketId == null) return
    let cancel = false
    const load = async () => {
      try {
        const [d, a, r] = await Promise.all([
          api.ticket(ticketId), api.activity({ ticket_id: ticketId, since_reset: true, limit: 1000 }), api.runs(ticketId),
        ])
        if (cancel) return
        setDetail(d)
        setEvents(a.events)
        setRuns(r.runs)
        setError(null)
      } catch (e) {
        if (!cancel) setError(e instanceof Error ? e.message : String(e))
      }
    }
    load()
    const t = runningHere ? window.setInterval(load, 2000) : undefined
    return () => { cancel = true; window.clearInterval(t) }
  }, [ticketId, version, runningHere])

  const timeline = useMemo(() => buildTimeline(detail, events), [detail, events])
  const latest = runs[0]

  if (ticketId == null) {
    return (
      <section className="panel detail-panel" id="timeline">
        <div className="empty">Select a ticket to see its timeline and agent summaries.</div>
      </section>
    )
  }

  return (
    <section className="panel detail-panel" id="timeline" aria-labelledby="detail-title">
      <header className="panel-head">
        <div>
          <h2 id="detail-title">Ticket {ticketId}{detail ? `: ${detail.ticket.subject}` : ''}</h2>
          <p className="panel-sub">
            {detail && <span className={`status status-${detail.ticket.status}`}>{statusLabel[detail.ticket.status]}</span>}
            {detail && ` ${detail.ticket.requester} · ${detail.approval_requests.filter((r) => r.status === 'pending').length} pending approval(s)`}
          </p>
        </div>
        <div className="seg" role="tablist" aria-label="Ticket views">
          {(['timeline', 'summary', 'drafts'] as Tab[]).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>
              {t === 'timeline' ? 'Timeline' : t === 'summary' ? 'Agent summaries' : `Drafts & notes${detail ? ` (${detail.drafts.length + detail.notes.length})` : ''}`}
            </button>
          ))}
        </div>
      </header>

      {error && <p className="banner banner-bad">{error}</p>}

      {tab === 'timeline' && (
        <ol className="timeline">
          {timeline.length === 0 && (
            <li className="empty">
              No activity on this ticket since the last reset.
              <button className="btn btn-primary" onClick={() => onRun(ticketId)} disabled={!!status?.busy}>Run agents on #{ticketId}</button>
            </li>
          )}
          {timeline.map((it) => (
            <li key={it.key} className={`tl tl-${it.kind} ${it.pending ? 'tl-pending' : ''}`}>
              <span className="tl-dot" aria-hidden="true">{KIND_ICON[it.kind]}</span>
              <div className="tl-main">
                <div className="tl-head">
                  {isAgent(it.actor) && <AgentAvatar actor={it.actor} size={22} />}
                  <strong>{it.title}</strong>
                  {it.pending && <span className="badge b-warn">pending</span>}
                  <time className="ev-time">{clock(it.time)}</time>
                </div>
                {it.body && <p className={it.kind === 'tool' ? 'mono small muted' : 'small'}>{it.body}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}

      {tab === 'summary' && (
        <div className="summary">
          {!latest && <div className="empty">No runs on this ticket since the last reset.</div>}
          {latest && (
            <>
              <div className={`outcome outcome-${latest.status}`}>
                <div className="outcome-head">
                  <span className={`badge ${latest.status === 'completed' ? 'b-good' : latest.status === 'running' ? 'b-deleg' : latest.status === 'limit_stopped' ? 'b-warn' : 'b-bad'}`}>{latest.status.replace('_', ' ')}</span>
                  <span className="muted small">Run {latest.run_id} · {clock(latest.started_at)}{latest.ended_at ? `–${clock(latest.ended_at)}` : ''} · {latest.delegations} delegations{latest.refused_delegations ? ` (${latest.refused_delegations} refused)` : ''} · {(latest.input_tokens + latest.output_tokens).toLocaleString()} tokens</span>
                </div>
                <h3>Final outcome</h3>
                <p>{latest.outcome ?? (latest.status === 'running' ? 'The Boss is still working…' : 'No final answer recorded.')}</p>
                <p className="muted small">
                  Steps used: {latest.model_steps}{limits ? ` of ${limits.max_steps_per_ticket}` : ''} · repeated tool calls blocked: {latest.repeats_blocked}
                </p>
                {latest.limit_stops.length > 0 && (
                  <p className="appr-warn">⚠ Execution limit reached: {latest.limit_stops.join('; ')}. The run stopped safely; running again needs your permission.</p>
                )}
              </div>
              <div className="contribs">
                {latest.agents.map((c) => <Contribution key={c.agent} c={c} />)}
              </div>
              {runs.length > 1 && (
                <p className="muted small">Earlier runs on this ticket since reset: {runs.slice(1).map((r) => `${r.run_id} (${r.status})`).join(', ')}</p>
              )}
            </>
          )}
        </div>
      )}

      {tab === 'drafts' && detail && (
        <div className="drafts">
          <h3>Customer drafts <span className="muted small">(never sent; review before anything goes out)</span></h3>
          {detail.drafts.length === 0 && <p className="muted">No drafts yet.</p>}
          {detail.drafts.map((d) => (
            <article key={d.id} className="draft">
              <header><span className="badge b-neutral">Draft #{d.id}</span> To <strong>{d.recipient}</strong> · by {d.written_by} · {clock(d.created_at)}</header>
              <h4>{d.subject}</h4>
              <pre>{d.body}</pre>
            </article>
          ))}
          <h3>Ticket notes</h3>
          {detail.notes.length === 0 && <p className="muted">No notes yet.</p>}
          <ul className="notes">
            {detail.notes.map((n, i) => (
              <li key={i}><AgentAvatar actor={n.author} size={22} /> <strong>{n.author}</strong> <time className="ev-time">{clock(n.created_at)}</time><p>{n.note}</p></li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
