/**
 * ABC-XYZ классификация станций ЭЗС — управление активом сети.
 *
 * ABC (строки) — вклад станции в результат сети (выручка/энергия), накопленной
 * долей: A ≤80%, B ≤95%, C — хвост. XYZ (колонки) — стабильность спроса по
 * коэф. вариации спроса по неделям/месяцам (с нулевыми периодами): X ровно,
 * Z рвано. На пересечении — 9 групп: AX = ядро сети (беречь), CZ = кандидаты
 * на вывод/переезд. Клик по клетке матрицы фильтрует таблицу станций.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { ExportButton } from './analytics/ExportButton'
import { ViewParamsBar } from './ViewParamsBar'
import { MetricHint } from './analytics/MetricHint'
import { fmtMoney, fmtMoneyShort } from '@/services/analyticsService'
import { getStationAbcXyz, type AbcXyzMeasure, type AbcXyzBucket, type AbcXyzStation } from '@/services/abcXyzService'
import { useNetScope, useScopeSubtitle } from '@/hooks/useScopeReset'
import { useTabParams } from '@/hooks/useTabParams'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

// Тон клетки по классу: AX — ядро (зелёный), CZ — хвост (красный), между — градация.
const CLASS_TONE: Record<string, string> = {
  AX: 'border-emerald-500/40 bg-emerald-500/10 hover:bg-emerald-500/20',
  AY: 'border-teal-500/30 bg-teal-500/10 hover:bg-teal-500/20',
  AZ: 'border-amber-500/30 bg-amber-500/10 hover:bg-amber-500/20',
  BX: 'border-green-500/30 bg-green-500/10 hover:bg-green-500/20',
  BY: 'border-yellow-500/25 bg-yellow-500/10 hover:bg-yellow-500/20',
  BZ: 'border-orange-500/30 bg-orange-500/10 hover:bg-orange-500/20',
  CX: 'border-sky-500/25 bg-sky-500/10 hover:bg-sky-500/20',
  CY: 'border-zinc-500/25 bg-muted/40 hover:bg-muted/60',
  CZ: 'border-red-500/40 bg-red-500/10 hover:bg-red-500/20',
}
// Короткая подпись категории — прямо в клетке (полное объяснение — в title/hint).
const CELL_CAPTION: Record<string, string> = {
  AX: 'Ядро сети — беречь',
  AY: 'Крупные, спрос колеблется',
  AZ: 'Крупные, спрос рваный',
  BX: 'Опора сети',
  BY: 'Потенциал роста',
  BZ: 'Середняк, рвано',
  CX: 'Стабильная ниша',
  CY: 'Малые, наблюдать',
  CZ: 'Кандидаты на вывод',
}
const CLASS_BADGE: Record<string, string> = {
  A: 'text-emerald-600 dark:text-emerald-400', B: 'text-amber-600 dark:text-amber-400',
  C: 'text-red-600 dark:text-red-400',
  X: 'text-emerald-600 dark:text-emerald-400', Y: 'text-amber-600 dark:text-amber-400',
  Z: 'text-red-600 dark:text-red-400', '—': 'text-muted-foreground',
}

function Seg<T extends string>({ value, onChange, opts }: {
  value: T; onChange: (v: T) => void; opts: { v: T; label: string }[]
}) {
  return (
    <div className="inline-flex rounded-md border border-border bg-muted/60 p-0.5">
      {opts.map((o) => (
        <button key={o.v} type="button" onClick={() => onChange(o.v)}
          className={`h-8 rounded px-2.5 text-xs font-medium transition-colors ${
            value === o.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function AbcXyzPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const sc = useNetScope()
  const subtitle = useScopeSubtitle({ scopeApplied: true })
  const ref = useRef<HTMLDivElement>(null)
  const [p, patch] = useTabParams('cs_abcxyz', {
    measure: 'amount' as AbcXyzMeasure, bucket: 'week' as AbcXyzBucket,
  })
  // Выбор клетки/группы для фильтра таблицы (локально, не персистится).
  const [sel, setSel] = useState<{ abc?: string; xyz?: string }>({})
  const [sort, setSort] = useState<{ key: keyof AbcXyzStation; dir: 'asc' | 'desc' }>({ key: 'measure', dir: 'desc' })

  const { data, isLoading } = useQuery({
    queryKey: ['abc-xyz', companyId, dateFrom, dateTo, p.measure, p.bucket, sc.key],
    queryFn: () => getStationAbcXyz({ companyId, dateFrom, dateTo, measure: p.measure, bucket: p.bucket, stations: sc.stations, regions: sc.regions }),
  })

  const isMoney = p.measure === 'amount'
  const fmtM = (v: number) => (isMoney ? `${fmtMoney(v)} ₽` : `${nf0.format(Math.round(v))} кВтч`)
  const cellByClass = useMemo(() => {
    const m = new Map<string, { stations: number; share_pct: number; hint: string }>()
    for (const c of data?.cells ?? []) m.set(`${c.abc}${c.xyz}`, c)
    return m
  }, [data])

  const rows = useMemo(() => {
    let r = data?.stations ?? []
    if (sel.abc) r = r.filter((s) => s.abc === sel.abc)
    if (sel.xyz) r = r.filter((s) => s.xyz === sel.xyz)
    const { key, dir } = sort
    const mul = dir === 'asc' ? 1 : -1
    return [...r].sort((a, b) => {
      const av = a[key], bv = b[key]
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * mul
      return String(av).localeCompare(String(bv)) * mul
    })
  }, [data, sel, sort])

  const toggleSort = (key: keyof AbcXyzStation) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: 'desc' }))

  const xyzCols = ['X', 'Y', 'Z', ...(data && data.n_buckets < 2 ? ['—'] : [])]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 pb-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          ABC-XYZ станций
          <MetricHint text="ABC — вклад станции в результат сети (накопленной долей: A ≤80%, B ≤95%, C — хвост). XYZ — стабильность спроса по коэффициенту вариации по неделям/месяцам (X ровно, Z рвано). AX = ядро сети (беречь), CZ = кандидаты на вывод. Клик по клетке — список станций." />
        </div>
        <ExportButton title="ABC-XYZ станций ЭЗС" subtitle={subtitle} getEl={() => ref.current} />
      </div>

      <div className="px-4">
        <ViewParamsBar>
          <label className="text-xs text-muted-foreground">Метрика (ABC)</label>
          <Seg value={p.measure} onChange={(v) => patch({ measure: v })}
            opts={[{ v: 'amount', label: 'Выручка' }, { v: 'energy', label: 'Энергия' }]} />
          <label className="ml-2 text-xs text-muted-foreground">Шаг спроса (XYZ)</label>
          <Seg value={p.bucket} onChange={(v) => patch({ bucket: v })}
            opts={[{ v: 'week', label: 'Неделя' }, { v: 'month', label: 'Месяц' }]} />
        </ViewParamsBar>
      </div>

      {isLoading || !data ? (
        <div className="flex h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
      ) : (
        <div ref={ref} className="space-y-4 px-4">
          {/* Итоговые карточки: ядро AX и хвост CZ */}
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryCard title="Всего станций" value={nf0.format(data.stations_total)}
              sub={`результат сети ${fmtM(data.total_measure)}`} />
            <SummaryCard title="Ядро сети (AX)" value={nf0.format(data.core.stations)}
              sub={`${data.core.share_pct}% результата · беречь`} tone="text-emerald-600 dark:text-emerald-400" />
            <SummaryCard title="Хвост (CZ)" value={nf0.format(data.tail.stations)}
              sub={`${data.tail.share_pct}% результата · кандидаты на вывод`} tone="text-red-600 dark:text-red-400" />
          </div>

          {/* Матрица 3×3 */}
          <Card>
            <CardContent className="overflow-x-auto pt-4">
              <table className="w-full min-w-[560px] border-separate border-spacing-1 text-xs">
                <thead>
                  <tr>
                    <th className="w-24" />
                    {xyzCols.map((x) => (
                      <th key={x} className="p-1 text-center font-medium">
                        <div className={CLASS_BADGE[x]}>{x}</div>
                        <div className="text-[10px] font-normal text-muted-foreground">{data.xyz_labels[x]?.replace(/^. — /, '')}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(['A', 'B', 'C'] as const).map((a) => (
                    <tr key={a}>
                      <th className="pr-2 text-right align-middle">
                        <div className={`text-sm ${CLASS_BADGE[a]}`}>{a}</div>
                        <div className="text-[10px] font-normal text-muted-foreground">{data.abc_labels[a]?.replace(/^. — /, '')}</div>
                      </th>
                      {xyzCols.map((x) => {
                        const cls = `${a}${x}`
                        const c = cellByClass.get(cls)
                        const active = sel.abc === a && sel.xyz === x
                        return (
                          <td key={x} className="p-0">
                            <button type="button"
                              onClick={() => setSel((s) => (s.abc === a && s.xyz === x ? {} : { abc: a, xyz: x }))}
                              title={c?.hint}
                              className={`h-full w-full rounded-lg border p-2 text-left transition-colors ${CLASS_TONE[cls] ?? 'border-border bg-muted/30'} ${active ? 'ring-2 ring-primary' : ''}`}>
                              <div className="flex items-baseline justify-between gap-1">
                                <span className="text-lg font-semibold tabular-nums leading-none">{nf0.format(c?.stations ?? 0)}</span>
                                <span className="text-[10px] text-muted-foreground">{cls}</span>
                              </div>
                              {CELL_CAPTION[cls] && (
                                <div className="mt-1 text-[10px] font-medium leading-tight text-foreground/80">{CELL_CAPTION[cls]}</div>
                              )}
                              <div className="mt-0.5 text-[10px] text-muted-foreground">{c?.share_pct ?? 0}% результата</div>
                            </button>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="mt-2 text-[11px] text-muted-foreground">
                Строки — вклад в {isMoney ? 'выручку' : 'энергию'} (ABC), колонки — стабильность спроса по {p.bucket === 'week' ? 'неделям' : 'месяцам'} (XYZ, за период {data.n_buckets} {p.bucket === 'week' ? 'нед.' : 'мес.'}).
                {sel.abc || sel.xyz ? (
                  <button type="button" onClick={() => setSel({})} className="ml-2 text-primary hover:underline">сбросить фильтр ✕</button>
                ) : ' Клик по клетке — список станций ниже.'}
              </div>
            </CardContent>
          </Card>

          {/* Таблица станций */}
          <Card>
            <CardContent className="overflow-x-auto pt-4">
              <div className="mb-2 text-xs text-muted-foreground">
                Станций: {nf0.format(rows.length)}
                {(sel.abc || sel.xyz) && <span> · фильтр: {sel.abc ?? '*'}{sel.xyz ?? '*'}</span>}
              </div>
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b text-muted-foreground">
                    <th className="p-2 text-left font-medium">Станция</th>
                    <th className="p-2 text-left font-medium">Регион</th>
                    <th className="p-2 text-left font-medium">Владелец</th>
                    <Th label={isMoney ? 'Выручка' : 'Энергия'} k="measure" sort={sort} onSort={toggleSort} />
                    <Th label="Доля" k="share_pct" sort={sort} onSort={toggleSort} />
                    <Th label="Накопл." k="cum_share_pct" sort={sort} onSort={toggleSort} />
                    <Th label="Сессии" k="sessions" sort={sort} onSort={toggleSort} />
                    <Th label="CV" k="cv" sort={sort} onSort={toggleSort} />
                    <Th label="Класс" k="class" sort={sort} onSort={toggleSort} />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => (
                    <tr key={s.location_id} className="border-b border-border/30 hover:bg-muted/30">
                      <td className="p-2 font-medium">{s.name} {s.station_number && <span className="text-muted-foreground">№{s.station_number}</span>}</td>
                      <td className="p-2 text-muted-foreground">{s.region}</td>
                      <td className="p-2 text-muted-foreground">{s.owner_label}</td>
                      <td className="p-2 text-right font-mono tabular-nums">{isMoney ? fmtMoneyShort(s.measure) : nf0.format(Math.round(s.measure))}</td>
                      <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">{s.share_pct}%</td>
                      <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">{s.cum_share_pct}%</td>
                      <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">{nf0.format(s.sessions)}</td>
                      <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">{s.cv.toFixed(2)}</td>
                      <td className="p-2 text-center font-mono font-semibold">
                        <span className={CLASS_BADGE[s.abc]}>{s.abc}</span><span className={CLASS_BADGE[s.xyz]}>{s.xyz}</span>
                      </td>
                    </tr>
                  ))}
                  {rows.length === 0 && (
                    <tr><td colSpan={9} className="p-6 text-center text-muted-foreground">Нет станций в выбранной группе.</td></tr>
                  )}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}

function SummaryCard({ title, value, sub, tone }: { title: string; value: string; sub: string; tone?: string }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{title}</div>
        <div className={`mt-1 text-2xl font-semibold tabular-nums leading-tight ${tone ?? ''}`}>{value}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>
      </CardContent>
    </Card>
  )
}

function Th({ label, k, sort, onSort }: {
  label: string; k: keyof AbcXyzStation
  sort: { key: keyof AbcXyzStation; dir: 'asc' | 'desc' }; onSort: (k: keyof AbcXyzStation) => void
}) {
  const active = sort.key === k
  return (
    <th className="p-2 text-right font-medium">
      <button type="button" onClick={() => onSort(k)} className={`hover:text-foreground ${active ? 'text-foreground' : ''}`}>
        {label}{active ? (sort.dir === 'desc' ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  )
}
