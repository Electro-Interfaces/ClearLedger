/**
 * «План-факт-светофор» (О-1, слой политик) — директорский монитор на Обзоре.
 * Карты факт / план / % / 🟢🟡🔴 по выручке (всего, категории, АЗС) + позиции,
 * спарклайн выручки по дням. План — ручной ввод руководителя (дефолт слоя
 * политик; альтернативы импорт/экстраполяция — задел). Тренд к ППГ включится с
 * накоплением истории (сейчас данные ≈ 1 месяц).
 * Данные: /api/store/plan-facts, /api/store/plan (GoodsDashboardService).
 */
import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Target, Pencil, Check, X, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import {
  getStorePlanFacts, saveStorePlan,
  type PlanFactCard, type PlanRow, type PlanTraffic,
} from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const fmtVal = (metric: string, v: number) => (metric === 'revenue' ? fmtMoney(v) : nf(v))

const TRAFFIC: Record<PlanTraffic, { dot: string; text: string; ring: string; label: string }> = {
  green: { dot: 'bg-emerald-400', text: 'text-emerald-300/90', ring: 'border-emerald-400/40', label: 'план выполнен' },
  amber: { dot: 'bg-amber-400', text: 'text-amber-300/90', ring: 'border-amber-400/40', label: 'зона внимания' },
  red: { dot: 'bg-red-400', text: 'text-red-400/80', ring: 'border-red-400/40', label: 'отставание' },
}

const keyOf = (c: { scope_kind: string; scope_key: string; metric: string }) =>
  `${c.scope_kind}|${c.scope_key}|${c.metric}`

/** Мини-спарклайн выручки по дням (SVG, без recharts). */
function Sparkline({ pts }: { pts: { date: string; value: number }[] }) {
  if (pts.length < 2) return null
  const w = 120, h = 28
  const max = Math.max(1, ...pts.map((p) => p.value))
  const step = w / (pts.length - 1)
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(h - (p.value / max) * (h - 2) - 1).toFixed(1)}`).join(' ')
  return (
    <svg width={w} height={h} className="opacity-70" aria-hidden>
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.4} className="text-primary" />
    </svg>
  )
}

function TrafficCard({ c, compact = false }: { c: PlanFactCard; compact?: boolean }) {
  const t = c.traffic ? TRAFFIC[c.traffic] : null
  return (
    <div className={`rounded-lg border bg-card/40 p-3 ${t ? t.ring : 'border-border/50'}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] text-muted-foreground truncate" title={c.label}>{c.label}</div>
        {t && <span className={`inline-block w-2 h-2 rounded-full ${t.dot} shrink-0`} title={t.label} />}
      </div>
      <div className={`font-semibold tabular-nums mt-0.5 ${compact ? 'text-base' : 'text-lg'}`}>{fmtVal(c.metric, c.fact)}</div>
      {c.plan != null ? (
        <div className="mt-1 flex items-center gap-1.5 text-[11px] flex-wrap">
          <span className="text-muted-foreground">план {fmtVal(c.metric, c.plan)}</span>
          {c.pct != null && t && <span className={`font-medium tabular-nums ${t.text}`}>{nf(c.pct, 0)}%</span>}
          {c.delta != null && (
            <span className={`inline-flex items-center gap-0.5 tabular-nums ${c.delta >= 0 ? 'text-emerald-300/80' : 'text-red-400/70'}`}>
              {c.delta > 0 ? <TrendingUp className="h-3 w-3" /> : c.delta < 0 ? <TrendingDown className="h-3 w-3" /> : <Minus className="h-3 w-3" />}
              {c.delta >= 0 ? '+' : ''}{fmtVal(c.metric, c.delta)}
            </span>
          )}
        </div>
      ) : (
        <div className="mt-1 text-[11px] text-muted-foreground/60">план не задан</div>
      )}
      {c.sparkline && c.sparkline.length > 1 && <div className="mt-1.5"><Sparkline pts={c.sparkline} /></div>}
    </div>
  )
}

export function StorePlanMonitor({ companyId, period }: { companyId: string; period: string }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, number>>({})

  const { data, isLoading } = useQuery({
    queryKey: ['store-plan-facts', companyId, period],
    queryFn: () => getStorePlanFacts(period),
    enabled: !!period && period.length === 7,
  })

  const cards = useMemo(
    () => (data ? [data.total, data.units, ...data.by_category, ...data.by_station] : []),
    [data],
  )

  const save = useMutation({
    mutationFn: (items: PlanRow[]) => saveStorePlan(period, items),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['store-plan-facts', companyId, period] })
      setEditing(false)
    },
  })

  if (isLoading || !data) {
    return <div className="rounded-lg border border-border/50 bg-card/40 p-4 text-sm text-muted-foreground">Загрузка план-факта…</div>
  }

  const startEdit = () => {
    const d: Record<string, number> = {}
    for (const c of cards) d[keyOf(c)] = c.plan ?? 0
    setDraft(d)
    setEditing(true)
  }
  const onSave = () => {
    const items: PlanRow[] = cards.map((c) => ({
      scope_kind: c.scope_kind, scope_key: c.scope_key, metric: c.metric,
      plan_value: Number(draft[keyOf(c)]) || 0,
    }))
    save.mutate(items)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium">План-факт · {data.period.ym}</span>
          {!data.has_plan && !editing && (
            <span className="text-[11px] text-muted-foreground/70">— план на месяц не задан</span>
          )}
        </div>
        {editing ? (
          <div className="flex items-center gap-1.5">
            <button onClick={onSave} disabled={save.isPending}
              className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md text-xs bg-primary/15 text-primary hover:bg-primary/25 disabled:opacity-50">
              <Check className="h-3.5 w-3.5" /> Сохранить
            </button>
            <button onClick={() => setEditing(false)}
              className="inline-flex items-center gap-1 h-7 px-2 rounded-md text-xs text-muted-foreground hover:bg-accent/40">
              <X className="h-3.5 w-3.5" /> Отмена
            </button>
          </div>
        ) : (
          <button onClick={startEdit}
            className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md text-xs border border-border/50 hover:bg-accent/40">
            <Pencil className="h-3.5 w-3.5" /> {data.has_plan ? 'Изменить план' : 'Задать план'}
          </button>
        )}
      </div>

      {editing ? (
        <div className="rounded-lg border border-border/50 bg-card/40 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium text-left">Показатель</th>
                <th className="px-3 py-2 font-medium text-right">Факт</th>
                <th className="px-3 py-2 font-medium text-right w-40">План на {data.period.ym}</th>
              </tr>
            </thead>
            <tbody>
              {cards.map((c) => {
                const k = keyOf(c)
                return (
                  <tr key={k} className="border-t border-border/30">
                    <td className="px-3 py-1.5">
                      {c.label}
                      <span className="text-muted-foreground/60 ml-1">{c.metric === 'qty' ? '(позиции)' : '(₽)'}</span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{fmtVal(c.metric, c.fact)}</td>
                    <td className="px-3 py-1.5 text-right">
                      <input
                        type="number" min={0} inputMode="numeric"
                        value={draft[k] ?? 0}
                        onChange={(e) => setDraft((p) => ({ ...p, [k]: Number(e.target.value) }))}
                        className="w-32 text-right tabular-nums px-2 py-1 rounded border border-border/50 bg-background"
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="px-3 py-2 text-[10px] text-muted-foreground/60 border-t border-border/30">
            Пусто или 0 — показатель без плана. 🟢 ≥100% · 🟡 80–99% · 🔴 &lt;80%.
          </div>
        </div>
      ) : (
        <>
          <div className="grid gap-2.5 grid-cols-2 lg:grid-cols-4">
            <TrafficCard c={data.total} />
            <TrafficCard c={data.units} />
            {data.by_category.map((c) => <TrafficCard key={keyOf(c)} c={c} compact />)}
          </div>
          {data.by_station.length > 1 && (
            <div className="grid gap-2.5 grid-cols-2 lg:grid-cols-4">
              {data.by_station.map((c) => <TrafficCard key={keyOf(c)} c={c} compact />)}
            </div>
          )}
        </>
      )}
    </div>
  )
}
