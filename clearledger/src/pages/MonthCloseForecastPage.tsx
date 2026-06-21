/**
 * Страница «Прогноз закрытия месяца».
 *
 * Сводит управленческий + НДС + контроль документов в одно представление:
 * - факт за дни прошедшие vs экстраполяция на конец месяца
 * - перечень отсутствующих документов (смены без ОРП и т.п.)
 * - риски: незаквиченные пакеты, расхождения, закрытый период
 *
 * Источник — /api/analytics/forecast/month
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, AlertCircle, AlertTriangle, Info, FileWarning, CalendarCheck2 } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { EnergyForecastView } from '@/components/workspace/EnergyForecastView'
import {
  getMonthForecast, fmtMoney, fmtMoneyShort, fmtPct, currentMonthBounds,
} from '@/services/analyticsService'
import { KpiCard } from '@/components/workspace/analytics/AnalyticsPeriodPicker'

const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

export function MonthCloseForecastPage() {
  const init = currentMonthBounds()
  const [year, setYear] = useState(init.year)
  const [month, setMonth] = useState(init.month)
  const { companyId, company } = useCompany()

  const { data, isLoading, error } = useQuery({
    queryKey: ['month-forecast', companyId, year, month],
    queryFn: () => getMonthForecast({ companyId, year, month }),
    enabled: company.profileId !== 'energy',
  })

  // Energy-профиль: закрытие по энергометрикам (эталон = биллинг компании), без ОРП/1С.
  if (company.profileId === 'energy') return <EnergyForecastView />

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <CalendarCheck2 className="h-6 w-6" />
            Прогноз закрытия месяца
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Экстраполяция по фактическим дням + контроль готовности документов и рисков.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={String(month)} onValueChange={(v) => setMonth(Number(v))}>
            <SelectTrigger className="w-[140px] h-9 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {MONTHS.map((m, i) => (
                <SelectItem key={i} value={String(i + 1)}>{m}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={String(year)} onValueChange={(v) => setYear(Number(v))}>
            <SelectTrigger className="w-[100px] h-9 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {[init.year - 1, init.year, init.year + 1].map((y) => (
                <SelectItem key={y} value={String(y)}>{y}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          Расчёт...
        </div>
      )}
      {error && (
        <Card className="border-red-500/40">
          <CardContent className="pt-4 text-sm text-red-400 flex gap-2">
            <AlertCircle className="h-4 w-4 mt-0.5" />
            <span>{(error as Error).message}</span>
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          <ProgressStrip days={data.days_elapsed} total={data.days_total} closed={data.period_closed} />

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="Дней прошло" value={`${data.days_elapsed} / ${data.days_total}`}
              hint={`Средняя выручка/день: ${fmtMoney(data.daily_avg_revenue)} ₽`} />
            <KpiCard label="Выручка факт" value={fmtMoneyShort(data.revenue.fact) + ' ₽'} accent="info" />
            <KpiCard label="Прогноз на месяц" value={fmtMoneyShort(data.revenue.projected) + ' ₽'} accent="success"
              hint={`vs факт +${fmtMoneyShort(data.revenue.projected - data.revenue.fact)} ₽`} />
            <KpiCard label="Прогноз маржи" value={fmtMoneyShort(data.margin.projected) + ' ₽'}
              accent={data.margin.projected >= 0 ? 'success' : 'danger'}
              hint={data.revenue.projected > 0 ? fmtPct(100 * data.margin.projected / data.revenue.projected) : '—'} />
            <KpiCard label="НДС к уплате (факт)" value={fmtMoneyShort(data.vat_payable.fact) + ' ₽'} accent="warning" />
            <KpiCard label="НДС к уплате (прогноз)" value={fmtMoneyShort(data.vat_payable.projected) + ' ₽'} accent="warning" />
            <KpiCard label="Недостающих позиций"
              value={String(data.missing_docs.reduce((a, b) => a + b.count, 0))}
              accent={data.missing_docs.length ? 'warning' : 'success'} />
            <KpiCard label="Рисков"
              value={String(data.risks.length)}
              accent={data.risks.length ? 'danger' : 'success'} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center gap-2 mb-3">
                  <FileWarning className="h-4 w-4 text-amber-400" />
                  <span className="text-sm font-medium">Недостающие документы</span>
                </div>
                {data.missing_docs.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Все документы проведены за фактический период.</p>
                ) : (
                  <div className="space-y-2">
                    {data.missing_docs.map((m, i) => (
                      <div key={i} className="flex items-center justify-between border-b last:border-0 border-border/30 pb-2 last:pb-0">
                        <div>
                          <div className="text-sm font-medium">{m.type}</div>
                          <div className="text-[11px] text-muted-foreground">{m.reason}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-sm font-mono">{m.count} шт</div>
                          <div className="text-[11px] text-muted-foreground font-mono">{fmtMoney(m.amount)} ₽</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center gap-2 mb-3">
                  <AlertTriangle className="h-4 w-4 text-red-400" />
                  <span className="text-sm font-medium">Риски и предупреждения</span>
                </div>
                {data.risks.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Рисков не обнаружено.</p>
                ) : (
                  <div className="space-y-2">
                    {data.risks.map((r, i) => (
                      <div key={i} className="flex items-start gap-2">
                        {r.severity === 'critical' ? (
                          <AlertTriangle className="h-4 w-4 text-red-400 mt-0.5" />
                        ) : r.severity === 'warn' ? (
                          <AlertTriangle className="h-4 w-4 text-amber-400 mt-0.5" />
                        ) : (
                          <Info className="h-4 w-4 text-blue-400 mt-0.5" />
                        )}
                        <div className="flex-1">
                          <div className="text-sm">{r.message}</div>
                          <Badge variant="outline" className="text-[9px] mt-1">{r.type}</Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardContent className="pt-4 text-xs text-muted-foreground space-y-1">
              <p className="font-medium text-sm text-foreground">Метод прогноза</p>
              <p>
                Линейная экстраполяция: <code className="text-foreground">прогноз = факт × (дней_всего / дней_прошло)</code>.
                Не учитывает сезонность, недельные паттерны, выходные. На конец месяца (28+ дней прошло) ошибка падает до ±5%.
                Для точного прогноза в первой декаде месяца используйте прошлогодний месяц как baseline.
              </p>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

function ProgressStrip({ days, total, closed }: { days: number; total: number; closed: boolean }) {
  const pct = Math.min(100, Math.round(100 * days / Math.max(1, total)))
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="font-medium">Прогресс месяца</span>
          <span className="text-muted-foreground">{pct}% ({days} из {total} дней)</span>
          {closed && <Badge variant="outline" className="border-red-400/50 text-red-400">Период закрыт в БП</Badge>}
        </div>
        <div className="h-2 bg-muted rounded overflow-hidden">
          <div className={`h-full ${closed ? 'bg-red-400' : 'bg-primary'}`} style={{ width: `${pct}%` }} />
        </div>
      </CardContent>
    </Card>
  )
}
