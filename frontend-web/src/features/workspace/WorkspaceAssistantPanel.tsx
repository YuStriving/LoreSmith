import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import type { AwaitingConfirmation, StoryWorkspace, WorkspaceReference } from '../../lib/types/api'

type WorkspaceAssistantPanelProps = {
  mode: 'run' | 'workspace'
  workspace: StoryWorkspace
  reference: WorkspaceReference
  selectedNodeId: string | null
  tab: 'assistant' | 'reference'
  onTabChange: (tab: 'assistant' | 'reference') => void
  isPending: boolean
  streamingText?: string
  streamingRunText?: string
  awaitingConfirmation?: AwaitingConfirmation | null
  onSubmit: (instruction: string) => Promise<void>
  onContinueRun: () => Promise<void>
  onSaveReference: () => Promise<void>
  onRefreshReference: () => Promise<void>
  runStatus?: string | null
  isContinuingRun?: boolean
}

function readText(value: unknown, fallback = '未提供') {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || fallback
}

function ReferenceSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className='workspace-reference-section is-active'>
      <div className='workspace-reference-section__header'>
        <strong>{title}</strong>
      </div>
      <div className='workspace-sidecard workspace-sidecard--reference'>{children}</div>
    </section>
  )
}

function EmptyReference({ text }: { text: string }) {
  return <p className='workspace-reference-empty'>{text}</p>
}

export function WorkspaceAssistantPanel({
  mode,
  workspace,
  reference,
  selectedNodeId,
  tab,
  onTabChange,
  isPending,
  streamingText = '',
  streamingRunText = '',
  awaitingConfirmation,
  onSubmit,
  onContinueRun,
  onSaveReference,
  onRefreshReference,
  runStatus,
  isContinuingRun = false,
}: WorkspaceAssistantPanelProps) {
  const [instruction, setInstruction] = useState('')
  const navigate = useNavigate()

  const latestAssistant = useMemo(() => {
    if (streamingText.trim()) {
      return streamingText
    }
    return [...workspace.assistantThread].reverse().find((message) => message.role === 'assistant')?.content ?? ''
  }, [streamingText, workspace.assistantThread])

  const canContinueRun = Boolean(workspace.runBridge?.activeRunId && (awaitingConfirmation || runStatus === 'idle'))

  return (
    <aside className='workspace-assistant panel'>
      <div className='assistant-panel__header'>
        <h2>{mode === 'workspace' ? 'AI 润色' : '作品资料'}</h2>
      </div>

      <div className='workspace-tabs'>
        <button type='button' className={`workspace-tab ${tab === 'assistant' ? 'is-active' : ''}`} onClick={() => onTabChange('assistant')}>
          AI 润色
        </button>
        <button type='button' className={`workspace-tab ${tab === 'reference' ? 'is-active' : ''}`} onClick={() => onTabChange('reference')}>
          作品资料
        </button>
      </div>

      {tab === 'assistant' ? (
        <>
          <div className='workspace-assistant__notice'>
            {mode === 'workspace' ? '针对当前章节提出修改要求，AI 会直接改写中间正文。' : 'Run 模式下此区域展示生成过程，不会直接写入当前编辑区。'}
          </div>

          <div className='workspace-assistant__thread'>
            {workspace.assistantThread.map((message) => (
              <div key={message.id} className={`workspace-message workspace-message--${message.role}`}>
                <div className='workspace-message__role'>{message.role === 'assistant' ? 'AI' : message.role === 'user' ? '你' : '系统'}</div>
                <div className='workspace-message__content'>{message.content}</div>
              </div>
            ))}
            {streamingText ? (
              <div className='workspace-message workspace-message--assistant'>
                <div className='workspace-message__role'>AI</div>
                <div className='workspace-message__content'>{latestAssistant}</div>
              </div>
            ) : null}
            {mode === 'run' && streamingRunText ? (
              <div className='workspace-message workspace-message--assistant'>
                <div className='workspace-message__role'>生成中</div>
                <div className='workspace-message__content'>{streamingRunText}</div>
              </div>
            ) : null}
          </div>

          <div className='assistant-panel__composer'>
            <input
              className='input assistant-panel__input'
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              placeholder='例如：压缩开头节奏并强化人物心理'
              disabled={mode !== 'workspace' || isPending || !selectedNodeId}
            />
            <button
              className='assistant-panel__send'
              type='button'
              disabled={mode !== 'workspace' || isPending || !selectedNodeId}
              onClick={async () => {
                await onSubmit(instruction)
                setInstruction('')
              }}
            >
              ✦
            </button>
          </div>
        </>
      ) : null}

      {tab === 'reference' ? (
        <div className='workspace-panel-list'>
          <ReferenceSection title='作品设定'>
            <p>{readText(reference.premise, '暂无作品设定')}</p>
            <button type='button' className='primary-button primary-button--small workspace-reference-entry' onClick={() => navigate(`/stories/${workspace.storyId}/reference`)}>
              展开作品资料
            </button>
          </ReferenceSection>

          <ReferenceSection title='大纲'>
            {reference.outline.length ? (
              <div className='workspace-reference-list'>
                {reference.outline.slice(0, 4).map((item, index) => (
                  <div key={`outline-${index}`} className='workspace-reference-item'>
                    <strong>{readText(item.chapter, `第 ${index + 1} 章`)} {typeof item.title === 'string' && item.title.trim() ? `· ${item.title.trim()}` : ''}</strong>
                    <p>{readText(item.core_event, '暂无核心事件')}</p>
                    {typeof item.hook === 'string' && item.hook.trim() ? <span>{item.hook.trim()}</span> : null}
                  </div>
                ))}
              </div>
            ) : (
              <EmptyReference text='暂无大纲信息。' />
            )}
          </ReferenceSection>

          <ReferenceSection title='人物'>
            {reference.characters.length ? (
              <div className='character-list workspace-reference-characters'>
                {reference.characters.slice(0, 4).map((item, index) => (
                  <div key={`character-${index}`} className='character-card workspace-reference-character-card'>
                    <strong>{readText(item.name, `人物 ${index + 1}`)}</strong>
                    <span>{readText(item.role, '未标注角色定位')}</span>
                    <p>{readText(item.description, '暂无人物描述')}</p>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyReference text='暂无人物资料。' />
            )}
          </ReferenceSection>

          <ReferenceSection title='世界设定'>
            {reference.worldRules.length ? (
              <div className='workspace-reference-list'>
                {reference.worldRules.map((item, index) => (
                  <div key={`world-${index}`} className='workspace-reference-item'>
                    <strong>{readText(item.category, `规则 ${index + 1}`)}</strong>
                    <p>{readText(item.rule, '暂无规则说明')}</p>
                    {typeof item.boundary === 'string' && item.boundary.trim() ? <span>{item.boundary.trim()}</span> : null}
                  </div>
                ))}
              </div>
            ) : (
              <EmptyReference text='暂无世界设定。' />
            )}
          </ReferenceSection>

          <ReferenceSection title='时间线'>
            {reference.timeline.length ? (
              <div className='workspace-reference-list'>
                {reference.timeline.map((item, index) => (
                  <div key={`timeline-${index}`} className='workspace-reference-item'>
                    <strong>{readText(item.time, `节点 ${index + 1}`)}</strong>
                    <p>{readText(item.event, '暂无事件说明')}</p>
                    {Array.isArray(item.characters) && item.characters.length ? <span>{item.characters.join('、')}</span> : null}
                  </div>
                ))}
              </div>
            ) : (
              <EmptyReference text='暂无时间线信息。' />
            )}
          </ReferenceSection>

          <ReferenceSection title='人物关系'>
            {reference.relationshipState.length ? (
              <div className='workspace-reference-list'>
                {reference.relationshipState.map((item, index) => (
                  <div key={`relationship-${index}`} className='workspace-reference-item'>
                    <strong>{readText(item.character_a, '角色A')} × {readText(item.character_b, '角色B')}</strong>
                    <p>{readText(item.relation, '暂无关系说明')}</p>
                    {item.chapter != null ? <span>章节：{String(item.chapter)}</span> : null}
                  </div>
                ))}
              </div>
            ) : (
              <EmptyReference text='暂无人物关系。' />
            )}
          </ReferenceSection>

          <ReferenceSection title='伏笔'>
            {reference.foreshadowLedger.length ? (
              <div className='workspace-reference-list'>
                {reference.foreshadowLedger.slice(0, 4).map((item, index) => (
                  <div key={`foreshadow-${index}`} className='workspace-reference-item'>
                    <strong>{readText(item.id, `伏笔 ${index + 1}`)}</strong>
                    <p>{readText(item.description, '暂无伏笔说明')}</p>
                    {typeof item.status === 'string' && item.status.trim() ? <span>状态：{item.status.trim()}</span> : null}
                  </div>
                ))}
              </div>
            ) : (
              <EmptyReference text='暂无伏笔信息。' />
            )}
          </ReferenceSection>

          <ReferenceSection title='运行状态'>
            <p>{isContinuingRun ? '继续写作请求已发出，正在等待新的流式输出。' : runStatus ? `当前状态：${runStatus}` : '当前暂无运行状态。'}</p>
          </ReferenceSection>

          <div className='workspace-assistant__actions workspace-assistant__actions--stack'>
            <button type='button' className='secondary-button' disabled={isPending} onClick={() => void onRefreshReference()}>
              刷新资料
            </button>
            <button type='button' className='secondary-button' disabled={isPending} onClick={() => void onSaveReference()}>
              保存资料
            </button>
            <button type='button' className='primary-button primary-button--small' disabled={isPending || !canContinueRun} onClick={() => void onContinueRun()}>
              继续编写
            </button>
          </div>

          {awaitingConfirmation ? (
            <ReferenceSection title='等待继续编写'>
              <strong>已写到第 {awaitingConfirmation.pauseAfterChapter} 章</strong>
              <p>当前已完成 {awaitingConfirmation.completedCount} 章，确认后将从第 {awaitingConfirmation.nextChapter} 章继续生成。</p>
            </ReferenceSection>
          ) : null}
        </div>
      ) : null}
    </aside>
  )
}
