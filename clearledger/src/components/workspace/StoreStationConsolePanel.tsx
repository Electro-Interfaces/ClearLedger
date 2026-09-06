/**
 * «Магазин» → Станции → Рабочее место АЗС.
 *
 * Администратор выбирает назначенную ему станцию и работает в её агенте:
 * приёмка, инвентаризация, остатки, карточки. Внутри — не копия экранов, а сам
 * агент станции: он и есть источник правды АЗС, а вторая реализация тех же
 * операций в центре разъехалась бы с первой в первый же месяц.
 *
 * Станция за CGNAT, поэтому запрос идёт через мастер и хаб TradeLink по тому же
 * overlay, по которому станция и так на связи. Офлайн-станция не открывается —
 * и это честно: её база живёт на месте, без канала центр до неё не дотянется.
 */
import { useState } from 'react'
import { toast } from 'sonner'
import { useQuery } from '@tanstack/react-query'
import { MonitorSmartphone, RadioTower } from 'lucide-react'
import { getStoreStations, openStationSession, type StoreStation } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { useStoreAccessPolicy } from './useStoreCommercialPolicy'

export function StoreStationConsolePanel() {
  const { company } = useCompany()
  const accessPolicy = useStoreAccessPolicy()
  const [открываем, setОткрываем] = useState<number | null>(null)

  // Станция открывается отдельной вкладкой: центр остаётся там, где был, и к
  // нему возвращаются одним переключением, не теряя фильтров и экрана.
  // Вкладку заводим сразу по клику — после await браузер счёл бы её попапом.
  // Сессию открываем ДО перехода: иначе первая же страница станции придёт
  // с «Требуется авторизация», и человек решит, что сломано рабочее место.
  async function войти(id: number) {
    const вкладка = window.open('about:blank', '_blank')
    setОткрываем(id)
    try {
      await openStationSession(id)
      const адрес = `/api/store/station/${id}/console/`
      if (вкладка) вкладка.location.href = адрес
      else window.open(адрес, '_blank') // попапы запрещены — пробуем ещё раз, уже с браузерным вопросом
    } catch (e) {
      вкладка?.close()
      toast.error('Не удалось открыть рабочее место', { description: (e as Error).message })
    } finally {
      setОткрываем(null)
    }
  }

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка станций…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить список станций</div>
  if (!data) return null

  const stations = data.stations as StoreStation[]

  return (
    <div className="max-w-4xl space-y-6 p-6">
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold">
          <MonitorSmartphone className="h-4 w-4 text-primary" />Рабочее место АЗС
        </h3>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          Выберите станцию, чтобы работать на ней из центра: приёмка, инвентаризация, остатки,
          карточки. Открывается сам агент станции, а не копия его экранов, — всё введённое
          сразу становится учётом АЗС и помечается вашим именем. Станция открывается
          отдельной вкладкой, эта остаётся здесь. Кнопка доступна только администратору,
          назначенному именно на эту АЗС.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {stations.map((s) => {
          const онлайн = s.state === 'онлайн'
          const назначен = accessPolicy?.capabilities.station_administrator.includes(String(s.station_id)) === true
          // Кликается вся карточка, а не только кнопка: выбирают станцию, а не
          // жмут кнопку — целиться мышью незачем. Кнопка остаётся: она называет
          // действие и держит состояние «Открываем…».
          const можно = онлайн && назначен && открываем === null
          const почему = !назначен
            ? 'Нужно назначение «Администратор АЗС» на эту станцию'
            : онлайн ? 'Открыть рабочее место станции' : 'Станция не на связи'
          return (
            <div key={s.station_id}
                 role={можно ? 'button' : undefined}
                 tabIndex={можно ? 0 : undefined}
                 title={почему}
                 onClick={можно ? () => void войти(s.station_id) : undefined}
                 onKeyDown={можно ? (e) => {
                   if (e.key === 'Enter' || e.key === ' ') {
                     e.preventDefault()
                     void войти(s.station_id)
                   }
                 } : undefined}
                 className={`rounded-lg border p-4 transition-colors ${
                   онлайн ? 'border-border' : 'border-dashed border-border'} ${
                   можно ? 'cursor-pointer hover:border-primary/60 hover:bg-primary/5'
                         : 'cursor-not-allowed opacity-90'}`}>
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
                  {/* Кто уже там. Видно до входа: столкнуться на одном документе
                      дешевле предупредить, чем потом объяснять отказ в сохранении.
                      Данные приезжают телеметрией раз в минуту — отсюда «минуту назад». */}
                  {(s.active_users?.length ?? 0) > 0 && (
                    <div className="mt-1 text-xs text-amber-500">
                      сейчас работает: {s.active_users.map((u) =>
                        u.remote ? `${u.name} (из центра)` : u.name).join(', ')}
                    </div>
                  )}
                </div>
                <Button size="sm" disabled={!можно}
                        onClick={(e) => { e.stopPropagation(); void войти(s.station_id) }}
                        title={почему}>
                  {открываем === s.station_id ? 'Открываем…' : 'Работать'}
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
