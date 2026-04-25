import { ApiError, apiFetch } from './client'
import { pythonCreateRun, pythonFetch, pythonStream } from './pythonClient'
import { fetchStories } from './stories'
import type { StoryCharacter, StoryWorkspace, WorkspaceAssistantStreamResponse, WorkspaceNodeType, WorkspaceReference } from '../types/api'
import {
  createWorkspaceFromStory,
  createWorkspaceNodeLocal,
  loadWorkspaceLocal,
  saveWorkspaceLocal,
  updateWorkspaceNodeLocal,
} from './workspaceLocal'

function isWorkspaceFallbackError(error: unknown) {
  return error instanceof ApiError && [404, 405, 501].includes(error.status)
}

function normalizeReferencePayload(payload: Record<string, unknown> | WorkspaceReference | null | undefined): WorkspaceReference {
  const source = (payload ?? {}) as Record<string, unknown>
  return {
    premise: typeof source.premise === 'string' ? source.premise : '',
    outline: Array.isArray(source.outline) ? (source.outline as Array<Record<string, unknown>>) : [],
    characters: Array.isArray(source.characters) ? (source.characters as Array<Record<string, unknown>>) : [],
    worldRules: Array.isArray(source.worldRules)
      ? (source.worldRules as Array<Record<string, unknown>>)
      : Array.isArray(source.world_rules)
        ? (source.world_rules as Array<Record<string, unknown>>)
        : [],
    timeline: Array.isArray(source.timeline) ? (source.timeline as Array<Record<string, unknown>>) : [],
    relationshipState: Array.isArray(source.relationshipState)
      ? (source.relationshipState as Array<Record<string, unknown>>)
      : Array.isArray(source.relationship_state)
        ? (source.relationship_state as Array<Record<string, unknown>>)
        : [],
    foreshadowLedger: Array.isArray(source.foreshadowLedger)
      ? (source.foreshadowLedger as Array<Record<string, unknown>>)
      : Array.isArray(source.foreshadow_ledger)
        ? (source.foreshadow_ledger as Array<Record<string, unknown>>)
        : [],
  }
}

function serializeReferencePayload(reference: WorkspaceReference) {
  return {
    premise: reference.premise,
    outline: reference.outline,
    characters: reference.characters,
    world_rules: reference.worldRules,
    timeline: reference.timeline,
    relationship_state: reference.relationshipState,
    foreshadow_ledger: reference.foreshadowLedger,
  }
}

function normalizeStoryCharacters(reference?: WorkspaceReference): StoryCharacter[] {
  return (reference?.characters ?? [])
    .map((item) => ({
      name: String(item.name ?? '').trim(),
      role: String(item.role ?? '').trim(),
      description: String(item.description ?? item.summary ?? '').trim(),
    }))
    .filter((item) => item.name)
}

async function loadStoryOrThrow(storyId: string) {
  const stories = await fetchStories()
  const story = stories.find((item) => item.storyId === storyId)
  if (!story) {
    throw new Error('作品不存在')
  }
  return story
}

export async function fetchStoryWorkspace(storyId: string) {
  try {
    return await pythonFetch<StoryWorkspace>(`/internal/v1/workspace?story_id=${encodeURIComponent(storyId)}`)
  } catch (error) {
    if (!isWorkspaceFallbackError(error)) {
      throw error
    }

    const local = loadWorkspaceLocal(storyId)
    if (local) {
      return local
    }

    const story = await loadStoryOrThrow(storyId)
    return saveWorkspaceLocal(createWorkspaceFromStory(story))
  }
}

export async function fetchStoryWorkspaceReference(storyId: string, workspace?: StoryWorkspace) {
  try {
    const payload = await pythonFetch<Record<string, unknown>>(`/internal/v1/workspace/reference-snapshot?story_id=${encodeURIComponent(storyId)}`)
    return normalizeReferencePayload(payload)
  } catch (error) {
    if (!isWorkspaceFallbackError(error)) {
      throw error
    }
    return {
      premise: workspace?.premise ?? '',
      outline: [],
      characters: [],
      worldRules: [],
      timeline: [],
      relationshipState: [],
      foreshadowLedger: [],
    } satisfies WorkspaceReference
  }
}

export async function saveWorkspaceNode(
  storyId: string,
  workspace: StoryWorkspace,
  nodeId: string,
  payload: { title?: string; summary?: string; content?: string },
) {
  try {
    return await pythonFetch<StoryWorkspace>(`/internal/v1/workspace/nodes/${encodeURIComponent(nodeId)}?story_id=${encodeURIComponent(storyId)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  } catch (error) {
    if (!isWorkspaceFallbackError(error)) {
      throw error
    }
    return updateWorkspaceNodeLocal(workspace, nodeId, payload)
  }
}

export async function createWorkspaceNode(storyId: string, workspace: StoryWorkspace, parentId: string | null, type: WorkspaceNodeType) {
  try {
    return await pythonFetch<StoryWorkspace>(`/internal/v1/workspace/nodes?story_id=${encodeURIComponent(storyId)}`, {
      method: 'POST',
      body: JSON.stringify({ parentId, type }),
    })
  } catch (error) {
    if (!isWorkspaceFallbackError(error)) {
      throw error
    }
    return createWorkspaceNodeLocal(workspace, parentId, type)
  }
}

export async function appendAssistantMessage(
  storyId: string,
  workspace: StoryWorkspace,
  action: string,
  instruction: string,
  onDelta?: (delta: string) => void,
) {
  void workspace
  const response = await pythonStream(`/internal/v1/workspace/intent/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      intent_type: 'assistant_reply',
      story: {
        story_id: storyId,
        title: workspace.title,
        premise: workspace.premise,
        style: workspace.style ?? '',
      },
      node: {
        node_id: workspace.activeNodeId ?? '',
        type: 'chapter',
        title: workspace.nodes.find((item) => item.id === workspace.activeNodeId)?.title ?? '',
        summary: '',
        chapter: 0,
        asset_type: 'chapter',
      },
      content: workspace.activeNodeId ? workspace.contentByNodeId[workspace.activeNodeId] ?? '' : '',
      action,
      instruction,
      label: '',
      payload: {},
      metadata: {
        workspace_id: storyId,
        tenant_id: 'workspace-agent',
        user_id: 'assistant-reply',
      },
    }),
  })

  if (!response.ok) {
    const text = await response.text()
    let json: { code?: string; message?: string } | null = null
    try {
      json = text ? (JSON.parse(text) as { code?: string; message?: string }) : null
    } catch {
      json = null
    }
    throw new ApiError(json?.message ?? '请求失败', json?.code ?? 'HTTP_ERROR', response.status)
  }

  if (!response.body) {
    throw new ApiError('流式响应为空', 'EMPTY_STREAM', response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let donePayload: WorkspaceAssistantStreamResponse | null = null

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })

    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      const lines = frame.split('\n')
      const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
      const data = lines
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('\n')
      if (!event || !data) {
        continue
      }
      const payload = JSON.parse(data) as { delta?: string } | WorkspaceAssistantStreamResponse
      if (event === 'delta' && 'delta' in payload && payload.delta) {
        onDelta?.(payload.delta)
      }
      if (event === 'done') {
        donePayload = payload as WorkspaceAssistantStreamResponse
      }
    }

    if (done) {
      break
    }
  }

  if (!donePayload) {
    throw new ApiError('流式响应未结束', 'INCOMPLETE_STREAM', response.status)
  }

  return donePayload
}

export async function startWorkspaceRun(storyId: string, prompt: string, workspace?: StoryWorkspace, reference?: WorkspaceReference) {
  const runId = workspace?.runBridge?.activeRunId ?? crypto.randomUUID()
  const storyTitle = workspace?.title ?? storyId
  const storyPremise = reference?.premise || workspace?.premise || prompt
  await pythonCreateRun({
    run_id: runId,
    story: {
      story_id: storyId,
      title: storyTitle,
      premise: storyPremise,
      style: workspace?.style ?? 'default',
      characters: normalizeStoryCharacters(reference),
      word_count: {
        min_words: 1200,
        target_words: 1800,
        max_words: 2600,
      },
    },
    execution: {
      provider: 'openrouter',
      model: 'qwen3.5-flash',
      context_window: 128000,
    },
    input: {
      mode: 'start',
      prompt,
    },
    storage: {
      kind: 'local',
      base_path: `output/workspace/${storyId}`,
    },
    metadata: {
      workspace_id: storyId,
      tenant_id: 'workspace-agent',
      user_id: 'run-start',
      extra: reference
        ? {
            reference_snapshot: serializeReferencePayload(reference),
          }
        : {},
    },
    config_path: 'dev_config.json',
  })
  if (reference) {
    await updateWorkspaceReference(storyId, reference)
  }

  return pythonFetch<StoryWorkspace>(`/internal/v1/workspace/run-bridge?story_id=${encodeURIComponent(storyId)}`, {
    method: 'PUT',
    body: JSON.stringify({
      activeRunId: runId,
      runAfterSeq: workspace?.runBridge?.runAfterSeq ?? 0,
      runSyncStatus: 'running',
      runSyncUpdatedAt: new Date().toISOString(),
      lastCompletedChapter: workspace?.runBridge?.lastCompletedChapter ?? null,
    }),
  })
}

export async function updateWorkspaceReference(storyId: string, reference: WorkspaceReference) {
  const payload = await pythonFetch<Record<string, unknown>>(`/internal/v1/workspace/reference-snapshot?story_id=${encodeURIComponent(storyId)}`, {
    method: 'PUT',
    body: JSON.stringify(serializeReferencePayload(reference)),
  })
  return normalizeReferencePayload(payload)
}

export async function updateWorkspaceRunBridgeSeq(storyId: string, runId: string, runAfterSeq: number) {
  return pythonFetch<StoryWorkspace>(`/internal/v1/workspace/run-bridge?story_id=${encodeURIComponent(storyId)}`, {
    method: 'PUT',
    body: JSON.stringify({
      activeRunId: runId,
      runAfterSeq,
      runSyncStatus: 'running',
      runSyncUpdatedAt: new Date().toISOString(),
      lastCompletedChapter: null,
    }),
  })
}
