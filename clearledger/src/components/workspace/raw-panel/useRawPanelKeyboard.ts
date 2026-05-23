import { useEffect, useCallback, type RefObject } from 'react'
import type { FsNode } from './raw-panel-types'
import type { RawPanelState } from './useRawPanelState'

interface KeyboardOptions {
  state: RawPanelState
  visibleNodes: { node: FsNode; depth: number }[]
  containerRef: RefObject<HTMLDivElement | null>
  searchInputRef: RefObject<HTMLInputElement | null>
  onRefresh: () => void
}

export function useRawPanelKeyboard({
  state,
  visibleNodes,
  containerRef,
  searchInputRef,
  onRefresh,
}: KeyboardOptions) {
  const { focusedPath, setFocusedPath, isExpanded, toggleExpanded, openFile, goUp } = state

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // Don't handle if focus is in an input
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
      if (e.key === 'Escape') {
        (e.target as HTMLElement).blur()
        containerRef.current?.focus()
      }
      return
    }

    const currentIndex = focusedPath
      ? visibleNodes.findIndex((v) => v.node.path === focusedPath)
      : -1

    switch (e.key) {
      case 'ArrowDown': {
        e.preventDefault()
        const next = Math.min(currentIndex + 1, visibleNodes.length - 1)
        if (visibleNodes[next]) setFocusedPath(visibleNodes[next].node.path)
        // Scroll into view
        const el = containerRef.current?.querySelector(`[data-path="${CSS.escape(visibleNodes[next]?.node.path ?? '')}"]`)
        el?.scrollIntoView({ block: 'nearest' })
        break
      }
      case 'ArrowUp': {
        e.preventDefault()
        const prev = Math.max(currentIndex - 1, 0)
        if (visibleNodes[prev]) setFocusedPath(visibleNodes[prev].node.path)
        const el = containerRef.current?.querySelector(`[data-path="${CSS.escape(visibleNodes[prev]?.node.path ?? '')}"]`)
        el?.scrollIntoView({ block: 'nearest' })
        break
      }
      case 'ArrowRight': {
        e.preventDefault()
        if (currentIndex >= 0) {
          const node = visibleNodes[currentIndex].node
          if (node.type === 'folder' && !isExpanded(node.path)) {
            toggleExpanded(node.path)
          } else if (node.type === 'folder' && currentIndex + 1 < visibleNodes.length) {
            setFocusedPath(visibleNodes[currentIndex + 1].node.path)
          }
        }
        break
      }
      case 'ArrowLeft': {
        e.preventDefault()
        if (currentIndex >= 0) {
          const node = visibleNodes[currentIndex].node
          if (node.type === 'folder' && isExpanded(node.path)) {
            toggleExpanded(node.path)
          } else {
            // Move to parent folder
            const parentPath = node.path.split('/').slice(0, -1).join('/')
            const parentIndex = visibleNodes.findIndex((v) => v.node.path === parentPath)
            if (parentIndex >= 0) setFocusedPath(visibleNodes[parentIndex].node.path)
          }
        }
        break
      }
      case 'Enter': {
        e.preventDefault()
        if (currentIndex >= 0) {
          const node = visibleNodes[currentIndex].node
          if (node.type === 'folder') {
            toggleExpanded(node.path)
          } else {
            openFile(node)
          }
        }
        break
      }
      case 'Backspace': {
        e.preventDefault()
        goUp()
        break
      }
      case 'F5': {
        e.preventDefault()
        onRefresh()
        break
      }
      case 'f': {
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault()
          searchInputRef.current?.focus()
        }
        break
      }
    }
  }, [focusedPath, visibleNodes, state])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    container.addEventListener('keydown', handleKeyDown)
    return () => container.removeEventListener('keydown', handleKeyDown)
  }, [containerRef, handleKeyDown])
}
