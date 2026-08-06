/**
 * «Пульс» → «Бизнес» → «Продажи»: деньги сети глазами руководителя.
 *
 * Раньше здесь стояла витрина приложения «Продажи» как есть. Она отвечает
 * коммерсанту («как устроена выручка: коннекторы, часы, тарифы, доли»), а
 * руководителю нужны три других ответа — продаём ли столько же, вся ли сеть в
 * работе и доезжает ли клиент до заряда. Плюс то, чего нет ни в одной витрине:
 * ЧТО именно двигает недельную цифру, поимённо.
 *
 * Окна — от даты последней загруженной сессии, а не от «сегодня»: выгрузка
 * приезжает файлом с отставанием, и календарная неделя резала бы живые данные.
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, MapPin, PlugZap } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getPulseSales } from './pulseService'
import { KpiTile, PulseError, PulseLoading, fmtNum, fmtDate } from './parts'

/** Δ выручки словами и цветом: рост зелёный, падение красное, ноль молчит. */
function Delta({ value }: { value: number }) {
  if (!Math.round(value)) return <span className="text-muted-foreground">—</span>
  return (
    <span className={cn('tabular-nums',
      value > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
      {value > 0 ? '+' : '−'}{fmtNum(Math.abs(value), '₽')}
    </span>
  )
}

export function SalesView() {
  const { company } = useCompany()
  const q = useQuery({
    queryKey: ['pulse-sales', company.id],
    queryFn: () => getPulseSales(company.id),
    refetchInterval: 10 * 60_000,
  })
  const d = q.data

  if (q.isLoading) return <PulseLoading what="продаж" />
  if (q.isError) return <PulseError what="картину продаж" onRetry={() => q.refetch()} />
  if (d && !d.available) {
    return (
      <Card className="border-dashed py-0">
        <CardContent className="p-4 text-xs text-muted-foreground">
          Сессий в пространстве пока нет — считать выручку не по чему.
          Загрузка данных сети живёт в «Данных».
        </CardContent>
      </Card>
    )
  }
  if (!d) return null

  // Сдвиг вниз и вверх разводим по колонкам: смешанный список читается как
  // рейтинг, а вопрос у руководителя другой — «где потеряли и где нашли».
  const down = d.movers.filter((m) => m.delta < 0).slice(0, 5)
  const up = d.movers.filter((m) => m.delta > 0).slice(0, 5)
  const maxMove = Math.max(1, ...d.movers.map((m) => Math.abs(m.delta)))
  const maxRegion = Math.max(1, ...d.regions.map((r) => r.current))

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        {d.kpi.map((k) => <KpiTile key={k.key} k={k} />)}
      </div>

      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Что двигает цифру · неделя против предыдущей
          </h2>
          <span className="text-[11px] text-muted-foreground">
            данные сети на {fmtDate(d.as_of)}
          </span>
        </div>
        <div className="grid min-w-0 gap-2 md:grid-cols-2">
          {[{ title: 'Потеряли', rows: down }, { title: 'Прибавили', rows: up }].map((col) => (
            <Card key={col.title} className="py-0">
              <CardContent className="p-3">
                <div className="mb-2 text-[11px] uppercase tracking-wider text-muted-foreground">
                  {col.title}
                </div>
                {col.rows.length ? (
                  <div className="space-y-1.5">
                    {col.rows.map((m) => (
                      <div key={m.location_id} className="flex items-center gap-2 text-xs">
                        <span className="min-w-0 flex-1 truncate" title={m.station}>{m.station}</span>
                        {/* Полоса — доля этой станции в общем сдвиге недели:
                            «минус 18 тысяч» без масштаба ни о чём не говорит. */}
                        <div className="hidden h-1.5 w-20 shrink-0 rounded bg-muted sm:block">
                          <div className={cn('h-1.5 rounded',
                            m.delta < 0 ? 'bg-red-500/60' : 'bg-emerald-500/60')}
                            style={{ width: `${(Math.abs(m.delta) / maxMove) * 100}%` }} />
                        </div>
                        <span className="w-24 shrink-0 text-right"><Delta value={m.delta} /></span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-muted-foreground">Заметных сдвигов нет.</div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {d.out_stations.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            Выпали из работы · {d.stations_out} {d.stations_out === 1 ? 'станция' : 'станций'}
          </h2>
          {/* Поимённо и с ценой вопроса: «38 станций молчат» не превращается в
              задачу, а «Гоголя 1, последняя сессия 24.07, минус 16 580 ₽» — да. */}
          <Card className="border-amber-500/40 bg-amber-500/5 py-0">
            <CardContent className="divide-y divide-border/40 p-0">
              {d.out_stations.map((s) => (
                <div key={s.location_id} className="flex items-center gap-3 px-3 py-2 text-xs">
                  <PlugZap className="h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
                  <span className="min-w-0 flex-1 truncate" title={s.station}>{s.station}</span>
                  <span className="shrink-0 text-muted-foreground">
                    последняя сессия {fmtDate(s.last_seen)}
                  </span>
                  <span className="w-24 shrink-0 text-right tabular-nums">
                    {fmtNum(s.lost, '₽')}
                  </span>
                </div>
              ))}
              {d.stations_out > d.out_stations.length && (
                <div className="px-3 py-2 text-[11px] text-muted-foreground">
                  и ещё {d.stations_out - d.out_stations.length} — в списке крупнейшие по выручке
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
          Регионы
        </h2>
        <Card className="py-0">
          <CardContent className="divide-y divide-border/40 p-0">
            {d.regions.map((r) => (
              <div key={r.region} className="flex items-center gap-3 px-3 py-2 text-xs">
                <MapPin className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{r.region}</span>
                <span className="hidden w-20 shrink-0 text-right text-muted-foreground sm:block">
                  {r.stations} ст.
                </span>
                <div className="hidden h-1.5 w-24 shrink-0 rounded bg-muted md:block">
                  <div className="h-1.5 rounded bg-primary/60"
                    style={{ width: `${(r.current / maxRegion) * 100}%` }} />
                </div>
                <span className="w-24 shrink-0 text-right font-medium tabular-nums">
                  {fmtNum(r.current, '₽')}
                </span>
                <span className="w-24 shrink-0 text-right">
                  <Delta value={r.current - r.previous} />
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      {/* Лестница погружения: дальше — витрина «Продаж» с коннекторами, часами,
          тарифами и долями клиентов. */}
      <a href="/sales" className="inline-flex min-h-9 items-center gap-1 text-xs text-primary hover:underline sm:min-h-0">
        Открыть приложение «Продажи»<ArrowUpRight className="h-3.5 w-3.5" />
      </a>
    </div>
  )
}
