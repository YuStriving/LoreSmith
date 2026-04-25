import type { AwaitingConfirmation, RunEventPayload } from '../../lib/types/api'

export function formatDate(value?: string | null) {
  if (!value) {
    return '最近创建'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function formatWordCount(value?: number | null) {
  if (!value) {
    return '0'
  }
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function statusLabel(status?: string | null) {
  switch (status) {
    case 'running':
      return '创作中'
    case 'queued':
      return '排队中'
    case 'waiting_input':
      return '待补充'
    case 'paused':
      return '已暂停'
    case 'completed':
      return '已完结'
    case 'failed':
      return '失败'
    case 'canceled':
      return '已取消'
    default:
      return status || '草稿'
  }
}

export function normalizeAwaitingConfirmation(value: unknown): AwaitingConfirmation | undefined {
  if (!value || typeof value !== 'object') {
    return undefined
  }
  const raw = value as Record<string, unknown>
  return {
    pauseAfterChapter: Number(raw.pause_after_chapter ?? 0),
    nextChapter: Number(raw.next_chapter ?? 0),
    completedCount: Number(raw.completed_count ?? 0),
    status: raw.status == null ? null : String(raw.status),
  }
}

export function normalizeEvent(record: Record<string, unknown>, index: number) {
  const seq = Number(record.seq ?? index)
  const rawPayload = (record.payload as Record<string, unknown> | undefined) ?? {}
  const payload: RunEventPayload = {
    ...rawPayload,
    summary: rawPayload.summary == null ? undefined : String(rawPayload.summary),
    delta: rawPayload.delta == null ? undefined : String(rawPayload.delta),
    level: rawPayload.level == null ? undefined : String(rawPayload.level),
    event: rawPayload.event == null ? undefined : String(rawPayload.event),
    awaiting_confirmation: normalizeAwaitingConfirmation(rawPayload.awaiting_confirmation),
  }
  return {
    eventId: String(record.event_id ?? record.eventId ?? `evt-${seq}`),
    seq,
    type: String(record.type ?? 'ui.event'),
    category: String(record.category ?? 'system'),
    time: String(record.time ?? new Date().toISOString()),
    payload,
  }
}
