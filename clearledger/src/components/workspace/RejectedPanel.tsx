/**
 * Отбракованное источником — зарядки, которые витрина АСУиМ пометила как
 * недостоверные (колонка «подозрительная»).
 *
 * В учёте этих строк нет вовсе: ни в сессиях, ни в платежах (решение МАГа
 * 27.08.2026 — «не показываем вообще»). Поэтому здесь принципиально не считают
 * выручку сети и не сравнивают с ней: экран отвечает на единственный вопрос —
 * где и у кого источник счёл транзакцию битой, и много ли этого.
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Kpi } from './analytics/Kpi'
import { useFilters } from '@/contexts/FilterContext'
import { getRejected, type RejectedSummary } from '@/services/chargePaymentsService'
import { formatBucket } from '@/lib/formatDate'

function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text }: { text: string }) {
  return <div className="p-6 text-center text-sm text-muted-foreground">{text}</div>
}

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const money = (v: number) => `${nf0.format(Math.round(v))} ₽`
const kwh = (v: number) => `${nf0.format(Math.round(v))} кВт·ч`

interface Props { companyId: string; dateFrom: string; dateTo: string }

export function RejectedPanel({ companyId, dateFrom, dateTo }: Props) {
  const { stationCodes, regionIds } = useFilters()
  const stations = stationCodes.map(String)
  const scopeKey = `${stations.join(',')}|${regionIds.join(',')}`

  const { data, isLoading } = useQuery<RejectedSummary>({
    queryKey: ['charge-rejected', companyId, dateFrom, dateTo, scopeKey],
    queryFn: () => getRejected({ companyId, dateFrom, dateTo, stations, regions: regionIds }),
    enabled: !!companyId,
  })

  if (isLoading) return <Loading />
  if (!data || !data.totals.sessions) {
    return <Empty text="За период отбракованных зарядок нет" />
  }
  const t = data.totals

  return (
    <div className="space-y-4 p-4">
      <p className="text-xs text-muted-foreground">
        Зарядки, помеченные источником как недостоверные. В выручку, отпуск и надёжность
        сети они не входят — этих строк нет в учёте. Здесь они собраны для разбора.
      </p>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Отбраковано зарядок" value={nf0.format(t.sessions)}
             sub={`на ${t.stations} станциях, у ${t.users} клиентов`} />
        <Kpi label="Сумма зарядок" value={money(t.amount)}
             sub={`${kwh(t.kwh)} не вошли в отпуск`} />
        <Kpi label="Платежей по ним" value={nf0.format(t.payments)}
             sub={t.payments ? `на ${money(t.paid)} — тоже вне учёта` : 'платежей не было'} />
        <Kpi label="Средняя зарядка" value={money(t.sessions ? t.amount / t.sessions : 0)}
             sub={t.sessions ? `${nf2.format(t.kwh / t.sessions)} кВт·ч` : undefined} />
      </div>

      {/* По месяцам: метки обычно собраны в конкретном эпизоде, а не размазаны. */}
      {data.byMonth.length > 1 && (
        <Card><CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="p-2 text-left font-medium">Месяц</th>
              <th className="p-2 text-right font-medium">Зарядок</th>
              <th className="p-2 text-right font-medium">Сумма</th>
            </tr></thead>
            <tbody>
              {data.byMonth.map((m) => (
                <tr key={m.bucket} className="border-b last:border-0">
                  <td className="p-2">{formatBucket(m.bucket)}</td>
                  <td className="p-2 text-right tabular-nums">{nf0.format(m.count)}</td>
                  <td className="p-2 text-right tabular-nums">{money(m.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>
      )}

      {data.byStation.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">Где отбраковано чаще</div>
          <div className="flex flex-wrap gap-1.5">
            {data.byStation.map((s) => (
              <Badge key={s.code} variant="outline" className="font-normal">
                ЭЗС {s.code} · {nf0.format(s.count)} · {money(s.amount)}
              </Badge>
            ))}
          </div>
        </div>
      )}

      <Card><CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="border-b bg-muted/40 text-muted-foreground">
            <th className="p-2 text-left font-medium">Сессия</th>
            <th className="p-2 text-left font-medium">Когда</th>
            <th className="p-2 text-left font-medium">ЭЗС</th>
            <th className="p-2 text-left font-medium">Клиент</th>
            <th className="p-2 text-right font-medium">кВт·ч</th>
            <th className="p-2 text-right font-medium">Сумма</th>
            <th className="p-2 text-right font-medium">Оплачено</th>
            <th className="p-2 text-left font-medium">Исход</th>
          </tr></thead>
          <tbody>
            {data.items.map((r) => (
              <tr key={r.id} className="border-b last:border-0">
                <td className="p-2 font-mono">{r.sessionId}</td>
                <td className="p-2 whitespace-nowrap">
                  {r.occurredAt ? new Date(r.occurredAt).toLocaleString('ru-RU') : '—'}
                </td>
                <td className="p-2">{r.stationCode || '—'}</td>
                <td className="p-2">{r.userId || '—'}</td>
                <td className="p-2 text-right tabular-nums">{nf2.format(r.energyKwh)}</td>
                <td className="p-2 text-right tabular-nums">{money(r.amount)}</td>
                <td className="p-2 text-right tabular-nums">
                  {r.paidAmount == null ? '—' : money(r.paidAmount)}
                </td>
                <td className="p-2 text-muted-foreground">{r.status || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  )
}
