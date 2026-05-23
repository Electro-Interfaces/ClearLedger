/**
 * LinkedDocsCompact — компактный блок связанных документов.
 * Показывает до 4 связанных документов как кликабельные чипы.
 */

import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { getLinksForEntry } from '@/services/linkService'
import { getEntry } from '@/services/dataEntryService'
import { resolveRole, BUNDLE_ROLE_LABELS } from '@/services/bundleService'
import { Badge } from '@/components/ui/badge'
import type { DataEntry, DocumentLink } from '@/types'

interface LinkedDocsCompactProps {
  entry: DataEntry
}

const MAX_VISIBLE = 4

const LINK_TYPE_LABELS: Record<string, string> = {
  'subordinate': 'Подчинённый',
  'related': 'Связанный',
  'email-attachment': 'Вложение',
  'duplicate': 'Дубликат',
  'correction': 'Исправление',
  'manual': 'Связь',
}

interface LinkedDoc {
  entry: DataEntry
  link: DocumentLink
}

export function LinkedDocsCompact({ entry }: LinkedDocsCompactProps) {
  const { companyId } = useCompany()

  const { data: linkedDocs = [] } = useQuery({
    queryKey: ['linked-docs-compact', companyId, entry.id],
    queryFn: async () => {
      const links = await getLinksForEntry(entry.id)
      if (links.length === 0) return []

      const results: LinkedDoc[] = []
      for (const link of links) {
        const otherId = link.sourceEntryId === entry.id ? link.targetEntryId : link.sourceEntryId
        const other = await getEntry(companyId, otherId)
        if (other) results.push({ entry: other, link })
      }
      return results
    },
    staleTime: 30_000,
  })

  if (linkedDocs.length === 0) return null

  const visible = linkedDocs.slice(0, MAX_VISIBLE)
  const remaining = linkedDocs.length - MAX_VISIBLE

  return (
    <div className="space-y-1.5">
      <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Связанные</h4>
      <div className="flex flex-wrap gap-1.5">
        {visible.map(({ entry: linked, link }) => {
          const role = resolveRole(linked.docTypeId)
          const roleLabel = BUNDLE_ROLE_LABELS[role]
          const linkLabel = LINK_TYPE_LABELS[link.type] || link.type
          const shortTitle = linked.title.length > 25
            ? linked.title.slice(0, 25) + '…'
            : linked.title

          return (
            <Link
              key={linked.id}
              to={`/data/${linked.categoryId}/${linked.id}`}
              className="no-underline"
            >
              <Badge
                variant="outline"
                className="cursor-pointer hover:bg-accent transition-colors text-xs gap-1 py-0.5"
                title={`${linkLabel}: ${linked.title} (${roleLabel})`}
              >
                <span className="text-muted-foreground">{roleLabel}</span>
                <span className="truncate max-w-[120px]">{shortTitle}</span>
              </Badge>
            </Link>
          )
        })}
        {remaining > 0 && (
          <Badge variant="secondary" className="text-xs py-0.5">
            +{remaining} ещё
          </Badge>
        )}
      </div>
    </div>
  )
}
