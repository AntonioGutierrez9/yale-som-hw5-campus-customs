import { useMemo, useState } from 'react'
import { AGENT_META, isAgent } from '../agents'
import { clock } from '../api'
import type { AgentLive } from '../hooks/agentStates'
import type { AgentName, AuditEvent, Status } from '../types'
import { AgentAvatar } from './AgentAvatar'

type Filter = 'key' | 'messages' | 'delegations' | 'tools' | 'all'
const FILTERS: { id: Filter; label: string }[] = [
  { id: 'key', label: 'Key events' },
  { id: 'messages', label: 'Messages' },
  { id: 'delegations', label: 'Delegations' },
  { id: 'tools', label: 'MCP tools' },
  { id: 'all', label: 'Everything' },
]
const KEY = new Set(['run_start', 'tool_call', 'delegate', 'delegation_result', 'final_answer', 'run_end',
  'human_approval', 'human_rejection', 'db_reset', 'limit_stop', 'human_continue', 'tool_repeat', 'status_sync', 'approval_created', 'human_undo'])

function matches(e: AuditEvent, f: Filter) {
  switch (f) {
    case 'key': return KEY.has(e.event) && !(e.event === 'run_start' && e.depth > 0)
    case 'messages': return e.event === 'final_answer' || e.event === 'delegation_result' || e.event.startsWith('human')
    case 'delegations': return e.event === 'delegate' || e.event === 'delegation_result'
    case 'tools': return e.event === 'tool_call' || e.event === 'tool_result' || e.event === 'tool_retry'
    case 'all': return true
  }
}

const refused = (e: AuditEvent) => (e.result ?? '').startsWith('REFUSED')

function Badge({ e }: { e: AuditEvent }) {
  const map: Partial<Record<AuditEvent['event'], [string, string]>> = {
    run_start: ['Started', 'b-neutral'],
    model_response: ['Thinking', 'b-muted'],
    tool_call: ['MCP tool', 'b-tool'],
    tool_result: ['Result', 'b-muted'],
    tool_retry: ['Retry', 'b-warn'],
    delegate: refused(e) ? ['Refused', 'b-bad'] : ['Delegation', 'b-deleg'],
    delegation_result: ['Reported back', 'b-deleg'],
    final_answer: ['Said', 'b-said'],
    run_end: e.stop_reason === 'final_answer' ? ['Finished', 'b-good'] : ['Stopped', 'b-bad'],
    human_approval: refused(e) ? ['Approval refused', 'b-bad'] : ['Human approved', 'b-good'],
    human_rejection: ['Human rejected', 'b-warn'],
    db_reset: ['Reset', 'b-neutral'],
    tool_repeat: ['Repeat blocked', 'b-muted'],
    limit_stop: ['Limit reached', 'b-warn'],
    human_continue: ['Human: run again', 'b-good'],
    status_sync: ['Status updated', 'b-good'],
    approval_created: ['Sent to inbox', 'b-warn'],
    human_undo: ['Human undid decision', 'b-warn'],
  }
  const [label, cls] = map[e.event] ?? [e.event, 'b-muted']
  return <span className={`badge ${cls}`}>{label}</span>
}

function Body({ e }: { e: AuditEvent }) {
  switch (e.event) {
    case 'run_start':
      return <p className="ev-text muted">{e.args}</p>
    case 'tool_call':
      return <p className="ev-text"><code className="tool">{e.tool}</code> <span className="muted mono">{e.args !== '{}' ? e.args : ''}</span></p>
    case 'tool_result':
      return <p className="ev-text muted mono small"><code className="tool">{e.tool}</code> → {e.result}</p>
    case 'delegate':
      return (
        <div className="ev-text">
          <div className="deleg-line">
            <AgentAvatar actor={e.agent} size={22} /> <span className="arrow">→</span> <AgentAvatar actor={e.to_agent!} size={22} />
            <strong>{e.agent} → {e.to_agent}</strong>
          </div>
          <p className="muted">{e.args}</p>
          {refused(e) && <p className="bad small">{e.result}</p>}
        </div>
      )
    case 'delegation_result':
      return <p className="ev-text"><strong>{e.to_agent}</strong> → {e.agent}: <span className="quote">{e.result}</span></p>
    case 'final_answer':
      return <p className="ev-text quote">“{e.result}”</p>
    case 'run_end':
      return <p className="ev-text muted">{e.stop_reason === 'final_answer' ? 'Finished its loop with a final answer.' : e.stop_reason}{e.output_tokens ? ` · ${e.input_tokens?.toLocaleString()} in / ${e.output_tokens.toLocaleString()} out tokens` : ''}</p>
    case 'model_response':
      return <p className="ev-text muted small">Step {e.step}: {e.result}</p>
    default:
      return <p className="ev-text">{e.args ? `${e.args}: ` : ''}{e.result}</p>
  }
}

export function ActivityFeed({ events, status, live, ticketId }: {
  events: AuditEvent[]
  status: Status | null
  live: Record<AgentName, AgentLive>
  ticketId: number | null
}) {
  const [filter, setFilter] = useState<Filter>('key')
  const [scope, setScope] = useState<'ticket' | 'all'>('ticket')
  const shown = useMemo(
    () => events
      .filter((e) => scope === 'all' || ticketId == null || e.ticket_id === ticketId)
      .filter((e) => matches(e, filter)).slice(-250).reverse(),
    [events, filter, scope, ticketId],
  )
  const busy = status?.busy && status.action === 'run'
  const working = (Object.keys(live) as AgentName[]).filter((a) => live[a].state === 'working' || live[a].state === 'delegating')

  return (
    <section className="panel feed-panel" id="activity" aria-labelledby="feed-title">
      <header className="panel-head">
        <div>
          <h2 id="feed-title">Live agent activity</h2>
          <p className="panel-sub" aria-live="polite">
            {busy ? (
              <><span className="live-dot" aria-hidden="true" /> Ticket {status?.ticket_id} · refreshing every 1.2 s{working.length ? ` · working: ${working.join(', ')}` : ''}</>
            ) : events.length ? `Idle · ${scope === 'ticket' ? `ticket ${ticketId}` : 'all tickets'} since the last reset` : 'No agent activity since the last reset'}
          </p>
        </div>
        <div className="seg" role="tablist" aria-label="Which tickets">
          <button role="tab" aria-selected={scope === 'ticket'} className={scope === 'ticket' ? 'on' : ''} onClick={() => setScope('ticket')}>
            Ticket {ticketId}
          </button>
          <button role="tab" aria-selected={scope === 'all'} className={scope === 'all' ? 'on' : ''} onClick={() => setScope('all')}>
            All tickets
          </button>
        </div>
        <div className="seg" role="tablist" aria-label="Filter activity">
          {FILTERS.map((f) => (
            <button key={f.id} role="tab" aria-selected={filter === f.id} className={filter === f.id ? 'on' : ''} onClick={() => setFilter(f.id)}>
              {f.label}
            </button>
          ))}
        </div>
      </header>

      <ol className="feed" aria-label="Agent events, newest first">
        {shown.length === 0 && (
          <li className="empty">
            {events.length ? (scope === 'ticket' ? `No matching activity on ticket ${ticketId} yet.` : 'Nothing matches this filter yet.') : 'Run a ticket and the agents’ steps will stream in here.'}
          </li>
        )}
        {shown.map((e) => {
          const st = busy && isAgent(e.agent) && e.run_id === status?.run_id ? live[e.agent].state : 'idle'
          return (
            <li key={e.id} className={`ev ev-${e.event}`} style={{ ['--agent' as string]: isAgent(e.agent) ? AGENT_META[e.agent].color : '#475569' }}>
              <AgentAvatar actor={e.agent} size={34} state={st} />
              <div className="ev-main">
                <div className="ev-head">
                  <span className="ev-agent">{e.agent}</span>
                  <Badge e={e} />
                  {e.ticket_id != null && <span className="ev-ticket">#{e.ticket_id}</span>}
                  <time className="ev-time" dateTime={e.time}>{clock(e.time)}</time>
                </div>
                <Body e={e} />
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
