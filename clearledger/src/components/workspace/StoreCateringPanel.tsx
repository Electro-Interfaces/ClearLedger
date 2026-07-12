/**
 * «Общепит» (Аналитика) — инструмент менеджера: инжиниринг меню.
 * Классификация блюд (Звёзды / Рабочие лошадки / Загадки / Собаки) по популярности ×
 * маржинальности (Kasavana–Smith), продажи/фудкост/маржа. Клик по строке открывает
 * свойства блюда в МОДАЛЬНОМ окне: метрики + состав ТТК (себест. на порцию) + динамика.
 * Данные: /api/store/catering (GoodsDashboardService.catering_menu).
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ResponsiveContainer, BarChart, Bar, XAxis, Tooltip, CartesianGrid } from 'recharts'
import { getStoreCateringMenu, type CateringDish, type MenuClass } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const pctStr = (v: number | null, d = 1) => (v == null ? '—' : `${nf(v, d)}%`)

const CLASS_META: Record<MenuClass, { label: string; short: string; emoji: string; text: string; badge: string; desc: string }> = {
  star:      { label: 'Звезда', short: 'Звезда', emoji: '⭐', text: 'text-emerald-300', badge: 'border-emerald-400/40 text-emerald-300/90', desc: 'Популярное и маржинальное — двигатель прибыли. Держать качество и наличие, не трогать цену.' },
  plowhorse: { label: 'Рабочая лошадка', short: 'Лошадка', emoji: '🐎', text: 'text-amber-300', badge: 'border-amber-400/40 text-amber-300/90', desc: 'Популярное, но низкомаржинальное. Поднять цену аккуратно / снизить себестоимость порции.' },
  puzzle:    { label: 'Загадка', short: 'Загадка', emoji: '🧩', text: 'text-sky-300', badge: 'border-sky-400/40 text-sky-300/90', desc: 'Маржинальное, но мало продаётся. Продвигать, переставить в меню, попробовать промо.' },
  dog:       { label: 'Собака', short: 'Собака', emoji: '🐶', text: 'text-red-300', badge: 'border-red-400/40 text-red-300/80', desc: 'Непопулярное и немаржинальное — кандидат на вывод из меню.' },
  unknown:   { label: 'Без себестоимости', short: '—', emoji: '❔', text: 'text-muted-foreground', badge: 'border-zinc-600 text-zinc-400', desc: 'Нет данных о себестоимости ингредиентов (нет закупки за период).' },
}

const ORDER: MenuClass[] = ['star', 'plowhorse', 'puzzle', 'dog']

type SortKey = 'qty' | 'popularity_pct' | 'revenue' | 'share' | 'avg_price' | 'food_cost_pct' | 'margin_pct'

export function StoreCateringPanel({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [sortKey, setSortKey] = useState<SortKey>('revenue')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [classFilter, setClassFilter] = useState<MenuClass | null>(null)
  const [openDish, setOpenDish] = useState<CateringDish | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-catering', companyId, dateFrom, dateTo],
    queryFn: () => getStoreCateringMenu(dateFrom, dateTo),
  })

  const dishes = useMemo(() => {
    const rows = (data?.dishes ?? []).filter((d) => !classFilter || d.menu_class === classFilter)
    const dir = sortDir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = a[sortKey] ?? -Infinity, bv = b[sortKey] ?? -Infinity
      return av === bv ? 0 : (av > bv ? dir : -dir)
    })
  }, [data, classFilter, sortKey, sortDir])

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка меню общепита…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки общепита</div>
  if (!data) return null

  const s = data.summary
  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(k); setSortDir('desc') }
  }

  const KPIS = [
    { label: 'Выручка общепита', value: fmtMoney(s.revenue) },
    { label: 'Блюд в меню', value: nf(s.dishes_count), hint: `${nf(s.portions)} порций` },
    { label: 'Фудкост', value: pctStr(s.food_cost_pct), hint: 'себест. ингр. / выручка' },
    { label: 'Валовая маржа', value: pctStr(s.margin_pct), cls: 'text-emerald-300/90' },
    { label: 'Валовая прибыль', value: fmtMoney(s.margin), cls: 'text-emerald-300/90' },
  ]

  const th = (k: SortKey, label: string) => (
    <th onClick={() => toggleSort(k)} className="px-3 py-2 font-medium text-right whitespace-nowrap cursor-pointer select-none hover:text-foreground">
      {label}{sortKey === k && <span className="ml-0.5 opacity-60">{sortDir === 'asc' ? '▲' : '▼'}</span>}
    </th>
  )

  return (
    <div className="p-6 space-y-4">
      <div>
        <h3 className="text-base font-semibold">Общепит — инжиниринг меню</h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          {data.period.from} – {data.period.to}. Блюда по популярности × маржинальности; клик по строке —
          свойства блюда (состав ТТК и динамика продаж). Фудкост — по ингредиентам × закупочной себестоимости.
        </p>
      </div>

      {/* KPI */}
      <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
        {KPIS.map((k) => (
          <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">{k.label}</div>
            <div className={`text-lg font-semibold tabular-nums mt-0.5 ${k.cls ?? ''}`}>{k.value}</div>
            {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5">{k.hint}</div>}
          </div>
        ))}
      </div>

      {/* Матрица инжиниринга меню */}
      <div className="grid gap-2.5 grid-cols-2 lg:grid-cols-4">
        {ORDER.map((c) => {
          const m = data.matrix[c] ?? { count: 0, revenue: 0 }
          const meta = CLASS_META[c]
          const active = classFilter === c
          return (
            <button
              key={c} onClick={() => setClassFilter(active ? null : c)}
              className={`text-left rounded-lg border p-3 transition-colors ${active ? 'border-primary bg-primary/5' : 'border-border/50 bg-card/40 hover:bg-accent/20'}`}
            >
              <div className="flex items-center justify-between">
                <span className={`text-sm font-semibold ${meta.text}`}>{meta.emoji} {meta.label}</span>
                <span className="text-lg font-semibold tabular-nums">{m.count}</span>
              </div>
              <div className="text-[11px] text-muted-foreground mt-1 leading-snug">{meta.desc}</div>
              <div className="text-[11px] text-muted-foreground/70 mt-1 tabular-nums">выручка {fmtMoney(m.revenue)}</div>
            </button>
          )
        })}
      </div>
      {classFilter && (
        <div className="text-xs text-muted-foreground -mt-1">
          Фильтр: {CLASS_META[classFilter].emoji} {CLASS_META[classFilter].label} · <button className="underline" onClick={() => setClassFilter(null)}>сбросить</button>
        </div>
      )}

      {/* Таблица блюд */}
      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium text-left">Блюдо</th>
              {th('qty', 'Продано')}
              {th('popularity_pct', 'Попул.%')}
              {th('revenue', 'Выручка')}
              {th('share', 'Доля%')}
              {th('avg_price', 'Ср.цена')}
              {th('food_cost_pct', 'Фудкост%')}
              {th('margin_pct', 'Маржа%')}
            </tr>
          </thead>
          <tbody>
            {dishes.map((d) => {
              const meta = CLASS_META[d.menu_class]
              return (
                <tr key={d.guid} onClick={() => setOpenDish(d)} className="border-t border-border/30 hover:bg-accent/20 cursor-pointer">
                  <td className="px-3 py-1.5">
                    <span className="font-medium">{d.name}</span>
                    <span className={`ml-2 inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${meta.badge}`}>{meta.emoji} {meta.short}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{nf(d.qty)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{pctStr(d.popularity_pct)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(d.revenue)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{pctStr(d.share)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(d.avg_price)}</td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${d.food_cost_pct != null && d.food_cost_pct > 40 ? 'text-amber-300/90' : ''}`}>{pctStr(d.food_cost_pct)}</td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${d.margin_pct != null && d.margin_pct < 30 ? 'text-red-400/70' : 'text-emerald-300/70'}`}>{pctStr(d.margin_pct)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {dishes.length === 0 && (
          <div className="px-3 py-6 text-sm text-muted-foreground text-center">Нет блюд за период (поставьте апрель — локальная копия ЦБ до 29.04).</div>
        )}
      </div>

      {openDish && <DishModal dish={openDish} onClose={() => setOpenDish(null)} />}
    </div>
  )
}

function DishModal({ dish: d, onClose }: { dish: CateringDish; onClose: () => void }) {
  const meta = CLASS_META[d.menu_class]
  const METRICS: { label: string; value: string; cls?: string }[] = [
    { label: 'Продано, порций', value: nf(d.qty) },
    { label: 'Выручка', value: fmtMoney(d.revenue) },
    { label: 'Средняя цена', value: fmtMoney(d.avg_price) },
    { label: 'Себест. порции', value: d.cost_per_portion != null ? fmtMoney(d.cost_per_portion) : '—' },
    { label: 'Фудкост', value: pctStr(d.food_cost_pct), cls: d.food_cost_pct != null && d.food_cost_pct > 40 ? 'text-amber-300/90' : '' },
    { label: 'Маржа', value: pctStr(d.margin_pct), cls: 'text-emerald-300/90' },
    { label: 'Вклад-маржа/порц', value: d.cm_unit != null ? fmtMoney(d.cm_unit) : '—', cls: 'text-emerald-300/90' },
    { label: 'Популярность', value: pctStr(d.popularity_pct), cls: 'text-muted-foreground' },
  ]

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-lg shadow-xl max-w-4xl w-full max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* Шапка */}
        <div className="flex items-start justify-between gap-3 px-5 py-3.5 border-b border-border/50">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-semibold">{d.name}</h3>
              <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${meta.badge}`}>{meta.emoji} {meta.label}</span>
            </div>
            <p className="text-xs text-muted-foreground mt-1 max-w-2xl leading-snug">{meta.desc}</p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none px-2 shrink-0">×</button>
        </div>

        <div className="overflow-auto p-5 space-y-4">
          {/* Метрики */}
          <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-4">
            {METRICS.map((m) => (
              <div key={m.label} className="rounded-lg border border-border/50 bg-card/40 p-2.5">
                <div className="text-[10px] text-muted-foreground">{m.label}</div>
                <div className={`text-sm font-semibold tabular-nums mt-0.5 ${m.cls ?? ''}`}>{m.value}</div>
              </div>
            ))}
          </div>

          <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
            {/* Состав порции (ТТК) */}
            <div>
              <div className="text-xs font-medium mb-1.5">Состав порции (ТТК) · {d.ing_count} ингр.</div>
              <div className="rounded-md border border-border/40 overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-muted/20 text-muted-foreground">
                    <tr>
                      <th className="px-2.5 py-1.5 text-left font-medium">Ингредиент</th>
                      <th className="px-2.5 py-1.5 text-right font-medium">На порцию</th>
                      <th className="px-2.5 py-1.5 text-right font-medium">Себест/порц</th>
                      <th className="px-2.5 py-1.5 text-right font-medium">Всего за период</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.ingredients.map((ing) => (
                      <tr key={ing.ref} className="border-t border-border/20">
                        <td className="px-2.5 py-1">{ing.marked && '🔖 '}{ing.name}</td>
                        <td className="px-2.5 py-1 text-right tabular-nums">{ing.qty_per_portion != null ? nf(ing.qty_per_portion, 3) : '—'}</td>
                        <td className="px-2.5 py-1 text-right tabular-nums">{ing.cost_per_portion != null ? fmtMoney(ing.cost_per_portion) : '—'}</td>
                        <td className="px-2.5 py-1 text-right tabular-nums text-muted-foreground">{ing.cost_total != null ? fmtMoney(ing.cost_total) : '—'}</td>
                      </tr>
                    ))}
                    <tr className="border-t border-border/40 font-medium">
                      <td className="px-2.5 py-1">Итого себестоимость порции</td>
                      <td />
                      <td className="px-2.5 py-1 text-right tabular-nums">{d.cost_per_portion != null ? fmtMoney(d.cost_per_portion) : '—'}</td>
                      <td className="px-2.5 py-1 text-right tabular-nums">{d.cost != null ? fmtMoney(d.cost) : '—'}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* Динамика продаж */}
            <div>
              <div className="text-xs font-medium mb-1.5">Динамика продаж (выручка/день) · {d.daily.length} дн.</div>
              <div className="rounded-md border border-border/40 bg-card/30 p-2">
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={d.daily} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border/40" vertical={false} />
                    <XAxis dataKey="date" tickFormatter={(v) => String(v).slice(8, 10)} tick={{ fontSize: 9 }} interval="preserveStartEnd" />
                    <Tooltip
                      contentStyle={{ fontSize: 11, borderRadius: 8, background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))' }}
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      formatter={(v: any, _n: any, p: any) => [`${fmtMoney(v)} · ${nf(p?.payload?.qty ?? 0)} порц`, 'Выручка']}
                      labelFormatter={(l) => `Дата: ${l}`}
                    />
                    <Bar dataKey="revenue" fill="currentColor" className={meta.text} radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
