import { useMemo, useState } from 'react'
import { Globe, Ruler, Users } from 'lucide-react'
import type { CreateStoryRequest } from '../../lib/types/api'

type StoryCreateFormProps = {
  onSubmit: (payload: CreateStoryRequest) => Promise<void>
  isSubmitting: boolean
  onTitleChange?: (value: string) => void
  onPromptChange?: (value: string) => void
}

type CharacterDraft = {
  id: string
  name: string
  role: string
  description: string
}

const genres = [
  { value: 'fantasy', label: '奇幻' },
  { value: 'scifi', label: '科幻' },
  { value: 'romance', label: '言情' },
  { value: 'mystery', label: '悬疑' },
  { value: 'historical', label: '历史' },
  { value: 'urban', label: '都市' },
]

const styles = [
  { value: 'literary', label: '文学性' },
  { value: 'light', label: '轻松' },
  { value: 'dramatic', label: '戏剧化' },
  { value: 'poetic', label: '诗意' },
]

export function StoryCreateForm({ onSubmit, isSubmitting, onTitleChange, onPromptChange }: StoryCreateFormProps) {
  const [title, setTitle] = useState('')
  const [genre, setGenre] = useState('')
  const [style, setStyle] = useState('')
  const [genreOpen, setGenreOpen] = useState(false)
  const [styleOpen, setStyleOpen] = useState(false)
  const [worldSetting, setWorldSetting] = useState('')
  const [synopsis, setSynopsis] = useState('写一部充满悬念与情绪张力的长篇小说，从第一章开始创作。')
  const [characters, setCharacters] = useState<CharacterDraft[]>([])
  const [minWords, setMinWords] = useState(1200)
  const [targetWords, setTargetWords] = useState(1800)
  const [maxWords, setMaxWords] = useState(2600)

  const ids = useMemo(
    () => ({
      storyId: crypto.randomUUID(),
      runId: crypto.randomUUID(),
    }),
    [],
  )

  const addCharacter = () => {
    setCharacters((current) => [...current, { id: crypto.randomUUID(), name: '', role: '', description: '' }])
  }

  const updateCharacter = (index: number, field: keyof CharacterDraft, value: string) => {
    setCharacters((current) =>
      current.map((character, currentIndex) =>
        currentIndex === index ? { ...character, [field]: value } : character,
      ),
    )
  }

  const removeCharacter = (index: number) => {
    setCharacters((current) => current.filter((_, currentIndex) => currentIndex !== index))
  }

  return (
    <form
      className='creation-sidebar__form'
      onSubmit={async (event) => {
        event.preventDefault()
        await onSubmit({
          storyId: ids.storyId,
          runId: ids.runId,
          title,
          premise: worldSetting,
          genre,
          style,
          characters: characters
            .map((character) => ({
              name: character.name.trim(),
              role: character.role.trim(),
              description: character.description.trim(),
            }))
            .filter((character) => character.name),
          wordCount: {
            minWords: Math.max(200, minWords),
            targetWords: Math.max(Math.max(200, minWords), targetWords),
            maxWords: Math.max(Math.max(200, minWords, targetWords), maxWords),
          },
          prompt: synopsis,
          configPath: 'dev_config.json',
        })
      }}
    >
      <label className='field'>
        <span>作品标题</span>
        <input
          className='input'
          value={title}
          onChange={(event) => {
            setTitle(event.target.value)
            onTitleChange?.(event.target.value)
          }}
          placeholder='为你的小说取个名字...'
          required
        />
      </label>

      <div className='field-row'>
        <div className='field'>
          <span>题材</span>
          <div className={`select-wrap ${genreOpen ? 'is-open' : ''}`}>
            <button
              className='select-button'
              type='button'
              onClick={() => {
                setGenreOpen((current) => !current)
                setStyleOpen(false)
              }}
            >
              <span>{genres.find((item) => item.value === genre)?.label ?? '选择题材'}</span>
            </button>
            {genreOpen ? (
              <div className='select-menu'>
                {genres.map((item) => (
                  <button
                    key={item.value}
                    className={`select-menu__item ${genre === item.value ? 'is-selected' : ''}`}
                    type='button'
                    onClick={() => {
                      setGenre(item.value)
                      setGenreOpen(false)
                    }}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        <div className='field'>
          <span>风格</span>
          <div className={`select-wrap ${styleOpen ? 'is-open' : ''}`}>
            <button
              className='select-button'
              type='button'
              onClick={() => {
                setStyleOpen((current) => !current)
                setGenreOpen(false)
              }}
            >
              <span>{styles.find((item) => item.value === style)?.label ?? '选择风格'}</span>
            </button>
            {styleOpen ? (
              <div className='select-menu'>
                {styles.map((item) => (
                  <button
                    key={item.value}
                    className={`select-menu__item ${style === item.value ? 'is-selected' : ''}`}
                    type='button'
                    onClick={() => {
                      setStyle(item.value)
                      setStyleOpen(false)
                    }}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <label className='field'>
        <div className='field__label-group'>
          <Globe size={14} className='field__icon' />
          <span>世界观设定</span>
        </div>
        <textarea
          className='textarea textarea--compact'
          value={worldSetting}
          onChange={(event) => setWorldSetting(event.target.value)}
          placeholder='描述你的世界设定...'
        />
      </label>

      <div className='field field--characters'>
        <div className='field__header'>
          <div className='field__label-group'>
            <Users size={14} className='field__icon' />
            <span>角色设定</span>
          </div>
          <button className='field__link' type='button' onClick={addCharacter}>
            + 添加角色
          </button>
        </div>
        <div className='character-list'>
          {characters.map((character, index) => (
            <div key={character.id} className='character-card'>
              <button className='character-card__remove' type='button' onClick={() => removeCharacter(index)}>
                ×
              </button>
              <input
                className='input input--compact'
                value={character.name}
                onChange={(event) => updateCharacter(index, 'name', event.target.value)}
                placeholder='角色名'
              />
              <input
                className='input input--compact'
                value={character.role}
                onChange={(event) => updateCharacter(index, 'role', event.target.value)}
                placeholder='角色身份（如：主角、反派）'
              />
              <textarea
                className='textarea textarea--compact textarea--character'
                value={character.description}
                onChange={(event) => updateCharacter(index, 'description', event.target.value)}
                placeholder='简要描述...'
              />
            </div>
          ))}
        </div>
      </div>

      <div className='field'>
        <div className='field__label-group'>
          <Ruler size={14} className='field__icon' />
          <span>章节字数</span>
        </div>
        <div className='field-row'>
          <label className='field'>
            <span>最少</span>
            <input className='input input--compact' type='number' min={200} step={100} value={minWords} onChange={(event) => setMinWords(Number(event.target.value) || 200)} />
          </label>
          <label className='field'>
            <span>目标</span>
            <input className='input input--compact' type='number' min={200} step={100} value={targetWords} onChange={(event) => setTargetWords(Number(event.target.value) || 200)} />
          </label>
        </div>
        <label className='field'>
          <span>最多</span>
          <input className='input input--compact' type='number' min={200} step={100} value={maxWords} onChange={(event) => setMaxWords(Number(event.target.value) || 200)} />
        </label>
      </div>

      <label className='field'>
        <span>故事简介</span>
        <textarea
          className='textarea textarea--compact'
          value={synopsis}
          onChange={(event) => {
            setSynopsis(event.target.value)
            onPromptChange?.(event.target.value)
          }}
          placeholder='简要描述你的故事...'
          required
        />
      </label>

      <button className='primary-button' type='submit' disabled={isSubmitting}>
        {isSubmitting ? '创建中...' : '保存并开始创作'}
      </button>
    </form>
  )
}
