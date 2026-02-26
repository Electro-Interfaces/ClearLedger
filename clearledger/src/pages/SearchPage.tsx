import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, FileText } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { StatusBadge } from '@/components/data/StatusBadge'
import { mockEntries } from '@/services/mockData'
import { useCompany } from '@/contexts/CompanyContext'
import { getCategoryById } from '@/config/categories'

export function SearchPage() {
  const [query, setQuery] = useState('')
  const { company, companyId } = useCompany()
  const navigate = useNavigate()

  const results = useMemo(() => {
    if (query.length < 2) return []
    const q = query.toLowerCase()
    return mockEntries
      .filter((e) => (e.companyId === companyId || companyId === 'npk'))
      .filter((e) =>
        e.title.toLowerCase().includes(q) ||
        Object.values(e.metadata).some((v) => v.toLowerCase().includes(q))
      )
  }, [query, companyId])

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

      {query.length >= 2 && results.length === 0 && (
        <div className="text-center py-12 text-muted-foreground">
          Ничего не найдено по запросу &laquo;{query}&raquo;
        </div>
      )}

      {results.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">Найдено: {results.length}</p>
          {results.map((entry) => {
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
                      {category?.label} &middot; {new Date(entry.createdAt).toLocaleDateString('ru-RU')}
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
        </div>
      )}
    </div>
  )
}
