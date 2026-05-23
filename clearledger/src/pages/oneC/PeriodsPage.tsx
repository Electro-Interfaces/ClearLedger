/**
 * Страница «1С → Периоды». Показывает учётные периоды компании
 * с признаком «закрыт/открыт» — берётся из БП через
 * InformationRegister_ДатыЗапретаИзменения после интеграции.
 * Пока заглушка с локальной демо-моделью.
 */

import { useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CalendarClock, Lock, Unlock, AlertCircle } from 'lucide-react'
import { getOneCConnection } from '@/services/oneCConnectionService'

interface PeriodRow {
  year: number
  month: number
  status: 'open' | 'closed' | 'pending'
  closedAt: string | null
  docsCount: number | null
}

const MONTH_NAMES = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

function buildDemoPeriods(): PeriodRow[] {
  const now = new Date()
  const rows: PeriodRow[] = []
  for (let i = 0; i < 12; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    const year = d.getFullYear()
    const month = d.getMonth() + 1
    const status: PeriodRow['status'] = i < 3 ? 'open' : 'closed'
    rows.push({
      year, month,
      status,
      closedAt: status === 'closed'
        ? new Date(year, month, 5).toISOString().slice(0, 10)
        : null,
      docsCount: null,
    })
  }
  return rows
}

const STATUS_META = {
  open: { label: 'Открыт', icon: Unlock, color: 'text-emerald-500', bg: 'bg-emerald-500/10' },
  closed: { label: 'Закрыт', icon: Lock, color: 'text-muted-foreground', bg: 'bg-muted/50' },
  pending: { label: 'В процессе', icon: AlertCircle, color: 'text-amber-500', bg: 'bg-amber-500/10' },
} as const

export function PeriodsPage() {
  const conn = getOneCConnection()
  const periods = useMemo(() => buildDemoPeriods(), [])
  const isConnected = conn.status === 'connected'

  const stats = useMemo(() => ({
    total: periods.length,
    closed: periods.filter((p) => p.status === 'closed').length,
    open: periods.filter((p) => p.status === 'open').length,
  }), [periods])

  return (
    <div className="space-y-4 max-w-4xl">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Учётные периоды</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Реплицируются из БП через <code className="font-mono text-foreground/70">ДатыЗапретаИзменения</code>.
          Закрытые периоды = эталон для сверки, в них данные не редактируются.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Card className="py-3 gap-1">
          <CardHeader className="pb-0">
            <CardDescription className="text-[10px] uppercase tracking-wide">Всего</CardDescription>
            <CardTitle className="text-2xl font-bold tabular-nums">{stats.total}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="py-3 gap-1">
          <CardHeader className="pb-0">
            <CardDescription className="text-[10px] uppercase tracking-wide">Закрытые</CardDescription>
            <CardTitle className="text-2xl font-bold tabular-nums text-muted-foreground">
              {stats.closed}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card className="py-3 gap-1">
          <CardHeader className="pb-0">
            <CardDescription className="text-[10px] uppercase tracking-wide">Открытые</CardDescription>
            <CardTitle className="text-2xl font-bold tabular-nums text-emerald-500">
              {stats.open}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" />
            Периоды компании
            <span className="text-xs text-muted-foreground font-normal ml-auto">
              {isConnected ? 'из БП ГИГ' : 'демо (не из БП)'}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-0">
          {!isConnected && (
            <p className="text-[11px] text-amber-500 mb-2">
              ⚠ Подключение к 1С не настроено — показаны демо-периоды.
              Реальные периоды появятся после первой синхронизации.
            </p>
          )}
          <div className="grid grid-cols-[1fr_120px_140px_100px] gap-3 px-2 py-1.5 text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wide border-b border-border/40">
            <span>Период</span>
            <span>Статус</span>
            <span>Закрыт</span>
            <span className="text-right">Документов</span>
          </div>
          <div className="max-h-[440px] overflow-y-auto -mx-2 px-2">
            {periods.map((p) => {
              const meta = STATUS_META[p.status]
              const StatusIcon = meta.icon
              return (
                <div key={`${p.year}-${p.month}`}
                  className="grid grid-cols-[1fr_120px_140px_100px] gap-3 items-center px-2 py-2 text-xs border-b border-border/30 hover:bg-accent/30 last:border-b-0">
                  <div className="flex items-center gap-2">
                    <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="font-medium">{MONTH_NAMES[p.month - 1]} {p.year}</span>
                  </div>
                  <div>
                    <Badge variant="outline" className={`text-[10px] h-5 px-1.5 gap-1 ${meta.color} ${meta.bg} border-transparent`}>
                      <StatusIcon className="h-3 w-3" />
                      {meta.label}
                    </Badge>
                  </div>
                  <span className="text-muted-foreground tabular-nums text-[11px]">
                    {p.closedAt ?? '—'}
                  </span>
                  <span className="text-right text-muted-foreground tabular-nums">
                    {p.docsCount ?? '—'}
                  </span>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
