import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, FileText, SearchX } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
import { SearchSkeleton } from '@/components/common/Skeletons'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { StatusBadge } from '@/components/data/StatusBadge'
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationPrevious,
  PaginationNext,
} from '@/components/ui/pagination'
import { useSearchEntries } from '@/hooks/useEntries'
import { useCompany } from '@/contexts/CompanyContext'
import { getCategoryById } from '@/config/categories'
import { formatDate } from '@/lib/formatDate'

const PAGE_SIZE = 15

export function SearchPage() {
  const [searchParams] = useSearchParams()
  const initialQuery = searchParams.get('q') ?? ''
  const [query, setQuery] = useState(initialQuery)
  const [page, setPage] = useState(1)
  const { company } = useCompany()
  const navigate = useNavigate()
  const { data: results = [], isLoading } = useSearchEntries(query)

  const totalPages = Math.max(1, Math.ceil(results.length / PAGE_SIZE))
  const paginatedResults = useMemo(
    () => results.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [results, page],
  )

  // Синхронизируем с URL при навигации из Header
  useEffect(() => {
    const q = searchParams.get('q')
    if (q && q !== query) setQuery(q)
  }, [searchParams])

  // Сброс пагинации при смене запроса
  useEffect(() => { setPage(1) }, [query])

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

      {query.length < 2 && (
        <div className="text-center py-12 text-muted-foreground">
          Введите минимум 2 символа для поиска
        </div>
      )}

      {query.length >= 2 && isLoading && <SearchSkeleton />}

      {query.length >= 2 && !isLoading && results.length === 0 && (
        <EmptyState
          icon={SearchX}
          title="Ничего не найдено"
          description={`По запросу «${query}» не найдено документов`}
        />
      )}

      {results.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">Найдено: {results.length}</p>
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
                    <div className="font-medium truncate">{entry.title}</div>
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
        </div>
      )}
    </div>
  )
}
