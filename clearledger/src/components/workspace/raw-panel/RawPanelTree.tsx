import { useMemo } from 'react'
import { ChevronRight, Folder, FolderOpen, FileText, Fuel } from 'lucide-react'
import { RawPanelContextMenu } from './RawPanelContextMenu'
import { buildVisibleList } from './useRawPanelTree'
import type { FsNode } from './raw-panel-types'
import type { RawPanelState } from './useRawPanelState'

interface Props {
  state: RawPanelState
  fsTree: Map<string, FsNode[]>
  onRefresh: () => void
}

function NodeIcon({ node, isExpanded }: { node: FsNode; isExpanded: boolean }) {
  if (node.type === 'folder') {
    return isExpanded
      ? <FolderOpen className="h-3.5 w-3.5 text-amber-500 shrink-0" />
      : <Folder className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
  }
  if (node.docType === 'delivery' || node.name.includes('ТТН')) {
    return <Fuel className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
  }
  return <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
}

function StatusDot({ status }: { status?: string }) {
  if (!status) return null
  const isClosed = status === 'Закрыта'
  return (
    <span
      className={`h-1.5 w-1.5 rounded-full shrink-0 ${
        isClosed ? 'bg-emerald-500' : 'bg-amber-500'
      }`}
      title={status}
    />
  )
}

export function RawPanelTree({ state, fsTree, onRefresh }: Props) {
  const { treeState, isExpanded, toggleExpanded, openFile, workspace, selectedNode, focusedPath } = state
  const { selectedStationId, selectedShiftNumber } = workspace

  const visibleNodes = useMemo(
    () => buildVisibleList(fsTree, treeState.expandedPaths),
    [fsTree, treeState.expandedPaths],
  )

  function handleClick(node: FsNode) {
    if (node.type === 'folder') {
      toggleExpanded(node.path)
    } else {
      openFile(node)
    }
  }

  function isSelected(node: FsNode): boolean {
    if (node.type !== 'file') return false
    // Selected via tab or workspace selection
    if (selectedNode?.path === node.path) return true
    if (node.shift && selectedShiftNumber === node.shift.shift && selectedStationId === node.stationId) return true
    return false
  }

  return (
    <div role="tree" aria-label="Проводник документов">
      {visibleNodes.length === 0 && (
        <p className="text-xs text-muted-foreground text-center py-8">Нет данных</p>
      )}
      {visibleNodes.map(({ node, depth }) => {
        const isFolder = node.type === 'folder'
        const expanded = isFolder && isExpanded(node.path)
        const selected = isSelected(node)
        const focused = focusedPath === node.path

        return (
          <RawPanelContextMenu key={node.path} node={node} onOpen={handleClick} onRefresh={onRefresh}>
            <button
              role="treeitem"
              aria-expanded={isFolder ? expanded : undefined}
              aria-level={depth + 1}
              aria-selected={selected}
              data-path={node.path}
              onClick={() => handleClick(node)}
              className={[
                'w-full flex items-center gap-1.5 py-1 pr-2 text-sm transition-colors',
                'hover:bg-accent/40',
                selected && 'bg-primary/10 border-l-2 border-primary',
                !selected && 'border-l-2 border-transparent',
                focused && 'ring-1 ring-ring ring-inset',
              ].filter(Boolean).join(' ')}
              style={{ paddingLeft: `${depth * 16 + 8}px` }}
            >
              {/* Chevron for folders */}
              {isFolder ? (
                <ChevronRight
                  className={`h-3 w-3 text-muted-foreground shrink-0 transition-transform duration-150 ${
                    expanded ? 'rotate-90' : ''
                  }`}
                />
              ) : (
                <span className="w-3 shrink-0" />
              )}

              {/* Icon */}
              <NodeIcon node={node} isExpanded={expanded} />

              {/* Name */}
              <span
                className={`truncate text-left flex-1 ${
                  selected ? 'font-semibold text-primary' : isFolder ? 'font-medium' : ''
                }`}
              >
                {node.name}
              </span>

              {/* Status dot for files */}
              {!isFolder && <StatusDot status={node.status} />}

              {/* Child count for folders */}
              {isFolder && node.childCount != null && (
                <span className="text-xs text-muted-foreground/50 ml-auto shrink-0 tabular-nums">
                  ({node.childCount})
                </span>
              )}
            </button>
          </RawPanelContextMenu>
        )
      })}
    </div>
  )
}
