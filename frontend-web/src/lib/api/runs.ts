import { buildQuery } from './client'
import { pythonFetch, pythonStream } from './pythonClient'
import type { ChapterResponse, ResumeRunRequest, Run, RunAck, RunEventStreamHandler, RunEventsResponse, RunInstructionRequest, RunListResponse } from '../types/api'
import { normalizeAwaitingConfirmation, normalizeEvent } from '../utils/format'

function normalizeRun(run: Run & Record<string, unknown>): Run {
  return {
    ...run,
    runId: String(run.runId ?? run.run_id ?? ''),
    storyId: String(run.storyId ?? run.story_id ?? ''),
    kernelStatus: String(run.kernelStatus ?? run.kernel_status ?? ''),
    currentChapter: run.currentChapter == null ? Number(run.current_chapter ?? 0) || null : run.currentChapter,
    completedCount: run.completedCount == null ? Number(run.completed_count ?? 0) || null : run.completedCount,
    totalWordCount: run.totalWordCount == null ? Number(run.total_word_count ?? 0) || null : run.totalWordCount,
    awaitingConfirmation: normalizeAwaitingConfirmation(run.awaitingConfirmation ?? run.awaiting_confirmation),
  }
}

export async function fetchRuns(filters?: { status?: string; storyId?: string }) {
  const query = buildQuery({ status: filters?.status, storyId: filters?.storyId })
  const data = await pythonFetch<RunListResponse>(`/internal/v1/runs${query}`)
  return data.items.map(normalizeRun)
}

export async function fetchRun(runId: string) {
  const run = await pythonFetch<Run & Record<string, unknown>>(`/internal/v1/runs/${runId}`)
  return normalizeRun(run)
}

export async function streamRunEvents(runId: string, afterSeq: number, onEvent: RunEventStreamHandler) {
  const query = `?after_seq=${encodeURIComponent(String(afterSeq))}`
  const response = await pythonStream(`/internal/v1/runs/${runId}/events/stream${query}`)
  if (!response.ok || !response.body) {
    throw new Error('stream unavailable')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const lines = frame.split('\n')
      const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')
      if (!data) {
        continue
      }
      onEvent(normalizeEvent(JSON.parse(data) as Record<string, unknown>, 0))
    }
    if (done) {
      break
    }
  }
}

export async function fetchChapter(runId: string, chapterNumber: number) {
  return pythonFetch<ChapterResponse>(`/internal/v1/runs/${runId}/chapters/${chapterNumber}`)
}

export async function pauseRun(runId: string) {
  return pythonFetch<Run>(`/internal/v1/runs/${runId}/pause`, {
    method: 'POST',
  })
}

export async function resumeRun(runId: string, payload: ResumeRunRequest) {
  return pythonFetch<RunAck>(`/internal/v1/runs/${runId}/resume`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function cancelRun(runId: string) {
  return pythonFetch<Run>(`/internal/v1/runs/${runId}/cancel`, {
    method: 'POST',
  })
}

export async function sendInstruction(runId: string, payload: RunInstructionRequest) {
  return pythonFetch<Record<string, unknown>>(`/internal/v1/runs/${runId}/instructions`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
