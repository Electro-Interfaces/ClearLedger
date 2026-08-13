/**
 * Отпуск электроэнергии станцией за период.
 *
 * Вопрос эксплуатации «сколько эта станция отпустила с … по …» до сих пор
 * решался только через «Реализацию», а она — разрез продаж: у рабочих мест
 * эксплуатации и проектов её нет. Поэтому энергия вынесена отдельной вкладкой,
 * сквозной для всех продуктов, и денег в ней нет вовсе.
 *
 * Канон цифр раздела: средние — по СОСТОЯВШИМСЯ заправкам (треть сессий тока не
 * даёт), «зарядились» — доля визитов с отпуском, а не доля result='Complete'.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { BarChart } from '@/components/ui/bar-chart'
import { Zap, Plug, Loader2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { getStationEnergy, type StationEnergy } from '@/services/chargePaymentsService'
import type { ServiceLocation } from '@/types/location'
import { SectionCard, Placeholder, ScrollTab, typeFlags } from './shared'
import { MetricTile } from '@/components/ui/metric-tile'

const RANGE_KEY = 'ezs-energy-range'
const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

/** Локальная дата в «YYYY-MM-DD» (toISOString сдвинул бы на часовой пояс). */
function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Готовые периоды: подпись → границы. Кнопкой закрывается 9 из 10 вопросов. */
const PRESETS: { label: string; range: () => [string, string] }[] = [
  { label: '7 дней', range: () => { const t = new Date(); const f = new Date(); f.setDate(t.getDate() - 6); return [iso(f), iso(t)] } },
  { label: '30 дней', range: () => { const t = new Date(); const f = new Date(); f.setDate(t.getDate() - 29); return [iso(f), iso(t)] } },
  { label: 'Этот месяц', range: () => { const t = new Date(); return [iso(new Date(t.getFullYear(), t.getMonth(), 1)), iso(t)] } },
  { label: 'Прошлый месяц', range: () => { const t = new Date(); return [iso(new Date(t.getFullYear(), t.getMonth() - 1, 1)), iso(new Date(t.getFullYear(), t.getMonth(), 0))] } },
  { label: 'Год', range: () => { const t = new Date(); const f = new Date(); f.setFullYear(t.getFullYear() - 1); f.setDate(f.getDate() + 1); return [iso(f), iso(t)] } },
]

export function EnergyTab({ location }: { location: ServiceLocation }) {
  const { companyId } = useCompany()
  // Период держим в сессии браузера: Radix размонтирует содержимое вкладки, и
  // выбранные границы терялись при каждом уходе на «Паспорт» и обратно
  // (замечание И. Н. Ступина 13.08.2026). Заодно он сохраняется при переходе к
  // другой станции — сравнивать соседние объекты за один период удобнее.
  const [[from, to], setRange] = useState<[string, string]>(() => {
    const saved = sessionStorage.getItem(RANGE_KEY)
    if (saved) {
      const [f, t] = saved.split('|')
      if (f && t) return [f, t]
    }
    return PRESETS[1].range()
  })
  const applyRange = (r: [string, string]) => {
    sessionStorage.setItem(RANGE_KEY, r.join('|'))
    setRange(r)
  }

  const { data, isLoading, isError } = useQuery<StationEnergy>({
    queryKey: ['station-energy', companyId, location.id, from, to],
    queryFn: () => getStationEnergy(companyId!, location.id, from, to),
    enabled: !!companyId && !!location.id && !!from && !!to && typeFlags(location.type).isEv,
  })

  const chart = useMemo(() => (data?.series ?? []).map((s) => ({
    period: data?.bucket === 'day' ? s.bucket.slice(8) + '.' + s.bucket.slice(5, 7) : s.bucket,
    'кВт·ч': Math.round(s.kwh),
  })), [data])

  if (!typeFlags(location.type).isEv) {
    return (
      <ScrollTab>
        <Placeholder icon={Zap} title="Отпуск энергии не ведётся"
          text="Вкладка считает зарядные сессии — она заполняется только для электрозарядных станций." />
      </ScrollTab>
    )
  }

  const t = data?.totals
  const chargedPct = t?.sessions ? Math.round((t.charged / t.sessions) * 100) : 0
  const visitPct = t?.visits ? Math.round((t.visitsCharged / t.visits) * 1000) / 10 : 0

  return (
    <ScrollTab>
      {/* Период: пресеты + произвольные границы */}
      <div className="flex flex-wrap items-center gap-1.5">
        {PRESETS.map((p) => {
          const [f, tt] = p.range()
          const on = f === from && tt === to
          return (
            <button key={p.label} type="button" onClick={() => applyRange([f, tt])}
              className={`h-7 rounded-md border px-2.5 text-xs transition-colors ${
                on ? 'border-primary bg-primary text-primary-foreground'
                   : 'border-input text-muted-foreground hover:text-foreground'}`}>
              {p.label}
            </button>
          )
        })}
        <span className="mx-1 h-5 w-px bg-border" />
        <input type="date" value={from} max={to} onChange={(e) => applyRange([e.target.value, to])}
          className="h-7 rounded-md border border-input bg-background px-2 text-xs" />
        <span className="text-xs text-muted-foreground">—</span>
        <input type="date" value={to} min={from} onChange={(e) => applyRange([from, e.target.value])}
          className="h-7 rounded-md border border-input bg-background px-2 text-xs" />
      </div>

      {isLoading && (
        <div className="flex justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      )}
      {isError && <p className="text-sm text-muted-foreground">Не удалось получить данные за период.</p>}

      {t && !isLoading && (t.sessions === 0 ? (
        <Placeholder icon={Zap} title="За период сессий нет"
          text="По этой станции в выбранных границах зарядных сессий не было. Проверьте другой период или сопоставление станции с выгрузкой (вкладка «Интеграции»)." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <MetricTile label="Отпущено" value={`${nf0.format(t.kwh)} кВт·ч`}
              hint={`за период ${new Date(from).toLocaleDateString('ru-RU')} — ${new Date(to).toLocaleDateString('ru-RU')}`} />
            <MetricTile label="Заправок" value={nf0.format(t.charged)}
              hint={`${chargedPct} % из ${nf0.format(t.sessions)} сессий дали ток`} />
            <MetricTile label="Средняя заправка" value={`${nf1.format(t.avgKwh)} кВт·ч`}
              hint={`${nf0.format(t.avgMin)} мин на состоявшуюся`} />
            <MetricTile label="Клиенты зарядились" value={`${nf1.format(visitPct)} %`}
              hint={`${nf0.format(t.visitsCharged)} из ${nf0.format(t.visits)} визитов`} />
            <MetricTile label="В среднем за месяц" value={`${nf0.format(t.avgMonthKwh)} кВт·ч`}
              hint={`по ${t.months} ${t.months === 1 ? 'месяцу' : 'месяцам'} периода, включая простой`} />
          </div>

          <Card>
            <CardContent className="pt-5">
              <div className="mb-3 text-xs font-medium text-muted-foreground">
                Отпуск {data.bucket === 'day' ? 'по дням' : 'по месяцам'}
              </div>
              <BarChart className="h-56" data={chart} index="period" categories={['кВт·ч']}
                colors={['green']} valueFormatter={(v) => nf0.format(v)} showLegend={false} />
            </CardContent>
          </Card>

          {data.byConnector.length > 0 && (
            <SectionCard title="По коннекторам" icon={Plug}>
              <table className="w-full text-xs">
                <thead><tr className="border-b text-muted-foreground">
                  <th className="p-2 text-left font-medium">Коннектор</th>
                  <th className="p-2 text-left font-medium">Тип</th>
                  <th className="p-2 text-right font-medium">Сессий</th>
                  <th className="p-2 text-right font-medium">кВт·ч</th>
                  <th className="p-2 text-right font-medium">Доля</th>
                </tr></thead>
                <tbody>
                  {data.byConnector.map((c) => (
                    <tr key={c.no} className="border-b last:border-0">
                      <td className="p-2 font-mono">{c.no}</td>
                      <td className="p-2 text-muted-foreground">{c.type || '—'}</td>
                      <td className="p-2 text-right tabular-nums">{nf0.format(c.sessions)}</td>
                      <td className="p-2 text-right tabular-nums">{nf0.format(c.kwh)}</td>
                      <td className="p-2 text-right tabular-nums text-muted-foreground">
                        {t.kwh ? `${Math.round((c.kwh / t.kwh) * 100)} %` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </SectionCard>
          )}
        </>
      ))}
    </ScrollTab>
  )
}
