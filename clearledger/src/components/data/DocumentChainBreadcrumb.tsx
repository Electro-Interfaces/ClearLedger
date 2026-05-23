/**
 * DocumentChainBreadcrumb — хлебные крошки цепочки документов в бандле.
 * Показывает путь от корня до текущего документа: Договор №18 → СФ №128 → [Акт №52]
 */

import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { useBundleTree } from '@/hooks/useBundle'
import { isInBundle } from '@/services/bundleService'
import { BUNDLE_ROLE_LABELS, resolveRole } from '@/services/bundleService'
import type { DataEntry, BundleNode } from '@/types'

interface DocumentChainBreadcrumbProps {
  entry: DataEntry
}

/** Найти путь от корня до целевого узла */
function findPathToNode(node: BundleNode, targetId: string): BundleNode[] | null {
  if (node.entry.id === targetId) return [node]
  for (const child of node.children) {
    const path = findPathToNode(child, targetId)
    if (path) return [node, ...path]
  }
  return null
}

export function DocumentChainBreadcrumb({ entry }: DocumentChainBreadcrumbProps) {
  const { data: tree } = useBundleTree(entry.id)

  if (!isInBundle(entry) || !tree) return null

  const path = findPathToNode(tree.root, entry.id)
  if (!path || path.length <= 1) return null // не показываем если нет цепочки

  return (
    <nav className="flex items-center gap-1 text-sm flex-wrap">
      {path.map((node, idx) => {
        const isLast = idx === path.length - 1
        const role = resolveRole(node.entry.docTypeId)
        const roleLabel = BUNDLE_ROLE_LABELS[role]
        const shortTitle = node.entry.title.length > 30
          ? node.entry.title.slice(0, 30) + '…'
          : node.entry.title

        return (
          <span key={node.entry.id} className="flex items-center gap-1">
            {idx > 0 && <ChevronRight className="size-3.5 text-muted-foreground shrink-0" />}
            {isLast ? (
              <span className="font-medium text-foreground px-1.5 py-0.5 rounded bg-accent">
                {shortTitle}
              </span>
            ) : (
              <Link
                to={`/data/${node.entry.categoryId}/${node.entry.id}`}
                className="text-muted-foreground hover:text-foreground hover:underline transition-colors"
                title={`${roleLabel}: ${node.entry.title}`}
              >
                {shortTitle}
              </Link>
            )}
          </span>
        )
      })}
    </nav>
  )
}
