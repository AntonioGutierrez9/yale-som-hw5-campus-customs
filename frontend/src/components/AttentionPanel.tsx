import type { Attention, AttentionItem } from '../types'

const ICON: Record<AttentionItem['kind'], string> = {
  overdue_invoice: '🧾',
  low_inventory: '📦',
  blocked_vendor: '⛔',
  rent_due: '🏠',
  pending_approval: '✋',
  cash_shortfall: '💵',
}
const KIND: Record<AttentionItem['kind'], string> = {
  overdue_invoice: 'Overdue invoice',
  low_inventory: 'Inventory',
  blocked_vendor: 'Blocked vendor',
  rent_due: 'Rent deadline',
  pending_approval: 'Pending approval',
  cash_shortfall: 'Cash',
}

export function AttentionPanel({ attention, onTicket }: { attention: Attention | null; onTicket: (id: number) => void }) {
  return (
    <section className="panel attention-panel" id="attention" aria-labelledby="att-title">
      <header className="panel-head">
        <div>
          <h2 id="att-title">Attention needed {attention && attention.count > 0 && <span className="count-pill count-pill--warn">{attention.count}</span>}</h2>
          <p className="panel-sub">{attention ? `From the live database · shop date ${attention.today}` : 'Loading…'}</p>
        </div>
      </header>
      <ul className="attention">
        {attention?.items.length === 0 && <li className="empty">All clear. Nothing needs attention.</li>}
        {attention?.items.map((it, i) => (
          <li key={`${it.kind}-${i}`} className={`att att-${it.severity}`}>
            <span className="att-icon" aria-hidden="true">{ICON[it.kind]}</span>
            <div>
              <div className="att-kind">{KIND[it.kind]} · <span className={`sev sev-${it.severity}`}>{it.severity}</span></div>
              <strong>{it.title}</strong>
              <p>{it.detail}</p>
              {it.ticket_id && <button className="link" onClick={() => onTicket(it.ticket_id!)}>Open ticket {it.ticket_id}</button>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
