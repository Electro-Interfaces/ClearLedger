/**
 * «Магазин» → Закрытие → Станции.
 *
 * Парк агентов АЗС глазами центра: связь, версия кода, очередь пакетов. Тот же
 * разрез, что оператор видит у себя в шапке рабочего места, только по всем
 * станциям сразу — центр должен понимать состояние АЗС до того, как оттуда
 * придёт письмо.
 *
 * Главное, что экран обязан объяснять человеку: «онлайн» означает «канал есть и
 * обмен возможен», а не «идёт передача». Станция работает и офлайн — данные
 * копятся локально и уходят сами, когда связь вернётся.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RadioTower, PackageOpen, GitCompareArrows, ExternalLink, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { getStoreStations, openStationSession, type StoreStation } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

/** Молчание в человеческих единицах: секунды оператору ничего не говорят. */
function silence(sec: number | null): string {
  if (sec === null) return 'никогда не выходила на связь'
  if (sec < 60) return `${sec} с назад`
  if (sec < 3600) return `${Math.round(sec / 60)} мин назад`
  if (sec < 86400) return `${Math.round(sec / 3600)} ч назад`
  return `${Math.round(sec / 86400)} сут назад`
}

const STATE_STYLE: Record<string, string> = {
  'онлайн': 'bg-emerald-500',
  'офлайн': 'bg-amber-500',
  'молчит': 'bg-red-500',
}

function StateDot({ state }: { state: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`h-2.5 w-2.5 rounded-full ${STATE_STYLE[state] ?? 'bg-zinc-500'}`} />
      {state}
    </span>
  )
}

function Kpi({ icon: Icon, label, value, hint, alarm }: {
  icon: typeof RadioTower; label: string; value: string | number; hint?: string; alarm?: boolean
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />{label}
      </div>
      <div className={`mt-1 text-2xl font-semibold ${alarm ? 'text-red-400/90' : ''}`}>{value}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}

export function StoreStationsPanel() {
  const { company } = useCompany()
  // Открытая станция: рабочее место разворачивается на весь холст, а не в
  // модалке — в нём работают, а не заглядывают.
  const [openStation, setOpenStation] = useState<number | null>(null)

  // Сессия работы открывается до показа рамки: у навигации внутри неё нет
  // токена приложения, и без cookie станция ответит «требуется авторизация».
  async function открыть(id: number) {
    try {
      await openStationSession(id)
      setOpenStation(id)
    } catch (e) {
      toast.error('Не удалось открыть рабочее место', { description: (e as Error).message })
    }
  }
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
    // Экран смотрят, когда что-то пошло не так — данные должны быть свежими.
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка станций…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить состояние станций</div>
  if (!data) return null

  const { stations } = data
  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Станции</h3>
        <p className="text-xs text-muted-foreground">
          Агенты АЗС: связь, версия кода, очередь пакетов. «Онлайн» — канал есть и обмен
          возможен; станция работает и без связи, накапливая данные локально.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi icon={RadioTower} label="На связи" value={`${data.online} из ${data.total}`}
             alarm={data.total > 0 && data.online < data.total} />
        <Kpi icon={PackageOpen} label="Пакетов в очереди" value={data.queue_total}
             hint="ещё не доехало до центра" alarm={data.queue_total > 20} />
        <Kpi icon={GitCompareArrows} label="Версия кода" value={data.desired_version}
             hint={data.version_mismatch ? `расходится на ${data.version_mismatch} станциях` : 'везде совпадает'}
             alarm={data.version_mismatch > 0} />
        <Kpi icon={RadioTower} label="Всего станций" value={data.total} hint="с установленным агентом" />
      </div>

      {stations.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border/50 p-6 text-sm text-muted-foreground">
          Ни одна станция ещё не выходила на связь. Агент ставится на рабочую станцию и сам
          начинает присылать телеметрию — отдельной настройки в центре не нужно.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="px-3 py-2 text-left">АЗС</th>
                <th className="px-3 py-2 text-left">Связь</th>
                <th className="px-3 py-2 text-left">Последний ответ</th>
                <th className="px-3 py-2 text-left">Версия</th>
                <th className="px-3 py-2 text-right">В очереди</th>
                <th className="px-3 py-2 text-right">Отправлено</th>
                <th className="px-3 py-2 text-right">Смена</th>
                <th className="px-3 py-2 text-left">Учёт агента</th>
                <th className="px-3 py-2 text-left">Касса</th>
                <th className="px-3 py-2 text-right">Рабочее место</th>
              </tr>
            </thead>
            <tbody>
              {stations.map((s: StoreStation) => (
                <tr key={s.station_id} className="border-b border-border last:border-0">
                  <td className="px-3 py-2 font-medium">{s.station_id}</td>
                  <td className="px-3 py-2"><StateDot state={s.state} /></td>
                  <td className="px-3 py-2 text-muted-foreground">{silence(s.silence_seconds)}</td>
                  <td className="px-3 py-2">
                    <span className={s.version_ok ? '' : 'text-amber-400/90'}>
                      {s.version ?? '—'}
                    </span>
                    {!s.version_ok && s.version && (
                      <span className="ml-2 text-xs text-muted-foreground">
                        ожидается {data.desired_version}
                      </span>
                    )}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums ${s.queue_pending > 0 ? 'text-amber-400/90' : ''}`}>
                    {s.queue_pending}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{s.queue_sent}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.last_shift ?? '—'}</td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {!s.ledger_stock_ok ? <span className="text-red-400/90">снимок не снят</span>
                      : s.snapshot_at ? new Date(s.snapshot_at).toLocaleString('ru-RU',
                          { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {/* Работа на станции из центра: открываем не копию экранов,
                        а сам агент — он и есть источник правды станции. Офлайн
                        кнопка не жмётся: открывать нечего, канала нет. */}
                    <Button size="sm" variant="outline" disabled={s.state !== 'онлайн'}
                      title={s.state === 'онлайн'
                        ? 'Открыть рабочее место станции: приёмка, инвентаризация, остатки'
                        : 'Станция не на связи — рабочее место недоступно'}
                      onClick={() => void открыть(s.station_id)}>
                      <ExternalLink className="h-3.5 w-3.5 mr-1" />Открыть
                    </Button>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {!s.cash_policy ? 'политика не отправлена'
                      : s.cash_policy.ready ? <span className="text-emerald-400/90">dry-run совпал</span>
                      : <span className="text-amber-400/90">
                          расхождений {s.cash_policy.missing + s.cash_policy.extra + s.cash_policy.price_diff + s.cash_policy.code_diff + s.cash_policy.skipped}
                        </span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Расхождение версий — не авария: обновление агента идёт по команде из центра, а не
        по факту расхождения, и только в рабочее окно с проверенным откатом.
      </p>

      {/* Рабочее место станции внутри «Магазина». Показываем сам агент через
          прокси мастера: это те же экраны, что видит товаровед на АЗС, и всё
          введённое здесь ложится в документы станции именем вошедшего. */}
      {openStation !== null && (
        <div className="fixed inset-0 z-50 flex flex-col bg-background">
          <div className="flex items-center justify-between gap-4 border-b border-border px-4 py-2">
            <div className="text-sm">
              <b>АЗС {openStation}</b>
              <span className="text-muted-foreground ml-2">
                рабочее место станции · вы работаете на ней из центра
              </span>
            </div>
            <div className="flex items-center gap-2">
              <a className="text-xs text-muted-foreground hover:text-foreground"
                 href={`/api/store/station/${openStation}/console/`} target="_blank" rel="noreferrer">
                открыть отдельной вкладкой
              </a>
              <Button size="sm" variant="outline" onClick={() => setOpenStation(null)}>
                <X className="h-3.5 w-3.5 mr-1" />Закрыть
              </Button>
            </div>
          </div>
          <iframe
            title={`Рабочее место АЗС ${openStation}`}
            src={`/api/store/station/${openStation}/console/`}
            className="flex-1 w-full border-0"
          />
        </div>
      )}
    </div>
  )
}
