import { useNavigate } from 'react-router-dom'
import type { Story } from '../../lib/types/api'
import { formatDate } from '../../lib/utils/format'

type StoryCardProps = {
  story: Story & {
    teaser: string
    genre: string
    stats: {
      words: number
      chapters: number
    }
  }
  onRequestDelete: (story: Story) => void
  isDeleting?: boolean
}

export function StoryCard({ story, onRequestDelete, isDeleting = false }: StoryCardProps) {
  const navigate = useNavigate()

  return (
    <article className='story-card panel' onClick={() => navigate(story.storyId ? `/stories/${story.storyId}/workspace` : '/stories/new')}>
      <div className='story-card__cover'>
        <button
          type='button'
          className='story-card__delete'
          disabled={isDeleting}
          onClick={(event) => {
            event.stopPropagation()
            if (!story.storyId) {
              return
            }
            onRequestDelete(story)
          }}
        >
          {isDeleting ? '删除中' : '删除'}
        </button>
        <span className='status-badge'>{story.latestRunId ? '创作中' : '草稿'}</span>
        <div className='story-card__book'>📖</div>
      </div>
      <div className='story-card__body'>
        <h3>{story.title}</h3>
        <span className='story-card__genre'>{story.genre}</span>
        <p>{story.teaser}</p>
        <div className='story-card__meta'>
          <span>{story.stats.words} 字</span>
          <span>{story.stats.chapters} 章</span>
          <span>{formatDate(story.createdAt)}</span>
        </div>
      </div>
    </article>
  )
}
