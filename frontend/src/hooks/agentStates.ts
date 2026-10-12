import { AGENTS, isAgent } from '../agents'
import type { DogState } from '../components/Bulldog'
import type { AgentName, AuditEvent, Status } from '../types'

export interface AgentLive {
  state: DogState
  lastTool?: string
  delegatingTo?: AgentName
  delegateEventId?: number
  steps: number
}

export interface Edge {
  from: AgentName
  to: AgentName
  count: number
}

const isRefused = (e: AuditEvent) => (e.result ?? '').startsWith('REFUSED')

/**
 * Each agent's state, derived only from real audit events.
 * While a run is live: idle -> working (run_start) -> delegating (delegate, until delegation_result)
 * -> finished (run_end). When nothing is running, `runId` is the selected ticket's last run and
 * the agents that took part show as finished (tails still), with their step counts.
 */
export function deriveAgentStates(events: AuditEvent[], status: Status | null, runId: string | null = null): Record<AgentName, AgentLive> {
  const out = Object.fromEntries(AGENTS.map((a) => [a, { state: 'idle', steps: 0 } as AgentLive])) as Record<AgentName, AgentLive>
  const liveRun = status?.busy && status.action === 'run' ? status.run_id : null
  runId = liveRun ?? runId
  if (!runId) return out
  for (const e of events) {
    if (e.run_id !== runId || !isAgent(e.agent)) continue
    const a = out[e.agent]
    switch (e.event) {
      case 'run_start':
        a.state = 'working'
        break
      case 'model_response':
        a.steps++
        break
      case 'tool_call':
        a.lastTool = e.tool
        break
      case 'delegate':
        if (!isRefused(e) && e.to_agent) {
          a.state = 'delegating'
          a.delegatingTo = e.to_agent
          a.delegateEventId = e.id
        }
        break
      case 'delegation_result':
        a.state = 'working'
        a.delegatingTo = undefined
        break
      case 'run_end':
        a.state = 'finished'
        a.delegatingTo = undefined
        break
    }
  }
  if (!liveRun) {
    // A finished run: nobody is still working, even if an event was cut off.
    for (const a of AGENTS) if (out[a].state !== 'idle') { out[a].state = 'finished'; out[a].delegatingTo = undefined }
  }
  return out
}

/** The run to show on the map: the live one, otherwise the selected ticket's most recent run. */
export function focusRunId(events: AuditEvent[], status: Status | null, ticketId: number | null): string | null {
  if (status?.busy && status.action === 'run' && status.run_id) return status.run_id
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (isAgent(e.agent) && (ticketId == null || e.ticket_id === ticketId)) return e.run_id
  }
  return null
}

/** Delegations that actually happened in one run (refused ones excluded). */
export function runEdges(events: AuditEvent[], runId: string | null): Edge[] {
  if (!runId) return []
  const map = new Map<string, Edge>()
  for (const e of events) {
    if (e.run_id !== runId || e.event !== 'delegate' || isRefused(e) || !isAgent(e.agent) || !e.to_agent) continue
    const key = `${e.agent}>${e.to_agent}`
    const edge = map.get(key) ?? { from: e.agent, to: e.to_agent, count: 0 }
    edge.count++
    map.set(key, edge)
  }
  return [...map.values()]
}
