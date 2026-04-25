import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { fetchStories, buildStoryDraft, deleteStory } from '../lib/api/stories'
import { StoryList } from '../features/stories/StoryList'
import type { Story } from '../lib/types/api'
import './pages.css'

export function StoriesPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [pendingDeleteStory, setPendingDeleteStory] = useState<Story | null>(null)
  const storiesQuery = useQuery({ queryKey: ['stories'], queryFn: fetchStories })
  const deleteMutation = useMutation({
    mutationFn: deleteStory,
    onSuccess: (result) => {
      setPendingDeleteStory(null)
      queryClient.setQueryData<Story[] | undefined>(['stories'], (current) =>
        current?.filter((item) => item.storyId !== result.storyId) ?? current,
      )
      void queryClient.invalidateQueries({ queryKey: ['stories'] })
    },
    onError: () => {
      window.alert('删除作品失败，请稍后重试。')
    },
  })

  const stories = useMemo(() => {
    const items = buildStoryDraft(storiesQuery.data ?? [])
    return items.filter((item) => item.title.includes(search) || item.premise.includes(search))
  }, [search, storiesQuery.data])

  return (
    <section className='stories-page'>
      <div className='stories-page__hero'>
        <div className='stories-page__header'>
          <div>
            <h1 className='section-title'>我的作品</h1>
            <p>管理和浏览你的所有小说</p>
          </div>
          <button className='primary-button' onClick={() => navigate('/stories/new')}>
            <span>＋</span>
            新建作品
          </button>
        </div>

        <div className='stories-toolbar'>
          <input className='input stories-toolbar__search' value={search} onChange={(event) => setSearch(event.target.value)} placeholder='搜索作品...' />
          <div className='stories-toolbar__filters'>
            <button className='stories-tab is-active'>全部</button>
            <button className='stories-tab'>创作中</button>
            <button className='stories-tab'>已完结</button>
            <button className='stories-tab'>草稿</button>
          </div>
        </div>
      </div>

      {storiesQuery.isLoading ? <div className='panel page-empty'>正在加载作品...</div> : null}
      {storiesQuery.isError ? <div className='panel page-empty'>作品列表加载失败，请确认 Java API 已启动。</div> : null}
      {!storiesQuery.isLoading && !storiesQuery.isError && (
        <StoryList
          stories={stories}
          deletingStoryId={deleteMutation.isPending ? deleteMutation.variables : null}
          onRequestDelete={(story) => {
            setPendingDeleteStory(story)
          }}
        />
      )}

      {pendingDeleteStory ? (
        <div className='stories-dialog-backdrop' onClick={() => !deleteMutation.isPending && setPendingDeleteStory(null)}>
          <div className='stories-dialog panel' onClick={(event) => event.stopPropagation()}>
            <div className='stories-dialog__header'>
              <h3>删除作品？</h3>
            </div>
            <div className='stories-dialog__body'>
              <p className='stories-dialog__danger'>确定要删除《{pendingDeleteStory.title}》吗？此操作不可撤销。</p>
            </div>
            <div className='stories-dialog__actions'>
              <button className='secondary-button' type='button' disabled={deleteMutation.isPending} onClick={() => setPendingDeleteStory(null)}>
                取消
              </button>
              <button
                className='primary-button primary-button--small stories-dialog__confirm'
                type='button'
                disabled={deleteMutation.isPending}
                onClick={() => {
                  if (!pendingDeleteStory.storyId) {
                    return
                  }
                  deleteMutation.mutate(pendingDeleteStory.storyId)
                }}
              >
                {deleteMutation.isPending ? '删除中...' : '删除作品'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}
