import type { AgentName } from './types'

export const AGENTS: AgentName[] = ['Boss', 'Inventory', 'Accounting', 'Facilities', 'Customer Service']

export const AGENT_META: Record<AgentName, { role: string; color: string; short: string }> = {
  Boss: { role: 'Triage · delegates · final calls', color: '#00356B', short: 'Boss' },
  Inventory: { role: 'Stock · vendors · restocks', color: '#C2410C', short: 'Inventory' },
  Accounting: { role: 'Cash · invoices · margins', color: '#0F766E', short: 'Accounting' },
  Facilities: { role: 'Lease · rent · shop space', color: '#A16207', short: 'Facilities' },
  'Customer Service': { role: 'Customer drafts (never sent)', color: '#7C3AED', short: 'Cust. Service' },
}

export const isAgent = (x: string | undefined | null): x is AgentName => !!x && x in AGENT_META
