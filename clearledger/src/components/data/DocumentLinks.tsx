/**
 * DocumentLinks — отображение связей документа с другими записями.
 * Показывает список связанных документов с типом связи и возможностью навигации.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { getLinksForEntry, createLink, removeLink } from '@/services/linkService'
import { getEntries } from '@/services/dataEntryService'
import type { DataEntry, DocumentLink, LinkType } from '@/types'
import { StatusBadge } from './StatusBadge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Link2, Mail, Copy, GitBranch, PenLine, X, Plus, FileText,
} from 'lucide-react'

const LINK_TYPE_CONFIG: Record<LinkType, { label: string; icon: typeof Link2; color: string }> = {
  'email-attachment': { label: 'Вложение', icon: Mail, color: 'text-blue-500' },
  'duplicate': { label: 'Дубликат', icon: Copy, color: 'text-amber-500' },
  'related': { label: 'Связан', icon: GitBranch, color: 'text-green-500' },
  'correction': { label: 'Исправление', icon: FileText, color: 'text-purple-500' },
  'manual': { label: 'Связь', icon: PenLine, color: 'text-gray-500' },
}

interface Props {
  entryId: string
  /** Показывать кнопку «Добавить связь» */
  allowAdd?: boolean
}

export function DocumentLinks({ entryId, allowAdd }: Props) {
  const { companyId } = useCompany()
  const [refreshKey, setRefreshKey] = useState(0)

  const { links, linkedEntries } = useMemo(() => {
    const allLinks = getLinksForEntry(entryId)
    const allEntries = getEntries(companyId)
    const entryMap = new Map(allEntries.map((e) => [e.id, e]))

    const linked: Array<{ link: DocumentLink; entry: DataEntry; direction: 'from' | 'to' }> = []
    for (const link of allLinks) {
      const otherId = link.sourceEntryId === entryId ? link.targetEntryId : link.sourceEntryId
      const entry = entryMap.get(otherId)
      if (entry) {
        linked.push({
          link,
          entry,
          direction: link.sourceEntryId === entryId ? 'to' : 'from',
        })
      }
    }

    return { links: allLinks, linkedEntries: linked }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entryId, companyId, refreshKey])

  const [showAddForm, setShowAddForm] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  const availableEntries = useMemo(() => {
    if (!showAddForm) return []
    const allEntries = getEntries(companyId)
    const linkedIds = new Set(linkedEntries.map((l) => l.entry.id))
    linkedIds.add(entryId)
    return allEntries
      .filter((e) => !linkedIds.has(e.id))
      .filter((e) =>
        !searchQuery ||
        e.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        e.id.includes(searchQuery),
      )
      .slice(0, 10)
  }, [showAddForm, companyId, linkedEntries, entryId, searchQuery])

  function handleAddLink(targetId: string) {
    createLink(entryId, targetId, 'manual')
    setShowAddForm(false)
    setSearchQuery('')
    setRefreshKey((k) => k + 1)
  }

  function handleRemoveLink(linkId: string) {
    removeLink(linkId)
    setRefreshKey((k) => k + 1)
  }

  if (links.length === 0 && !allowAdd) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Link2 className="size-4" />
            Связи ({links.length})
          </CardTitle>
          {allowAdd && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowAddForm(!showAddForm)}
            >
              <Plus className="size-3.5" />
              Связать
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {linkedEntries.map(({ link, entry, direction }) => {
          const config = LINK_TYPE_CONFIG[link.type]
          const Icon = config.icon
          const categoryPath = entry.categoryId

          return (
            <div
              key={link.id}
              className="flex items-center gap-2 p-2 rounded-md border bg-muted/30 group"
            >
              <Icon className={`size-4 shrink-0 ${config.color}`} />
              <div className="flex-1 min-w-0">
                <Link
                  to={`/data/${categoryPath}/${entry.id}`}
                  className="text-sm font-medium hover:underline truncate block"
                >
                  {entry.title}
                </Link>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <Badge variant="outline" className="text-[10px] px-1 py-0">
                    {config.label}
                    {direction === 'from' ? ' ←' : ' →'}
                  </Badge>
                  <StatusBadge status={entry.status} />
                  {link.label && (
                    <span className="text-[10px] text-muted-foreground">{link.label}</span>
                  )}
                </div>
              </div>
              {link.type === 'manual' && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="opacity-0 group-hover:opacity-100 size-6 p-0"
                  onClick={() => handleRemoveLink(link.id)}
                >
                  <X className="size-3" />
                </Button>
              )}
            </div>
          )
        })}

        {links.length === 0 && (
          <p className="text-xs text-muted-foreground py-1">Нет связей с другими документами</p>
        )}

        {/* Форма добавления связи */}
        {showAddForm && (
          <div className="border rounded-md p-2 space-y-2 mt-2">
            <input
              type="text"
              placeholder="Поиск по названию..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full text-sm border rounded px-2 py-1 bg-background"
              autoFocus
            />
            <div className="max-h-40 overflow-y-auto space-y-1">
              {availableEntries.map((e) => (
                <button
                  key={e.id}
                  onClick={() => handleAddLink(e.id)}
                  className="w-full text-left text-sm p-1.5 rounded hover:bg-accent flex items-center gap-2"
                >
                  <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate">{e.title}</span>
                </button>
              ))}
              {availableEntries.length === 0 && searchQuery && (
                <p className="text-xs text-muted-foreground p-1">Ничего не найдено</p>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
