/**
 * BundleSuggestionsPanel — сворачиваемая панель авто-предложений для комплекта.
 * Показывает кандидатов с причинами и кнопками «Добавить» / «Отклонить».
 */

import { useState, useCallback, memo } from 'react'
import { useBundleSuggestions, useAddToBundle } from '@/hooks/useBundle'
import { isInBundle, resolveRole, BUNDLE_ROLE_LABELS } from '@/services/bundleService'
import type { DataEntry, BundleSuggestion } from '@/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Lightbulb, Plus, X, ChevronDown, ChevronRight,
} from 'lucide-react'

interface Props {
  entry: DataEntry
}

export function BundleSuggestionsPanel({ entry }: Props) {
  const inBundle = isInBundle(entry)
  const { data: suggestions = [], isLoading } = useBundleSuggestions(entry.id, inBundle)
  const addToBundle = useAddToBundle()

  const [collapsed, setCollapsed] = useState(false)
  const [dismissed, setDismissed] = useState<Set<string>>(() => {
    try {
      const raw = sessionStorage.getItem(`bundle-dismissed-${entry.id}`)
      return raw ? new Set(JSON.parse(raw)) : new Set()
    } catch {
      return new Set()
    }
  })

  const dismiss = useCallback((id: string) => {
    setDismissed((prev) => {
      const next = new Set(prev)
      next.add(id)
      sessionStorage.setItem(`bundle-dismissed-${entry.id}`, JSON.stringify([...next]))
      return next
    })
  }, [entry.id])

  const handleAdd = useCallback((suggestion: BundleSuggestion) => {
    addToBundle.mutate({ parentId: entry.id, childId: suggestion.entry.id })
  }, [addToBundle, entry.id])

  // Фильтруем отклонённые
  const visible = suggestions.filter((s) => !dismissed.has(s.entry.id))

  if (!inBundle || isLoading || visible.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-2">
        <button
          type="button"
          className="flex items-center justify-between w-full"
          onClick={() => setCollapsed(!collapsed)}
        >
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Lightbulb className="size-4 text-amber-500" />
            Возможные связанные ({visible.length})
          </CardTitle>
          {collapsed ? (
            <ChevronRight className="size-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="size-4 text-muted-foreground" />
          )}
        </button>
      </CardHeader>

      {!collapsed && (
        <CardContent className="space-y-2 pt-0">
          {visible.map((suggestion) => (
            <SuggestionItem
              key={suggestion.entry.id}
              suggestion={suggestion}
              onAdd={handleAdd}
              onDismiss={dismiss}
              isAdding={addToBundle.isPending}
            />
          ))}
        </CardContent>
      )}
    </Card>
  )
}

// ---- Мемоизированный элемент предложения ----

const SuggestionItem = memo(function SuggestionItem({
  suggestion,
  onAdd,
  onDismiss,
  isAdding,
}: {
  suggestion: BundleSuggestion
  onAdd: (s: BundleSuggestion) => void
  onDismiss: (id: string) => void
  isAdding: boolean
}) {
  return (
    <div className="flex items-start gap-2 p-2 rounded-md border bg-muted/30 group">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <Badge variant="outline" className="text-[9px] px-1 py-0 shrink-0">
            {BUNDLE_ROLE_LABELS[resolveRole(suggestion.entry.docTypeId)]}
          </Badge>
          <p className="text-sm font-medium truncate">
            {suggestion.entry.title}
          </p>
        </div>
        <div className="flex flex-wrap gap-1 mt-1">
          {suggestion.reasons.map((reason) => (
            <Badge key={reason} variant="secondary" className="text-[10px] px-1.5 py-0">
              {reason}
            </Badge>
          ))}
          <Badge variant="outline" className="text-[10px] px-1.5 py-0">
            {suggestion.score}%
          </Badge>
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <Button
          variant="ghost"
          size="sm"
          className="size-7 p-0 text-green-600 hover:text-green-700 hover:bg-green-50"
          onClick={() => onAdd(suggestion)}
          disabled={isAdding}
        >
          <Plus className="size-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="size-7 p-0 text-muted-foreground hover:text-foreground"
          onClick={() => onDismiss(suggestion.entry.id)}
        >
          <X className="size-3.5" />
        </Button>
      </div>
    </div>
  )
})
