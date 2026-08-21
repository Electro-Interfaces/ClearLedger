/**
 * Карточка одной ЭЗС — то, ради чего человек ищет станцию в списке.
 *
 * До неё станция существовала только строкой в разрезах: в раскрытии «Парка по
 * владельцу» одни колонки, на карте другие, в «Молчащих» третьи, и ни из одной
 * нельзя было провалиться внутрь. Руководитель заказчика сказал прямо: «ни в
 * одном окне на ЭЗС не провалиться, чтобы посмотреть статистику», и отдельно —
 * «здесь уже совсем другое представление ЭЗС» (21.08.2026). Это две жалобы на
 * одно: у станции не было единого представления.
 *
 * Карточка отвечает на три вопроса и в этом порядке: что это за станция, как она
 * работала за выбранный период, и что с ней было весь год. Паспорт первым, потому
 * что человек пришёл сюда, опознав станцию по номеру, — и должен убедиться, что
 * открыл ту самую.
 *
 * Своего бэкенда у карточки нет намеренно: паспорт берётся из уже загруженного
 * реестра объектов, работа и динамика — теми же ручками, что и разрезы, с
 * контуром из одной станции. Новая ручка означала бы четвёртый способ считать
 * одни и те же цифры.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer, ComposedChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts'
import { Loader2, MapPin, Zap, Building2, ExternalLink } from 'lucide-react'
import { ModalCard } from '@/components/ui/modal-card'
import { getChargeTimeseries } from '@/services/analyticsService'
import { loadLocations } from '@/services/locationService'
import { rechartsTooltipTheme } from '@/components/ui/chart-utils'
import { seriesColor } from './analytics/palette'
import { formatMonth } from '@/lib/formatDate'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

/** Что известно о станции из строки списка, откуда её открыли. */
export interface StationCardSeed {
  /** Номер станции — ключ, которым её знают сессии. */
  code: string
  name?: string | null
  /** Идентификатор объекта сети, если строка его знала. */
  locationId?: string | null
}

const OP_STATUS: Record<string, string> = {
  working: 'работает',
  not_working: 'не работает',
  on_repair: 'в ремонте',
  maintenance: 'обслуживание',
  decommissioned: 'выведена',
  unknown: 'состояние неизвестно',
}

/** Значение паспорта: нормализованный слой L2, ключи заданы нормализацией станций. */
function passport(loc: { passport?: Record<string, unknown> } | undefined, key: string): string | null {
  const v = loc?.passport?.[key]
  if (v === null || v === undefined || v === '') return null
  return String(v)
}

export function StationCardModal({ companyId, seed, period, onClose }: {
  companyId: string
  seed: StationCardSeed
  period: { from: string; to: string }
  onClose: () => void
}) {
  // Реестр объектов уже загружен соседними панелями — берём из общего кэша, а не
  // отдельным запросом на одну станцию.
  const locations = useQuery({
    queryKey: ['locations', companyId],
    queryFn: () => loadLocations(companyId),
    staleTime: 5 * 60_000,
  })

  const loc = useMemo(() => {
    const rows = locations.data ?? []
    if (seed.locationId) return rows.find((l) => l.id === seed.locationId)
    // Номер станции живёт либо своей колонкой, либо в метаданных — обе дороги
    // существуют исторически, и полагаться на одну нельзя.
    return rows.find((l) => {
      const n = (l as { stationNumber?: string | null }).stationNumber
        ?? (l.metadata?.number as string | undefined)
      return n != null && String(n).trim() === seed.code
    })
  }, [locations.data, seed.locationId, seed.code])

  // Работа станции по месяцам — тем же разрезом, что и вся аналитика, с контуром
  // из одной станции. Горизонт шире периода намеренно: «как шло весь год» нельзя
  // увидеть внутри одного месяца, и об этом сказано подписью.
  const months = useQuery({
    queryKey: ['station-card-months', companyId, seed.code],
    queryFn: () => getChargeTimeseries({
      companyId,
      dateFrom: `${Number(period.from.slice(0, 4)) - 1}-01-01`,
      dateTo: period.to,
      bucket: 'month', metric: 'amount', stations: [seed.code],
    }),
  })

  const inPeriod = useQuery({
    queryKey: ['station-card-period', companyId, seed.code, period.from, period.to],
    queryFn: () => getChargeTimeseries({
      companyId, dateFrom: period.from, dateTo: period.to,
      bucket: 'month', metric: 'amount', stations: [seed.code],
    }),
  })

  const title = loc?.name || seed.name || `Станция ${seed.code}`
  const place = [
    (loc?.metadata?.city as string | undefined) || null,
    loc?.address || null,
  ].filter(Boolean).join(' · ')

  /** Ряд без разреза приходит одной серией: её имя — в `series[0]`. */
  const rowsOf = (r: typeof inPeriod.data): { period: string; value: number }[] => {
    const key = r?.series?.[0]
    if (!r || !key) return []
    return r.data.map((row) => ({
      period: String(row.bucket ?? '').slice(0, 7),
      value: Number(row[key] ?? 0),
    }))
  }
  const periodRows = rowsOf(inPeriod.data)
  const periodSum = periodRows.reduce((a, r) => a + r.value, 0)
  const chart = rowsOf(months.data)

  return (
    <ModalCard title={title} onClose={onClose}>
      <div className="space-y-4">
        {/* Паспорт: человек пришёл по номеру и должен убедиться, что открыл ту станцию */}
        <section className="rounded-lg border border-border bg-muted/20 p-3">
          {locations.isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Паспорт станции…
            </div>
          ) : (
            <div className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              <Field icon={MapPin} label="Где" value={place || '— адрес не заполнен'} />
              <Field icon={Building2} label="Номер станции" value={seed.code} mono />
              <Field icon={Zap} label="Мощность"
                value={passport(loc, 'powerKwt') ? `${passport(loc, 'powerKwt')} кВт` : '—'} />
              <Field icon={Zap} label="Коннекторы"
                value={passport(loc, 'connectorTypes') || passport(loc, 'connectorsCount') || '—'} />
              <Field icon={Building2} label="Владелец" value={passport(loc, 'owner') || '—'} />
              <Field icon={Building2} label="Состояние"
                value={OP_STATUS[loc?.operationalStatus ?? 'unknown'] ?? (loc?.operationalStatus || '—')} />
            </div>
          )}
          {!locations.isLoading && !loc && (
            // Молчать нельзя: без объекта паспорт пуст не потому, что данных нет,
            // а потому, что сессии этой станции ни с чем не связаны.
            <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
              Станция не связана с объектом сети — паспорт показать не из чего.
              Связь заводится в «Нормализации», разделе связи каналов.
            </p>
          )}
        </section>

        {/* Работа за выбранный период — то, ради чего пришли */}
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Tile label="Выручка за период" value={`${nf0.format(periodSum)} ₽`}
            hint={`${formatMonth(period.from.slice(0, 7))} — ${formatMonth(period.to.slice(0, 7))}`} />
          <Tile label="Месяцев с работой" value={String(periodRows.filter((r) => r.value > 0).length)}
            hint={`из ${periodRows.length || '—'} в периоде`} />
          <Tile label="Средняя за месяц"
            value={periodRows.length ? `${nf0.format(periodSum / periodRows.length)} ₽` : '—'}
            hint="по месяцам периода" />
        </section>

        {/* Динамика: горизонт СОЗНАТЕЛЬНО шире периода — и это сказано вслух */}
        <section className="rounded-lg border border-border">
          <div className="flex flex-wrap items-center gap-2 border-b bg-muted/40 px-3 py-2">
            <span className="text-sm font-semibold">Динамика выручки</span>
            <span className="rounded border border-amber-400/40 px-1.5 py-0.5 text-[10px] text-amber-600 dark:text-amber-400"
              title="Чтобы увидеть ход станции, горизонт шире выбранного периода. Плитки выше — строго по периоду.">
              горизонт шире периода
            </span>
          </div>
          <div className="p-3">
            {months.isLoading ? (
              <div className="flex justify-center py-8"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
            ) : chart.length === 0 ? (
              <p className="py-8 text-center text-xs text-muted-foreground">
                За горизонт по этой станции сессий нет.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <ComposedChart data={chart} margin={{ top: 4, right: 8, left: 4, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.08} />
                  <XAxis dataKey="period" tick={{ fontSize: 10 }} tickFormatter={formatMonth} interval={1} />
                  <YAxis tick={{ fontSize: 10 }} width={44}
                    tickFormatter={(v: number) => `${nf1.format(v / 1000)}к`} />
                  <Tooltip {...rechartsTooltipTheme}
                    formatter={(v) => [`${nf0.format(Number(v))} ₽`, 'Выручка']}
                    labelFormatter={(l) => formatMonth(String(l))} />
                  <Bar dataKey="value" fill={seriesColor(0, 1)} radius={[3, 3, 0, 0]} />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </div>
        </section>

        {loc && (
          <a href={`/ClearLedger/admin/objects?object=${encodeURIComponent(loc.id)}`}
            className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline">
            <ExternalLink className="h-3 w-3" aria-hidden />
            Открыть объект в реестре пространства
          </a>
        )}
      </div>
    </ModalCard>
  )
}

function Field({ icon: Icon, label, value, mono }: {
  icon: typeof MapPin; label: string; value: string; mono?: boolean
}) {
  return (
    <div className="flex items-start gap-2">
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0">
        <div className="text-[11px] text-muted-foreground">{label}</div>
        <div className={`truncate ${mono ? 'font-mono' : ''}`}>{value}</div>
      </div>
    </div>
  )
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-[11px] text-muted-foreground/70">{hint}</div>}
    </div>
  )
}

export default StationCardModal
