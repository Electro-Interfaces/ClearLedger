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
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RadioTower, PackageOpen, ArrowUpFromLine, ArrowDownToLine } from 'lucide-react'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  getStoreExchange, getStoreExchangeStation, type StoreExchangeStation,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { useStoreWindow } from './StoreWindow'
import { rowDrill } from './rowDrill'

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

function трафик(bytes: number, measured: number, packets: number): string {
  if (!measured) return packets ? 'замер начнётся после обновления' : '—'
  const coverage = measured < packets ? ` · ${measured} из ${packets} пакетов` : ''
  return `${объём(bytes)}${coverage}`
}

function время(sec: number | null): string {
  if (sec === null) return '—'
  if (sec < 60) return `${sec} с`
  if (sec < 3600) return `${Math.round(sec / 60)} мин`
  return `${Math.round(sec / 3600)} ч`
}

function возраст(iso: string | null): string {
  if (!iso) return '—'
  return silence(Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000)))
}

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function дата(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' })
}

/** Длительность сеанса и паузы между ними — в тех же единицах, что молчание. */
function длительность(min: number | null): string {
  if (min === null) return '—'
  if (min < 1) return 'меньше минуты'
  if (min < 60) return `${min} мин`
  if (min < 1440) return `${Math.round(min / 60)} ч`
  return `${Math.round(min / 1440)} сут`
}

const STATE_STYLE: Record<string, string> = {
  'онлайн': 'bg-emerald-500',
  'офлайн': 'bg-amber-500',
  'молчит': 'bg-red-500',
  'нет агента': 'bg-zinc-500',
}

const STATE_LABEL: Record<string, string> = {
  'онлайн': 'на связи',
  'офлайн': 'нет связи',
  'молчит': 'нет связи больше часа',
  'нет агента': 'агент не зарегистрирован',
}

function StateDot({ state }: { state: string }) {
  return (
    <span className="inline-flex items-center gap-2" aria-label={`Связь: ${STATE_LABEL[state] ?? state}`}>
      <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${STATE_STYLE[state] ?? 'bg-zinc-500'}`} />
      {STATE_LABEL[state] ?? state}
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

/** Пара «подпись — значение» в шапке карточки станции. */
function Факт({ label, value, title }: {
  label: string; value: string | number | null; title?: string
}) {
  return (
    <div title={title}>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-sm">{value ?? '—'}</div>
    </div>
  )
}

/**
 * Карточка станции: сеть отвечает «где плохо», станция — «что там произошло».
 * Сеансы перечислены поимённо, с паузой перед каждым: длина молчания и есть
 * качество канала, а средняя по парку её прячет.
 */
function StationExchangeDialog({ stationId, dateFrom, dateTo, onClose }: {
  stationId: number; dateFrom: string; dateTo: string; onClose: () => void
}) {
  const { company } = useCompany()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-exchange-station', company.id, stationId, dateFrom, dateTo],
    queryFn: () => getStoreExchangeStation(stationId, dateFrom, dateTo),
  })

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            АЗС {stationId} · обмен с центром
            {data?.agent && <StateDot state={data.agent.state} />}
          </DialogTitle>
          <DialogDescription>
            {data
              ? `${дата(data.from)} — ${дата(data.to)} · сеанс считается по паузе дольше ${data.session_gap_minutes} минут`
              : 'Загрузка…'}
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <div className="p-4 text-sm text-red-400/90">
            Не удалось получить историю обмена станции.{' '}
            <button type="button" className="underline" onClick={() => refetch()}>Повторить</button>
          </div>
        ) : isLoading || !data ? (
          <div className="p-4 text-sm text-muted-foreground">Загрузка обмена станции…</div>
        ) : (
          <div className="space-y-5">
            {data.agent ? (
              <div className={`rounded-lg border px-3 py-2.5 ${
                data.agent.state === 'онлайн'
                  ? 'border-emerald-500/25 bg-emerald-500/5'
                  : 'border-amber-500/30 bg-amber-500/5'
              }`}>
                <div className="text-sm font-medium">
                  {data.agent.state === 'онлайн'
                    ? 'Центр видит актуальное состояние станции'
                    : 'Центр показывает последнее известное состояние'}
                </div>
                <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                  {data.agent.state === 'онлайн'
                    ? 'Станция обновляет телеметрию раз в минуту. Очередь ниже совпадает с тем, что видит локальный экран «Состояние».'
                    : `Последний ответ — ${silence(data.agent.silence_seconds)}. Очередь и показатели ниже зафиксированы на тот момент; сейчас точные значения видны только на самой станции. Работа на АЗС продолжается локально, накопленное уйдёт после восстановления связи.`}
                </p>
              </div>
            ) : (
              <div className="rounded-lg border border-border bg-muted/20 px-3 py-2.5 text-sm text-muted-foreground">
                Агент этой станции ещё не зарегистрирован — у центра нет локального состояния АЗС.
              </div>
            )}

            <div className="grid grid-cols-2 gap-3 rounded-lg border border-border p-3 sm:grid-cols-3 lg:grid-cols-6">
              <Факт label="Сеансов" value={data.totals.sessions} />
              <Факт label="Пакетов" value={data.totals.packets} />
              <Факт label="Трафик наверх"
                    value={трафик(data.totals.wire_bytes, data.totals.wire_packets, data.totals.packets)}
                    title="Фактический объём HTTP-тел после gzip; старые пакеты без замера не включены" />
              <Факт label="Данных до сжатия" value={объём(data.totals.bytes)} />
              <Факт label="Пауза в среднем" value={длительность(data.totals.avg_silence_min)} />
              <Факт label={data.agent?.state === 'онлайн' ? 'Очередь наверх' : 'Очередь на последнем ответе'}
                    value={data.agent
                      ? `${data.agent.queue_pending} · ${объём(data.agent.queue_wire_bytes)}`
                      : '—'} />
            </div>

            {data.agent && (
              <div className={`rounded-lg border px-3 py-2.5 ${
                data.agent.queue_failing > 0
                  ? 'border-amber-500/30 bg-amber-500/5'
                  : 'border-border'
              }`}>
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
                  <span className="font-medium">Очередь станции наверх</span>
                  <span>{data.agent.queue_pending} пакетов</span>
                  <span className="text-muted-foreground">
                    {объём(data.agent.queue_wire_bytes)} по каналу · {объём(data.agent.queue_bytes)} данных
                  </span>
                  <span className="text-muted-foreground">
                    старшему {возраст(data.agent.queue_oldest_at)}
                  </span>
                  <span className={data.agent.queue_failing > 0 ? 'text-amber-400/90' : 'text-muted-foreground'}>
                    с ошибкой {data.agent.queue_failing}
                  </span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  За сутки доставлено {data.agent.queue_sent_24} пакетов ·{' '}
                  {объём(data.agent.sent_24_wire_bytes)} по каналу · последняя доставка{' '}
                  {когда(data.agent.last_sent_at)}
                </div>
                {data.agent.last_error && (
                  <div className="mt-2 rounded-md bg-amber-500/10 px-2 py-1.5 text-xs text-amber-200/90">
                    Последняя ошибка отправки: {data.agent.last_error}
                  </div>
                )}
              </div>
            )}

            <div className="rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="text-sm font-medium">
                  Доступность канала{' '}
                  <span className="tabular-nums">
                    {data.availability.pct === null ? '—' : `${data.availability.pct}%`}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {data.availability.outages.length > 0
                    ? `обрывов ${data.availability.outages.length} · всего ${длительность(data.availability.outage_minutes)}`
                    : 'обрывов не было'}
                </div>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-emerald-500/70"
                     style={{ width: `${data.availability.pct ?? 0}%` }} />
              </div>
              <div className="mt-1 text-[10px] text-muted-foreground">
                Считается от начала наблюдения ({когда(data.availability.first_at)}): из времени
                периода вычитаются паузы между heartbeat дольше трёх минут. Короткая осечка
                отдельным обрывом не считается.
              </div>
              {data.availability.outages.length > 0 && (
                <div className="mt-2 max-h-40 overflow-y-auto">
                  <table className="w-full text-xs">
                    <tbody>
                      {data.availability.outages.map((o, i) => (
                        <tr key={`${o.started}-${i}`} className="border-t border-border/30 first:border-t-0">
                          <td className="py-1 text-muted-foreground">{когда(o.started)}</td>
                          <td className="py-1 text-muted-foreground">
                            → {o.ongoing ? 'идёт сейчас' : когда(o.ended)}
                          </td>
                          <td className="py-1 text-right tabular-nums text-amber-400/90">
                            {длительность(o.minutes)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {data.agent && (
              <div className="grid grid-cols-2 gap-3 rounded-lg border border-border p-3 sm:grid-cols-3 lg:grid-cols-6">
                <Факт label="Последний ответ" value={silence(data.agent.silence_seconds)} />
                <Факт label="Версия агента"
                      value={`${data.agent.version ?? '—'}${data.agent.version_ok ? '' : ' (отстаёт)'}`} />
                <Факт label="Последняя доставка" value={когда(data.agent.last_sent_at)} />
                <Факт label="Последняя попытка" value={когда(data.agent.last_attempt_at)} />
                <Факт label="Снимок остатков" value={когда(data.agent.snapshot_at)} />
                <Факт label="Часы станции"
                      value={data.agent.clock_skew_seconds === null
                        ? 'нет замера'
                        : Math.abs(data.agent.clock_skew_seconds) <= 60
                          ? 'совпадают'
                          : `расходятся на ${время(Math.abs(data.agent.clock_skew_seconds))}`} />
              </div>
            )}

            <div>
              <div className="mb-1.5 text-xs text-muted-foreground">
                Выходы на связь — свежие сверху
              </div>
              {data.sessions.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border/50 p-4 text-sm text-muted-foreground">
                  За период станция ничего не передавала.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-xs text-muted-foreground">
                        <th className="px-3 py-2 text-left">Начало</th>
                        <th className="px-3 py-2 text-left">Длился</th>
                        <th className="px-3 py-2 text-right">Пакетов</th>
                        <th className="px-3 py-2 text-right">Канал / данные</th>
                        <th className="px-3 py-2 text-left">Что везла</th>
                        <th className="px-3 py-2 text-left">Молчала перед этим</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.sessions.map((s) => (
                        <tr key={s.session_no} className="border-b border-border last:border-0">
                          <td className="px-3 py-1.5">{когда(s.started)}</td>
                          <td className="px-3 py-1.5 text-muted-foreground">{длительность(s.duration_min)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{s.packets}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">
                            <div>{трафик(s.wire_bytes, s.wire_packets, s.packets)}</div>
                            <div className="text-[10px] text-muted-foreground">{объём(s.bytes)} данных</div>
                          </td>
                          <td className="px-3 py-1.5 text-muted-foreground">{s.kinds.join(' · ')}</td>
                          <td className="px-3 py-1.5 text-muted-foreground">
                            {длительность(s.silence_before_min)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-lg border border-border">
                <div className="border-b border-border px-3 py-2 text-xs text-muted-foreground">
                  Состав переданного
                </div>
                {data.by_kind.length === 0 ? (
                  <div className="p-3 text-sm text-muted-foreground">Пусто.</div>
                ) : (
                  <table className="w-full text-sm">
                    <tbody>
                      {data.by_kind.map((k) => (
                        <tr key={k.kind} className="border-b border-border last:border-0">
                          <td className="px-3 py-1.5">{k.label}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{k.packets}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">
                            <div>{трафик(k.wire_bytes, k.wire_packets, k.packets)}</div>
                            <div className="text-[10px] text-muted-foreground">{объём(k.bytes)} данных</div>
                          </td>
                          <td className="px-3 py-1.5 text-right text-muted-foreground">{когда(k.last_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div className="rounded-lg border border-border">
                <div className="border-b border-border px-3 py-2 text-xs text-muted-foreground">
                  Задания центра станции — ждёт {data.totals.down_waiting} ·
                  без подтверждения {data.totals.down_unacked} · применено {data.totals.down_acked} ·{' '}
                  {объём(data.totals.down_bytes)} данных · подтверждение в среднем{' '}
                  {время(data.totals.down_avg_ack_seconds)}
                </div>
                {data.downlink.length === 0 ? (
                  <div className="p-3 text-sm text-muted-foreground">
                    Центр этой станции ничего не отправлял.
                  </div>
                ) : (
                  <div className="max-h-64 overflow-y-auto">
                    <table className="w-full text-sm">
                      <tbody>
                        {data.downlink.map((d, i) => (
                          <tr key={`${d.created_at}-${i}`} className="border-b border-border last:border-0">
                            <td className="px-3 py-1.5 text-muted-foreground">{когда(d.created_at)}</td>
                            <td className="px-3 py-1.5">{d.label}</td>
                            <td className="px-3 py-1.5 text-muted-foreground">{d.note ?? ''}</td>
                            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                              <div>{объём(d.size_bytes)}</div>
                              <div className="text-[10px]">{d.ack_seconds === null ? 'без подтверждения' : `за ${время(d.ack_seconds)}`}</div>
                            </td>
                            <td className={`px-3 py-1.5 text-right ${
                              d.state === 'ждёт станции' ? 'text-amber-400/90' : 'text-muted-foreground'}`}>
                              {d.state}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function StoreStationsPanel({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const { company } = useCompany()
  const открытьОкном = useStoreWindow()
  // Два уровня чтения: сверху сеть целиком, по клику — конкретная АЗС. Смешивать
  // их в одной таблице нельзя: у сети вопрос «где плохо», у станции — «что там
  // произошло», и ответы на них живут в разных разрезах.
  const [выбрана, выбрать] = useState<number | null>(null)
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-exchange', company.id, dateFrom, dateTo],
    queryFn: () => getStoreExchange(dateFrom, dateTo),
    // Экран смотрят, когда что-то пошло не так — данные должны быть свежими.
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка обмена…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить состояние обмена. <button type="button" className="underline" onClick={() => refetch()}>Повторить</button></div>
  if (!data) return null

  const { totals, stations, by_kind, by_day, recent, ingest } = data
  const пик = Math.max(1, ...by_day.map((d) => d.packets))
  // Принято ≠ усвоено: пакет ложится сырьём, документы рождает разбор. Считаем
  // только те виды, которые обязаны порождать документы.
  const неразобрано = (ingest ?? []).filter((i) => i.projects_docs)
    .reduce((a, i) => a + i.unprojected, 0)
  const безСвежихДанных = stations.filter((s) => s.state === 'офлайн' || s.state === 'молчит').length

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

      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        По сети целиком
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi icon={RadioTower} label="На связи" value={`${totals.online} из ${totals.stations}`}
             hint={`сеансов обмена за период: ${totals.sessions}`}
             alarm={totals.stations > 0 && totals.online < totals.stations} />
        <Kpi icon={ArrowUpFromLine} label="Принято наверх" value={totals.packets}
             hint={`${трафик(totals.wire_bytes, totals.wire_packets, totals.packets)} по каналу · ${объём(totals.bytes)} данных`} />
        <Kpi icon={PackageOpen} label="В очереди на станциях" value={totals.queue_pending}
             hint={`${объём(totals.queue_wire_bytes)} по каналу${
               безСвежихДанных > 0 ? ` · у ${безСвежихДанных} АЗС значение неактуально` : ''}`}
             alarm={totals.queue_failing > 0 || totals.queue_pending > 20} />
        <Kpi icon={ArrowDownToLine} label="Отправлено вниз" value={totals.down_waiting}
             hint={totals.down_unacked
               ? `${объём(totals.down_pending_bytes)} · ${totals.down_unacked} без подтверждения`
               : `${объём(totals.down_pending_bytes)} ждёт станции`}
             alarm={totals.down_waiting > 0} />
      </div>

      {by_day.length > 0 && (
        <div className="rounded-lg border border-border p-4">
          <div className="text-xs text-muted-foreground">Приём по дням, пакетов</div>
          <div className="mt-3 flex items-end gap-1.5">
            {by_day.map((d) => (
              <div key={d.day} className="min-w-0 flex-1"
                   title={`${d.day}: ${d.packets} пакетов · ${трафик(d.wire_bytes, d.wire_packets, d.packets)} по каналу · ${объём(d.bytes)} данных`}>
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

      <div className="flex items-baseline justify-between gap-4 pt-2">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          По каждой станции
        </div>
        <div className="text-xs text-muted-foreground">клик по строке — сеансы и состав обмена АЗС</div>
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
                <th className="px-3 py-2 text-right">Доступность</th>
                <th className="px-3 py-2 text-right">Сеансов</th>
                <th className="px-3 py-2 text-right">Пакетов ↑</th>
                <th className="px-3 py-2 text-right">Канал / данные ↑</th>
                <th className="px-3 py-2 text-left">Последний пакет</th>
                <th className="px-3 py-2 text-right">Очередь ↑</th>
                <th className="px-3 py-2 text-left">Вниз</th>
                <th className="px-3 py-2 text-left">Версия</th>
                <th className="px-3 py-2 text-right">Смена</th>
              </tr>
            </thead>
            <tbody>
              {stations.map((s: StoreExchangeStation) => (
                <tr key={s.station_id}
                    {...rowDrill(
                      () => выбрать(s.station_id),
                      `АЗС ${s.station_id}: сеансы, состав обмена, задания вниз`,
                      'border-b border-border last:border-0 hover:bg-muted/40',
                    )}>
                  <td className="px-3 py-2 font-medium">{s.station_id}</td>
                  <td className="px-3 py-2"><StateDot state={s.state} /></td>
                  <td className="px-3 py-2 text-muted-foreground">{silence(s.silence_seconds)}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${
                    s.uptime_pct !== null && s.uptime_pct < 95 ? 'text-amber-400/90' : ''}`}
                      title="Доля времени без обрывов heartbeat дольше трёх минут">
                    {s.uptime_pct === null ? '—' : `${s.uptime_pct}%`}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.sessions || '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.packets || '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <div>{трафик(s.wire_bytes, s.wire_packets, s.packets)}</div>
                    <div className="whitespace-nowrap text-[10px] text-muted-foreground">{объём(s.bytes)} данных</div>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{когда(s.last_packet_at)}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${s.queue_pending > 0 ? 'text-amber-400/90' : ''}`}>
                    <div>{s.queue_pending}</div>
                    {s.queue_pending > 0 && (
                      <div className="whitespace-nowrap text-[10px] font-normal text-muted-foreground">
                        {объём(s.queue_wire_bytes)} · старшему {возраст(s.queue_oldest_at)}
                        {s.queue_failing > 0 ? ` · ошибок ${s.queue_failing}` : ''}
                      </div>
                    )}
                    {s.state !== 'онлайн' && s.state !== 'нет агента' && (
                      <div className="whitespace-nowrap text-[10px] font-normal text-muted-foreground">
                        последнее известное
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {s.down_waiting > 0
                      ? <span className="text-amber-400/90">ждёт {s.down_waiting} · {объём(s.down_pending_bytes)}</span>
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

      {Object.values(data.nsi ?? {}).some((n) => n > 0) && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border px-3 py-2.5">
          <span className="text-xs text-muted-foreground">Станции прислали на решение центра:</span>
          {Object.entries(data.nsi).filter(([, n]) => n > 0).map(([вид, n]) => (
            <span key={вид} className="text-sm">
              <span className="tabular-nums font-medium">{n}</span>{' '}
              <span className="text-muted-foreground">{вид}</span>
            </span>
          ))}
          {/* Очередь разбирают, не отходя от состояния станций: уйти отсюда
              совсем — значит потерять из виду, кто именно молчит. */}
          <button type="button"
            onClick={() => открытьОкном('station-drafts')}
            className="ml-auto text-xs text-primary hover:underline">
            разобрать в «Каталоге» →
          </button>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border">
          <div className="flex flex-wrap items-baseline gap-x-2 border-b border-border px-3 py-2 text-xs text-muted-foreground">
            <span>Что везёт канал наверх — по видам пакетов</span>
            <span className={`ml-auto ${неразобрано > 0 ? 'text-amber-400/90' : ''}`}>
              {неразобрано > 0
                ? `не разобрано в документы: ${неразобрано}`
                : 'всё принятое разобрано'}
            </span>
          </div>
          {by_kind.length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">За период станции ничего не отдавали.</div>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {by_kind.map((k) => {
                  const раз = (ingest ?? []).find((i) => i.kind === k.kind)
                  return (
                    <tr key={k.kind} className="border-b border-border last:border-0">
                      <td className="px-3 py-1.5">
                        {k.label}
                        {раз && раз.projects_docs && (
                          <span className={`ml-2 text-[11px] ${раз.unprojected > 0 ? 'text-amber-400/90' : 'text-muted-foreground'}`}>
                            {раз.unprojected > 0
                              ? `${раз.unprojected} без документов`
                              : `${раз.entries} документов`}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{k.packets}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        <div>{трафик(k.wire_bytes, k.wire_packets, k.packets)}</div>
                        <div className="text-[10px] text-muted-foreground">{объём(k.bytes)} данных</div>
                      </td>
                      <td className="px-3 py-1.5 text-right text-muted-foreground">{когда(k.last_at)}</td>
                    </tr>
                  )
                })}
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
                      {r.direction === 'вверх'
                        ? `${r.wire_size_bytes === null ? 'без замера' : объём(r.wire_size_bytes)} · ${объём(r.size_bytes)} данных`
                        : `${r.note ?? ''} · ${объём(r.size_bytes)}`}
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
        в пункте «Рабочее место АЗС». «Канал» — фактический размер HTTP-тела после gzip;
        «данные» — JSON после распаковки.
      </p>

      {выбрана !== null && (
        <StationExchangeDialog stationId={выбрана} dateFrom={dateFrom} dateTo={dateTo}
                               onClose={() => выбрать(null)} />
      )}
    </div>
  )
}
