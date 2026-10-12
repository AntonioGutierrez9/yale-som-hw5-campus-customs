import { useEffect, useRef, type ReactNode } from 'react'

/** Accessible modal on the native <dialog> element (focus trap + Esc to close). */
export function Modal({ open, onClose, title, children, labelledBy = 'modal-title' }: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  labelledBy?: string
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])
  return (
    <dialog ref={ref} className="modal" aria-labelledby={labelledBy} onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) onClose() }}>
      {open && (
        <div className="modal-body">
          <header className="modal-head">
            <h2 id={labelledBy}>{title}</h2>
            <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
          </header>
          {children}
        </div>
      )}
    </dialog>
  )
}
