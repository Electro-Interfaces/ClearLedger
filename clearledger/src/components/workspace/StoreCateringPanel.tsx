import { useMemo, useRef, useState, type ComponentType } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpDown, CircleAlert, CircleHelp, CircleMinus, ExternalLink, Fuel, Search,
  ShieldCheck, ShieldQuestion, Star, UtensilsCrossed,
} from 'lucide-react'
import {
  getStoreCateringMenu, type CateringComparison, type CateringDish, type CateringMenuData, type MenuClass,
} from '@/services/storeService'
import { getDemoStoreCateringMenu } from '@/services/storeDemoService'
import { fmtMoney } from '@/services/analyticsService'
import { ExportButton } from './analytics/ExportButton'
import { ChzBadge } from '@/components/common/ChzBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { rowDrill } from './rowDrill'

const nf = (n: number, digits = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(n)
const pct = (value: number | null, digits = 1) => value == null ? '—' : `${nf(value, digits)}%`

type CostStatus = CateringMenuData['summary']['cost_status']
type Icon = ComponentType<{ className?: string }>
type SortKey = 'revenue' | 'qty' | 'food_cost_pct' | 'margin'

const STATUS: Record<CostStatus, { label: string; className: string }> = {
  exact: { label: 'Точно', className: 'border-emerald-500/40 text-emerald-600 dark:text-emerald-300' },
  estimate: { label: 'Есть оценки', className: 'border-amber-500/40 text-amber-700 dark:text-amber-300' },
  partial: { label: 'Неполно', className: 'border-amber-500/40 text-amber-700 dark:text-amber-300' },
  missing: { label: 'Нет данных', className: 'border-destructive/40 text-destructive' },
}

const CLASS_META: Record<MenuClass, { label: string; short: string; description: string; icon: Icon }> = {
  star: { label: 'Звезда', short: 'Звезда', icon: Star, description: 'Высокий спрос и высокий вклад порции.' },
  plowhorse: { label: 'Рабочая лошадка', short: 'Лошадка', icon: ShieldCheck, description: 'Высокий спрос, но вклад порции ниже среднего.' },
  puzzle: { label: 'Загадка', short: 'Загадка', icon: CircleHelp, description: 'Высокий вклад порции при низком спросе.' },
  dog: { label: 'Балласт', short: 'Балласт', icon: CircleMinus, description: 'Низкий спрос и низкий вклад порции.' },
  unknown: { label: 'Без точной себестоимости', short: 'Нет расчёта', icon: ShieldQuestion, description: 'Классификация отключена, пока себестоимость неполна.' },
}

export function StoreCateringPanel({ companyId, dateFrom, dateTo, stations, demo = false }: {
  companyId: string
  dateFrom: string
  dateTo: string
  stations?: string[]
  demo?: boolean
}) {
  const [search, setSearch] = useState('')
  const [classFilter, setClassFilter] = useState<MenuClass | 'all'>('all')
  const [costFilter, setCostFilter] = useState<CostStatus | 'all'>('all')
  const [sortKey, setSortKey] = useState<SortKey>('revenue')
  const [openDish, setOpenDish] = useState<CateringDish | null>(null)
  const exportRef = useRef<HTMLDivElement>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-catering', companyId, dateFrom, dateTo, stations, demo],
    queryFn: () => demo
      ? getDemoStoreCateringMenu(dateFrom, dateTo, stations)
      : getStoreCateringMenu(dateFrom, dateTo, stations),
  })

  const dishes = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('ru')
    return [...(data?.dishes ?? [])]
      .filter((dish) => !query || dish.name.toLocaleLowerCase('ru').includes(query))
      .filter((dish) => classFilter === 'all' || dish.menu_class === classFilter)
      .filter((dish) => costFilter === 'all' || dish.cost_status === costFilter)
      .sort((left, right) => (right[sortKey] ?? -Infinity) - (left[sortKey] ?? -Infinity))
  }, [classFilter, costFilter, data?.dishes, search, sortKey])

  if (isLoading) return <CateringSkeleton />
  if (error) return <div className="p-6 text-sm text-destructive">Не удалось загрузить экономику общепита.</div>
  if (!data) return null

  const summary = data.summary
  const status = STATUS[summary.cost_status]
  const contribution = summary.operating_contribution ?? summary.preliminary_contribution
  const contributionLabel = summary.operating_contribution == null ? 'Предварительный вклад' : 'Операционный вклад'
  const foodCostLabel = summary.cost_status === 'exact' ? 'Фактический фудкост' : 'Предварительный фудкост'

  return (
    <div ref={exportRef} className="flex flex-col gap-5 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h3 className="text-base font-semibold">Общепит</h3>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            Рабочее место управляющего сетью: фактическая экономика, станции по неделям,
            меню и наблюдаемые кросс-продажи. Операционный вклад не включает аренду, ФОТ,
            коммунальные расходы и амортизацию.
          </p>
        </div>
        <ExportButton title="Общепит" subtitle={`${data.period.from} — ${data.period.to}`} getEl={() => exportRef.current} />
      </div>

      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-2 py-4">
          <Badge variant="outline" className={status.className}>{status.label}</Badge>
          <span className="text-sm font-medium">Достоверность экономики</span>
          <span className="text-xs text-muted-foreground">точное покрытие {pct(summary.exact_coverage_pct)}</span>
          {summary.missing_loss_documents > 0 && (
            <span className="inline-flex items-center gap-1 text-xs text-amber-700 dark:text-amber-300">
              <CircleAlert className="size-3.5" /> без оценки потерь: {summary.missing_loss_documents}
            </span>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Фактическая экономика</CardTitle>
          <CardDescription>Один порядок расчёта для станции и сети.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 overflow-hidden rounded-lg border lg:grid-cols-4 xl:grid-cols-7">
            <BridgeMetric label="Выручка с НДС" value={fmtMoney(summary.sales_gross)} />
            <BridgeMetric label="Возвраты гостей" value={`− ${fmtMoney(summary.customer_returns)}`} loss />
            <BridgeMetric label="НДС" value={`− ${fmtMoney(summary.vat)}`} loss />
            <BridgeMetric label="Ингредиенты" value={`− ${fmtMoney(summary.ingredient_cost)}`} loss />
            <BridgeMetric label="Списания" value={`− ${fmtMoney(summary.writeoffs)}`} loss />
            <BridgeMetric label="Недостачи" value={`− ${fmtMoney(summary.shortages)}`} loss />
            <BridgeMetric label={contributionLabel} value={fmtMoney(contribution)} strong />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
            <span>Выручка без НДС: {fmtMoney(summary.net_revenue)}</span>
            <span>{foodCostLabel}: {pct(summary.food_cost_pct)}</span>
            <span>{nf(summary.portions)} порций · {nf(summary.dishes_count)} позиций</span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Рекомендации</CardTitle>
          <CardDescription>Список по фактам периода. Задачи не создаются.</CardDescription>
        </CardHeader>
        <CardContent className="divide-y">
          {data.recommendations.map((item) => (
            <div key={`${item.title}-${item.evidence}`} className="grid gap-2 py-3 first:pt-0 last:pb-0 lg:grid-cols-[minmax(180px,.8fr)_minmax(220px,1fr)_minmax(280px,1.2fr)]">
              <div className="text-sm font-medium">{item.title}</div>
              <div className="text-xs text-muted-foreground">{item.evidence}</div>
              <div className="text-xs leading-relaxed text-muted-foreground">{item.action}</div>
            </div>
          ))}
          {data.recommendations.length === 0 && (
            <div className="py-3 text-sm text-muted-foreground">За выбранный период рекомендаций нет.</div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Станции и недели</CardTitle>
          <CardDescription>Сравнение по тому же экономическому мосту; неполные цифры помечены.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow>
                <TableHead>АЗС</TableHead><TableHead>Неделя</TableHead>
                <TableHead className="text-right">Без НДС</TableHead><TableHead className="text-right">Ингредиенты</TableHead>
                <TableHead className="text-right">Потери</TableHead><TableHead className="text-right">Вклад</TableHead>
                <TableHead className="text-right">Фудкост</TableHead><TableHead className="text-right">К топливу</TableHead><TableHead>Статус</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {data.comparison.map((row) => (
                  <TableRow key={`${row.station_id}-${row.week_from}`}>
                    <TableCell><StationCell row={row} demo={demo} /></TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{row.week_from} — {row.week_to}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtMoney(row.net_revenue)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtMoney(row.ingredient_cost)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtMoney(row.direct_losses)}</TableCell>
                    <TableCell className="text-right font-medium tabular-nums">{fmtMoney(row.operating_contribution ?? row.preliminary_contribution)}</TableCell>
                    <TableCell className="text-right tabular-nums">{pct(row.food_cost_pct)}</TableCell>
                    <TableCell className="text-right tabular-nums">{pct(row.attach_rate)}</TableCell>
                    <TableCell><StatusBadge status={row.cost_status} /></TableCell>
                  </TableRow>
                ))}
                {data.comparison.length === 0 && <TableRow><TableCell colSpan={9} className="h-24 text-center text-muted-foreground">За период нет продаж общепита.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Fuel className="size-4" /> Наблюдаемая связь с топливом</CardTitle>
          <CardDescription>Совместное появление в чеках, не доказанный эффект предложения кассира.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 lg:grid-cols-[280px_1fr]">
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border lg:grid-cols-1">
            <BridgeMetric label="Топливных чеков с кухней" value={pct(data.cross_sell.attach_rate)} />
            <BridgeMetric label="Кухни в таком чеке" value={fmtMoney(data.cross_sell.avg_kitchen_in_fuel ?? 0)} />
            <BridgeMetric label="Чеков с кухней" value={nf(data.cross_sell.kitchen_cheques)} />
          </div>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader><TableRow><TableHead>Блюдо</TableHead><TableHead>Вместе с</TableHead><TableHead className="text-right">Чеков</TableHead><TableHead className="text-right">Сумма соседней позиции</TableHead></TableRow></TableHeader>
              <TableBody>
                {data.cross_sell.pairs.slice(0, 8).map((pair) => (
                  <TableRow key={`${pair.dish}-${pair.with_item}`}><TableCell className="font-medium">{pair.dish}</TableCell><TableCell>{pair.with_item}</TableCell><TableCell className="text-right tabular-nums">{nf(pair.cheques)}</TableCell><TableCell className="text-right tabular-nums">{fmtMoney(pair.with_item_amount)}</TableCell></TableRow>
                ))}
                {data.cross_sell.pairs.length === 0 && <TableRow><TableCell colSpan={4} className="h-20 text-center text-muted-foreground">Чеков для анализа пар пока нет.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><UtensilsCrossed className="size-4" /> Меню</CardTitle>
          <CardDescription>Классификация доступна только при точной себестоимости блюда.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_190px_190px_190px]">
            <div className="relative"><Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" /><Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Найти блюдо" className="pl-9" /></div>
            <Select value={classFilter} onValueChange={(value) => setClassFilter(value as MenuClass | 'all')}><SelectTrigger><SelectValue placeholder="Класс меню" /></SelectTrigger><SelectContent><SelectItem value="all">Все классы</SelectItem>{Object.entries(CLASS_META).map(([key, value]) => <SelectItem key={key} value={key}>{value.label}</SelectItem>)}</SelectContent></Select>
            <Select value={costFilter} onValueChange={(value) => setCostFilter(value as CostStatus | 'all')}><SelectTrigger><SelectValue placeholder="Достоверность" /></SelectTrigger><SelectContent><SelectItem value="all">Любая достоверность</SelectItem>{Object.entries(STATUS).map(([key, value]) => <SelectItem key={key} value={key}>{value.label}</SelectItem>)}</SelectContent></Select>
            <Select value={sortKey} onValueChange={(value) => setSortKey(value as SortKey)}><SelectTrigger><ArrowUpDown className="mr-2 size-4" /><SelectValue /></SelectTrigger><SelectContent><SelectItem value="revenue">По выручке</SelectItem><SelectItem value="qty">По продажам</SelectItem><SelectItem value="food_cost_pct">По фудкосту</SelectItem><SelectItem value="margin">По вкладу</SelectItem></SelectContent></Select>
          </div>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader><TableRow><TableHead>Блюдо</TableHead><TableHead>Класс</TableHead><TableHead className="text-right">Продано</TableHead><TableHead className="text-right">Выручка</TableHead><TableHead className="text-right">Возвраты</TableHead><TableHead className="text-right">Себест. порции</TableHead><TableHead className="text-right">Фудкост</TableHead><TableHead className="text-right">Вклад</TableHead><TableHead>Достоверность</TableHead></TableRow></TableHeader>
              <TableBody>
                {dishes.map((dish) => {
                  const meta = CLASS_META[dish.menu_class]
                  const MetaIcon = meta.icon
                  return <TableRow key={dish.guid} {...rowDrill(() => setOpenDish(dish), `${dish.name} — состав и продажи`)}>
                    <TableCell className="font-medium">
                      <div>{dish.name}</div>
                      <div className="mt-1"><StatusBadge status={dish.cost_status} /></div>
                    </TableCell>
                    <TableCell><Badge variant="outline" className="gap-1"><MetaIcon className="size-3" />{meta.short}</Badge></TableCell>
                    <TableCell className="text-right tabular-nums">{nf(dish.qty, 1)}</TableCell><TableCell className="text-right tabular-nums">{fmtMoney(dish.revenue)}</TableCell><TableCell className="text-right tabular-nums">{fmtMoney(dish.returns)}</TableCell>
                    <TableCell className="text-right tabular-nums">{dish.cost_per_portion == null ? '—' : fmtMoney(dish.cost_per_portion)}</TableCell><TableCell className="text-right tabular-nums">{pct(dish.food_cost_pct)}</TableCell><TableCell className="text-right tabular-nums">{dish.margin == null ? '—' : fmtMoney(dish.margin)}</TableCell><TableCell><StatusBadge status={dish.cost_status} /></TableCell>
                  </TableRow>
                })}
                {dishes.length === 0 && <TableRow><TableCell colSpan={9} className="h-24 text-center text-muted-foreground">Нет блюд по выбранным фильтрам.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {openDish && <DishDialog dish={openDish} onClose={() => setOpenDish(null)} />}
    </div>
  )
}

function BridgeMetric({ label, value, loss, strong }: { label: string; value: string; loss?: boolean; strong?: boolean }) {
  return <div className="bg-card p-3"><div className="text-xs text-muted-foreground">{label}</div><div className={cn('mt-1 whitespace-nowrap text-base font-semibold tabular-nums', loss && 'text-destructive', strong && 'text-emerald-700 dark:text-emerald-300')}>{value}</div></div>
}

function StatusBadge({ status }: { status: CostStatus }) {
  const meta = STATUS[status]
  return <Badge variant="outline" className={meta.className}>{meta.label}</Badge>
}

function StationCell({ row, demo }: { row: CateringComparison; demo: boolean }) {
  const content = <>
    <span className="inline-flex items-center gap-1 font-medium">
      АЗС {row.station_id}{!demo && <ExternalLink className="size-3.5" aria-hidden="true" />}
    </span>
    <span className="mt-1 block"><StatusBadge status={row.cost_status} /></span>
  </>
  if (demo) return <div>{content}</div>
  const href = `/api/store/station/${row.station_id}/console/menu?from=${row.week_from}&to=${row.week_to}`
  return <a href={href} target="_blank" rel="noreferrer" className="inline-block rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={`Открыть экономику АЗС ${row.station_id} за неделю ${row.week_from}`}>
    {content}
  </a>
}

function CateringSkeleton() {
  return <div className="flex flex-col gap-5 p-6"><Skeleton className="h-12 w-2/3" /><Skeleton className="h-16 w-full" /><Skeleton className="h-48 w-full" /><Skeleton className="h-72 w-full" /></div>
}

function DishDialog({ dish, onClose }: { dish: CateringDish; onClose: () => void }) {
  const meta = CLASS_META[dish.menu_class]
  const MetaIcon = meta.icon
  return <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
    <DialogContent className="flex max-h-[85vh] max-w-4xl flex-col gap-0 p-0">
      <DialogHeader className="border-b px-5 py-4 pr-12"><DialogTitle className="flex flex-wrap items-center gap-2">{dish.name}<Badge variant="outline" className="gap-1"><MetaIcon className="size-3" />{meta.label}</Badge></DialogTitle><DialogDescription>{meta.description} Себестоимость: {STATUS[dish.cost_status].label.toLocaleLowerCase('ru')}.</DialogDescription></DialogHeader>
      <div className="flex flex-col gap-5 overflow-auto p-5">
        <div className="grid overflow-hidden rounded-lg border sm:grid-cols-2 lg:grid-cols-4"><BridgeMetric label="Выручка без НДС" value={fmtMoney(dish.revenue_net)} /><BridgeMetric label="Возвраты" value={fmtMoney(dish.returns)} /><BridgeMetric label="Себестоимость" value={dish.cost == null ? '—' : fmtMoney(dish.cost)} /><BridgeMetric label="Вклад до общих потерь" value={dish.margin == null ? '—' : fmtMoney(dish.margin)} strong /></div>
        <div><h4 className="mb-2 text-sm font-medium">Состав ТТК</h4><div className="overflow-x-auto rounded-lg border"><Table><TableHeader><TableRow><TableHead>Ингредиент</TableHead><TableHead className="text-center">ЧЗ</TableHead><TableHead className="text-right">На порцию</TableHead><TableHead className="text-right">Себест. порции</TableHead><TableHead className="text-right">За период</TableHead></TableRow></TableHeader><TableBody>{dish.ingredients.map((item) => <TableRow key={item.ref}><TableCell>{item.name}</TableCell><TableCell className="text-center">{item.marked && <ChzBadge />}</TableCell><TableCell className="text-right tabular-nums">{item.qty_per_portion == null ? '—' : nf(item.qty_per_portion, 3)}</TableCell><TableCell className="text-right tabular-nums">{item.cost_per_portion == null ? '—' : fmtMoney(item.cost_per_portion)}</TableCell><TableCell className="text-right tabular-nums">{item.cost_total == null ? '—' : fmtMoney(item.cost_total)}</TableCell></TableRow>)}</TableBody></Table></div></div>
        <div><div className="mb-2 flex items-center justify-between"><h4 className="text-sm font-medium">Продажи по дням</h4><Button type="button" variant="ghost" size="sm" onClick={onClose}>Закрыть</Button></div><div className="overflow-x-auto rounded-lg border"><Table><TableHeader><TableRow><TableHead>Дата</TableHead><TableHead className="text-right">Порций</TableHead><TableHead className="text-right">Выручка</TableHead></TableRow></TableHeader><TableBody>{dish.daily.map((day) => <TableRow key={day.date}><TableCell>{day.date}</TableCell><TableCell className="text-right tabular-nums">{nf(day.qty, 1)}</TableCell><TableCell className="text-right tabular-nums">{fmtMoney(day.revenue)}</TableCell></TableRow>)}</TableBody></Table></div></div>
      </div>
    </DialogContent>
  </Dialog>
}
