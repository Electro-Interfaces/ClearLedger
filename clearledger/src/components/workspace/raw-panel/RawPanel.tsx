import { useRef, useEffect, useMemo } from 'react'
import { Loader2 } from 'lucide-react'
import { useRawPanelState } from './useRawPanelState'
import { useRawPanelTree, buildVisibleList } from './useRawPanelTree'
import { useRawPanelKeyboard } from './useRawPanelKeyboard'
import { RawPanelAddressBar } from './RawPanelAddressBar'
import { RawPanelToolbar } from './RawPanelToolbar'
import { RawPanelTree } from './RawPanelTree'
import { RawPanelFileList } from './RawPanelFileList'
import { RawPanelDetailsPane } from './RawPanelDetailsPane'
import { RawPanelTabs } from './RawPanelTabs'
import { RawPanelStatusBar } from './RawPanelStatusBar'
import { RawPanelFilterDialog } from './RawPanelFilterDialog'
import { ShiftDetailModal } from '@/components/shift-reports/ShiftDetailModal'
import { DeliveryDetailModal } from '@/components/shift-reports/DeliveryDetailModal'

interface Props {
  hideHeader?: boolean
  collapseButton?: React.ReactNode
}

export function RawPanel({ collapseButton }: Props) {
  const state = useRawPanelState()
  const tree = useRawPanelTree(state.filters, state.sortConfig)
  const containerRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Build visible nodes for keyboard navigation (tree mode only)
  const visibleNodes = useMemo(
    () => state.viewMode === 'tree'
      ? buildVisibleList(tree.fsTree, state.treeState.expandedPaths)
      : tree.flatFiles.map((node) => ({ node, depth: 0 })),
    [state.viewMode, tree.fsTree, state.treeState.expandedPaths, tree.flatFiles],
  )

  useRawPanelKeyboard({
    state,
    visibleNodes,
    containerRef,
    searchInputRef,
    onRefresh: tree.handleRefresh,
  })

  // Restore scroll position on mount
  useEffect(() => {
    if (scrollRef.current && state.treeState.scrollTop > 0) {
      scrollRef.current.scrollTop = state.treeState.scrollTop
    }
  }, [])

  // Item count based on view mode
  const displayCount = state.viewMode === 'tree'
    ? tree.totalItemCount
    : tree.flatFiles.length

  return (
    <div
      className="flex flex-col h-full"
      ref={containerRef}
      tabIndex={0}
    >
      {/* Address Bar */}
      <RawPanelAddressBar
        currentPath={state.currentPath}
        onNavigate={state.navigateTo}
        onGoUp={state.goUp}
        viewMode={state.viewMode}
        collapseButton={collapseButton}
      />

      {/* Toolbar */}
      <RawPanelToolbar
        state={state}
        isFetching={tree.isFetching}
        onRefresh={tree.handleRefresh}
      />

      {/* Content area */}
      <div
        className="flex-1 overflow-y-auto min-h-0 scroll-thin"
        ref={scrollRef}
        onScroll={(e) => state.saveScrollPosition(e.currentTarget.scrollTop)}
      >
        {tree.isLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : state.viewMode === 'tree' ? (
          <RawPanelTree
            state={state}
            fsTree={tree.fsTree}
            onRefresh={tree.handleRefresh}
          />
        ) : (
          <RawPanelFileList
            state={state}
            flatFiles={tree.flatFiles}
            onRefresh={tree.handleRefresh}
          />
        )}
      </div>

      {/* Details pane — closeable */}
      <RawPanelDetailsPane node={state.selectedNode} onClose={() => state.setSelectedNode(null)} />

      {/* Open tabs */}
      <RawPanelTabs
        tabs={state.openTabs}
        activeId={state.activeTabId}
        onSwitch={state.switchTab}
        onClose={state.closeTab}
      />

      {/* Status bar */}
      <RawPanelStatusBar
        count={displayCount}
        dataUpdatedAt={tree.dataUpdatedAt}
      />

      {/* Filter dialog */}
      <RawPanelFilterDialog
        state={state}
        flatFiles={tree.flatFiles}
        totalCount={tree.totalItemCount}
      />

      {/* Modals */}
      <ShiftDetailModal shift={state.viewingShift} onClose={() => state.setViewingShift(null)} />
      <DeliveryDetailModal delivery={state.viewingDelivery} onClose={() => state.setViewingDelivery(null)} />
    </div>
  )
}
