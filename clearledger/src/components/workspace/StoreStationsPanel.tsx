/**
 * «Магазин» → Станции → Парк станций.
 *
 * Экран про обмен, а не про работу на АЗС: сеансы связи, что и сколько доехало
 * наверх, что центр отправил вниз и дошло ли. Работают на станции в соседнем
 * пункте «Рабочее место АЗС» — заходить туда отсюда незачем, иначе один экран
 * пытается быть и диспетчерской канала, и рабочим местом товароведа.
 *
 * Главное, что экран обязан объяснять человеку: «онлайн» означает «канал есть и
 * обмен возможен», а не «идёт передача». Станция работает и офлайн — данные
 * копятся локально и уходят одним сеансом, когда связь вернётся.
 */
import { useQuery } from '@tanstack/react-query'
import { RadioTower, PackageOpen, ArrowUpFromLine, ArrowDownToLine } from 'lucide-react'
import { getStoreExchange, type StoreExchangeStation } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

/** Молчание в человеческих единицах: секунды оператору ничего не говорят. */
function silence(sec: number | null): string {
  if (sec === null) return 'никогда не выходила на связь'
  if (sec < 60) return `${sec} с назад`
  if (sec < 3600) return `${Math.round(sec / 60)} мин назад`
  if (sec < 86400) return `${Math.round(sec / 3600)} ч назад`
  return `${Math.round(sec / 86400)} сут назад`
}

/** Объём канала: байты в отчёте о связи никто не читает. */
function объём(bytes: number): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
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

export function StoreStationsPanel({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const { company } = useCompany()
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-exchange', company.id, dateFrom, dateTo],
    queryFn: () => getStoreExchange(dateFrom, dateTo),
    // Экран смотрят, когда что-то пошло не так — данные должны быть свежими.
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка обмена…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить состояние обмена</div>
  if (!data) return null

  const { totals, stations, by_kind, by_day, recent } = data
  const пик = Math.max(1, ...by_day.map((d) => d.packets))

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Обмен со станциями</h3>
        <p className="text-xs text-muted-foreground">
          Сеансы связи, пакеты и объёмы за период: что станция отдала наверх и что центр
          отправил вниз. «Онлайн» — канал есть и обмен возможен; станция работает и без
          связи, накапливая данные локально и отдавая их одним сеансом.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi icon={RadioTower} label="На связи" value={`${totals.online} из ${totals.stations}`}
             hint={`сеансов обмена за период: ${totals.sessions}`}
             alarm={totals.stations > 0 && totals.online < totals.stations} />
        <Kpi icon={ArrowUpFromLine} label="Принято наверх" value={totals.packets}
             hint={`${объём(totals.bytes)} · последний ${когда(totals.last_packet_at)}`} />
        <Kpi icon={PackageOpen} label="В очереди на станциях" value={totals.queue_pending}
             hint="ещё не доехало до центра" alarm={totals.queue_pending > 20} />
        <Kpi icon={ArrowDownToLine} label="Отправлено вниз" value={totals.down_waiting}
             hint={totals.down_unacked
               ? `ждут станции · ${totals.down_unacked} без подтверждения`
               : 'ждут станции'}
             alarm={totals.down_waiting > 0} />
      </div>

      {by_day.length > 0 && (
        <div className="rounded-lg border border-border p-4">
          <div className="text-xs text-muted-foreground">Приём по дням, пакетов</div>
          <div className="mt-3 flex items-end gap-1.5">
            {by_day.map((d) => (
              <div key={d.day} className="flex-1 min-w-0" title={`${d.day}: ${d.packets} пакетов · ${объём(d.bytes)}`}>
                <div className="rounded-sm bg-primary/70"
                     style={{ height: `${Math.max(3, Math.round((d.packets / пик) * 72))}px` }} />
                <div className="mt-1 truncate text-center text-[10px] text-muted-foreground">
                  {new Date(d.day).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

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
                <th className="px-3 py-2 text-right">Сеансов</th>
                <th className="px-3 py-2 text-right">Пакетов ↑</th>
                <th className="px-3 py-2 text-right">Объём ↑</th>
                <th className="px-3 py-2 text-left">Последний пакет</th>
                <th className="px-3 py-2 text-right">В очереди</th>
                <th className="px-3 py-2 text-left">Вниз</th>
                <th className="px-3 py-2 text-left">Версия</th>
                <th className="px-3 py-2 text-right">Смена</th>
              </tr>
            </thead>
            <tbody>
              {stations.map((s: StoreExchangeStation) => (
                <tr key={s.station_id} className="border-b border-border last:border-0">
                  <td className="px-3 py-2 font-medium">{s.station_id}</td>
                  <td className="px-3 py-2"><StateDot state={s.state} /></td>
                  <td className="px-3 py-2 text-muted-foreground">{silence(s.silence_seconds)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.sessions || '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.packets || '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{объём(s.bytes)}</td>
                  <td className="px-3 py-2 text-muted-foreground">{когда(s.last_packet_at)}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${s.queue_pending > 0 ? 'text-amber-400/90' : ''}`}>
                    {s.queue_pending}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {s.down_waiting > 0
                      ? <span className="text-amber-400/90">ждёт {s.down_waiting}</span>
                      : s.down_unacked > 0
                        ? `${s.down_unacked} без подтверждения`
                        : s.down_acked > 0 ? `применено ${s.down_acked}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{s.version ?? '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.last_shift ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border">
          <div className="border-b border-border px-3 py-2 text-xs text-muted-foreground">
            Что везёт канал наверх — по видам пакетов
          </div>
          {by_kind.length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">За период станции ничего не отдавали.</div>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {by_kind.map((k) => (
                  <tr key={k.kind} className="border-b border-border last:border-0">
                    <td className="px-3 py-1.5">{k.label}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{k.packets}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{объём(k.bytes)}</td>
                    <td className="px-3 py-1.5 text-right text-muted-foreground">{когда(k.last_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="rounded-lg border border-border">
          <div className="border-b border-border px-3 py-2 text-xs text-muted-foreground">
            Последние обмены — обе стороны, свежие сверху
          </div>
          <div className="max-h-80 overflow-y-auto">
            <table className="w-full text-sm">
              <tbody>
                {recent.map((r, i) => (
                  <tr key={`${r.at}-${i}`} className="border-b border-border last:border-0">
                    <td className="px-3 py-1.5 text-muted-foreground">{когда(r.at)}</td>
                    <td className="px-3 py-1.5">
                      {r.direction === 'вверх'
                        ? <ArrowUpFromLine className="inline h-3.5 w-3.5 text-emerald-500/80" />
                        : <ArrowDownToLine className="inline h-3.5 w-3.5 text-sky-500/80" />}
                      <span className="ml-1.5">АЗС {r.station_id}</span>
                    </td>
                    <td className="px-3 py-1.5">{r.label}</td>
                    <td className="px-3 py-1.5 text-right text-muted-foreground">
                      {r.direction === 'вверх' ? объём(r.size_bytes) : r.note}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Сеанс — серия пакетов без паузы дольше {data.session_gap_minutes} минут: агент,
        дождавшись канала, отдаёт накопленное подряд. Работать на самой станции —
        в пункте «Рабочее место АЗС».
      </p>
    </div>
  )
}
