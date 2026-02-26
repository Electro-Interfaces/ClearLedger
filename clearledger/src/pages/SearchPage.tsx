import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, FileText, SearchX } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
import { SearchSkeleton } from '@/components/common/Skeletons'
import { PaginationWrapper } from '@/components/common/PaginationWrapper'
import { AdvancedFilters } from '@/components/common/AdvancedFilters'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { StatusBadge } from '@/components/data/StatusBadge'
import { useSearchEntries } from '@/hooks/useEntries'
import { useCompany } from '@/contexts/CompanyContext'
import { getCategoryById } from '@/config/categories'
import { formatDate } from '@/lib/formatDate'
import type { AdvancedFilters as AdvancedFiltersType } from '@/types'

const STATUSES = [
  { value: 'new', label: 'Новый' },
  { value: 'recognized', label: 'Распознан' },
  { value: 'verified', label: 'Проверен' },
  { value: 'transferred', label: 'Передан' },
  { value: 'error', label: 'Ошибка' },
]

export function SearchPage() {
  const [searchParams] = useSearchParams()
  const initialQuery = searchParams.get('q') ?? ''
  const [query, setQuery] = useState(initialQuery)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [advFilters, setAdvFilters] = useState<AdvancedFiltersType>({})
  const { company } = useCompany()
  const navigate = useNavigate()
  const { data: results = [], isLoading } = useSearchEntries(query)

  // Apply advanced filters
  const filtered = useMemo(() => {
    let r = results
    if (advFilters.dateFrom) r = r.filter((e) => e.createdAt.slice(0, 10) >= advFilters.dateFrom!)
    if (advFilters.dateTo) r = r.filter((e) => e.createdAt.slice(0, 10) <= advFilters.dateTo!)
    if (advFilters.status && advFilters.status !== 'all') r = r.filter((e) => e.status === advFilters.status)
    if (advFilters.source && advFilters.source !== 'all') r = r.filter((e) => e.source === advFilters.source)
    if (advFilters.counterparty) {
      const cp = advFilters.counterparty.toLowerCase()
      r = r.filter((e) => (e.metadata.counterparty || '').toLowerCase().includes(cp) || (e.metadata.inn || '').includes(cp))
    }
    if (advFilters.amountMin !== undefined) {
      r = r.filter((e) => Number(e.metadata.amount || 0) >= advFilters.amountMin!)
    }
    if (advFilters.amountMax !== undefined) {
      r = r.filter((e) => Number(e.metadata.amount || 0) <= advFilters.amountMax!)
    }
    return r
  }, [results, advFilters])

  const paginatedResults = useMemo(
    () => filtered.slice((page - 1) * pageSize, page * pageSize),
    [filtered, page, pageSize],
  )

  // Sync with URL
  useEffect(() => {
    const q = searchParams.get('q')
    if (q && q !== query) setQuery(q)
  }, [searchParams])

  // Reset pagination on query/filter change
  useEffect(() => { setPage(1) }, [query, advFilters])

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
    <div className="space-y-6">
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

      {/* Advanced filters */}
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

      {query.length >= 2 && !isLoading && filtered.length === 0 && (
        <EmptyState
          icon={SearchX}
          title="Ничего не найдено"
          description={`По запросу «${query}» не найдено документов`}
        />
      )}

      {filtered.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">Найдено: {filtered.length}</p>
          {paginatedResults.map((entry) => {
            const category = getCategoryById(company.profileId, entry.categoryId)
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
                      {category?.label} &middot; {formatDate(entry.createdAt)}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant="outline" className="text-xs">{entry.sourceLabel}</Badge>
                    <StatusBadge status={entry.status} />
                  </div>
                </CardContent>
              </Card>
            )
          })}

          <PaginationWrapper
            total={filtered.length}
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
