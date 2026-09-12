/**
 * «Развитие» — рынок глазами нашей компании (решение МАГа 12.09.2026).
 *
 * Главный экран продукта отвечает не на «что происходит на рынке», а на «как нам
 * расти». Сеть растёт пятью способами сразу — своя стройка, роуминг с чужой сетью,
 * франшиза (чужая сеть на нашем обслуживании), корпоративные продажи, программа
 * лояльности, — и в разных регионах уместны разные.
 *
 * Поэтому первое, что здесь видно, — НАШЕ ПОЛОЖЕНИЕ по регионам: где мы почти одни,
 * где делим рынок, где нас нет. Там, где мы одни, строить вторую станцию рядом с
 * собой бессмысленно — расти надо выручкой; там, где нас нет, никакая цена уже не
 * наша, и вход идёт стройкой, роумингом или франшизой.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Compass } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { useCompany } from '@/contexts/CompanyContext'
import {
  getGrowthOverview, getGrowthPresence, type GrowthPresenceRow,
} from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

const ВИДЫ = [
  { k: 'tracks', label: 'Направления роста' },
  { k: 'presence', label: 'Наше положение по регионам' },
] as const

function money(v: number): string {
  if (v >= 1_000_000) return `${nf1.format(v / 1_000_000)} млн ₽`
  if (v >= 1_000) return `${nf.format(Math.round(v / 1_000))} тыс ₽`
  return `${nf.format(Math.round(v))} ₽`
}

/** Положение цветом и словом: цвет один не носитель состояния. */
function Presence({ row }: { row: GrowthPresenceRow }) {
  const tone = row.presence === 'monopoly' || row.presence === 'strong' ? 'text-success'
    : row.presence === 'absent' ? 'text-warning' : ''
  return (
    <span className={tone}>
      {row.presenceLabel}
      {row.sharePct != null && row.presence !== 'absent' && (
        <span className="ml-1 tabular-nums text-muted-foreground">
          {nf1.format(row.sharePct)} %
        </span>
      )}
    </span>
  )
}

function Skeleton() {
  return (
    <div className="space-y-2 p-4" aria-busy="true">
      <span className="sr-only">Считаем направления роста</span>
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-20 animate-pulse rounded-lg border border-border bg-muted/40" />
      ))}
    </div>
  )
}

export function MarketGrowthPanel() {
  const { companyId } = useCompany()
  const [вид, setВид] = useState<string>('tracks')
  const [filter, setFilter] = useState('all')

  const overview = useQuery({
    queryKey: ['market-growth-overview', companyId],
    queryFn: () => getGrowthOverview(companyId, { days: 90 }),
    enabled: !!companyId,
  })
  const presence = useQuery({
    queryKey: ['market-growth-presence', companyId],
    queryFn: () => getGrowthPresence(companyId, { days: 90 }),
    enabled: !!companyId && вид === 'presence',
  })

  if (overview.isLoading) return <Skeleton />

  const groups = overview.data?.presence ?? []
  const absent = groups.find((g) => g.presence === 'absent')
  const monopoly = groups.find((g) => g.presence === 'monopoly')
  const regions = (presence.data?.regions ?? []).filter(
    (r) => filter === 'all' || r.presence === filter)

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Compass className="size-4 text-primary" aria-hidden />
            {groups.length === 0
              ? 'Регионы пока не разложены: нет ни наших объектов с регионом, ни рынка.'
              : `Мы почти одни в ${monopoly?.regions ?? 0} регионах; рынок есть без нас в ${absent?.regions ?? 0}.`}
          </span>
          <span className="text-xs text-muted-foreground">
            положение считается по доле точек сети в регионе, за 90 дней
          </span>
        </CardContent>
      </Card>

      <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={setВид} />

      {вид === 'tracks' && (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          {(overview.data?.tracks ?? []).map((t) => (
            <Card key={t.track}>
              <CardContent className="space-y-2 p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-headline text-sm font-semibold">{t.label}</span>
                  <span className="text-xs text-muted-foreground">
                    {Object.entries(t.leads).length === 0
                      ? 'кандидатов не заведено'
                      : Object.entries(t.leads)
                          .map(([k, v]) => `${LEAD_STATUS[k] ?? k}: ${v}`).join(' · ')}
                  </span>
                </div>
                <p className="text-sm">{t.headline}</p>
                <div className="flex flex-wrap gap-x-6 gap-y-1">
                  {t.metrics.map((m) => (
                    <span key={m.label} className="text-xs text-muted-foreground">
                      {m.label}: <span className="tabular-nums text-foreground">{nf.format(m.value)}</span>
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
          <p className="text-xs text-muted-foreground">
            Мера направления — факт сегодняшнего дня, а не план: сколько возможностей
            видно в данных и сколько уже взято в работу. Где данных нет, строка это и
            говорит — придуманный показатель хуже пустого.
          </p>
        </div>
      )}

      {вид === 'presence' && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={filter} onValueChange={setFilter}>
              <SelectTrigger className="h-8 w-[220px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все регионы</SelectItem>
                <SelectItem value="monopoly">Мы почти одни</SelectItem>
                <SelectItem value="strong">Мы сильнее рынка</SelectItem>
                <SelectItem value="contested">Делим рынок</SelectItem>
                <SelectItem value="weak">Мы слабее рынка</SelectItem>
                <SelectItem value="absent">Нас нет</SelectItem>
              </SelectContent>
            </Select>
            {(presence.data?.groups ?? []).map((g) => (
              <span key={g.presence} className="text-xs text-muted-foreground">
                {g.label}: <span className="tabular-nums text-foreground">{g.regions}</span>
              </span>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
            <table className="w-full text-xs">
              <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
                <tr>
                  <th className="p-2 text-left font-medium">Регион</th>
                  <th className="p-2 text-left font-medium">Наше положение</th>
                  <th className="p-2 text-right font-medium">Наши точки</th>
                  <th className="p-2 text-right font-medium">Чужие</th>
                  <th className="p-2 text-right font-medium">Живые чужие</th>
                  <th className="p-2 text-right font-medium">Сессий</th>
                  <th className="p-2 text-right font-medium">Выручка</th>
                  <th className="p-2 text-left font-medium">Чем расти</th>
                </tr>
              </thead>
              <tbody>
                {regions.map((r) => (
                  <tr key={r.name} className="border-t border-border/60">
                    <td className="p-2 font-medium">{r.name}</td>
                    <td className="p-2"><Presence row={r} /></td>
                    <td className="p-2 text-right tabular-nums">{nf.format(r.ourSites)}</td>
                    <td className="p-2 text-right tabular-nums">{nf.format(r.rivalSites)}</td>
                    <td className="p-2 text-right tabular-nums">{nf.format(r.rivalAlive)}</td>
                    <td className="p-2 text-right tabular-nums">{nf.format(r.ourSessions)}</td>
                    <td className="p-2 text-right tabular-nums">
                      {r.ourRevenue > 0 ? money(r.ourRevenue) : '—'}
                    </td>
                    <td className="p-2 text-muted-foreground">
                      {r.suggestedTracks
                        .map((t) => overview.data?.trackLabels?.[t] ?? t)
                        .slice(0, 2).join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {regions.length === 0 && (
              <p className="p-6 text-center text-xs text-muted-foreground">
                Регионов с таким положением нет.
              </p>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            «Чем расти» — подсказка по положению, а не предписание: где мы одни, растят
            выручку с имеющейся сети, где нас нет — входят стройкой, роумингом или
            франшизой. Решает человек. {presence.data?.note}
          </p>
        </>
      )}
    </div>
  )
}

const LEAD_STATUS: Record<string, string> = {
  new: 'новых',
  working: 'в проработке',
  in_project: 'в проектах',
  rejected: 'отклонено',
  done: 'сделано',
}
