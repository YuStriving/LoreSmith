import type {
  Story,
  StoryWorkspace,
  WorkspaceNode,
  WorkspaceNodeType,
} from '../types/api'

const STORAGE_VERSION = 3
const STORAGE_PREFIX = 'ainovel-workspace:'

function nowIso() {
  return new Date().toISOString()
}

function createId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`
}

function normalizeWorkspace(workspace: StoryWorkspace): StoryWorkspace {
  return {
    ...workspace,
  }
}

function defaultBriefForType(type: WorkspaceNodeType, story: Story) {
  if (type === 'volume') return story.premise || '围绕核心设定展开主线。'
  return '交代本章目标、冲突与转折。'
}

function buildInitialNodes(story: Story): WorkspaceNode[] {
  const volumeId = createId('volume')
  const chapterId = createId('chapter')

  return [
    {
      id: volumeId,
      parentId: null,
      type: 'volume',
      title: '第一卷 · 故事初启',
      order: 0,
      summary: defaultBriefForType('volume', story),
    },
    {
      id: chapterId,
      parentId: volumeId,
      type: 'chapter',
      title: '第一章 · 起笔',
      order: 0,
      summary: defaultBriefForType('chapter', story),
    },
  ]
}

function buildInitialContent(story: Story, nodes: WorkspaceNode[]) {
  const chapterNode = nodes.find((node) => node.type === 'chapter')
  const draft = story.premise || '从一个能立刻建立悬念的场景开始。'

  return {
    ...(chapterNode ? { [chapterNode.id]: `${story.title}\n\n${draft}` } : {}),
  }
}

export function createWorkspaceFromStory(story: Story): StoryWorkspace {
  const nodes = buildInitialNodes(story)
  const activeNodeId = nodes.find((node) => node.type === 'chapter')?.id ?? nodes[0]?.id ?? null
  const contentByNodeId = buildInitialContent(story, nodes)
  return {
    storyId: story.storyId,
    title: story.title,
    premise: story.premise,
    style: story.style,
    updatedAt: nowIso(),
    localOnly: true,
    nodes,
    activeNodeId,
    contentByNodeId,
    assistantThread: [
      {
        id: createId('msg'),
        role: 'assistant',
        content: '我已经为这部作品准备好了共享工作台。你可以在左侧切换章节，在中间直接编辑正文。',
        createdAt: nowIso(),
      },
    ],
    runBridge: {
      activeRunId: story.latestRunId,
      runAfterSeq: 0,
      runSyncStatus: story.latestRunId ? 'running' : 'idle',
      runSyncUpdatedAt: nowIso(),
      lastCompletedChapter: null,
    },
  }
}

function getStorageKey(storyId: string) {
  return `${STORAGE_PREFIX}${storyId}`
}

export function loadWorkspaceLocal(storyId: string) {
  if (typeof window === 'undefined') {
    return null
  }

  const raw = window.localStorage.getItem(getStorageKey(storyId))
  if (!raw) {
    return null
  }

  try {
    const parsed = JSON.parse(raw) as {
      version: number
      data: StoryWorkspace
    }

    if (parsed.version === STORAGE_VERSION) {
      return normalizeWorkspace({ ...parsed.data, localOnly: true }) satisfies StoryWorkspace
    }

    return null
  } catch {
    return null
  }
}

export function saveWorkspaceLocal(workspace: StoryWorkspace) {
  if (typeof window === 'undefined') {
    return workspace
  }

  const nextWorkspace: StoryWorkspace = normalizeWorkspace({
    ...workspace,
    localOnly: true,
    updatedAt: nowIso(),
  })

  window.localStorage.setItem(
    getStorageKey(workspace.storyId),
    JSON.stringify({ version: STORAGE_VERSION, data: nextWorkspace }),
  )

  return nextWorkspace
}

export function updateWorkspaceNodeLocal(
  workspace: StoryWorkspace,
  nodeId: string,
  payload: { title?: string; summary?: string; content?: string },
) {
  return saveWorkspaceLocal({
    ...workspace,
    activeNodeId: nodeId,
    nodes: workspace.nodes.map((node) =>
      node.id === nodeId
        ? {
            ...node,
            title: payload.title ?? node.title,
            summary: payload.summary ?? node.summary,
          }
        : node,
    ),
    contentByNodeId:
      payload.content === undefined
        ? workspace.contentByNodeId
        : {
            ...workspace.contentByNodeId,
            [nodeId]: payload.content,
          },
  })
}

const titleMap: Record<WorkspaceNodeType, (index: number) => string> = {
  volume: (index) => `第 ${index} 卷`,
  chapter: (index) => `第 ${index} 章`,
}

export function createWorkspaceNodeLocal(workspace: StoryWorkspace, parentId: string | null, type: WorkspaceNodeType) {
  const siblings = workspace.nodes.filter((node) => node.parentId === parentId && node.type === type)
  const nextIndex = siblings.length + 1

  const node: WorkspaceNode = {
    id: createId(type),
    parentId,
    type,
    title: titleMap[type](nextIndex),
    order: siblings.length,
    summary: '',
  }

  return saveWorkspaceLocal({
    ...workspace,
    nodes: [...workspace.nodes, node],
    activeNodeId: node.id,
    contentByNodeId: {
      ...workspace.contentByNodeId,
      [node.id]: '',
    },
  })
}
