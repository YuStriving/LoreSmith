import type { Story } from '../../lib/types/api'
import { StoryCard } from './StoryCard'

type StoryListProps = {
  stories: Array<Story & {
    teaser: string
    genre: string
    stats: {
      words: number
      chapters: number
    }
  }>
  onRequestDelete: (story: Story) => void
  deletingStoryId?: string | null
}

export function StoryList({ stories, onRequestDelete, deletingStoryId }: StoryListProps) {
  return (
    <div className='story-grid'>
      {stories.map((story) => (
        <StoryCard key={story.storyId} story={story} onRequestDelete={onRequestDelete} isDeleting={deletingStoryId === story.storyId} />
      ))}
    </div>
  )
}
