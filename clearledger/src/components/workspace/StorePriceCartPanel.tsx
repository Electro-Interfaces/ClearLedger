/**
 * «Корзина цен» — накопленные изменения и время их применения.
 *
 * Между правилом и ценой на кассе стоит этот шаг, и он не лишний: массовая
 * переоценка — самая опасная операция сети, одна опечатка в поле «процент»
 * переписывает весь прайс. Здесь изменения видно списком, строку можно
 * поправить руками или снять, а применение назначить на нужное время: цены
 * меняют к открытию смены, а не посреди неё, когда у колонки стоит очередь.
 *
 * Пока строка лежит в корзине, на полке и в кассе прежняя цена — это намерение,
 * а не факт. Отложенное применение исполняет фоновый воркер центра, а не
 * открытый экран.
 *
 * Тот же порядок работы, что на станции (agent/internal/web/priceplan.go).
 *
 * Данные: /api/store/price-plan.
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Kpi } from './analytics/Kpi'
import { StoreCommercialPolicyNotice } from './StoreCommercialPolicyNotice'
import { useCentralCommercialWrite } from './useStoreCommercialPolicy'
import {
  getStorePricePlan, applyStorePricePlan, editStorePricePlan, cancelStorePricePlan,
  type PricePlanRow,
} from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const знак = (n: number) => (n > 0 ? '+' : '')
const вход = 'h-8 rounded-md border border-border/60 bg-background px-2 text-sm'

function момент(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit' })
}

/** Ближайшее «завтра к открытию» — им заполняем поле времени по умолчанию. */
function завтраУтром(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  d.setHours(6, 0, 0, 0)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

/**
 * Строка корзины. Значение поля цены живёт в состоянии панели, а не строки:
 * после сохранения список перезапрашивается, и собственное состояние строки
 * молча возвращало бы старую цифру в поле.
 */
function СтрокаКорзины({ r, цена, ввод, править, снять, можно }: {
  r: PricePlanRow
  цена: string
  ввод: (id: string, значение: string) => void
  править: (id: string, цена: number) => void
  снять: (id: string) => void
  можно: boolean
}) {
  const setЦена = (значение: string) => ввод(r.id, значение)
  const изменена = Number(цена.replace(',', '.')) !== r.new_price
  return (
    <tr className="border-b border-border/30">
      <td className="py-1.5 pr-3">
        {r.name || r.item_uuid}
        {r.error && <div className="text-[11px] text-amber-500">{r.error}</div>}
      </td>
      <td className="py-1.5 pr-3 text-muted-foreground">{r.station_id}</td>
      <td className="py-1.5 pr-3 text-right text-muted-foreground">
        {r.price == null ? '—' : fmtMoney(r.price)}
      </td>
      <td className="py-1.5 pr-3 text-right">
        {можно ? (
          <span className="inline-flex items-center gap-1">
            <input className={`${вход} w-24 text-right`} inputMode="decimal" value={цена}
                   onChange={(e) => setЦена(e.target.value)} />
            {изменена && (
              <button className="text-xs underline text-primary"
                      onClick={() => править(r.id, Number(цена.replace(',', '.')))}>
                сохранить
              </button>
            )}
          </span>
        ) : fmtMoney(r.new_price)}
      </td>
      <td className={`py-1.5 pr-3 text-right ${(r.delta ?? 0) < 0 ? 'text-amber-500' : 'text-emerald-500'}`}>
        {r.delta == null ? '—' : `${знак(r.delta)}${fmtMoney(r.delta)}`}
        {r.delta_pct != null && (
          <span className="text-muted-foreground"> ({знак(r.delta_pct)}{nf(r.delta_pct, 1)} %)</span>
        )}
      </td>
      <td className="py-1.5 pr-3 text-muted-foreground">{r.reason}</td>
      <td className="py-1.5 pr-3 text-muted-foreground">
        {r.status === 'scheduled' ? `к ${момент(r.effective_at)}` : 'черновик'}
      </td>
      <td className="py-1.5 text-right">
        {можно && (
          <button className="text-xs underline text-muted-foreground hover:text-foreground"
                  onClick={() => снять(r.id)}>снять</button>
        )}
      </td>
    </tr>
  )
}

export function StorePriceCartPanel({ companyId, stations }: {
  companyId: string; stations?: string[]
}) {
  const centralWrite = useCentralCommercialWrite()
  const [режим, setРежим] = useState<'now' | 'delay' | 'scheduled'>('now')
  const [минут, setМинут] = useState(30)
  const [время, setВремя] = useState(завтраУтром)
  const [итог, setИтог] = useState<string | null>(null)
  const [правки, setПравки] = useState<Record<string, string>>({})
  const scopeKey = stations?.join(',') || ''

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-price-plan', companyId, scopeKey],
    queryFn: () => getStorePricePlan(stations),
  })

  const сообщить = (текст: string) => { setИтог(текст); refetch() }
  const применение = useMutation({
    mutationFn: () => applyStorePricePlan({
      mode: режим,
      delay: режим === 'delay' ? минут : undefined,
      effective: режим === 'scheduled' ? время : undefined,
    }),
    onSuccess: (r) => сообщить(
      режим === 'now'
        ? `${r.note}. Позиций: ${r.applied}${r.failed ? `, не поехало: ${r.failed}` : ''}, станций: ${r.stations}.`
        : `${r.note} Позиций: ${r.scheduled}, время: ${момент(r.effective_at ?? null)}.`),
    onError: (e: unknown) => setИтог(e instanceof Error ? e.message : 'Не удалось применить'),
  })
  const правка = useMutation({
    mutationFn: ({ id, цена }: { id: string; цена: number }) => editStorePricePlan(id, цена),
    onSuccess: (r, { id }) => {
      // Правка сохранена — снимаем черновик поля, дальше цену показывает сервер.
      setПравки((prev) => { const next = { ...prev }; delete next[id]; return next })
      сообщить(r.note)
    },
    onError: (e: unknown) => setИтог(e instanceof Error ? e.message : 'Не удалось сохранить цену'),
  })
  const снятие = useMutation({
    mutationFn: (id: string) => cancelStorePricePlan(id),
    onSuccess: (r) => сообщить(r.note),
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Открываем корзину…</div>
  if (error || !data) {
    return (
      <div className="p-6 text-sm text-red-400/90">
        Не удалось прочитать корзину цен.{' '}
        <button type="button" className="underline" onClick={() => refetch()}>Повторить</button>
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 space-y-6">
      <StoreCommercialPolicyNotice />
      <div>
        <h2 className="text-lg font-semibold">Корзина цен</h2>
        <p className="text-sm text-muted-foreground max-w-4xl mt-1">
          Накопленные изменения цен. Пока строка здесь, на полке и в кассе <b>прежняя цена</b> —
          это намерение, а не факт. Цену можно поправить руками, строку снять, а применение
          назначить на нужное время: цены меняют к открытию смены, а не посреди неё.
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="В корзине" value={nf(data.drafts)} sub="черновиков без времени" />
        <Kpi label="Запланировано" value={nf(data.scheduled)}
             sub={data.next_at ? `ближайшее — ${момент(data.next_at)}` : 'времени не назначено'} />
        <Kpi label="Станций затронуто" value={nf(data.stations)} sub="в текущей корзине" />
        <Kpi label="Сдвиг цен" value={`${знак(data.delta_sum)}${fmtMoney(data.delta_sum)}`}
             sub="сумма изменений цены по позициям" />
      </div>

      {итог && (
        <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-sm">{итог}</div>
      )}

      <section className="rounded-lg border border-border/50 p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">Когда изменить рабочие цены</h3>
            <p className="text-xs text-muted-foreground mt-1 max-w-3xl">
              Применение записывает цену в историю центра и отправляет задание на станцию.
              Отложенное исполняет сам центр в назначенную минуту — держать браузер открытым
              не нужно.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select className={вход} value={режим}
                    onChange={(e) => setРежим(e.target.value as typeof режим)}>
              <option value="now">Сейчас</option>
              <option value="delay">Через</option>
              <option value="scheduled">К дате и времени</option>
            </select>
            {режим === 'delay' && (
              <span className="inline-flex items-center gap-1 text-xs">
                <input className={`${вход} w-20`} inputMode="numeric" value={минут}
                       onChange={(e) => setМинут(Number(e.target.value) || 0)} />
                минут
              </span>
            )}
            {режим === 'scheduled' && (
              <input type="datetime-local" className={вход} value={время}
                     onChange={(e) => setВремя(e.target.value)} />
            )}
            <button
              className="h-8 px-4 rounded-md bg-primary text-primary-foreground text-sm disabled:opacity-50"
              disabled={!centralWrite || применение.isPending || !data.rows.length}
              onClick={() => {
                if (режим !== 'now'
                    || confirm(`Применить ${data.rows.length} изменений прямо сейчас? Цены уедут на станции заданиями.`)) {
                  применение.mutate()
                }
              }}>
              {применение.isPending ? 'Применяем…' : 'Применить корзину'}
            </button>
          </div>
        </div>
        {!centralWrite && (
          <p className="text-xs text-amber-200/70 mt-2">
            В режиме «станция» цену утверждает администратор АЗС — корзина центра остаётся
            расчётом и предложением.
          </p>
        )}
      </section>

      <section className="rounded-lg border border-border/50 p-4">
        <h3 className="text-sm font-semibold">Что лежит в корзине</h3>
        {data.rows.length === 0 ? (
          <p className="text-xs text-muted-foreground py-3">
            Корзина пуста. Отберите позиции и правило на вкладке «Изменить цены» и нажмите
            «В корзину» — рабочие цены при этом не меняются.
          </p>
        ) : (
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="border-b border-border/50">
                  <th className="text-left py-1.5 pr-3 font-medium">Товар</th>
                  <th className="text-left py-1.5 pr-3 font-medium">АЗС</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Было</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Новая цена</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Разница</th>
                  <th className="text-left py-1.5 pr-3 font-medium">Причина</th>
                  <th className="text-left py-1.5 pr-3 font-medium">Состояние</th>
                  <th className="py-1.5" />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <СтрокаКорзины key={r.id} r={r} можно={centralWrite}
                    цена={правки[r.id] ?? String(r.new_price)}
                    ввод={(id, значение) => setПравки((prev) => ({ ...prev, [id]: значение }))}
                    править={(id, цена) => правка.mutate({ id, цена })}
                    снять={(id) => снятие.mutate(id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {data.history.length > 0 && (
        <section className="rounded-lg border border-border/50 p-4">
          <h3 className="text-sm font-semibold">Уже применённое и снятое</h3>
          <p className="text-xs text-muted-foreground mt-1 max-w-3xl">
            Последние решения по корзине. Полная история цены живёт в журнале цен сети —
            здесь только след того, что делали отсюда.
          </p>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="border-b border-border/50">
                  <th className="text-left py-1.5 pr-3 font-medium">Товар</th>
                  <th className="text-left py-1.5 pr-3 font-medium">АЗС</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Было</th>
                  <th className="text-right py-1.5 pr-3 font-medium">Стало</th>
                  <th className="text-left py-1.5 pr-3 font-medium">Автор</th>
                  <th className="text-left py-1.5 font-medium">Когда</th>
                </tr>
              </thead>
              <tbody>
                {data.history.map((r) => (
                  <tr key={r.id} className="border-b border-border/30">
                    <td className="py-1.5 pr-3">
                      {r.name || r.item_uuid}
                      {r.status === 'cancelled' && (
                        <span className="ml-2 text-muted-foreground">снято</span>
                      )}
                    </td>
                    <td className="py-1.5 pr-3 text-muted-foreground">{r.station_id}</td>
                    <td className="py-1.5 pr-3 text-right text-muted-foreground">
                      {r.price == null ? '—' : fmtMoney(r.price)}
                    </td>
                    <td className="py-1.5 pr-3 text-right">{fmtMoney(r.new_price)}</td>
                    <td className="py-1.5 pr-3 text-muted-foreground">{r.author || '—'}</td>
                    <td className="py-1.5 text-muted-foreground">
                      {момент(r.applied_at ?? r.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
