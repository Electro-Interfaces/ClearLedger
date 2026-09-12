/**
 * «Позиция» — главный экран пилота (docs/MARKET.md §5).
 *
 * Одна строка = один наш объект, и в ней сразу два мира: слева наши продажи и наша
 * цена, справа — кто стоит рядом и почём заряжает. Порознь они бесполезны: «выручка
 * упала» без соседей ничего не объясняет, а «рядом открылся конкурент» без нашей
 * выручки не говорит, важно ли это.
 *
 * Разворот строки показывает само окружение — с расстоянием, ценой и её датой.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { getMarketPosition, SITE_KIND_LABEL, type MarketPositionRow } from '@/services/marketService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

function money(v: number): string {
  if (v >= 1_000_000) return `${nf1.format(v / 1_000_000)} млн ₽`
  if (v >= 1_000) return `${nf0.format(v / 1_000)} тыс ₽`
  return `${nf0.format(v)} ₽`
}

/** Разрыв с рынком: плюс — мы дороже. Цвет помогает, но смысл несёт слово: цвет
 *  как единственный признак состояния не проходит ни в одной теме. Токены
 *  семантические (`warning`/`success`), а не палитра Tailwind — иначе контраст в
 *  тёмной теме никем не проверяется. */
function GapCell({ gap }: { gap: number | null }) {
  if (gap == null) return <span className="text-muted-foreground">нет сравнения</span>
  const dearer = gap > 5
  const cheaper = gap < -5
  const cls = dearer ? 'text-warning' : cheaper ? 'text-success' : 'text-foreground'
  return (
    <span className={`font-medium tabular-nums ${cls}`}>
      {gap > 0 ? '+' : ''}{nf1.format(gap)} %
      <span className="ml-1 font-normal text-muted-foreground">
        {dearer ? 'дороже' : cheaper ? 'дешевле' : 'на уровне'}
      </span>
    </span>
  )
}

function Neighbours({ row }: { row: MarketPositionRow }) {
  if (!row.neighbours.length) {
    return (
      <div className="px-4 py-3 text-xs text-muted-foreground">
        В радиусе никого не заведено. Это не значит, что рядом пусто — значит, рынок
        здесь ещё не наблюдали.
      </div>
    )
  }
  return (
    <div className="px-4 py-2">
      <table className="w-full text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-1 text-left font-medium">Кто рядом</th>
            <th className="py-1 text-left font-medium">Вид</th>
            <th className="py-1 text-left font-medium">Спрос</th>
            <th className="py-1 text-right font-medium">Расст.</th>
            <th className="py-1 text-right font-medium">Портов</th>
            <th className="py-1 text-right font-medium">Цена ₽/кВтч</th>
            <th className="py-1 text-left font-medium">Наблюдалась</th>
          </tr>
        </thead>
        <tbody>
          {row.neighbours.map((n) => (
            <tr key={n.id} className="border-t border-border/40">
              <td className="py-1">
                {n.name}
                {n.operatorName && (
                  <span className="text-muted-foreground"> · {n.operatorName}</span>
                )}
              </td>
              <td className="py-1 text-muted-foreground">
                {n.siteClass === 'home' ? 'домашняя розетка' : SITE_KIND_LABEL[n.kind]}
              </td>
              <td className="py-1 text-muted-foreground">
                {n.lastSessionAt
                  ? (n.alive ? 'заряжали недавно' : 'молчит больше 90 дней')
                  : 'нет данных'}
              </td>
              <td className="py-1 text-right tabular-nums">{nf1.format(n.distanceKm)} км</td>
              <td className="py-1 text-right tabular-nums">{n.ports ?? '—'}</td>
              <td className="py-1 text-right tabular-nums">
                {n.pricePerKwh != null ? nf1.format(n.pricePerKwh) : '—'}
              </td>
              <td className="py-1 text-muted-foreground">{n.observedOn ?? 'не наблюдалась'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function MarketPositionPanel() {
  const { companyId } = useCompany()
  const [radius, setRadius] = useState('5')
  const [days, setDays] = useState('30')
  const [q, setQ] = useState('')
  const [onlyRivals, setOnlyRivals] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  const pos = useQuery({
    queryKey: ['market-position', companyId, radius, days],
    queryFn: () => getMarketPosition(companyId, { radius_km: Number(radius), days: Number(days) }),
    enabled: !!companyId,
  })

  if (pos.isLoading) {
    // Скелетон, а не спиннер по центру: экран грузится в свою же раскладку, и человек
    // видит, ЧТО именно сейчас появится.
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        <span className="sr-only">Считаем окружение объектов</span>
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  const all = pos.data?.objects ?? []
  const rows = all.filter((r) =>
    (!onlyRivals || r.rivals > 0)
    && (!q || r.name.toLowerCase().includes(q.toLowerCase())
        || (r.city ?? '').toLowerCase().includes(q.toLowerCase())))

  const withRivals = all.filter((r) => r.rivals > 0).length
  const comparable = all.filter((r) => r.priceGapPct != null)
  const pricier = comparable.filter((r) => (r.priceGapPct ?? 0) > 5).length
  const cheaper = comparable.filter((r) => (r.priceGapPct ?? 0) < -5).length
  // Вывод экрана словами. Без покрытия он был бы враньём: «дороже рынка на четырёх
  // объектах» из шестисот — это про четыре объекта, а не про сеть.
  const verdict = comparable.length === 0
    ? 'Сравнивать пока не с чем: у соседей нет наблюдаемых цен в рублях за киловатт-час.'
    : pricier > cheaper
      ? `Мы дороже рынка на ${pricier} объектах и дешевле на ${cheaper}.`
      : cheaper > 0
        ? `Мы дешевле рынка на ${cheaper} объектах и дороже на ${pricier}.`
        : 'Наша цена держится на уровне рынка везде, где есть с чем сравнить.'
  const rivalsAlive = all.reduce((acc, r) => acc + (r.rivalsAlive ?? 0), 0)
  const rivalsAll = all.reduce((acc, r) => acc + r.rivals, 0)

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Объект или город"
          className="h-8 w-[220px] text-xs" />
        <Select value={radius} onValueChange={setRadius}>
          <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="2">Радиус 2 км</SelectItem>
            <SelectItem value="5">Радиус 5 км</SelectItem>
            <SelectItem value="10">Радиус 10 км</SelectItem>
            <SelectItem value="25">Радиус 25 км</SelectItem>
          </SelectContent>
        </Select>
        <Select value={days} onValueChange={setDays}>
          <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="30">Продажи 30 дн</SelectItem>
            <SelectItem value="90">Продажи 90 дн</SelectItem>
            <SelectItem value="365">Продажи год</SelectItem>
          </SelectContent>
        </Select>
        <button type="button" onClick={() => setOnlyRivals((v) => !v)}
          className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors
            ${onlyRivals ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-accent'}`}>
          Только с соседями
        </button>
        <span className="ml-auto text-xs text-muted-foreground">
          {rows.length} объектов · с соседями {withRivals} · дороже рынка {pricier}
        </span>
      </div>

      {/* Сначала вывод, потом данные, из которых он собран. */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="text-sm font-medium">{verdict}</span>
          <span className="text-xs text-muted-foreground">
            посчитано по {comparable.length} из {all.length} объектов
          </span>
          {rivalsAll > 0 && (
            <span className="text-xs text-muted-foreground">
              соседей рядом {rivalsAll}, из них заряжали за 90 дней {rivalsAlive}
            </span>
          )}
        </CardContent>
      </Card>

      {all.length > 0 && comparable.length === 0 && (
        <Card className="border-warning/40">
          <CardContent className="p-3 text-xs text-muted-foreground">
            Сравнивать пока не с чем: у соседей нет наблюдаемых цен. Заведите точки рынка
            и запишите по ним хотя бы одно ценовое наблюдение — колонка «Рынок» оживёт.
          </CardContent>
        </Card>
      )}

      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
            <tr>
              <th className="p-2 text-left font-medium">Наш объект</th>
              <th className="p-2 text-right font-medium">Сессий</th>
              <th className="p-2 text-right font-medium">кВтч</th>
              <th className="p-2 text-right font-medium">Выручка</th>
              <th className="p-2 text-right font-medium">Наша ₽/кВтч</th>
              <th className="p-2 text-right font-medium">Рынок ₽/кВтч</th>
              <th className="p-2 text-right font-medium">Разрыв</th>
              <th className="p-2 text-right font-medium">Соседи (живых)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const expanded = open === r.locationId
              return (
                <>
                  <tr key={r.locationId}
                    onClick={() => setOpen(expanded ? null : r.locationId)}
                    className="cursor-pointer border-t border-border/60 hover:bg-accent/30">
                    <td className="p-2">
                      <span className="flex items-center gap-1.5">
                        {expanded ? <ChevronDown className="size-3.5 opacity-60" />
                          : <ChevronRight className="size-3.5 opacity-60" />}
                        <span className="font-medium text-foreground">{r.name}</span>
                      </span>
                      <div className="pl-5 text-xs text-muted-foreground">
                        {r.city ?? '—'}{!r.hasGeo && ' · без координат'}
                      </div>
                    </td>
                    <td className="p-2 text-right tabular-nums">{nf0.format(r.sessions)}</td>
                    <td className="p-2 text-right tabular-nums">{nf0.format(r.energyKwh)}</td>
                    <td className="p-2 text-right tabular-nums">{money(r.revenue)}</td>
                    <td className="p-2 text-right tabular-nums">
                      {r.ourPricePerKwh != null ? nf1.format(r.ourPricePerKwh) : '—'}
                    </td>
                    <td className="p-2 text-right tabular-nums">
                      {r.marketPricePerKwh != null ? nf1.format(r.marketPricePerKwh) : '—'}
                    </td>
                    <td className="p-2 text-right"><GapCell gap={r.priceGapPct} /></td>
                    <td className="p-2 text-right tabular-nums">
                      {r.rivals > 0 ? `${r.rivals} ЭЗС (${r.rivalsAlive ?? 0})` : '—'}
                      {r.attractors > 0 && (
                        <span className="text-muted-foreground"> · {r.attractors} точек</span>
                      )}
                    </td>
                  </tr>
                  {expanded && (
                    <tr key={`${r.locationId}-n`} className="bg-muted/20">
                      <td colSpan={8}><Neighbours row={r} /></td>
                    </tr>
                  )}
                </>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
