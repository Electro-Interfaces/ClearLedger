/**
 * «Магазин» → Станции → Рабочее место АЗС.
 *
 * Менеджер выбирает станцию и работает на ней так же, как товаровед у кассы:
 * приёмка, инвентаризация, остатки, карточки. Внутри — не копия экранов, а сам
 * агент станции: он и есть источник правды АЗС, а вторая реализация тех же
 * операций в центре разъехалась бы с первой в первый же месяц.
 *
 * Станция за CGNAT, поэтому запрос идёт через мастер и хаб TradeLink по тому же
 * overlay, по которому станция и так на связи. Офлайн-станция не открывается —
 * и это честно: её база живёт на месте, без канала центр до неё не дотянется.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MonitorSmartphone, RadioTower } from 'lucide-react'
import { getStoreStations, type StoreStation } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'

export function StoreStationConsolePanel() {
  const { company } = useCompany()
  const [station, setStation] = useState<number | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка станций…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить список станций</div>
  if (!data) return null

  const stations = data.stations as StoreStation[]

  // Открытая станция занимает весь холст: в рабочем месте работают, а не
  // заглядывают в него — тесная рамка мешала бы вводить документы.
  if (station !== null) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between gap-4 border-b border-border px-4 py-2">
          <div className="text-sm">
            <b>АЗС {station}</b>
            <span className="ml-2 text-muted-foreground">
              рабочее место станции · вы работаете на ней из центра, документы уйдут вашим именем
            </span>
          </div>
          <div className="flex items-center gap-3">
            <a className="text-xs text-muted-foreground hover:text-foreground"
               href={`/api/store/station/${station}/console/`} target="_blank" rel="noreferrer">
              отдельной вкладкой
            </a>
            <Button size="sm" variant="outline" onClick={() => setStation(null)}>
              К списку станций
            </Button>
          </div>
        </div>
        <iframe
          title={`Рабочее место АЗС ${station}`}
          src={`/api/store/station/${station}/console/`}
          className="w-full flex-1 border-0"
        />
      </div>
    )
  }

  return (
    <div className="max-w-4xl space-y-6 p-6">
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold">
          <MonitorSmartphone className="h-4 w-4 text-primary" />Рабочее место АЗС
        </h3>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          Выберите станцию, чтобы работать на ней из центра: приёмка, инвентаризация, остатки,
          карточки. Открывается сам агент станции, а не копия его экранов, — всё введённое
          сразу становится учётом АЗС и помечается вашим именем.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {stations.map((s) => {
          const онлайн = s.state === 'онлайн'
          return (
            <div key={s.station_id}
                 className={`rounded-lg border p-4 ${онлайн ? 'border-border' : 'border-dashed border-border'}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 font-medium">
                    <RadioTower className={`h-4 w-4 ${онлайн ? 'text-emerald-500' : 'text-muted-foreground'}`} />
                    АЗС {s.station_id}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {онлайн
                      ? `на связи · агент ${s.version ?? '—'}${s.queue_pending > 0 ? ` · в очереди ${s.queue_pending}` : ''}`
                      : `${s.state} · работа идёт на станции, данные копятся у неё`}
                  </div>
                </div>
                <Button size="sm" disabled={!онлайн} onClick={() => setStation(s.station_id)}
                        title={онлайн ? 'Открыть рабочее место станции' : 'Станция не на связи'}>
                  Работать
                </Button>
              </div>
            </div>
          )
        })}
      </div>

      {stations.length === 0 && (
        <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          Ни одна станция ещё не выходила на связь.
        </div>
      )}
    </div>
  )
}
