export type ApiEnvelope<T> = {
  code: string
  message: string
  data: T
}

export type StoryCharacter = {
  name: string
  role?: string | null
  description?: string | null
}

export type StoryWordCount = {
  minWords: number
  targetWords: number
  maxWords: number
}

export type Story = {
  storyId: string
  title: string
  premise: string
  genre?: string | null
  style: string | null
  characters?: StoryCharacter[]
  wordCount?: StoryWordCount | null
  latestRunId: string | null
  createdAt: string | null
}

export type StoryListResponse = {
  items: Story[]
}

export type CreateStoryRequest = {
  storyId: string
  runId: string
  title: string
  premise: string
  genre?: string
  style?: string
  characters?: StoryCharacter[]
  wordCount?: StoryWordCount
  prompt: string
  provider?: string
  model?: string
  outputPath?: string
  configPath?: string
}

export type CreateStoryResponse = {
  storyId: string
  runId: string
  status: string
  kernelStatus: string
}

export type AwaitingConfirmation = {
  pauseAfterChapter: number
  nextChapter: number
  completedCount: number
  status?: string | null
}

export type Run = {
  runId: string
  storyId: string
  status: string
  kernelStatus: string
  phase: string | null
  flow: string | null
  provider: string | null
  model: string | null
  currentChapter: number | null
  completedCount: number | null
  totalWordCount: number | null
  awaitingConfirmation?: AwaitingConfirmation | null
}

export type RunListResponse = {
  items: Run[]
}

export type RunEventsResponse = {
  run_id: string
  after_seq: number
  limit: number
  returned_count: number
  total_available: number
  next_after_seq: number
  has_more: boolean
  items: Array<Record<string, unknown>>
}

export type RunEventPayload = Record<string, unknown> & {
  summary?: string
  delta?: string
  level?: string
  event?: string
  awaiting_confirmation?: AwaitingConfirmation
}

export type RunEvent = {
  eventId: string
  seq: number
  type: string
  category: string
  time: string
  payload: RunEventPayload
}

export type RunEventStreamHandler = (event: RunEvent) => void

export type ChapterResponse = {
  run_id: string
  chapter: Record<string, unknown>
}

export type Artifact = {
  artifactId: string
  type: string
  name: string
  chapter: number | null
  mimeType: string | null
  uri: string
  createdAt: string | null
}

export type ArtifactListResponse = {
  items: Artifact[]
}

export type ResumeRunRequest = {
  prompt?: string
  decision?: 'continue' | 'approve' | ''
  feedback?: string
}

export type RunInstructionRequest = {
  type: string
  text?: string
  decision?: 'continue' | 'approve' | ''
  feedback?: string
}

export type RunAck = {
  run_id: string
  status: string
  kernel_status?: string | null
  accepted?: boolean | null
}

export type WorkspaceNodeType = 'volume' | 'chapter'

export type WorkspaceNode = {
  id: string
  parentId: string | null
  type: WorkspaceNodeType
  title: string
  order: number
  summary?: string
}

export type WorkspaceAssistantMessage = {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  createdAt: string
}

export type WorkspaceAssistantStreamResponse = {
  storyId: string
  messageId: string
  content: string
  fallbackUsed: boolean
}

export type WorkspaceRunBridge = {
  activeRunId: string | null
  runAfterSeq: number
  runSyncStatus: 'idle' | 'running' | 'waiting_input' | 'completed' | 'failed' | 'canceled'
  runSyncUpdatedAt: string | null
  lastCompletedChapter?: string | null
}

export type StoryWorkspace = {
  storyId: string
  title: string
  premise: string
  style: string | null
  updatedAt: string | null
  localOnly?: boolean
  nodes: WorkspaceNode[]
  activeNodeId: string | null
  contentByNodeId: Record<string, string>
  assistantThread: WorkspaceAssistantMessage[]
  runBridge?: WorkspaceRunBridge
}

export type WorkspaceReference = {
  premise: string
  outline: Array<Record<string, unknown>>
  characters: Array<Record<string, unknown>>
  worldRules: Array<Record<string, unknown>>
  timeline: Array<Record<string, unknown>>
  relationshipState: Array<Record<string, unknown>>
  foreshadowLedger: Array<Record<string, unknown>>
}
