import { useState, useMemo, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { getCategoryById } from '@/config/categories'
import { useEntriesByCategory, useTransferEntries, useVerifyEntry, useDeleteEntry, useArchiveEntry, useExcludeEntry } from '@/hooks/useEntries'
import { DataTableToolbar } from '@/components/data/DataTableToolbar'
import { CategoryTabs } from '@/components/data/CategoryTabs'
import { DataTable } from '@/components/data/DataTable'
import { BulkActionsBar } from '@/components/data/BulkActionsBar'
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationPrevious,
  PaginationNext,
} from '@/components/ui/pagination'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { QueryError } from '@/components/common/QueryError'
import { toast } from 'sonner'
import type { FilterState } from '@/types'
import type { EntryStatus } from '@/config/statuses'

const PAGE_SIZE = 10

export function DataCategoryPage() {
  const { category } = useParams<{ category: string }>()
  const navigate = useNavigate()
  const { company } = useCompany()

  const categoryConfig = category ? getCategoryById(company.profileId, category) : undefined

  const [filters, setFilters] = useState<FilterState>({
    search: '',
    status: 'all',
    source: 'all',
    subcategory: 'all',
  })

  const [activeSubcategory, setActiveSubcategory] = useState('all')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [page, setPage] = useState(1)

  const effectiveFilters = useMemo(
    () => ({ ...filters, subcategory: activeSubcategory }),
    [filters, activeSubcategory],
  )

  const { data: entries = [], isError, refetch } = useEntriesByCategory(category ?? '', effectiveFilters)
  const transferEntries = useTransferEntries()
  const verifyEntry = useVerifyEntry()
  const deleteEntry = useDeleteEntry()
  const archiveEntry = useArchiveEntry()
  const excludeEntry = useExcludeEntry()

  const handleSubcategoryChange = useCallback((value: string) => {
    setActiveSubcategory(value)
    setFilters((prev) => ({ ...prev, subcategory: value }))
    setPage(1)
  }, [])

  const handleFiltersChange = useCallback((newFilters: FilterState) => {
    setFilters(newFilters)
    setPage(1)
  }, [])

  const totalPages = Math.max(1, Math.ceil(entries.length / PAGE_SIZE))
  const paginatedEntries = entries.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  function handleRowClick(id: string) {
    navigate(`/data/${category}/${id}`)
  }

  function handleChangeStatus(status: EntryStatus) {
    if (status === 'verified') {
      for (const id of selectedIds) {
        verifyEntry.mutate(id)
      }
    }
    setSelectedIds(new Set())
  }

  function handleTransfer() {
    transferEntries.mutate([...selectedIds])
    setSelectedIds(new Set())
  }

  function handleBulkDelete() {
    for (const id of selectedIds) {
      deleteEntry.mutate(id)
    }
    toast.success(`Удалено ${selectedIds.size} записей`)
    setSelectedIds(new Set())
  }

  function handleBulkArchive() {
    for (const id of selectedIds) {
      archiveEntry.mutate(id)
    }
    toast.success(`Архивировано ${selectedIds.size} записей`)
    setSelectedIds(new Set())
  }

  function handleBulkExclude() {
    for (const id of selectedIds) {
      excludeEntry.mutate(id)
    }
    toast.success(`Исключено из анализа: ${selectedIds.size} записей`)
    setSelectedIds(new Set())
  }

  function handleExportCsv() {
    const selected = entries.filter((e) => selectedIds.has(e.id))
    const header = 'ID,Название,Категория,Подкатегория,Статус,Источник,Дата создания\n'
    const rows = selected.map((e) =>
      [e.id, `"${e.title}"`, e.categoryId, e.subcategoryId, e.status, e.source, e.createdAt].join(','),
    ).join('\n')
    const blob = new Blob(['\uFEFF' + header + rows], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${category ?? 'export'}_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
    toast.success(`Экспортировано ${selected.length} записей`)
  }

  if (!categoryConfig) {
    return (
      <div className="flex items-center justify-center h-[50vh]">
        <p className="text-muted-foreground text-lg">Категория не найдена</p>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">{categoryConfig.label}</h1>
        <QueryError onRetry={() => refetch()} />
      </div>
    )
  }

  return (
    <div className="space-y-4 pb-16">
      <h1 className="text-2xl font-bold tracking-tight">{categoryConfig.label}</h1>

      <DataTableToolbar filters={filters} onFiltersChange={handleFiltersChange} />

      {/* Фильтры: архив, исключённые, версии */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Checkbox
            id="show-archived"
            checked={filters.showArchived ?? false}
            onCheckedChange={(checked) =>
              setFilters((prev) => ({ ...prev, showArchived: !!checked }))
            }
          />
          <Label htmlFor="show-archived" className="text-sm text-muted-foreground cursor-pointer">
            Показать архив
          </Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id="show-excluded"
            checked={filters.showExcluded ?? false}
            onCheckedChange={(checked) =>
              setFilters((prev) => ({ ...prev, showExcluded: !!checked }))
            }
          />
          <Label htmlFor="show-excluded" className="text-sm text-muted-foreground cursor-pointer">
            Показать исключённые
          </Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id="show-all-versions"
            checked={filters.showAllVersions ?? false}
            onCheckedChange={(checked) =>
              setFilters((prev) => ({ ...prev, showAllVersions: !!checked }))
            }
          />
          <Label htmlFor="show-all-versions" className="text-sm text-muted-foreground cursor-pointer">
            Показать все версии
          </Label>
        </div>
      </div>

      <CategoryTabs
        categoryId={category!}
        activeSubcategory={activeSubcategory}
        onSubcategoryChange={handleSubcategoryChange}
      />

      <DataTable
        entries={paginatedEntries}
        onRowClick={handleRowClick}
        selectedIds={selectedIds}
        onSelectionChange={setSelectedIds}
      />

      {/* Pagination */}
      {totalPages > 1 && (
        <Pagination>
          <PaginationContent>
            <PaginationItem>
              <PaginationPrevious
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                aria-disabled={page === 1}
                className={page === 1 ? 'pointer-events-none opacity-50' : 'cursor-pointer'}
              />
            </PaginationItem>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
              <PaginationItem key={p}>
                <PaginationLink
                  isActive={p === page}
                  onClick={() => setPage(p)}
                  className="cursor-pointer"
                >
                  {p}
                </PaginationLink>
              </PaginationItem>
            ))}
            <PaginationItem>
              <PaginationNext
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                aria-disabled={page === totalPages}
                className={page === totalPages ? 'pointer-events-none opacity-50' : 'cursor-pointer'}
              />
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      )}

      <BulkActionsBar
        selectedCount={selectedIds.size}
        onClearSelection={() => setSelectedIds(new Set())}
        onChangeStatus={handleChangeStatus}
        onTransfer={handleTransfer}
        onDelete={handleBulkDelete}
        onExportCsv={handleExportCsv}
        onArchive={handleBulkArchive}
        onExclude={handleBulkExclude}
      />
    </div>
  )
}
