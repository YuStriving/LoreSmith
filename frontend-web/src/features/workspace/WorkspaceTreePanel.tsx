import type { StoryWorkspace, WorkspaceNode, WorkspaceNodeType } from '../../lib/types/api'

type WorkspaceTreePanelProps = {
  workspace: StoryWorkspace
  activeNodeId: string | null
  onSelect: (nodeId: string) => void
  onCreateNode: (parentId: string | null, type: WorkspaceNodeType) => void
}

const typeLabel: Record<WorkspaceNodeType, string> = {
  volume: '卷',
  chapter: '章',
}

function renderNode(
  node: WorkspaceNode,
  nodes: WorkspaceNode[],
  activeNodeId: string | null,
  onSelect: (nodeId: string) => void,
  onCreateNode: (parentId: string | null, type: WorkspaceNodeType) => void,
): JSX.Element {
  const chapters = nodes.filter((item) => item.parentId === node.id && item.type === 'chapter').sort((a, b) => a.order - b.order)

  return (
    <div key={node.id} className='workspace-tree__branch'>
      <button type='button' className={`workspace-tree__node ${activeNodeId === node.id ? 'is-active' : ''}`} onClick={() => onSelect(node.id)}>
        <span className='workspace-tree__node-type'>{typeLabel[node.type]}</span>
        <span className='workspace-tree__node-title'>{node.title}</span>
      </button>
      {chapters.length > 0 ? (
        <div className='workspace-tree__children'>
          {chapters.map((chapter) => (
            <button
              key={chapter.id}
              type='button'
              className={`workspace-tree__node ${activeNodeId === chapter.id ? 'is-active' : ''}`}
              style={{ paddingLeft: '34px' }}
              onClick={() => onSelect(chapter.id)}
            >
              <span className='workspace-tree__node-type'>{typeLabel.chapter}</span>
              <span className='workspace-tree__node-title'>{chapter.title}</span>
            </button>
          ))}
        </div>
      ) : null}
      {activeNodeId === node.id && node.type === 'volume' ? (
        <div className='workspace-tree__actions' style={{ marginLeft: '16px' }}>
          <button type='button' className='workspace-tree__add' onClick={() => onCreateNode(node.id, 'chapter')}>
            + 新建章
          </button>
        </div>
      ) : null}
    </div>
  )
}

export function WorkspaceTreePanel({ workspace, activeNodeId, onSelect, onCreateNode }: WorkspaceTreePanelProps) {
  const roots = workspace.nodes.filter((node) => node.parentId === null && node.type === 'volume').sort((a, b) => a.order - b.order)
  const counts = {
    volumes: workspace.nodes.filter((node) => node.type === 'volume').length,
    chapters: workspace.nodes.filter((node) => node.type === 'chapter').length,
  }

  return (
    <aside className='workspace-sidebar panel'>
      <div className='workspace-sidebar__header'>
        <div>
          <div className='workspace-sidebar__eyebrow'>共享工作台</div>
          <h2>{workspace.title}</h2>
        </div>
        <button type='button' className='field__link' onClick={() => onCreateNode(null, 'volume')}>
          + 新建卷
        </button>
      </div>

      <div className='workspace-sidebar__meta workspace-sidebar__meta--stack'>
        <span>{counts.volumes} 卷</span>
        <span>{counts.chapters} 章</span>
        <span>{workspace.localOnly ? '本地草稿模式' : '云端工作台'}</span>
      </div>

      <div className='workspace-tree'>
        {roots.map((node) => renderNode(node, workspace.nodes, activeNodeId, onSelect, onCreateNode))}
      </div>
    </aside>
  )
}
