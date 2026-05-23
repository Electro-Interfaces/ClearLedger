/**
 * Страница «1С → Периоды». Реальная сводка из ClearLedger API:
 * - Бакеты (year, month) с количеством документов из AccountingDoc.
 * - Статус (open/closed) из таблицы Period — если запись есть.
 * Кнопка «Закрыть/Открыть» — оперативно меняет статус (closure_source=manual).
 * В производстве статус должен прилетать из БП ГИГ через
 * ДатыЗапретаИзменения.
 */

import { useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  CalendarClock, Lock, Unlock, Loader2,
} from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

import { useCompany } from '@/contexts/CompanyContext'
import { get, post } from '@/services/apiClient'

interface PeriodRow {
  id: string | null
  year: number
  month: number
  status: 'open' | 'closed'
  closedAt: string | null
  closureSource: 'manual' | 'from_bp' | 'derived'
  docsCount: number
  minDate: string | null
  maxDate: string | null
}

interface PeriodsSummary {
  items: PeriodRow[]
  totalDocs: number
  openCount: number
  closedCount: number
}

const MONTH_NAMES = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

async function fetchPeriods(companyId: string): Promise<PeriodsSummary> {
  return get<PeriodsSummary>('/api/periods/summary', { company_id: companyId })
}

async function togglePeriod(companyId: string, year: number, month: number, closed: boolean): Promise<PeriodRow> {
  return post<PeriodRow>('/api/periods/toggle', {
    company_id: companyId,
    year, month, closed,
  })
}

const SOURCE_META: Record<string, { label: string; cls: string }> = {
  from_bp: { label: 'из БП',   cls: 'border-emerald-400/40 text-emerald-300/70' },
  manual:  { label: 'вручную', cls: 'border-amber-400/40 text-amber-300/70' },
  derived: { label: 'выведено',cls: 'border-zinc-600 text-zinc-400' },
}

export function PeriodsPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['periods-summary', companyId],
    queryFn: () => fetchPeriods(companyId),
  })

  const mutation = useMutation({
    mutationFn: (vars: { year: number; month: number; closed: boolean }) =>
      togglePeriod(companyId, vars.year, vars.month, vars.closed),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['periods-summary', companyId] })
    },
  })

  async function handleToggle(row: PeriodRow) {
    const next = row.status === 'closed' ? 'open' : 'closed'
    try {
      await mutation.mutateAsync({ year: row.year, month: row.month, closed: next === 'closed' })
      toast.success(`${MONTH_NAMES[row.month - 1]} ${row.year} → ${next === 'closed' ? 'закрыт' : 'открыт'}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Ошибка изменения статуса')
    }
  }

  const stats = useMemo(() => ({
    total:  data?.items.length ?? 0,
    open:   data?.openCount ?? 0,
    closed: data?.closedCount ?? 0,
    docs:   data?.totalDocs ?? 0,
  }), [data])

  return (
    <div className="space-y-4 max-w-4xl">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Учётные периоды</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Сводка месяцев по импортированным документам БП ГИГ. Закрытые
          периоды — эталон для сверки. В производстве статус должен приходить
          из БП через <code className="font-mono text-foreground/70">ДатыЗапретаИзменения</code>;
          пока его можно менять вручную.
        </p>
      </div>

      <div className="grid grid-cols-4 gap-2">
        <Card className="py-3 gap-1">
          <CardHeader className="pb-0">
            <CardDescription className="text-[10px] uppercase tracking-wide">Месяцев</CardDescription>
            <CardTitle className="text-2xl font-bold tabular-nums">{stats.total}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="py-3 gap-1">
          <CardHeader className="pb-0">
            <CardDescription className="text-[10px] uppercase tracking-wide">Документов</CardDescription>
            <CardTitle className="text-2xl font-bold tabular-nums">{stats.docs.toLocaleString('ru-RU')}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="py-3 gap-1">
          <CardHeader className="pb-0">
            <CardDescription className="text-[10px] uppercase tracking-wide">Открыто</CardDescription>
            <CardTitle className="text-2xl font-bold tabular-nums text-emerald-500">{stats.open}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="py-3 gap-1">
          <CardHeader className="pb-0">
            <CardDescription className="text-[10px] uppercase tracking-wide">Закрыто</CardDescription>
            <CardTitle className="text-2xl font-bold tabular-nums text-muted-foreground">{stats.closed}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" />
            Периоды компании
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-0">
          {error && <p className="text-[11px] text-destructive">{(error as Error).message}</p>}
          {isLoading && <p className="text-[11px] text-muted-foreground py-3">Загружаю…</p>}

          <div className="grid grid-cols-[160px_120px_140px_120px_1fr_120px] gap-3 px-2 py-1.5 text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wide border-b border-border/40">
            <span>Период</span>
            <span>Статус</span>
            <span>Закрыт</span>
            <span>Источник</span>
            <span className="text-right">Документов</span>
            <span className="text-right">Действие</span>
          </div>

          <div className="max-h-[520px] overflow-y-auto">
            {(data?.items ?? []).map((p) => {
              const monthName = MONTH_NAMES[p.month - 1]
              const StatusIcon = p.status === 'closed' ? Lock : Unlock
              const sourceMeta = SOURCE_META[p.closureSource] ?? SOURCE_META.derived
              return (
                <div key={`${p.year}-${p.month}`}
                  className="grid grid-cols-[160px_120px_140px_120px_1fr_120px] gap-3 items-center px-2 py-2 text-xs border-b border-border/30 hover:bg-accent/30 last:border-b-0">
                  <div className="flex items-center gap-2">
                    <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="font-medium">{monthName} {p.year}</span>
                  </div>
                  <div>
                    <Badge variant="outline" className={`text-[10px] h-5 px-1.5 gap-1 ${
                      p.status === 'closed'
                        ? 'text-muted-foreground bg-muted/50 border-transparent'
                        : 'text-emerald-300/80 border-emerald-400/40'
                    }`}>
                      <StatusIcon className="h-3 w-3" />
                      {p.status === 'closed' ? 'Закрыт' : 'Открыт'}
                    </Badge>
                  </div>
                  <span className="text-muted-foreground tabular-nums text-[11px]">
                    {p.closedAt ? format(new Date(p.closedAt), 'dd.MM.yyyy') : '—'}
                  </span>
                  <div>
                    <Badge variant="outline" className={`text-[10px] h-5 px-1.5 ${sourceMeta.cls}`}>
                      {sourceMeta.label}
                    </Badge>
                  </div>
                  <span className="text-right tabular-nums font-mono text-[11px]">
                    {p.docsCount.toLocaleString('ru-RU')}
                  </span>
                  <div className="text-right">
                    <Button size="sm" variant="ghost"
                      className="h-6 px-2 text-[10px]"
                      disabled={mutation.isPending}
                      onClick={() => handleToggle(p)}>
                      {mutation.isPending
                        ? <Loader2 className="h-3 w-3 animate-spin" />
                        : (p.status === 'closed' ? 'Открыть' : 'Закрыть')}
                    </Button>
                  </div>
                </div>
              )
            })}
            {data && data.items.length === 0 && (
              <div className="text-center text-[11px] text-muted-foreground py-6">
                Нет периодов — импортируйте документы из 1С через «Документы → Обновить из 1С».
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
