import { FileText, Fuel, ChevronUp, ChevronDown } from 'lucide-react'
import { RawPanelContextMenu } from './RawPanelContextMenu'
import type { FsNode, SortColumn } from './raw-panel-types'
import type { RawPanelState } from './useRawPanelState'

interface Props {
  state: RawPanelState
  flatFiles: FsNode[]
  onRefresh: () => void
}

function FileIcon({ node }: { node: FsNode }) {
  const isDelivery = node.docType === 'delivery' || node.name.includes('ТТН')
  return isDelivery
    ? <Fuel className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
    : <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
}

function StatusDot({ status }: { status?: string }) {
  if (!status) return null
  const isClosed = status === 'Закрыта'
  return (
    <span className="flex items-center gap-1 shrink-0">
      <span className={`h-1.5 w-1.5 rounded-full ${isClosed ? 'bg-emerald-500' : 'bg-amber-500'}`} />
      <span className="text-xs text-muted-foreground">
        {isClosed ? 'Закр.' : 'Откр.'}
      </span>
    </span>
  )
}

function SortArrow({ column, sortConfig }: { column: SortColumn; sortConfig: RawPanelState['sortConfig'] }) {
  if (sortConfig.column !== column) return null
  return sortConfig.direction === 'asc'
    ? <ChevronUp className="h-3 w-3 inline" />
    : <ChevronDown className="h-3 w-3 inline" />
}

function shortDate(dateStr?: string): string {
  if (!dateStr || dateStr === '—') return '—'
  // "03.04.2026 14:30" → "03.04"
  return dateStr.slice(0, 5)
}

export function RawPanelFileList({ state, flatFiles, onRefresh }: Props) {
  const { sortConfig, toggleSort, openFile, workspace, selectedNode } = state
  const { selectedStationId, selectedShiftNumber } = workspace

  function isSelected(node: FsNode): boolean {
    if (selectedNode?.path === node.path) return true
    if (node.shift && selectedShiftNumber === node.shift.shift && selectedStationId === node.stationId) return true
    return false
  }

  return (
    <div>
      {/* Column headers — Windows Explorer style */}
      <div className="flex items-center px-2 py-1 border-b border-border/40 bg-muted/20 text-xs font-medium text-muted-foreground uppercase tracking-wider select-none">
        <button
          onClick={() => toggleSort('name')}
          className="flex-1 flex items-center gap-0.5 hover:text-foreground transition-colors text-left"
        >
          Имя <SortArrow column="name" sortConfig={sortConfig} />
        </button>
        <button
          onClick={() => toggleSort('date')}
          className="w-14 flex items-center justify-end gap-0.5 hover:text-foreground transition-colors"
        >
          Дата <SortArrow column="date" sortConfig={sortConfig} />
        </button>
        <span className="w-14 text-right">Статус</span>
      </div>

      {/* File rows */}
      {flatFiles.length === 0 ? (
        <p className="text-xs text-muted-foreground text-center py-8">
          {state.filters.searchQuery ? 'Ничего не найдено' : 'Нет документов'}
        </p>
      ) : (
        flatFiles.map((node) => {
          const selected = isSelected(node)
          return (
            <RawPanelContextMenu key={node.path} node={node} onOpen={openFile} onRefresh={onRefresh}>
              <button
                onClick={() => openFile(node)}
                className={[
                  'w-full flex items-center gap-1.5 px-2 py-1 text-sm transition-colors',
                  'hover:bg-accent/40 border-b border-border/10',
                  selected && 'bg-primary/10 border-l-2 border-primary',
                  !selected && 'border-l-2 border-transparent',
                ].filter(Boolean).join(' ')}
              >
                <FileIcon node={node} />
                <span className={`flex-1 text-left truncate ${selected ? 'font-semibold text-primary' : 'font-medium'}`}>
                  {node.name}
                </span>
                <span className="w-14 text-right text-muted-foreground text-xs tabular-nums shrink-0">
                  {shortDate(node.date)}
                </span>
                <span className="w-14 flex justify-end shrink-0">
                  <StatusDot status={node.status} />
                </span>
              </button>
            </RawPanelContextMenu>
          )
        })
      )}
    </div>
  )
}
