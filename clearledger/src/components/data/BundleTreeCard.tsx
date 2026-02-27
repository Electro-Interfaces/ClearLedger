/**
 * BundleTreeCard — карточка бизнес-комплекта документов.
 *
 * Три улучшения из 1С:УТ:
 * 1. Роли из enum (авто-определение по docTypeId)
 * 2. Валидация допустимых пар при добавлении
 * 3. Кнопка «Создать на основании» с предзаполнением полей
 */

import { useState, useMemo, memo, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useEntries } from '@/hooks/useEntries'
import { useBundleTree, useCreateBundle, useAddToBundle, useRemoveFromBundle } from '@/hooks/useBundle'
import {
  isInBundle, resolveRole, BUNDLE_ROLE_LABELS,
  validateSubordination, prefillFromParent,
} from '@/services/bundleService'
import { StatusBadge } from './StatusBadge'
import type { DataEntry, BundleNode } from '@/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  FolderTree, Plus, X, FileText, ChevronRight, ChevronDown,
  FilePlus2,
} from 'lucide-react'

interface Props {
  entry: DataEntry
}

export function BundleTreeCard({ entry }: Props) {
  const navigate = useNavigate()
  const { data: tree, isLoading } = useBundleTree(entry.id)
  const createBundle = useCreateBundle()
  const addToBundle = useAddToBundle()
  const removeFromBundle = useRemoveFromBundle()

  const [showAddForm, setShowAddForm] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  // React Query вместо getEntries() + useEffect
  const { data: allEntries = [] } = useEntries()

  const inBundle = isInBundle(entry)

  // Кандидаты для добавления: фильтр + валидация допустимых пар
  const availableEntries = useMemo(() => {
    if (!showAddForm) return []
    const bundleRootId = entry.metadata._bundleRootId
    return allEntries
      .filter((e) => {
        if (e.id === entry.id) return false
        if (bundleRootId && e.metadata._bundleRootId === bundleRootId) return false
        if (e.metadata._bundleRootId && e.metadata._bundleRootId !== bundleRootId) return false
        if (e.status === 'archived') return false
        if (e.metadata._excluded === 'true') return false
        // Валидация допустимой пары
        if (!validateSubordination(entry.docTypeId, e.docTypeId).allowed) return false
        if (!searchQuery) return true
        return (
          e.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          e.id.includes(searchQuery)
        )
      })
      .slice(0, 10)
  }, [showAddForm, allEntries, entry, searchQuery])

  const handleCreateBundle = useCallback(() => {
    createBundle.mutate({ rootEntryId: entry.id })
  }, [createBundle, entry.id])

  const handleAddChild = useCallback((childId: string) => {
    addToBundle.mutate({ parentId: entry.id, childId })
    setShowAddForm(false)
    setSearchQuery('')
  }, [addToBundle, entry.id])

  const handleRemove = useCallback((entryId: string) => {
    removeFromBundle.mutate(entryId)
  }, [removeFromBundle])

  /** «Создать на основании» — навигация на intake с предзаполнением */
  const handleCreateBased = useCallback(() => {
    const prefill = prefillFromParent(entry)
    const params = new URLSearchParams({
      basedOn: entry.id,
      categoryId: prefill.categoryId,
      subcategoryId: prefill.subcategoryId,
    })
    if (Object.keys(prefill.metadata).length > 0) {
      params.set('prefillMeta', JSON.stringify(prefill.metadata))
    }
    navigate(`/input?${params.toString()}`)
  }, [entry, navigate])

  // Если не в комплекте — показываем кнопку «Создать комплект»
  if (!inBundle && !isLoading) {
    return (
      <Card>
        <CardContent className="py-4">
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={handleCreateBundle}
            disabled={createBundle.isPending}
          >
            <FolderTree className="size-4" />
            Создать комплект
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (isLoading || !tree) return null

  const isRoot = entry.metadata._bundleRootId === entry.id

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <FolderTree className="size-4" />
            Комплект документов ({tree.totalCount})
          </CardTitle>
          <div className="flex items-center gap-1">
            {/* Кнопка «Создать на основании» */}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleCreateBased}
                  >
                    <FilePlus2 className="size-3.5" />
                    На основании
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Создать подчинённый документ с предзаполненными полями</TooltipContent>
              </Tooltip>
            </TooltipProvider>
            {/* Кнопка «Добавить существующий» */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowAddForm(!showAddForm)}
            >
              <Plus className="size-3.5" />
              Добавить
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-1">
        {/* Рекурсивное дерево */}
        <TreeNode
          node={tree.root}
          currentEntryId={entry.id}
          onRemove={handleRemove}
          isRemoving={removeFromBundle.isPending}
        />

        {/* Форма добавления существующего документа */}
        {showAddForm && (
          <div className="border rounded-md p-2 space-y-2 mt-2">
            <input
              type="text"
              placeholder="Поиск документа..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full text-sm border rounded px-2 py-1 bg-background"
              autoFocus
            />
            <div className="max-h-40 overflow-y-auto space-y-1">
              {availableEntries.map((e) => {
                const role = resolveRole(e.docTypeId)
                return (
                  <button
                    key={e.id}
                    onClick={() => handleAddChild(e.id)}
                    disabled={addToBundle.isPending}
                    className="w-full text-left text-sm p-1.5 rounded hover:bg-accent flex items-center gap-2 disabled:opacity-50"
                  >
                    <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                    <Badge variant="outline" className="text-[9px] px-1 py-0 shrink-0">
                      {BUNDLE_ROLE_LABELS[role]}
                    </Badge>
                    <span className="truncate">{e.title}</span>
                  </button>
                )
              })}
              {availableEntries.length === 0 && searchQuery && (
                <p className="text-xs text-muted-foreground p-1">Ничего не найдено</p>
              )}
            </div>
          </div>
        )}

        {/* Кнопка «Убрать из комплекта» для не-корневого документа — с подтверждением */}
        {!isRoot && (
          <div className="pt-2 border-t mt-2">
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full text-muted-foreground text-xs"
                  disabled={removeFromBundle.isPending}
                >
                  <X className="size-3" />
                  Убрать из комплекта
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Убрать из комплекта?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Документ «{entry.title}» и все его подчинённые будут откреплены от комплекта.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Отмена</AlertDialogCancel>
                  <AlertDialogAction onClick={() => handleRemove(entry.id)}>
                    Убрать
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---- TreeNode (рекурсивный, мемоизированный) ----

const TreeNode = memo(function TreeNode({
  node,
  currentEntryId,
  onRemove,
  isRemoving,
}: {
  node: BundleNode
  currentEntryId: string
  onRemove: (id: string) => void
  isRemoving: boolean
}) {
  const [collapsed, setCollapsed] = useState(false)
  const isCurrent = node.entry.id === currentEntryId
  const isRoot = node.depth === 0
  const hasChildren = node.children.length > 0

  // Роль из enum (авто-определяется по docTypeId, хранится в _bundleRole)
  const role = (node.entry.metadata._bundleRole || resolveRole(node.entry.docTypeId)) as keyof typeof BUNDLE_ROLE_LABELS
  const roleLabel = BUNDLE_ROLE_LABELS[role] ?? BUNDLE_ROLE_LABELS.other

  return (
    <div>
      <div
        className={`flex items-center gap-1.5 p-1.5 rounded-md group ${
          isCurrent ? 'bg-accent border border-border' : 'hover:bg-muted/50'
        }`}
        style={{ paddingLeft: `${node.depth * 20 + 4}px` }}
      >
        {/* Expand/collapse toggle */}
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            className="size-4 shrink-0 flex items-center justify-center text-muted-foreground hover:text-foreground"
          >
            {collapsed ? <ChevronRight className="size-3" /> : <ChevronDown className="size-3" />}
          </button>
        ) : (
          <span className="size-4 shrink-0" />
        )}

        {/* Role badge — всегда показываем (из enum) */}
        <Badge variant="outline" className="text-[10px] px-1 py-0 shrink-0">
          {roleLabel}
        </Badge>

        {/* Title link */}
        <Link
          to={`/data/${node.entry.categoryId}/${node.entry.id}`}
          className={`text-sm truncate flex-1 hover:underline ${
            isCurrent ? 'font-semibold' : 'font-medium'
          }`}
        >
          {node.entry.title}
        </Link>

        {/* Status */}
        <StatusBadge status={node.entry.status} />

        {/* Remove button (not for root, not for current) — с подтверждением */}
        {!isRoot && !isCurrent && (
          <AlertDialog>
            <TooltipProvider>
              <Tooltip>
                <AlertDialogTrigger asChild>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="opacity-0 group-hover:opacity-100 size-5 p-0"
                      disabled={isRemoving}
                    >
                      <X className="size-3" />
                    </Button>
                  </TooltipTrigger>
                </AlertDialogTrigger>
                <TooltipContent>Убрать из комплекта</TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Убрать из комплекта?</AlertDialogTitle>
                <AlertDialogDescription>
                  Документ «{node.entry.title}» и его подчинённые будут откреплены.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Отмена</AlertDialogCancel>
                <AlertDialogAction
                  onClick={(e) => {
                    e.preventDefault()
                    onRemove(node.entry.id)
                  }}
                >
                  Убрать
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>

      {/* Children */}
      {!collapsed && hasChildren && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.entry.id}
              node={child}
              currentEntryId={currentEntryId}
              onRemove={onRemove}
              isRemoving={isRemoving}
            />
          ))}
        </div>
      )}
    </div>
  )
})
