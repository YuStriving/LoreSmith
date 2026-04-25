import { apiFetch } from './client'
import type { CreateStoryRequest, CreateStoryResponse, Story, StoryListResponse } from '../types/api'

export type DeleteStoryResponse = {
  storyId: string
  deleted: boolean
}

export async function fetchStories() {
  const data = await apiFetch<StoryListResponse>('/api/v1/stories')
  return data.items
}

export async function createStory(payload: CreateStoryRequest) {
  return apiFetch<CreateStoryResponse>('/api/v1/stories', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function deleteStory(storyId: string) {
  return apiFetch<DeleteStoryResponse>(`/api/v1/stories/${storyId}`, {
    method: 'DELETE',
  })
}

export function buildStoryDraft(stories: Story[]) {
  return stories.map((story, index) => ({
    ...story,
    teaser: story.premise || '借助 AI 继续扩写这个世界观与主线设定。',
    genre: story.style || ['科幻', '历史', '言情', '悬疑'][index % 4],
    stats: {
      words: 120 + index * 43,
      chapters: 1 + (index % 4),
    },
  }))
}
