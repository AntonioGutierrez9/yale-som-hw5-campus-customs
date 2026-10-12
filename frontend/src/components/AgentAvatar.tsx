import { isAgent } from '../agents'
import type { Actor } from '../types'
import { Bulldog, type DogState } from './Bulldog'

/** Bulldog for agents, a simple person badge for human actions. */
export function AgentAvatar({ actor, size = 32, state = 'idle' }: { actor: Actor | string; size?: number; state?: DogState }) {
  if (isAgent(actor)) {
    return (
      <span className="avatar" style={{ width: size, height: size }}>
        <Bulldog agent={actor} size={size} state={state} />
      </span>
    )
  }
  return (
    <span className="avatar avatar-human" style={{ width: size, height: size }} aria-label="Human" role="img">
      <svg viewBox="0 0 24 24" width={size * 0.62} height={size * 0.62} aria-hidden="true">
        <title>{actor}</title>
        <circle cx="12" cy="8" r="4" fill="currentColor" />
        <path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" fill="currentColor" />
      </svg>
    </span>
  )
}
