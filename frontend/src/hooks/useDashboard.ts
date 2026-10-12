import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import type { Approvals, Attention, AuditEvent, Cash, Limits, RunResult, Status, TicketList } from '../types'

const BUSY_POLL_MS = 1200
const IDLE_POLL_MS = 5000

export interface Toast {
  id: number
  kind: 'success' | 'error' | 'info'
  title: string
  body?: string
}

/** All dashboard data, kept fresh by polling the real backend. */
export function useDashboard() {
  const [status, setStatus] = useState<Status | null>(null)
  const [tickets, setTickets] = useState<TicketList | null>(null)
  const [cash, setCash] = useState<Cash | null>(null)
  const [approvals, setApprovals] = useState<Approvals | null>(null)
  const [attention, setAttention] = useState<Attention | null>(null)
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [offline, setOffline] = useState<string | null>(null)
  const [runningTicket, setRunningTicket] = useState<number | null>(null)
  const [version, setVersion] = useState(0) // bumped when ticket-level panels should reload
  const [toasts, setToasts] = useState<Toast[]>([])
  const [limits, setLimits] = useState<Limits | null>(null)
  // Set when the backend says a ticket already ran and needs the human's permission to run again.
  const [permissionAsk, setPermissionAsk] = useState<{ ticket: number; message: string } | null>(null)
  const nextSince = useRef<number | null>(null)
  const wasBusy = useRef(false)
  const toastId = useRef(0)

  const toast = useCallback((t: Omit<Toast, 'id'>) => {
    const id = ++toastId.current
    setToasts((ts) => [...ts, { ...t, id }])
    window.setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), t.kind === 'error' ? 9000 : 6000)
  }, [])
  const dismissToast = useCallback((id: number) => setToasts((ts) => ts.filter((x) => x.id !== id)), [])

  const refreshCore = useCallback(async () => {
    const [t, c, a, at] = await Promise.allSettled([api.tickets(), api.cash(), api.approvals(), api.attention()])
    if (t.status === 'fulfilled') setTickets(t.value)
    if (c.status === 'fulfilled') setCash(c.value)
    if (a.status === 'fulfilled') setApprovals(a.value)
    if (at.status === 'fulfilled') setAttention(at.value)
    const failed = [t, c, a, at].find((r) => r.status === 'rejected') as PromiseRejectedResult | undefined
    setOffline(failed && failed.reason instanceof ApiError && failed.reason.code === 'offline' ? failed.reason.message : null)
  }, [])

  const loadEvents = useCallback(async (fresh = false) => {
    if (fresh || nextSince.current === null) {
      const res = await api.activity({ since_reset: true, limit: 1000 })
      setEvents(res.events)
      nextSince.current = res.next_since
      return res.status
    }
    const res = await api.activity({ since: nextSince.current, limit: 500, since_reset: true })
    if (res.events.length) setEvents((prev) => [...prev, ...res.events].slice(-2000))
    nextSince.current = res.next_since
    return res.status
  }, [])

  useEffect(() => { api.limits().then(setLimits).catch(() => undefined) }, [])

  // Polling loop: fast while agents work, slow when idle.
  useEffect(() => {
    let stop = false
    let timer: number | undefined
    let tick = 0
    const loop = async () => {
      let busy = false
      try {
        const st = await loadEvents()
        setStatus(st)
        busy = st.busy
        setOffline(null)
        if (tick === 0 || (busy && tick % 3 === 0) || (!busy && tick % 3 === 0)) await refreshCore()
        if (wasBusy.current && !busy) {
          await refreshCore() // a run (or reset) just finished: refresh everything
          setVersion((v) => v + 1)
        }
        wasBusy.current = busy
      } catch (e) {
        if (e instanceof ApiError && e.code === 'offline') setOffline(e.message)
      }
      tick++
      if (!stop) timer = window.setTimeout(loop, busy ? BUSY_POLL_MS : IDLE_POLL_MS)
    }
    loop()
    return () => {
      stop = true
      window.clearTimeout(timer)
    }
  }, [loadEvents, refreshCore])

  const runTicket = useCallback(async (id: number, continueConfirmed = false): Promise<RunResult | null> => {
    setPermissionAsk(null)
    setRunningTicket(id)
    setStatus((s) => (s ? { ...s, busy: true, action: 'run', ticket_id: id } : s))
    try {
      const result = await api.run(id, continueConfirmed)
      const r = result.run
      if (r.stop_reason === 'final_answer') {
        toast({ kind: 'success', title: `Ticket ${id}: run completed`, body: `${r.output?.summary ?? ''}${r.customer_reply ? ` Customer reply: ${r.customer_reply}.` : ''}` })
      } else if (r.limit_hit) {
        toast({ kind: 'info', title: `Ticket ${id}: stopped at an execution limit`, body: r.unresolved ?? r.error ?? undefined })
      } else {
        toast({ kind: 'error', title: `Ticket ${id}: run stopped (${r.stop_reason})`, body: r.error ?? undefined })
      }
      return result
    } catch (e) {
      if (e instanceof ApiError && e.code === 'needs_permission') {
        setPermissionAsk({ ticket: id, message: e.message })  // ask the human; never rerun automatically
        return null
      }
      toast({ kind: 'error', title: `Ticket ${id}: run failed`, body: e instanceof Error ? e.message : String(e) })
      return null
    } finally {
      setRunningTicket(null)
      await loadEvents().catch(() => undefined)
      await refreshCore()
      setVersion((v) => v + 1)
    }
  }, [loadEvents, refreshCore, toast])

  const approve = useCallback(async (id: number, name: string) => {
    const res = await api.approve(id, name)
    toast(res.kind === 'discount'
      ? { kind: 'success', title: `Discount #${id} approved`, body: res.effect }
      : { kind: 'success', title: `Approval #${id} paid`, body: `${res.effect} Checking is now ${res.checking_balance.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}.` })
    await refreshCore()
    await loadEvents().catch(() => undefined)
    setVersion((v) => v + 1)
  }, [loadEvents, refreshCore, toast])

  const undo = useCallback(async (id: number, name: string, reason: string) => {
    const res = await api.undo(id, name, reason)
    toast({ kind: 'info', title: `Decision on #${id} undone (was ${res.old_status})`, body: `${res.effect} The request is pending again.` })
    await refreshCore()
    await loadEvents().catch(() => undefined)
    setVersion((v) => v + 1)
  }, [loadEvents, refreshCore, toast])

  const reject = useCallback(async (id: number, name: string, reason: string) => {
    await api.reject(id, name, reason)
    toast({ kind: 'info', title: `Approval #${id} rejected`, body: 'No money moved.' })
    await refreshCore()
    await loadEvents().catch(() => undefined)
    setVersion((v) => v + 1)
  }, [loadEvents, refreshCore, toast])

  // Run ONLY Customer Service to write the requester's reply draft (cheaper than a full rerun).
  const draftReply = useCallback(async (id: number) => {
    setRunningTicket(id)
    setStatus((s) => (s ? { ...s, busy: true, action: 'run', ticket_id: id } : s))
    try {
      const result = await api.draftReply(id)
      const drafts = result.ticket.drafts?.length ?? 0
      toast(result.run.stop_reason === 'final_answer'
        ? { kind: 'success', title: `Ticket ${id}: reply drafted by Customer Service`, body: `${result.run.output?.summary ?? ''} (${drafts} draft(s) on this ticket; never sent)` }
        : { kind: 'error', title: `Ticket ${id}: reply not drafted (${result.run.stop_reason})`, body: result.run.error ?? undefined })
    } catch (e) {
      toast({ kind: 'error', title: `Ticket ${id}: couldn't draft a reply`, body: e instanceof Error ? e.message : String(e) })
    } finally {
      setRunningTicket(null)
      await loadEvents().catch(() => undefined)
      await refreshCore()
      setVersion((v) => v + 1)
    }
  }, [loadEvents, refreshCore, toast])

  // Re-read a ticket's status from the human decisions on its approval requests (no agents run).
  const syncTicket = useCallback(async (id: number) => {
    try {
      const res = await api.syncStatus(id)
      const label = (s: string) => s.replace(/_/g, ' ')
      toast({
        kind: res.changed ? 'success' : 'info',
        title: res.changed ? `Ticket ${id}: ${label(res.old_status)} → ${label(res.new_status)}` : `Ticket ${id}: status unchanged (${label(res.new_status)})`,
        body: `${res.reason} Human decisions: ${res.approved} approved · ${res.rejected} rejected · ${res.pending} pending.`,
      })
    } catch (e) {
      toast({ kind: 'error', title: `Ticket ${id}: couldn't update status`, body: e instanceof Error ? e.message : String(e) })
    }
    await refreshCore()
    await loadEvents().catch(() => undefined)
    setVersion((v) => v + 1)
  }, [loadEvents, refreshCore, toast])

  const reset = useCallback(async () => {
    await api.reset()
    toast({ kind: 'success', title: 'Database reset', body: 'campus_customs_new.db restored from the original.' })
    await loadEvents(true)
    await refreshCore()
    setVersion((v) => v + 1)
  }, [loadEvents, refreshCore, toast])

  return {
    status, tickets, cash, approvals, attention, events, offline, runningTicket, version, toasts, limits,
    permissionAsk, setPermissionAsk, runTicket, draftReply, syncTicket, approve, reject, undo, reset, toast, dismissToast,
  }
}
