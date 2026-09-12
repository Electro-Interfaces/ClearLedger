/**
 * «Территории» и «Белые пятна» (docs/MARKET-ROADMAP.md §9, этап 3).
 *
 * Клиент выбирает не нашу станцию против нашей же, а всё, что в радиусе. Поэтому
 * единица разговора — территория: сколько там нашего, сколько чужого, чья доля и
 * какая цена держится.
 *
 * Единица — город (и регион сверху), а не гексагон: сетка нужна, чтобы сравнивать
 * спрос по площади, а данных о спросе территории — населения, парка электромобилей,
 * трафика — у нас пока нет ни одного. Пока их нет, гексагон даёт то же, что город,
 * но в виде, о котором нельзя спросить человека.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Map as MapIcon } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import {
  createGrowthLead, getMarketTerritories, getMarketWhitespots, type MarketTerritory,
} from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

function money(v: number): string {
  if (v >= 1_000_000) return `${nf1.format(v / 1_000_000)} млн ₽`
  if (v >= 1_000) return `${nf.format(Math.round(v / 1_000))} тыс ₽`
  return `${nf.format(Math.round(v))} ₽`
}

function Num({ v, unit, digits = 0 }: { v: number | null | undefined; unit?: string; digits?: number }) {
  if (v == null) return <span className="text-muted-foreground">нет данных</span>
  return <span className="tabular-nums">
    {digits ? nf1.format(v) : nf.format(v)}{unit ? ` ${unit}` : ''}
  </span>
}

function Skeleton() {
  return (
    <div className="space-y-2 p-4" aria-busy="true">
      <span className="sr-only">Считаем территории</span>
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="h-10 animate-pulse rounded-lg border border-border bg-muted/40" />
      ))}
    </div>
  )
}

/** Доля рынка словами: цвет помогает, но состояние называет текст. */
function Share({ row }: { row: MarketTerritory }) {
  if (row.sharePct == null) return <span className="text-muted-foreground">—</span>
  const strong = row.sharePct >= 50
  const weak = row.sharePct < 20
  return (
    <span className={`tabular-nums ${strong ? 'text-success' : weak ? 'text-warning' : ''}`}>
      {nf1.format(row.sharePct)} %
    </span>
  )
}

export function MarketTerritoriesPanel() {
  const { companyId } = useCompany()
  const [level, setLevel] = useState<'city' | 'region'>('city')
  const [q, setQ] = useState('')

  const data = useQuery({
    queryKey: ['market-territories', companyId, level],
    queryFn: () => getMarketTerritories(companyId, { level, days: 90 }),
    enabled: !!companyId,
  })

  if (data.isLoading) return <Skeleton />

  const all = data.data?.territories ?? []
  const rows = all.filter((r) => !q || r.name.toLowerCase().includes(q.toLowerCase()))
  const withUs = all.filter((r) => r.ourSites > 0)
  const weak = withUs.filter((r) => r.sharePct != null && r.sharePct < 30)

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <MapIcon className="size-4 text-primary" aria-hidden />
            {withUs.length === 0
              ? 'Наших объектов в разрезе территорий пока нет.'
              : `Мы стоим в ${withUs.length} территориях; в ${weak.length} наша доля ниже 30 %.`}
          </span>
          <span className="text-xs text-muted-foreground">
            территорий всего {all.length}, продажи за 90 дней
          </span>
          <Select value={level} onValueChange={(v) => setLevel(v as 'city' | 'region')}>
            <SelectTrigger className="h-8 w-[140px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="city">По городам</SelectItem>
              <SelectItem value="region">По регионам</SelectItem>
            </SelectContent>
          </Select>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Территория"
            className="h-8 w-[180px] text-xs" />
        </CardContent>
      </Card>

      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
            <tr>
              <th className="p-2 text-left font-medium">Территория</th>
              <th className="p-2 text-right font-medium">Наши точки</th>
              <th className="p-2 text-right font-medium">Сессий</th>
              <th className="p-2 text-right font-medium">Выручка</th>
              <th className="p-2 text-right font-medium">Чужие точки</th>
              <th className="p-2 text-right font-medium">Живые</th>
              <th className="p-2 text-right font-medium">Наша доля</th>
              <th className="p-2 text-right font-medium">Наша ₽/кВт·ч</th>
              <th className="p-2 text-right font-medium">Рынок ₽/кВт·ч</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="border-t border-border/60">
                <td className="p-2 font-medium">{r.name}</td>
                <td className="p-2 text-right"><Num v={r.ourSites} /></td>
                <td className="p-2 text-right"><Num v={r.ourSessions} /></td>
                <td className="p-2 text-right tabular-nums">
                  {r.ourRevenue > 0 ? money(r.ourRevenue) : '—'}
                </td>
                <td className="p-2 text-right"><Num v={r.rivalSites} /></td>
                <td className="p-2 text-right"><Num v={r.rivalAlive} /></td>
                <td className="p-2 text-right"><Share row={r} /></td>
                <td className="p-2 text-right"><Num v={r.ourPricePerKwh} digits={1} /></td>
                <td className="p-2 text-right"><Num v={r.marketPricePerKwh} digits={1} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Доля считается по точкам сети: порты у чужих известны не везде, и доля по ним
        прыгала бы от заполненности поля, а не от рынка. Домашние розетки в счёт не идут.
      </p>
    </div>
  )
}

export function MarketWhitespotsPanel() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [level, setLevel] = useState<'city' | 'region'>('city')
  const [taken, setTaken] = useState<string[]>([])

  // Найденная возможность должна уходить в работу отсюда же: экран, с которого
  // нельзя ничего начать, остаётся чтением.
  const toLead = useMutation({
    mutationFn: (row: MarketTerritory) => createGrowthLead(companyId, {
      track: 'build',
      title: `Войти в ${row.name}: рынок есть, нас нет`,
      subject_kind: 'territory', subject_ref: row.name,
      evidence: {
        city: row.name, rivalSites: row.rivalSites, rivalAlive: row.rivalAlive,
        rivalPorts: row.rivalPorts, marketPricePerKwh: row.marketPricePerKwh,
        source: 'белые пятна',
      },
    }),
    onSuccess: (_data, row) => {
      setTaken((prev) => [...prev, row.name])
      qc.invalidateQueries({ queryKey: ['market-growth-leads', companyId] })
      qc.invalidateQueries({ queryKey: ['market-growth-overview', companyId] })
    },
  })

  const data = useQuery({
    queryKey: ['market-whitespots', companyId, level],
    queryFn: () => getMarketWhitespots(companyId, { level }),
    enabled: !!companyId,
  })

  if (data.isLoading) return <Skeleton />

  const spots = data.data?.spots ?? []
  const alive = spots.filter((s) => s.rivalAlive > 0)

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3">
          <span className="text-sm font-medium">
            {spots.length === 0
              ? 'Белых пятен не найдено: рынок наблюдается только там, где стоим мы.'
              : `Рынок есть, а нас нет в ${spots.length} территориях; в ${alive.length} из них за 90 дней заряжали.`}
          </span>
          <Select value={level} onValueChange={(v) => setLevel(v as 'city' | 'region')}>
            <SelectTrigger className="h-8 w-[140px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="city">По городам</SelectItem>
              <SelectItem value="region">По регионам</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
            <tr>
              <th className="p-2 text-left font-medium">Территория</th>
              <th className="p-2 text-right font-medium">Чужих точек</th>
              <th className="p-2 text-right font-medium">Живых за 90 дн</th>
              <th className="p-2 text-right font-medium">Портов</th>
              <th className="p-2 text-right font-medium">Цена рынка</th>
              <th className="p-2 text-right font-medium">Домашних розеток</th>
              <th className="p-2 text-left font-medium">Действие</th>
            </tr>
          </thead>
          <tbody>
            {spots.map((r) => (
              <tr key={r.name} className="border-t border-border/60">
                <td className="p-2 font-medium">{r.name}</td>
                <td className="p-2 text-right"><Num v={r.rivalSites} /></td>
                <td className="p-2 text-right"><Num v={r.rivalAlive} /></td>
                <td className="p-2 text-right"><Num v={r.rivalPorts} /></td>
                <td className="p-2 text-right"><Num v={r.marketPricePerKwh} digits={1} /></td>
                <td className="p-2 text-right"><Num v={r.homeSockets} /></td>
                <td className="p-2">
                  {taken.includes(r.name) ? (
                    <span className="text-xs text-muted-foreground">в кандидатах</span>
                  ) : (
                    <Button size="xs" variant="outline" disabled={toLead.isPending}
                      onClick={() => toLead.mutate(r)}>
                      В кандидаты
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        {data.data?.basis ?? ''} Территория с мёртвыми точками — не приглашение, а
        предупреждение: там уже пробовали.
      </p>
    </div>
  )
}
