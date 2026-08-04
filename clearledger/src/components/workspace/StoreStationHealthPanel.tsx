/**
 * «Магазин» → Станции → Состояние станций.
 *
 * Что на конкретной АЗС требует человека: товар, который касса не пробьёт;
 * позиции, не уехавшие в кассу; минусы в физике склада; устаревшие ставки НДС;
 * кончающиеся коды нефтесервера; расхождение смен с 1С.
 *
 * Эти находки считались и раньше — но жили в машинном контуре (`/edge/alerts`
 * по api-key) и доезжали до людей письмом оператора. Экран убирает посредника:
 * тот же отчёт, только в «Магазине» и по каждой станции парка.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ShieldAlert, TriangleAlert, CheckCircle2, RadioTower } from 'lucide-react'
import {
  getStoreStations, getStoreStationHealth, type StoreStation,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

const УРОВЕНЬ = {
  critical: { label: 'критично', icon: ShieldAlert, точка: 'bg-red-500', текст: 'text-red-400/90' },
  warning: { label: 'внимание', icon: TriangleAlert, точка: 'bg-amber-500', текст: 'text-amber-300/90' },
} as const

function Сводка({ label, value, cls, hint }: {
  label: string; value: string | number; cls?: string; hint?: string
}) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-xl font-semibold tabular-nums ${cls ?? ''}`}>{value}</div>
      {hint && <div className="mt-0.5 text-[10px] text-muted-foreground/70">{hint}</div>}
    </div>
  )
}

export function StoreStationHealthPanel() {
  const { company } = useCompany()
  const [станция, выбрать] = useState<number | null>(null)

  const { data: парк } = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
  })
  const станции = (парк?.stations ?? []) as StoreStation[]

  // Первая станция выбирается сама: экран без выбранной АЗС не показывает
  // ничего, а в парке из одной станции выбор — лишний шаг.
  useEffect(() => {
    if (станция === null && станции.length > 0) выбрать(станции[0].station_id)
  }, [станция, станции])

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-station-health', company.id, станция],
    queryFn: () => getStoreStationHealth(станция as number),
    enabled: станция !== null,
    refetchInterval: 120_000,
  })

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Состояние станций</h3>
        <p className="text-xs text-muted-foreground">
          Что на АЗС требует человека прямо сейчас: касса и выгрузка, физика склада, НСИ,
          коды нефтесервера, сходимость смен с 1С. Считается по свежему снимку станции —
          если снимка нет, это первая же строка отчёта.
        </p>
      </div>

      {станции.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {станции.map((s) => (
            <button key={s.station_id} type="button" onClick={() => выбрать(s.station_id)}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs tabular-nums ${
                станция === s.station_id
                  ? 'border-primary/60 bg-primary/10 text-foreground'
                  : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
              <RadioTower className={`h-3.5 w-3.5 ${s.state === 'онлайн' ? 'text-emerald-500' : 'text-muted-foreground'}`} />
              АЗС {s.station_id}
            </button>
          ))}
        </div>
      )}

      {станция === null ? (
        <div className="rounded-lg border border-dashed border-border/50 p-6 text-sm text-muted-foreground">
          Ни одна станция ещё не выходила на связь — отчёт строить не по чему.
        </div>
      ) : isLoading ? (
        <div className="text-sm text-muted-foreground">Собираем отчёт по станции…</div>
      ) : error ? (
        <div className="text-sm text-red-400/90">Не удалось получить состояние станции</div>
      ) : !data ? null : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Сводка label="Требует решения" value={data.critical}
                    cls={data.critical > 0 ? 'text-red-400/90' : 'text-emerald-400/90'}
                    hint={data.critical > 0 ? 'работа станции затронута' : 'критичного нет'} />
            <Сводка label="Стоит посмотреть" value={data.warnings}
                    cls={data.warnings > 0 ? 'text-amber-300/90' : ''}
                    hint="не блокирует работу" />
            <Сводка label="Смены с 1С"
                    value={data.shifts_clean === null ? '—' : data.shifts_clean ? 'сходятся' : 'расходятся'}
                    cls={data.shifts_clean === false ? 'text-red-400/90' : ''}
                    hint="подробности — в «Сверке с 1С»" />
            <Сводка label="АЗС" value={data.station_id} hint="отчёт по этой станции" />
          </div>

          {data.alerts.length === 0 ? (
            <div className="flex items-start gap-3 rounded-lg border border-border/50 bg-card/40 p-4">
              <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-400/90" />
              <div>
                <div className="text-sm font-medium">Ничего не требует внимания</div>
                <div className="text-xs text-muted-foreground">
                  Касса и учёт сходятся, минусов и просроченных ставок нет, кодов кассы хватает.
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-2.5">
              {data.alerts.map((a, i) => {
                const у = УРОВЕНЬ[a.level] ?? УРОВЕНЬ.warning
                const Icon = у.icon
                return (
                  <div key={i} className="rounded-lg border border-border/50 bg-card/40 p-3">
                    <div className="flex items-start gap-2.5">
                      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${у.текст}`} />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium">{a.topic}</span>
                          <span className={`inline-flex items-center gap-1 rounded-full border border-border/60 px-1.5 py-0.5 text-[10px] ${у.текст}`}>
                            <span className={`h-1.5 w-1.5 rounded-full ${у.точка}`} />{у.label}
                          </span>
                        </div>
                        <div className="mt-1 text-sm leading-relaxed">{a.text}</div>
                        {a.items && a.items.length > 0 && (
                          <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
                            {a.items.map((it, j) => (
                              <li key={j} className="truncate">· {it}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}
