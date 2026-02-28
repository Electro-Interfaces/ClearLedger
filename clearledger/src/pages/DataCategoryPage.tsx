import { useState, useMemo, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { getCategoryById } from '@/config/categories'
import { useEntriesByCategory, useTransferEntries, useVerifyEntry, useDeleteEntry, useArchiveEntry, useExcludeEntry, useAuditorVerify, useSetSyncStatus } from '@/hooks/useEntries'
import { DataTableToolbar } from '@/components/data/DataTableToolbar'
import { CategoryTabs } from '@/components/data/CategoryTabs'
import { DataTable } from '@/components/data/DataTable'
import { RegisterTable } from '@/components/data/RegisterTable'
import { ViewSwitcher, type ViewMode } from '@/components/data/ViewSwitcher'
import { RegisterStatsBar } from '@/components/data/RegisterStatsBar'
import { BulkActionsBar } from '@/components/data/BulkActionsBar'
import { PaginationWrapper } from '@/components/common/PaginationWrapper'
import { ExportModal } from '@/components/common/ExportModal'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { QueryError } from '@/components/common/QueryError'
import { useIsMobile } from '@/hooks/use-mobile'
import { toast } from 'sonner'
import { Download } from 'lucide-react'
import type { FilterState } from '@/types'
import type { EntryStatus } from '@/config/statuses'

// Lazy load тяжёлых компонентов
import { lazy, Suspense } from 'react'
const DocumentTreeView = lazy(() => import('@/components/data/DocumentTreeView').then(m => ({ default: m.DocumentTreeView })))

export function DataCategoryPage() {
  const { category } = useParams<{ category: string }>()
  const navigate = useNavigate()
  const { company, companyId } = useCompany()
  const isMobile = useIsMobile()

  const categoryConfig = category ? getCategoryById(company.profileId, category) : undefined

  const [filters, setFilters] = useState<FilterState>({
    search: '',
    status: 'all',
    source: 'all',
    subcategory: 'all',
  })

  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [activeSubcategory, setActiveSubcategory] = useState('all')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [exportOpen, setExportOpen] = useState(false)

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
  const auditorVerify = useAuditorVerify()
  const setSyncStatus = useSetSyncStatus()

  // Мобильный → только list
  const effectiveViewMode = isMobile ? 'list' : viewMode

  const handleSubcategoryChange = useCallback((value: string) => {
    setActiveSubcategory(value)
    setFilters((prev) => ({ ...prev, subcategory: value }))
    setPage(1)
  }, [])

  const handleFiltersChange = useCallback((newFilters: FilterState) => {
    setFilters(newFilters)
    setPage(1)
  }, [])

  const paginatedEntries = useMemo(
    () => entries.slice((page - 1) * pageSize, page * pageSize),
    [entries, page, pageSize],
  )

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

  function handleBulkAuditor() {
    for (const id of selectedIds) {
      auditorVerify.mutate(id)
    }
    toast.success(`Аудитор запущен для ${selectedIds.size} записей`)
  }

  function handleExportTo1C() {
    const selected = entries.filter((e) => selectedIds.has(e.id))
    const ready = selected.filter(
      (e) => e.docPurpose === 'accounting' && (e.status === 'verified' || e.status === 'transferred'),
    )
    if (ready.length === 0) {
      toast.error('Нет документов, готовых к выгрузке (нужен бухгалтерский + проверен/передан)')
      return
    }
    // Передаём и обновляем syncStatus
    transferEntries.mutate(ready.map((e) => e.id))
    for (const e of ready) {
      setSyncStatus.mutate({ id: e.id, syncStatus: 'exported' })
    }
    toast.success(`Выгружено ${ready.length} из ${selected.length} документов в 1С`)
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
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">{categoryConfig.label}</h1>
        <div className="flex items-center gap-2">
          {!isMobile && (
            <ViewSwitcher value={effectiveViewMode} onChange={setViewMode} />
          )}
          <Button variant="outline" size="sm" onClick={() => setExportOpen(true)}>
            <Download className="size-4" />
            Экспорт
          </Button>
        </div>
      </div>

      <RegisterStatsBar entries={entries} />

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

      {effectiveViewMode === 'list' && (
        <DataTable
          entries={paginatedEntries}
          onRowClick={handleRowClick}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          onAuditorVerify={(id) => auditorVerify.mutate(id)}
        />
      )}

      {effectiveViewMode === 'register' && (
        <RegisterTable
          entries={paginatedEntries}
          onRowClick={handleRowClick}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
        />
      )}

      {effectiveViewMode === 'tree' && (
        <Suspense fallback={<div className="flex items-center justify-center py-12 text-muted-foreground">Загрузка...</div>}>
          <DocumentTreeView
            entries={entries}
            onRowClick={handleRowClick}
          />
        </Suspense>
      )}

      {effectiveViewMode !== 'tree' && (
        <PaginationWrapper
          total={entries.length}
          page={page}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
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
        onAuditor={handleBulkAuditor}
        onExportTo1C={handleExportTo1C}
      />

      <ExportModal open={exportOpen} onOpenChange={setExportOpen} entries={entries} companyId={companyId} />
    </div>
  )
}
