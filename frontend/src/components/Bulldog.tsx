// Handsome Dan–inspired bulldog avatars. One shared body so all five match;
// each role adds its own accessory. Only the tail (.dog-tail) animates.
import type { AgentName } from '../types'

export type DogState = 'idle' | 'working' | 'delegating' | 'finished'

const O = '#1E2A3A' // outline
const FUR = '#F7F3EC'
const MUZZLE = '#FFFDF9'
const PATCH = '#B07F57'
const EAR = '#C49670'
const NOSE = '#23262F'
const YALE = '#00356B'

function Paw({ cx, cy }: { cx: number; cy: number }) {
  return (
    <g>
      <ellipse cx={cx} cy={cy} rx="6.5" ry="5.5" fill={FUR} stroke={O} strokeWidth="2" />
      <path d={`M${cx - 2.5} ${cy + 1.5} v2.5 M${cx + 1} ${cy + 1.5} v2.5`} stroke={O} strokeWidth="1.1" strokeLinecap="round" />
    </g>
  )
}

function Accessory({ agent }: { agent: AgentName }) {
  switch (agent) {
    case 'Boss':
      return (
        <g>
          {/* Yale-blue tie */}
          <path d="M60 86.5l-4 3 2.6 3-3.2 13.5 4.6 5 4.6-5-3.2-13.5 2.6-3z" fill={YALE} stroke={O} strokeWidth="1.4" strokeLinejoin="round" />
          <path d="M57.6 97l4.8-2.4M57 102l5.6-2.8" stroke="#4A78B5" strokeWidth="1.2" />
          {/* clipboard */}
          <rect x="12" y="84" width="23" height="29" rx="2.5" fill="#9A6B3F" stroke={O} strokeWidth="2" />
          <rect x="15" y="89" width="17" height="21" rx="1" fill="#fff" />
          <rect x="18.5" y="81.5" width="10" height="5.5" rx="1.6" fill="#A8B3C2" stroke={O} strokeWidth="1.4" />
          <path d="M18 94h11M18 98h11M18 102h7" stroke="#94A3B8" strokeWidth="1.3" />
          <path d="M26 104.5l2 2 3.5-4" stroke={YALE} strokeWidth="1.6" fill="none" strokeLinecap="round" />
          <Paw cx={35} cy={99} />
        </g>
      )
    case 'Inventory':
      return (
        <g>
          {/* package */}
          <rect x="10" y="88" width="26" height="22" rx="1.5" fill="#C08A57" stroke={O} strokeWidth="2" />
          <rect x="20.5" y="88" width="5" height="22" fill="#E8C9A0" />
          <path d="M10 94h26" stroke="#8E6237" strokeWidth="1.2" />
          <Paw cx={36} cy={99} />
        </g>
      )
    case 'Accounting':
      return (
        <g>
          {/* glasses */}
          <circle cx="47" cy="47" r="7.6" fill="rgba(255,255,255,.18)" stroke="#111827" strokeWidth="2.1" />
          <circle cx="73" cy="47" r="7.6" fill="rgba(255,255,255,.18)" stroke="#111827" strokeWidth="2.1" />
          <path d="M54.6 46.5q5.4-3 10.8 0M39.4 46l-8-3M80.6 46l8-3" stroke="#111827" strokeWidth="2" fill="none" strokeLinecap="round" />
          {/* calculator */}
          <rect x="12" y="84" width="22" height="29" rx="3" fill="#334155" stroke={O} strokeWidth="2" />
          <rect x="15" y="87.5" width="16" height="6.5" rx="1" fill="#A7F3D0" />
          {[0, 1, 2].map((r) => [0, 1, 2].map((c) => (
            <rect key={`${r}${c}`} x={15.5 + c * 5.4} y={97 + r * 4.9} width="4" height="3.4" rx=".8" fill={r === 2 && c === 2 ? '#F59E0B' : '#E2E8F0'} />
          )))}
          <Paw cx={34} cy={100} />
        </g>
      )
    case 'Facilities':
      return (
        <g>
          {/* hard hat */}
          <path d="M33 36q1-20 27-21 26 1 27 21z" fill="#FACC15" stroke={O} strokeWidth="2.2" strokeLinejoin="round" />
          <path d="M60 15.5v19" stroke="#CA8A04" strokeWidth="3.2" />
          <rect x="26" y="33.5" width="68" height="5.5" rx="2.75" fill="#EAB308" stroke={O} strokeWidth="2" />
          {/* wrench */}
          <g transform="rotate(-24 24 96)">
            <path d="M17 77h4v5h6v-5h4a7 7 0 0 1-5 8.4V110a2.5 2.5 0 0 1-5 0V85.4A7 7 0 0 1 17 77z" fill="#A8B3C2" stroke={O} strokeWidth="1.9" strokeLinejoin="round" />
          </g>
          <Paw cx={33} cy={99} />
        </g>
      )
    case 'Customer Service':
      return (
        <g>
          {/* headset */}
          <path d="M30 46q0-29 30-30 30 1 30 30" fill="none" stroke="#1F2937" strokeWidth="4" strokeLinecap="round" />
          <rect x="23.5" y="40" width="9.5" height="15" rx="4.5" fill={YALE} stroke={O} strokeWidth="1.8" />
          <rect x="87" y="40" width="9.5" height="15" rx="4.5" fill={YALE} stroke={O} strokeWidth="1.8" />
          <path d="M28 54q1 13 17 13.5" fill="none" stroke="#1F2937" strokeWidth="2.6" strokeLinecap="round" />
          <circle cx="46.5" cy="67.5" r="2.8" fill="#374151" />
        </g>
      )
  }
}

export function Bulldog({ agent, state = 'idle', size = 64, title }: {
  agent: AgentName
  state?: DogState
  size?: number
  title?: string
}) {
  const friendly = agent === 'Customer Service'
  return (
    <svg
      className={`dog dog--${state}`}
      viewBox="0 0 120 120"
      width={size}
      height={size}
      role="img"
      aria-label={title ?? `${agent} bulldog${state === 'idle' ? '' : `, ${state}`}`}
    >
      {/* tail first so it sits behind the body; the only part that animates */}
      <g className="dog-tail">
        <path d="M90 99c9-2 16-9 14-19" fill="none" stroke={O} strokeWidth="9" strokeLinecap="round" />
        <path d="M90 99c9-2 16-9 14-19" fill="none" stroke={FUR} strokeWidth="5" strokeLinecap="round" />
      </g>

      {/* body */}
      <ellipse cx="60" cy="96" rx="31" ry="21" fill={FUR} stroke={O} strokeWidth="2.4" />
      <ellipse cx="80" cy="95" rx="8" ry="7" fill={PATCH} opacity=".8" />
      <ellipse cx="60" cy="99" rx="14" ry="12" fill={MUZZLE} />
      {agent === 'Inventory' && (
        <g>
          {/* warehouse safety vest */}
          <path d="M31 88q2 16 13 24h9V87q-11-4-22 1z" fill="#F97316" stroke={O} strokeWidth="1.8" strokeLinejoin="round" />
          <path d="M89 88q-2 16-13 24h-9V87q11-4 22 1z" fill="#F97316" stroke={O} strokeWidth="1.8" strokeLinejoin="round" />
          <path d="M34 100h19M67 100h19" stroke="#FDE68A" strokeWidth="3" />
        </g>
      )}

      {/* front legs */}
      <rect x="43" y="101" width="13" height="16" rx="6" fill={FUR} stroke={O} strokeWidth="2.2" />
      <rect x="64" y="101" width="13" height="16" rx="6" fill={FUR} stroke={O} strokeWidth="2.2" />
      <path d="M47 114v2.5M51 114v2.5M68 114v2.5M72 114v2.5" stroke={O} strokeWidth="1.2" strokeLinecap="round" />

      {/* Yale collar + tag */}
      <path d="M35 75q25 11 50 0v5.5q-25 11-50 0z" fill={YALE} stroke={O} strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx="60" cy="87" r="4.4" fill="#fff" stroke={O} strokeWidth="1.3" />
      <path d="M57.8 84.8l2.2 2.6 2.2-2.6M60 87.4v2.4" stroke={YALE} strokeWidth="1.3" fill="none" strokeLinecap="round" />

      {/* ears */}
      <path d="M34 36q-11-7-8 9 4 2 11-3z" fill={EAR} stroke={O} strokeWidth="2" strokeLinejoin="round" />
      <path d="M86 36q11-7 8 9-4 2-11-3z" fill={EAR} stroke={O} strokeWidth="2" strokeLinejoin="round" />

      {/* head */}
      <path d="M60 26c22 0 32 12 32 26s-10 24-32 24-32-10-32-24 10-26 32-26z" fill={FUR} stroke={O} strokeWidth="2.4" />
      <path d="M66 38c10-4 18 2 17 11-3 6-13 6-17 1z" fill={PATCH} opacity=".85" />
      <path d="M50 37q4-3 8 0M62 37q4-3 8 0" stroke={O} strokeWidth="1.4" fill="none" strokeLinecap="round" opacity=".45" />

      {/* eyes */}
      <circle cx="47" cy="47" r="3.6" fill={O} />
      <circle cx="48.2" cy="45.8" r="1.1" fill="#fff" />
      <circle cx="73" cy="47" r="3.6" fill={O} />
      <circle cx="74.2" cy="45.8" r="1.1" fill="#fff" />

      {/* muzzle, nose, mouth */}
      <ellipse cx="60" cy="62" rx="17" ry="11.5" fill={MUZZLE} stroke={O} strokeWidth="1.6" />
      <path d="M53.5 53.5q6.5-3 13 0-1.5 5.5-6.5 6-5-.5-6.5-6z" fill={NOSE} />
      <path d="M60 59.5v3.5" stroke={O} strokeWidth="1.4" strokeLinecap="round" />
      {friendly ? (
        <g>
          <path d="M49 63.5q11 11.5 22 0-11 4.5-22 0z" fill="#7A2E3A" stroke={O} strokeWidth="1.4" strokeLinejoin="round" />
          <path d="M55 67.6q5 6.4 10 0-5 2-10 0z" fill="#E57A87" />
          <circle cx="40" cy="58" r="3.4" fill="#F9A8B8" opacity=".6" />
          <circle cx="80" cy="58" r="3.4" fill="#F9A8B8" opacity=".6" />
        </g>
      ) : (
        <g>
          <path d="M50 65q5 3.5 10-.5 5 4 10 .5" fill="none" stroke={O} strokeWidth="1.6" strokeLinecap="round" />
          <path d="M53 64.6l1.5-2.8 1.5 2.8zM64 64.6l1.5-2.8 1.5 2.8z" fill="#fff" stroke={O} strokeWidth=".8" strokeLinejoin="round" />
        </g>
      )}

      <Accessory agent={agent} />
    </svg>
  )
}
