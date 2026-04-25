import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { StoryCreateForm } from '../features/stories/StoryCreateForm'
import { createStory } from '../lib/api/stories'
import { startWorkspaceRun } from '../lib/api/workspace'
import type { CreateStoryRequest } from '../lib/types/api'
import './pages.css'

export function NewStoryPage() {
  const navigate = useNavigate()

  const createMutation = useMutation({
    mutationFn: async (payload: CreateStoryRequest) => {
      const story = await createStory(payload)
      await startWorkspaceRun(
        payload.storyId,
        payload.prompt,
        {
          storyId: payload.storyId,
          title: payload.title,
          premise: payload.premise,
          style: payload.style ?? 'default',
          updatedAt: null,
          localOnly: false,
          nodes: [],
          activeNodeId: null,
          contentByNodeId: {},
          assistantThread: [],
          runBridge: {
            activeRunId: payload.runId,
            runAfterSeq: 0,
            runSyncStatus: 'running',
            runSyncUpdatedAt: null,
            lastCompletedChapter: null,
          },
        },
        {
          premise: payload.premise,
          outline: [],
          characters: payload.characters ?? [],
          worldRules: [],
          timeline: [],
          relationshipState: [],
          foreshadowLedger: [],
        },
      )
      return story
    },
    onSuccess: (data) => {
      navigate(`/stories/${data.storyId}/workspace`)
    },
  })

  return (
    <section className='creation-onboarding-page'>
      <div className='creation-onboarding'>
        <div className='creation-onboarding__logo'>✎</div>
        <h1>新建小说</h1>
        <p>填写基本信息，AI 将为你量身构建创作环境</p>
        <div className='creation-onboarding__card panel'>
          <StoryCreateForm
            onSubmit={async (payload: CreateStoryRequest) => {
              await createMutation.mutateAsync(payload)
            }}
            isSubmitting={createMutation.isPending}
          />
          {createMutation.isError ? <div className='assistant-panel__error'>创建失败，请检查后端接口是否已启动。</div> : null}
        </div>
      </div>
    </section>
  )
}
