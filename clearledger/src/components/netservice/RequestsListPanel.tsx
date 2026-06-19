/**
 * Рабочий список заявок HubEx (сетевой, по всем станциям) — поиск, фильтр статуса,
 * пагинация, drill-down в станцию. Цвета статусов/критичности — из API.
 */
import { useEffect, useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Search, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'
import { getTasks, type NetFilters } from '@/services/netServiceService'

const PAGE = 50
const STATUSES = [
  { v: 'open', label: 'Открытые' },
  { v: 'overdue', label: 'Просроченные' },
  { v: 'closed', label: 'Закрытые' },
  { v: 'all', label: 'Все' },
]

function fmtDate(s: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return isNaN(d.getTime()) ? '—' : d.toLocaleDateString('ru-RU')
}

export function RequestsListPanel({ companyId, filters, onOpenStation }: {
  companyId: string
  filters: NetFilters
  onOpenStation: (locationId: string | null) => void
}) {
  const [status, setStatus] = useState('open')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(0)

  useEffect(() => { setPage(0) }, [status, q])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['netservice', 'tasks', companyId, filters, status, q, page],
    queryFn: () => getTasks(companyId, { ...filters, status, q: q || undefined, limit: PAGE, offset: page * PAGE }),
    enabled: !!companyId,
    placeholderData: keepPreviousData,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE))

  return (
    <div className="p-5 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} className="pl-8 h-9"
            placeholder="Поиск: номер, объект, исполнитель, подрядчик…" />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="h-9 w-[170px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            {STATUSES.map((s) => <SelectItem key={s.v} value={s.v}>{s.label}</SelectItem>)}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground ml-auto inline-flex items-center gap-2">
          {isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Найдено: {total.toLocaleString('ru-RU')}
        </span>
      </div>

      <div className="rounded-md border border-border/50">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[90px]">Номер</TableHead>
              <TableHead>Статус</TableHead>
              <TableHead className="hidden md:table-cell">Критичность</TableHead>
              <TableHead className="hidden lg:table-cell">Вид работ</TableHead>
              <TableHead>Объект</TableHead>
              <TableHead className="hidden lg:table-cell">Исполнитель</TableHead>
              <TableHead className="hidden sm:table-cell w-[100px]">Создано</TableHead>
              <TableHead className="hidden sm:table-cell w-[100px]">Срок</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow><TableCell colSpan={8} className="text-center py-10">
                <Loader2 className="h-5 w-5 animate-spin mx-auto text-muted-foreground" />
              </TableCell></TableRow>
            ) : rows.length === 0 ? (
              <TableRow><TableCell colSpan={8} className="text-center text-sm text-muted-foreground py-8">
                Заявок не найдено.
              </TableCell></TableRow>
            ) : rows.map((t) => (
              <TableRow key={t.hubex_id}
                className={t.location_id ? 'cursor-pointer hover:bg-secondary/50' : undefined}
                onClick={t.location_id ? () => onOpenStation(t.location_id) : undefined}>
                <TableCell className="font-mono text-xs font-medium">{t.number}</TableCell>
                <TableCell>
                  {t.status && (
                    <Badge variant="secondary" className="text-[10px]"
                      style={t.status_color ? { backgroundColor: `#${t.status_color}26`, color: `#${t.status_color}` } : undefined}>
                      {t.status}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  {t.criticality && (
                    <Badge variant="outline" className="text-[10px]"
                      style={t.criticality_color ? { borderColor: `#${t.criticality_color}`, color: `#${t.criticality_color}` } : undefined}>
                      {t.criticality}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="hidden lg:table-cell text-muted-foreground text-xs max-w-[200px] truncate">{t.work_type}</TableCell>
                <TableCell className="text-sm max-w-[220px] truncate">{t.asset_name}</TableCell>
                <TableCell className="hidden lg:table-cell text-muted-foreground text-xs">{t.assignee || '—'}</TableCell>
                <TableCell className="hidden sm:table-cell text-xs tabular-nums">{fmtDate(t.ts_created)}</TableCell>
                <TableCell className="hidden sm:table-cell text-xs tabular-nums">
                  <span className={t.is_overdue ? 'text-red-600 dark:text-red-400 font-medium' : ''}>{fmtDate(t.ts_deadline)}</span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {pageCount > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Страница {page + 1} из {pageCount}</span>
          <div className="flex gap-1">
            <Button variant="outline" size="icon" className="h-8 w-8" disabled={page === 0}
              onClick={() => setPage(page - 1)}><ChevronLeft className="h-4 w-4" /></Button>
            <Button variant="outline" size="icon" className="h-8 w-8" disabled={page >= pageCount - 1}
              onClick={() => setPage(page + 1)}><ChevronRight className="h-4 w-4" /></Button>
          </div>
        </div>
      )}
    </div>
  )
}
