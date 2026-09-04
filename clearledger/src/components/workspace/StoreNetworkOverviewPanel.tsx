/**
 * «Магазин» → Станции.
 *
 * Ходить по тридцати рабочим местам не масштабируется. Здесь строка на станцию
 * и один вопрос к каждой: нужен ли ей человек сегодня.
 *
 * Экран собран из трёх бывших пунктов меню — «Сеть одним взглядом», «Состояние
 * станций» и «Версии агента». Они отвечали на один и тот же вопрос с разных
 * сторон и заставляли выбирать станцию по три раза: версия и так колонка в
 * обзоре, а находки конкретной АЗС — второй вид этого же экрана.
 *
 * Четыре вещи ломают торговлю тихо, и все четыре видны отсюда: станция молчит;
 * справочник станции разошёлся с сетевым (карточка продаётся, а центр о ней не
 * знает — так на 208 четыре дня торговали десятью напитками); кончаются номера
 * (без артикула не завести карточку, без кода кассы не пробить товар); встала
 * очередь заданий вниз.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { RadioTower, AlertTriangle, Download, MonitorSmartphone } from 'lucide-react'
import { getStoreNetworkOverview, pushStoreNsi, openStationSession } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { useStoreAccessPolicy } from './useStoreCommercialPolicy'
import { PanelViewTabs, type ViewTab } from './PanelViewTabs'
import { StoreStationHealthPanel } from './StoreStationHealthPanel'

const ВИДЫ: readonly ViewTab[] = [
  { k: 'network', label: 'Обзор сети' },
  { k: 'health', label: 'Требует человека' },
] as const

/**
 * Вход в рабочее место станции прямо из строки сети.
 *
 * Раньше для этого был отдельный пункт меню с плитками станций — второй список
 * тех же АЗС рядом с этим. Человек и так смотрит сюда: здесь видно, жива ли
 * станция, сходится ли справочник и что у неё в очереди, — и отсюда же логично
 * зайти и поправить. Отдельный экран только заставлял выбирать станцию дважды.
 *
 * Вкладку открываем ДО запроса: после await браузер счёл бы её всплывающим
 * окном и заблокировал. Сессию ставим до перехода — иначе первая же страница
 * станции придёт с «Требуется авторизация», и человек решит, что сломано
 * рабочее место, а не доступ.
 */
function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** Молчание в человеческих словах: «4 мин» читается, «247 с» — нет. */
function молчит(секунд: number | null): string {
  if (секунд === null) return 'связи не было ни разу'
  if (секунд < 180) return 'на связи'
  if (секунд < 3600) return `молчит ${Math.round(секунд / 60)} мин`
  if (секунд < 86400) return `молчит ${Math.round(секунд / 3600)} ч`
  return `молчит ${Math.round(секунд / 86400)} дн`
}

/** Запас номеров: цифра важна не сама по себе, а тем, близко ли дно. */
function запас(осталось: number | null, порог: number): { текст: string; тревога: boolean } {
  if (осталось === null || осталось === undefined) {
    return { текст: '—', тревога: false }
  }
  return { текст: String(осталось), тревога: осталось < порог }
}

export function StoreNetworkOverviewPanel() {
  const { company } = useCompany()
  const [вид, задатьВид] = useState<string>('network')
  const qc = useQueryClient()
  const accessPolicy = useStoreAccessPolicy()
  const [открываем, setОткрываем] = useState<number | null>(null)

  // Право на вход: роль «Администратор АЗС» назначается на конкретную станцию,
  // и товаровед сети её не заменяет — он видит сеть, но в рабочее место не
  // заходит. Кнопка у чужой станции остаётся, но не нажимается и говорит почему:
  // спрятать её значило бы оставить человека гадать, куда делся вход.
  const назначен = (id: number) =>
    accessPolicy?.capabilities.station_administrator.includes(String(id)) === true

  async function войти(id: number) {
    const вкладка = window.open('about:blank', '_blank')
    setОткрываем(id)
    try {
      await openStationSession(id)
      const адрес = `/api/store/station/${id}/console/`
      if (вкладка) вкладка.location.href = адрес
      else window.open(адрес, '_blank')
    } catch (e) {
      вкладка?.close()
      toast.error('Не удалось открыть рабочее место', { description: (e as Error).message })
    } finally {
      setОткрываем(null)
    }
  }
  // Первый запуск АЗС: реплика справочника пуста, и рассылать полторы тысячи
  // карточек по одной бессмысленно — станция получает их одним заданием.
  const залить = useMutation({
    mutationFn: pushStoreNsi,
    onSuccess: (r) => {
      toast.success(`Справочник поставлен в очередь: ${r.карточек} карточек`)
      qc.invalidateQueries({ queryKey: ['store-network-overview'] })
    },
    onError: (e: Error) => toast.error('Справочник не поставлен', { description: e.message }),
  })
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-network-overview', company.id],
    queryFn: getStoreNetworkOverview,
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка состояния сети…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить состояние сети</div>
  if (!data) return null

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold">
            <RadioTower className="h-4 w-4" /> Станции
          </h3>
          <p className="text-xs text-muted-foreground">
            Строка на станцию: связь, версия агента, очередь в обе стороны, расхождение
            справочника и остаток свободных номеров (артикулы и коды кассы — сколько ещё можно
            раздать, а не сколько заведено). Станция ведёт учёт локально и работает при мёртвом
            канале — здесь видно, где работа стоит, а не где просто нет связи прямо сейчас.
          </p>
        </div>
        <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={задатьВид} />
      </div>

      {вид === 'health' ? <StoreStationHealthPanel embedded /> : null}
      {вид === 'health' ? null : (
      <>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">На связи</div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums">
            {data.online} из {data.total}
          </div>
          <div className="text-[10px] text-muted-foreground/70">станций отвечает центру</div>
        </div>
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">Требует человека</div>
          <div className={`mt-0.5 text-xl font-semibold tabular-nums ${
            data.alerts.length > 0 ? 'text-amber-400/90' : ''}`}>
            {data.alerts.length}
          </div>
          <div className="text-[10px] text-muted-foreground/70">находок по всей сети</div>
        </div>
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">Целевая версия агента</div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums">{data.desired_version}</div>
          <div className="text-[10px] text-muted-foreground/70">объявлена центром</div>
        </div>
      </div>

      {data.alerts.length > 0 && (
        <div className="space-y-1.5 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
          {data.alerts.map((т, i) => (
            <div key={`${т.station_id}-${i}`} className="flex items-start gap-2 text-xs">
              <AlertTriangle className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                т.level === 'critical' ? 'text-red-400/90' : 'text-amber-400/90'}`} />
              <span className="tabular-nums text-muted-foreground">АЗС {т.station_id}</span>
              <span>{т.text}</span>
            </div>
          ))}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">АЗС</th>
              <th className="px-3 py-2 text-left font-medium">Связь</th>
              <th className="px-3 py-2 text-left font-medium">Версия</th>
              <th className="px-3 py-2 text-right font-medium">Очередь наверх</th>
              <th className="px-3 py-2 text-right font-medium">Задания вниз</th>
              <th className="px-3 py-2 text-right font-medium">Справочник</th>
              <th className="px-3 py-2 text-right font-medium"
                  title="Сколько номеров осталось в блоке артикулов станции. Кончатся — станция не заведёт новую карточку.">
                Артикулов свободно
              </th>
              <th className="px-3 py-2 text-right font-medium"
                  title="Сколько свободных кодов нефтесервера осталось в пуле станции (302…5199). Кончатся — товар нечем будет пробить.">
                Кодов кассы свободно
              </th>
              <th className="px-3 py-2 text-left font-medium">Последний пакет</th>
              <th className="px-3 py-2 text-right font-medium">Действия</th>
            </tr>
          </thead>
          <tbody>
            {data.stations.map((с) => {
              const артикулы = запас(с.sku_left, 100)
              const коды = запас(с.ns_code_left, 50)
              const расхождение = с.catalog?.missing_in_center ?? null
              return (
                <tr key={с.station_id} className="border-t border-border/40">
                  <td className="px-3 py-2">
                    <div className="font-medium">{с.name}</div>
                    <div className="text-[10px] text-muted-foreground/70 tabular-nums">
                      {с.station_id}
                    </div>
                  </td>
                  <td className={`px-3 py-2 ${с.state === 'офлайн' ? 'text-red-400/90' : ''}`}>
                    {молчит(с.silence_seconds)}
                  </td>
                  <td className={`px-3 py-2 tabular-nums ${с.version_ok ? '' : 'text-amber-400/90'}`}>
                    {с.version ?? '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{с.queue_pending}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${
                    с.downlink_waiting > 20 ? 'text-amber-400/90' : ''}`}>
                    {с.downlink_waiting}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {с.catalog === null ? (
                      <span className="text-muted-foreground/70">не сверялся</span>
                    ) : (
                      <span
                        className={расхождение ? 'text-amber-400/90' : ''}
                        title={[
                          `сверено ${когда(с.catalog.checked_at)}`,
                          `на станции ${с.catalog.station_items}, в центре ${с.catalog.center_items}`,
                          с.catalog.drafts_pending
                            ? `черновиков ждёт признания: ${с.catalog.drafts_pending}`
                            : null,
                          ...(с.catalog.examples ?? []).map((п) => `нет в центре: ${п.name}`),
                        ].filter(Boolean).join('\n')}
                      >
                        {расхождение ? `нет в центре: ${расхождение}` : 'сходится'}
                      </span>
                    )}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums ${
                    артикулы.тревога ? 'text-amber-400/90' : ''}`}>
                    {артикулы.текст}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums ${
                    коды.тревога ? 'text-amber-400/90' : ''}`}>
                    {коды.текст}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{когда(с.last_packet_at)}</td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex items-center justify-end gap-2">
                    <button
                      onClick={() => войти(с.station_id)}
                      disabled={открываем !== null || с.state === 'офлайн' || !назначен(с.station_id)}
                      title={
                        с.state === 'офлайн'
                          ? 'Станция не отвечает: её база живёт на месте, без канала центр до неё не дотянется'
                          : назначен(с.station_id)
                            ? 'Открыть рабочее место станции: приёмка, остатки, карточки — в самом агенте АЗС'
                            : 'Нужна роль «Администратор АЗС» с назначением на эту станцию'
                      }
                      className="inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md
                                 border border-border bg-card px-2.5 text-xs font-medium
                                 text-foreground transition-colors hover:border-primary/60
                                 hover:bg-primary/10 hover:text-primary
                                 disabled:cursor-not-allowed disabled:opacity-40
                                 disabled:hover:border-border disabled:hover:bg-card
                                 disabled:hover:text-foreground"
                    >
                      <MonitorSmartphone className="h-4 w-4" />
                      {открываем === с.station_id ? 'Открываю…' : 'Рабочее место'}
                    </button>
                    <button
                      onClick={() => залить.mutate(с.station_id)}
                      disabled={залить.isPending}
                      title="Залить станции весь сетевой справочник одним заданием — первый запуск АЗС"
                      className="inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md
                                 border border-border bg-card px-2.5 text-xs font-medium
                                 text-foreground transition-colors hover:border-primary/60
                                 hover:bg-primary/10 hover:text-primary
                                 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <Download className="h-4 w-4" />
                      Залить каталог
                    </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-muted-foreground/70">
        «Нет в центре» — карточка продаётся на станции, а сетевой справочник о ней не знает:
        она не попадёт ни в один сводный отчёт и не уедет в бухгалтерию. Черновики станции сюда
        не считаются — они ждут признания на своём экране.
      </p>
      </>
      )}
    </div>
  )
}
