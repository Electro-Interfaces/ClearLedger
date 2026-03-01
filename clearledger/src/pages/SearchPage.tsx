import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, FileText, SearchX, ArrowUpDown } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
import { SearchSkeleton } from '@/components/common/Skeletons'
import { PaginationWrapper } from '@/components/common/PaginationWrapper'
import { AdvancedFilters } from '@/components/common/AdvancedFilters'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { StatusBadge } from '@/components/data/StatusBadge'
import { useSearchEntries } from '@/hooks/useEntries'
import { useCompany } from '@/contexts/CompanyContext'
import { getCategoryById } from '@/config/categories'
import { formatDate } from '@/lib/formatDate'
import type { AdvancedFilters as AdvancedFiltersType, DataEntry } from '@/types'

const STATUSES = [
  { value: 'new', label: 'Новый' },
  { value: 'recognized', label: 'Распознан' },
  { value: 'verified', label: 'Проверен' },
  { value: 'transferred', label: 'Передан' },
  { value: 'error', label: 'Ошибка' },
]

type SortMode = 'relevance' | 'date' | 'amount'

/** Определить совпавшие поля для отображения бейджей */
function getMatchedFields(entry: DataEntry, q: string): { label: string; value: string }[] {
  if (!q || q.length < 2) return []
  const ql = q.toLowerCase()
  const matched: { label: string; value: string }[] = []
  const meta = entry.metadata

  if (meta.docNumber && meta.docNumber.toLowerCase().includes(ql)) {
    matched.push({ label: 'Номер', value: meta.docNumber })
  }
  if (meta.counterparty && meta.counterparty.toLowerCase().includes(ql)) {
    matched.push({ label: 'Контрагент', value: meta.counterparty })
  }
  if (meta.inn && meta.inn.includes(ql)) {
    matched.push({ label: 'ИНН', value: meta.inn })
  }
  if (meta.amount && meta.amount.includes(ql)) {
    matched.push({ label: 'Сумма', value: meta.amount })
  }

  return matched
}

const amountFmt = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })

export function SearchPage() {
  const [searchParams] = useSearchParams()
  const initialQuery = searchParams.get('q') ?? ''
  const [query, setQuery] = useState(initialQuery)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [advFilters, setAdvFilters] = useState<AdvancedFiltersType>({})
  const [sortMode, setSortMode] = useState<SortMode>('relevance')

  // Быстрые фильтры (вынесены из AdvancedFilters)
  const [quickCounterparty, setQuickCounterparty] = useState('')
  const [quickAmountMin, setQuickAmountMin] = useState('')
  const [quickAmountMax, setQuickAmountMax] = useState('')
  const [quickDateFrom, setQuickDateFrom] = useState('')
  const [quickDateTo, setQuickDateTo] = useState('')

  const { company } = useCompany()
  const navigate = useNavigate()
  const { data: results = [], isLoading } = useSearchEntries(query)

  // Apply quick filters + advanced filters
  const filtered = useMemo(() => {
    let r = results

    // Быстрые фильтры
    if (quickCounterparty) {
      const cp = quickCounterparty.toLowerCase()
      r = r.filter((e) => (e.metadata.counterparty || '').toLowerCase().includes(cp) || (e.metadata.inn || '').includes(cp))
    }
    if (quickAmountMin) {
      const min = Number(quickAmountMin)
      if (!isNaN(min)) r = r.filter((e) => Number(e.metadata.amount || 0) >= min)
    }
    if (quickAmountMax) {
      const max = Number(quickAmountMax)
      if (!isNaN(max)) r = r.filter((e) => Number(e.metadata.amount || 0) <= max)
    }
    if (quickDateFrom) {
      r = r.filter((e) => (e.metadata.docDate || e.createdAt.slice(0, 10)) >= quickDateFrom)
    }
    if (quickDateTo) {
      r = r.filter((e) => (e.metadata.docDate || e.createdAt.slice(0, 10)) <= quickDateTo)
    }

    // AdvancedFilters (status, source — оставшиеся)
    if (advFilters.status && advFilters.status !== 'all') r = r.filter((e) => e.status === advFilters.status)
    if (advFilters.source && advFilters.source !== 'all') r = r.filter((e) => e.source === advFilters.source)

    return r
  }, [results, quickCounterparty, quickAmountMin, quickAmountMax, quickDateFrom, quickDateTo, advFilters])

  // Сортировка
  const sorted = useMemo(() => {
    const arr = [...filtered]
    if (sortMode === 'date') {
      arr.sort((a, b) => {
        const da = a.metadata.docDate || a.createdAt
        const db = b.metadata.docDate || b.createdAt
        return db.localeCompare(da)
      })
    } else if (sortMode === 'amount') {
      arr.sort((a, b) => Number(b.metadata.amount || 0) - Number(a.metadata.amount || 0))
    }
    // relevance — default order from search
    return arr
  }, [filtered, sortMode])

  const paginatedResults = useMemo(
    () => sorted.slice((page - 1) * pageSize, page * pageSize),
    [sorted, page, pageSize],
  )

  // Sync with URL
  useEffect(() => {
    const q = searchParams.get('q')
    if (q && q !== query) setQuery(q)
  }, [searchParams])

  // Reset pagination on query/filter change
  useEffect(() => { setPage(1) }, [query, advFilters, quickCounterparty, quickAmountMin, quickAmountMax, quickDateFrom, quickDateTo])

  /** Highlight search terms in text */
  function highlight(text: string): React.ReactNode {
    if (!query || query.length < 2) return text
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
    const parts = text.split(regex)
    return parts.map((part, i) =>
      regex.test(part) ? <mark key={i} className="bg-yellow-500/30 rounded px-0.5">{part}</mark> : part,
    )
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Поиск</h1>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground" />
        <Input
          placeholder="Поиск по документам, суммам, контрагентам..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="pl-10 h-12 text-base"
          autoFocus
        />
      </div>

      {/* Быстрые фильтры — всегда видны */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">Контрагент</Label>
          <Input
            placeholder="Название или ИНН"
            value={quickCounterparty}
            onChange={(e) => setQuickCounterparty(e.target.value)}
            className="h-8 text-sm"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Сумма от</Label>
            <Input
              type="number"
              placeholder="0"
              value={quickAmountMin}
              onChange={(e) => setQuickAmountMin(e.target.value)}
              className="h-8 text-sm"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Сумма до</Label>
            <Input
              type="number"
              placeholder="∞"
              value={quickAmountMax}
              onChange={(e) => setQuickAmountMax(e.target.value)}
              className="h-8 text-sm"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Дата от</Label>
            <Input
              type="date"
              value={quickDateFrom}
              onChange={(e) => setQuickDateFrom(e.target.value)}
              className="h-8 text-sm"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Дата до</Label>
            <Input
              type="date"
              value={quickDateTo}
              onChange={(e) => setQuickDateTo(e.target.value)}
              className="h-8 text-sm"
            />
          </div>
        </div>
      </div>

      {/* Ещё фильтры (status, source) */}
      <AdvancedFilters
        filters={advFilters}
        onFiltersChange={setAdvFilters}
        statuses={STATUSES}
      />

      {query.length < 2 && (
        <div className="text-center py-12 text-muted-foreground">
          Введите минимум 2 символа для поиска
        </div>
      )}

      {query.length >= 2 && isLoading && <SearchSkeleton />}

      {query.length >= 2 && !isLoading && sorted.length === 0 && (
        <EmptyState
          icon={SearchX}
          title="Ничего не найдено"
          description={`По запросу «${query}» не найдено документов`}
        />
      )}

      {sorted.length > 0 && (
        <div className="space-y-2">
          {/* Счётчик + сортировка */}
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">Найдено: {sorted.length}</p>
            <div className="flex items-center gap-2">
              <ArrowUpDown className="size-3.5 text-muted-foreground" />
              <Select value={sortMode} onValueChange={(v) => setSortMode(v as SortMode)}>
                <SelectTrigger className="h-7 text-xs w-[140px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="relevance">По релевантности</SelectItem>
                  <SelectItem value="date">По дате</SelectItem>
                  <SelectItem value="amount">По сумме</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {paginatedResults.map((entry) => {
            const category = getCategoryById(company.profileId, entry.categoryId)
            const matchedFields = getMatchedFields(entry, query)
            const amount = entry.metadata.amount ? Number(entry.metadata.amount) : null
            const counterparty = entry.metadata.counterparty

            return (
              <Card
                key={entry.id}
                className="cursor-pointer hover:bg-accent/30 transition-colors"
                onClick={() => navigate(`/data/${entry.categoryId}/${entry.id}`)}
              >
                <CardContent className="flex items-center gap-4 p-4">
                  <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <FileText className="h-5 w-5 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{highlight(entry.title)}</div>
                    <div className="text-sm text-muted-foreground">
                      {category?.label} &middot; {formatDate(entry.metadata.docDate || entry.createdAt)}
                    </div>
                    {/* Бейджи совпавших полей */}
                    {matchedFields.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {matchedFields.map((f, idx) => (
                          <Badge key={idx} variant="secondary" className="text-[10px] px-1.5 py-0">
                            {f.label}: {f.value}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    {amount != null && !isNaN(amount) && (
                      <span className="font-mono text-sm font-medium">{amountFmt.format(amount)} ₽</span>
                    )}
                    {counterparty && (
                      <span className="text-xs text-muted-foreground max-w-[140px] truncate">{counterparty}</span>
                    )}
                    <div className="flex items-center gap-1.5">
                      <StatusBadge status={entry.status} />
                    </div>
                  </div>
                </CardContent>
              </Card>
            )
          })}

          <PaginationWrapper
            total={sorted.length}
            page={page}
            pageSize={pageSize}
            onPageChange={setPage}
            onPageSizeChange={setPageSize}
          />
        </div>
      )}
    </div>
  )
}
