import { AGENTS, AGENT_META } from '../agents'
import type { AgentLive, Edge } from '../hooks/agentStates'
import { useReducedMotion } from '../hooks/useReducedMotion'
import type { AgentName, Limits, Status } from '../types'
import { Bulldog } from './Bulldog'

const W = 640
const H = 462
const POS: Record<AgentName, { x: number; y: number }> = {
  Boss: { x: 320, y: 82 },
  Inventory: { x: 112, y: 205 },
  Accounting: { x: 528, y: 205 },
  Facilities: { x: 196, y: 352 },
  'Customer Service': { x: 444, y: 352 },
}
const R = 54 // keep lines clear of the avatars
const AVATAR = 96

function trimmed(from: AgentName, to: AgentName) {
  const a = POS[from]
  const b = POS[to]
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len = Math.hypot(dx, dy)
  const ux = dx / len
  const uy = dy / len
  return { x1: a.x + ux * R, y1: a.y + uy * R, x2: b.x - ux * R, y2: b.y - uy * R }
}

const pairs: [AgentName, AgentName][] = []
AGENTS.forEach((a, i) => AGENTS.slice(i + 1).forEach((b) => pairs.push([a, b])))

const STATE_LABEL = { idle: 'Idle', working: 'Working', delegating: 'Delegating', finished: 'Done' } as const

export function CollaborationMap({ live, edges, status, runLabel, limits }: {
  live: Record<AgentName, AgentLive>
  edges: Edge[]
  status: Status | null
  runLabel: string
  limits: Limits | null
}) {
  const reduced = useReducedMotion()
  const used = new Map(edges.map((e) => [`${e.from}>${e.to}`, e]))
  const active = AGENTS.filter((a) => live[a].state === 'delegating' && live[a].delegatingTo)
  const busyRun = status?.busy && status.action === 'run'

  return (
    <section className="panel map-panel" id="map" aria-labelledby="map-title">
      <header className="panel-head">
        <div>
          <h2 id="map-title">Agent collaboration map</h2>
          <p className="panel-sub">{runLabel}</p>
          {limits && (
            <p className="panel-sub limits-line">
              Limits per run: {limits.max_steps_per_ticket} team steps · {limits.max_steps_per_agent} per agent · depth {limits.max_delegation_depth} · {limits.max_output_tokens_per_call.toLocaleString()} output tokens/call
            </p>
          )}
        </div>
        <ul className="map-legend" aria-label="Legend">
          <li><span className="lg lg-idle" />Idle</li>
          <li><span className="lg lg-working" />Working</li>
          <li><span className="lg lg-deleg" />Delegating</li>
          <li><span className="lg lg-used" />Delegated this run</li>
        </ul>
      </header>

      <div className="map-wrap">
        <svg className="map-svg" viewBox={`0 0 ${W} ${H}`} role="img"
          aria-label={`Five agents, fully connected. ${active.length ? active.map((a) => `${a} is delegating to ${live[a].delegatingTo}`).join('. ') : busyRun ? 'Agents are working.' : 'No agents active.'}`}>
          <defs>
            <marker id="arrowhead" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0 10 5 0 10z" fill="#00356B" />
            </marker>
            <radialGradient id="glow">
              <stop offset="0%" stopColor="#4A90E2" stopOpacity=".35" />
              <stop offset="100%" stopColor="#4A90E2" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* every possible connection (full connectivity) */}
          {pairs.map(([a, b]) => {
            const t = trimmed(a, b)
            const fwd = used.get(`${a}>${b}`)
            const back = used.get(`${b}>${a}`)
            const isUsed = !!(fwd || back)
            return (
              <line key={`${a}-${b}`} {...t} className={`edge ${isUsed ? 'edge--used' : ''}`}
                strokeWidth={isUsed ? 2.5 + Math.min(((fwd?.count ?? 0) + (back?.count ?? 0)) - 1, 3) : 1.4} />
            )
          })}

          {/* direction + count of delegations that happened */}
          {edges.map((e) => {
            const t = trimmed(e.from, e.to)
            const mx = t.x1 + (t.x2 - t.x1) * 0.62
            const my = t.y1 + (t.y2 - t.y1) * 0.62
            return (
              <g key={`u-${e.from}-${e.to}`} className="edge-count">
                <line x1={t.x1} y1={t.y1} x2={mx} y2={my} stroke="transparent" markerEnd="url(#arrowhead)" />
                {e.count > 1 && (
                  <g transform={`translate(${mx + 10} ${my - 10})`}>
                    <circle r="9" />
                    <text textAnchor="middle" dy="3.6">{e.count}</text>
                  </g>
                )}
              </g>
            )
          })}

          {/* live delegations: arrow travels toward the receiving agent */}
          {active.map((from) => {
            const to = live[from].delegatingTo as AgentName
            const t = trimmed(from, to)
            const id = `path-${live[from].delegateEventId}`
            return (
              <g key={id} className="edge-live">
                <path id={id} d={`M${t.x1} ${t.y1} L${t.x2} ${t.y2}`} className="edge-live-line" />
                {reduced ? (
                  <line x1={t.x1} y1={t.y1} x2={t.x1 + (t.x2 - t.x1) * 0.8} y2={t.y1 + (t.y2 - t.y1) * 0.8}
                    stroke="transparent" markerEnd="url(#arrowhead)" />
                ) : (
                  <g className="edge-runner">
                    <path d="M-9 -6 3 0 -9 6 -6 0z" fill="#00356B" stroke="#fff" strokeWidth="1.2" />
                    <animateMotion dur="1.3s" repeatCount="indefinite" rotate="auto">
                      <mpath href={`#${id}`} />
                    </animateMotion>
                  </g>
                )}
              </g>
            )
          })}

          {/* the five bulldogs */}
          {AGENTS.map((a) => {
            const p = POS[a]
            const s = live[a]
            const on = s.state === 'working' || s.state === 'delegating'
            return (
              <g key={a} className={`node node--${s.state}`} transform={`translate(${p.x} ${p.y})`}>
                {on && <circle r="62" fill="url(#glow)" className="node-glow" />}
                <circle r="50" className="node-ring" />
                <svg x={-AVATAR / 2} y={-AVATAR / 2 - 4} width={AVATAR} height={AVATAR} overflow="visible">
                  <Bulldog agent={a} state={s.state} size={AVATAR} />
                </svg>
                <text className="node-name" y="66" textAnchor="middle">{AGENT_META[a].short}</text>
                {s.steps > 0 && limits && (
                  <text className="node-steps" x="44" y="-38" textAnchor="middle">{s.steps}/{limits.max_steps_per_agent}</text>
                )}
                <g transform="translate(0 76)">
                  <rect x="-44" y="-1" width="88" height="17" rx="8.5" className={`node-chip chip-${s.state}`} />
                  <text className="node-chip-text" y="11.5" textAnchor="middle">
                    {s.state === 'delegating' ? `→ ${AGENT_META[s.delegatingTo as AgentName].short}` : STATE_LABEL[s.state]}
                  </text>
                </g>
                {on && s.lastTool && (
                  <text className="node-tool" y="-58" textAnchor="middle">{s.lastTool}</text>
                )}
              </g>
            )
          })}
        </svg>
      </div>
    </section>
  )
}
