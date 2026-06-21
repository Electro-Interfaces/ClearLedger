/**
 * Витрина «Баланс» — рендерит МОДУЛЬ баланса, подключённый профилю компании.
 * Баланс ЭЗС (energy) и Баланс АЗС (fuel) — РАЗНЫЕ модули (config/balanceModules.ts).
 * Модуль подключается к компании и отражается ПУНКТОМ суб-навигации режима
 * «Управленческий» рабочего стола (ManagementPanel). Drill-down по объекту →
 * интервальные статусы + декомпозиция потерь. Концепт: RusHydro\Ledger\docs\BALANCE_EE_DESIGN.md
 *
 * Компонент не управляет внешним контейнером (flex/scroll) — это делает вызывающий
 * (sub-панель «Управленческий» оборачивает в h-full overflow-y-auto).
 */
import { useState, Fragment } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Scale, ChevronLeft, ChevronRight, ChevronDown, Flame, ShieldCheck, Construction,
  LayoutGrid, Rows3, Search, ArrowUpDown,
} from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { balanceModuleForProfile, type BalanceModuleDef } from '@/config/balanceModules'
import { useModuleParams } from '@/services/moduleConnectionService'
import { BalanceStationDetail } from '@/components/balance/BalanceStationDetail'
import {
  DEMO_EZS, STATUS_META, SPEED_META, openClaimsCount,
  sumBuy, sumRelease, lossKwh, lossRub, lossPct, commLossKwh, commPct, overNorm, fmtN,
  type StationBalance,
} from '@/components/balance/balanceCalc'

type SortKey = 'name' | 'region' | 'buy' | 'release' | 'loss' | 'pct' | 'status'
type GroupKey = 'none' | 'region' | 'speed' | 'status' | 'supplier'

export function BalanceVitrine() {
  const { company } = useCompany()
  const mod = balanceModuleForProfile(company.profileId)

  const now = new Date()
  const [ym, setYm] = useState({ year: now.getFullYear(), month: now.getMonth() + 1 })
  const [view, setView] = useState<'summary' | 'crosstab'>('summary')
  const [selected, setSelected] = useState<StationBalance | null>(null)
  // Фильтры + сортировка
  const [q, setQ] = useState('')
  const [regionF, setRegionF] = useState('all')
  const [statusF, setStatusF] = useState('all')
  const [speedF, setSpeedF] = useState('all')
  const [lossF, setLossF] = useState('all') // all | over | commercial
  const [groupBy, setGroupBy] = useState<GroupKey>('none')
  const [sort, setSort] = useState<{ key: SortKey; asc: boolean }>({ key: 'loss', asc: false })
  const toggleSort = (key: SortKey) => setSort((p) => p.key === key ? { key, asc: !p.asc } : { key, asc: false })
  const periodLabel = new Date(ym.year, ym.month - 1, 1)
    .toLocaleString('ru-RU', { month: 'long', year: 'numeric' })
  const shiftMonth = (d: number) => setYm(({ year, month }) => {
    const m = month + d
    if (m < 1) return { year: year - 1, month: 12 }
    if (m > 12) return { year: year + 1, month: 1 }
    return { year, month: m }
  })

  // Параметры модуля под организацию (из каталога). Норматив из настроек переопределяет физику.
  const moduleParams = useModuleParams(mod?.id ?? '')
  const normOverride = Number(moduleParams.norm)
  const hasNormOverride = Number.isFinite(normOverride) && normOverride > 0

  if (!mod) return <Gate icon={Scale} title="Модуль баланса не подключён"
    text={`Профилю компании «${company.shortName || company.name}» не подключён модуль баланса.`} />
  if (mod.status === 'planned') return <Gate icon={Construction} title={`${mod.navLabel} — в разработке`}
    text={`${mod.title} (${mod.resource}, ${mod.unit}) — отдельный модуль для профиля. Сейчас в проработке; реализован модуль Баланс ЭЗС.`} />

  // Норматив из настроек (если задан) переопределяет рассчитанный от физики по всем ЭЗС.
  const all = hasNormOverride ? DEMO_EZS.map((s) => ({ ...s, normPct: normOverride })) : DEMO_EZS
  const regions = Array.from(new Set(all.map((s) => s.region))).sort()
  const stations = (() => {
    const qq = q.trim().toLowerCase()
    const list = all.filter((s) => {
      if (qq && !`${s.name} ${s.id}`.toLowerCase().includes(qq)) return false
      if (regionF !== 'all' && s.region !== regionF) return false
      if (statusF !== 'all' && s.status !== statusF) return false
      if (speedF !== 'all' && s.speed !== speedF) return false
      if (lossF === 'over' && !overNorm(s)) return false
      if (lossF === 'commercial' && commLossKwh(s) <= 0) return false
      return true
    })
    const rank = { ok: 0, review: 1, fail: 2 }
    const val = (s: StationBalance): string | number => {
      switch (sort.key) {
        case 'name': return s.name
        case 'region': return s.region
        case 'buy': return sumBuy(s).kwh
        case 'release': return sumRelease(s).kwh
        case 'loss': return lossKwh(s)
        case 'pct': return lossPct(s)
        case 'status': return rank[s.status]
        default: return s.name
      }
    }
    return [...list].sort((a, b) => {
      const va = val(a), vb = val(b)
      const c = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb), 'ru')
      return sort.asc ? c : -c
    })
  })()

  // Группировка по выбранному критерию (регион/скорость/статус/поставщик).
  const groupOf = (s: StationBalance): { key: string; label: string } => {
    switch (groupBy) {
      case 'region': return { key: s.region, label: s.region }
      case 'speed': return { key: s.speed, label: SPEED_META[s.speed] }
      case 'status': return { key: s.status, label: STATUS_META[s.status].label }
      case 'supplier': { const sup = s.purchase[0]?.supplier ?? '—'; return { key: sup, label: sup } }
      default: return { key: '_', label: '' }
    }
  }
  const groups = (() => {
    if (groupBy === 'none') return [{ key: '_', label: '', rows: stations }]
    const map = new Map<string, { key: string; label: string; rows: StationBalance[] }>()
    for (const s of stations) {
      const g = groupOf(s)
      if (!map.has(g.key)) map.set(g.key, { key: g.key, label: g.label, rows: [] })
      map.get(g.key)!.rows.push(s)
    }
    return Array.from(map.values()).sort((a, b) => a.label.localeCompare(b.label, 'ru'))
  })()

  const net = (g: (s: StationBalance) => { kwh: number; rub: number }) =>
    all.reduce((a, s) => { const v = g(s); return { kwh: a.kwh + v.kwh, rub: a.rub + v.rub } }, { kwh: 0, rub: 0 })
  const totalBuy = net(sumBuy)
  const totalRel = net(sumRelease)
  const totalLossKwh = all.reduce((a, s) => a + lossKwh(s), 0)
  const netLossPct = totalBuy.kwh > 0 ? (totalLossKwh / totalBuy.kwh) * 100 : 0
  const overCount = all.filter(overNorm).length
  const totalUnpaidRub = all.reduce((a, s) => a + s.unpaid.rub, 0)
  const openClaims = openClaimsCount(all)

  const heat = [...all].sort((a, b) => commPct(b) - commPct(a))
  const maxComm = Math.max(...all.map(commPct), 1)

  // Остальные параметры модуля из настроек: единица ресурса и подписи категорий отпуска.
  const unit = moduleParams.unit?.trim() || mod.unit
  const catLabels = moduleParams.categories?.split(',').map((x) => x.trim()).filter(Boolean) ?? []
  const categories = catLabels.length
    ? mod.categories.map((c, i) => ({ ...c, label: catLabels[i] ?? c.label }))
    : mod.categories
  const effMod: BalanceModuleDef = { ...mod, unit, categories }

  return (
    <>
      <div className="px-6 py-6 space-y-5">
        {/* Шапка */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <Scale className="h-6 w-6 text-primary shrink-0" />
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-semibold">{mod.title}</h1>
                <Badge variant="outline" className="text-[10px]">{mod.navLabel}</Badge>
                <Badge variant="secondary" className="text-[10px]">демо-данные</Badge>
                {hasNormOverride && (
                  <Badge variant="outline" className="text-[10px]">норматив из настроек: {normOverride}%</Badge>
                )}
              </div>
              <p className="text-sm text-muted-foreground mt-1 max-w-2xl">{mod.subtitle}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => shiftMonth(-1)}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="min-w-40 text-center text-sm font-medium capitalize">{periodLabel}</span>
            <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => shiftMonth(1)}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* KPI */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          <Kpi label={`Поступление, ${unit}`} value={fmtN(totalBuy.kwh)} />
          <Kpi label={`Полезный отпуск, ${unit}`} value={fmtN(totalRel.kwh)} />
          <Kpi label={`Потери, ${unit}`} value={fmtN(totalLossKwh)} accent="warn" />
          <Kpi label="% потерь по сети" value={`${netLossPct.toFixed(1)}%`} accent={netLossPct > 2 ? 'warn' : 'default'} />
          <Kpi label={`${mod.objectLabel} за пределами нормы`} value={String(overCount)} accent={overCount > 0 ? 'danger' : 'default'} />
          <Kpi label="Открытых обращений" value={String(openClaims)} accent={openClaims > 0 ? 'danger' : 'default'} />
        </div>

        {/* Панель фильтров + вид */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-md border border-border/60 p-0.5">
            <Button variant={view === 'summary' ? 'secondary' : 'ghost'} size="sm" className="h-8"
              onClick={() => setView('summary')} title={`Сводка по ${mod.objectLabel} (масштабируется)`}>
              <Rows3 className="h-4 w-4 mr-1.5" /> Сводка
            </Button>
            <Button variant={view === 'crosstab' ? 'secondary' : 'ghost'} size="sm" className="h-8"
              onClick={() => setView('crosstab')} title="Итоги по выборке/группам в структуре Табл.2 ТЗ">
              <LayoutGrid className="h-4 w-4 mr-1.5" /> Итоги (Табл.2)
            </Button>
          </div>
          <div className="relative min-w-[180px] flex-1">
            <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Поиск ${mod.objectLabel} (номер, адрес)…`} className="h-8 pl-8 text-xs" />
          </div>
          <Select value={regionF} onValueChange={setRegionF}>
            <SelectTrigger className="h-8 w-[170px] text-xs"><SelectValue placeholder="Регион" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все регионы</SelectItem>
              {regions.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={statusF} onValueChange={setStatusF}>
            <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue placeholder="Статус" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Любой статус</SelectItem>
              <SelectItem value="ok">Достоверно</SelectItem>
              <SelectItem value="review">Подозрительно</SelectItem>
              <SelectItem value="fail">Сбой</SelectItem>
            </SelectContent>
          </Select>
          <Select value={speedF} onValueChange={setSpeedF}>
            <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue placeholder="Скорость" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Любая скорость</SelectItem>
              <SelectItem value="fast">Быстрые (DC)</SelectItem>
              <SelectItem value="slow">Медленные (AC)</SelectItem>
            </SelectContent>
          </Select>
          <Select value={lossF} onValueChange={setLossF}>
            <SelectTrigger className="h-8 w-[180px] text-xs"><SelectValue placeholder="Потери" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все потери</SelectItem>
              <SelectItem value="over">Вне норматива</SelectItem>
              <SelectItem value="commercial">Есть коммерч. небаланс</SelectItem>
            </SelectContent>
          </Select>
          <Select value={groupBy} onValueChange={(v) => setGroupBy(v as GroupKey)}>
            <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue placeholder="Группировка" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{view === 'crosstab' ? 'Итого: одной колонкой' : 'Без группировки'}</SelectItem>
              <SelectItem value="region">Группировать: регион</SelectItem>
              <SelectItem value="speed">Группировать: скорость</SelectItem>
              <SelectItem value="status">Группировать: статус</SelectItem>
              <SelectItem value="supplier">Группировать: поставщик</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="-mt-2 text-xs text-muted-foreground">
          Показано {stations.length} из {all.length} {mod.objectLabel}{groupBy !== 'none' ? ` · ${groups.length} групп` : ''}
        </div>

        {view === 'summary'
          ? <SummaryTable mod={effMod} groups={groups} grouped={groupBy !== 'none'} unit={effMod.unit} onSelect={setSelected} sort={sort} onSort={toggleSort} />
          : <CrossTab mod={effMod} groups={groups} groupBy={groupBy} stations={stations} />}

        {/* Тепловая карта потерь — по коммерческому небалансу */}
        <Card>
          <CardContent className="pt-5">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium">
              <Flame className="h-4 w-4 text-muted-foreground" /> Очаги потерь (по коммерческому небалансу, сверх норматива)
            </div>
            <div className="space-y-2">
              {heat.map((s) => {
                const pct = commPct(s); const over = overNorm(s)
                return (
                  <button key={s.id} onClick={() => setSelected(s)} className="block w-full text-left">
                    <div className="mb-0.5 flex items-center justify-between text-xs">
                      <span className="truncate hover:text-foreground">{s.name}</span>
                      <span className={`shrink-0 tabular-nums ${over ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                        коммерч. {pct.toFixed(1)}% · {fmtN(commLossKwh(s))} {unit} (всего {lossPct(s).toFixed(1)}%)
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full" style={{
                        width: `${Math.max((pct / maxComm) * 100, 2)}%`,
                        backgroundColor: over ? '#ef4444' : '#10b981',
                      }} />
                    </div>
                  </button>
                )
              })}
            </div>
            {overCount === 0 && (
              <div className="mt-3 flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400">
                <ShieldCheck className="h-4 w-4" /> Коммерческий небаланс в пределах норматива по всем {mod.objectLabel}.
              </div>
            )}
          </CardContent>
        </Card>

        <p className="text-xs text-muted-foreground/70">
          Неоплаченная э/э (холд&lt;факт) за период: {fmtN(totalUnpaidRub)} ₽ — дебиторка к доплате, не потери.
          Клик по {mod.objectLabel} → интервальные статусы (Достоверно/Подозрительно/Сбой) и декомпозиция потерь.
          {moduleParams.etalon && <> · Эталон (закрытый период): {moduleParams.etalon}.</>}
        </p>
      </div>

      <BalanceStationDetail station={selected} mod={effMod} year={ym.year} month={ym.month} onClose={() => setSelected(null)} />
    </>
  )
}

interface Group { key: string; label: string; rows: StationBalance[] }
function groupSub(rows: StationBalance[]) {
  const buy = rows.reduce((a, s) => a + sumBuy(s).kwh, 0)
  const loss = rows.reduce((a, s) => a + lossKwh(s), 0)
  return { buy, loss, pct: buy > 0 ? (loss / buy) * 100 : 0, over: rows.filter(overNorm).length, count: rows.length }
}

/** Сводка по объектам в СТРОКАХ + опц. сворачиваемые группы с подытогами. */
function SummaryTable({ mod, groups, grouped, unit, onSelect, sort, onSort }: {
  mod: BalanceModuleDef; groups: Group[]; grouped: boolean; unit: string
  onSelect: (s: StationBalance) => void
  sort: { key: SortKey; asc: boolean }; onSort: (k: SortKey) => void
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const toggle = (k: string) => setCollapsed((p) => { const n = new Set(p); if (n.has(k)) n.delete(k); else n.add(k); return n })

  const SortHead = ({ k, children, className }: { k: SortKey; children: React.ReactNode; className?: string }) => (
    <TableHead className={className}>
      <button className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => onSort(k)}>
        {children}
        <ArrowUpDown className={`h-3 w-3 ${sort.key === k ? 'text-foreground' : 'text-muted-foreground/40'}`} />
      </button>
    </TableHead>
  )
  const Row = ({ s }: { s: StationBalance }) => (
    <TableRow className="cursor-pointer hover:bg-secondary/50" onClick={() => onSelect(s)}>
      <TableCell className={`font-medium ${grouped ? 'pl-6' : ''}`}>{s.name}</TableCell>
      <TableCell className="hidden lg:table-cell text-muted-foreground">{s.region}</TableCell>
      <TableCell className="text-center">
        <Badge variant="secondary" className={`text-[10px] ${STATUS_META[s.status].cls}`}>{STATUS_META[s.status].label}</Badge>
      </TableCell>
      <TableCell className="text-right tabular-nums">{fmtN(sumBuy(s).kwh)}</TableCell>
      <TableCell className="hidden md:table-cell text-right tabular-nums text-muted-foreground">{fmtN(sumRelease(s).kwh)}</TableCell>
      <TableCell className="text-right tabular-nums">{fmtN(lossKwh(s))}</TableCell>
      <TableCell className="hidden sm:table-cell text-right tabular-nums text-muted-foreground">{fmtN(lossRub(s))}</TableCell>
      <TableCell className="text-center">
        <Badge variant="secondary" className={`text-[10px] ${overNorm(s) ? 'bg-red-500/15 text-red-600 dark:text-red-400' : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'}`}>
          {lossPct(s).toFixed(1)}% {overNorm(s) ? `> ${s.normPct}% ✗` : `≤ ${s.normPct}% ✓`}
        </Badge>
      </TableCell>
    </TableRow>
  )
  const empty = groups.every((g) => g.rows.length === 0)
  return (
    <Card>
      <CardContent className="max-h-[60vh] overflow-auto pt-5">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-card">
            <TableRow>
              <SortHead k="name">{mod.objectLabel}</SortHead>
              <SortHead k="region" className="hidden lg:table-cell">Регион</SortHead>
              <SortHead k="status" className="text-center">Статус</SortHead>
              <SortHead k="buy" className="text-right">Покупка, {mod.unit}</SortHead>
              <SortHead k="release" className="hidden md:table-cell text-right">Отпуск, {mod.unit}</SortHead>
              <SortHead k="loss" className="text-right">Потери, {mod.unit}</SortHead>
              <TableHead className="hidden sm:table-cell text-right">Потери, ₽</TableHead>
              <SortHead k="pct" className="text-center">% / норматив</SortHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groups.map((g) => {
              const sub = groupSub(g.rows)
              const isCol = collapsed.has(g.key)
              return (
                <Fragment key={g.key}>
                  {grouped && g.label && (
                    <TableRow className="cursor-pointer bg-muted/40 hover:bg-muted/60" onClick={() => toggle(g.key)}>
                      <TableCell colSpan={8} className="py-1.5">
                        <div className="flex items-center gap-2 text-xs font-medium">
                          {isCol ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                          {g.label}
                          <Badge variant="secondary" className="text-[10px]">{sub.count}</Badge>
                          <span className="ml-auto flex flex-wrap gap-x-3 font-normal tabular-nums text-muted-foreground">
                            <span>покупка {fmtN(sub.buy)} {unit}</span>
                            <span>потери {fmtN(sub.loss)} {unit} ({sub.pct.toFixed(1)}%)</span>
                            {sub.over > 0 && <span className="text-red-600 dark:text-red-400">вне нормы {sub.over}</span>}
                          </span>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                  {!isCol && g.rows.map((s) => <Row key={s.id} s={s} />)}
                </Fragment>
              )
            })}
            {empty && (
              <TableRow><TableCell colSpan={8} className="py-8 text-center text-sm text-muted-foreground">Нет {mod.objectLabel} по фильтру.</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

/** Итоговый отчёт «Табл.2» — структура показателей × ИТОГИ по выборке/группам (не по станциям). */
function CrossTab({ mod, groups, groupBy, stations }: {
  mod: BalanceModuleDef
  groups: { key: string; label: string; rows: StationBalance[] }[]
  groupBy: GroupKey
  stations: StationBalance[]
}) {
  const u = mod.unit
  const grouped = groupBy !== 'none'
  // Колонки: либо одна «Итого по выборке», либо по группам + общий итог.
  const columns = grouped
    ? [...groups.map((g) => ({ key: g.key, label: g.label, rows: g.rows })), { key: '_grand', label: 'Итого', rows: stations }]
    : [{ key: 'total', label: 'Итого по выборке', rows: stations }]
  const allSuppliers = Array.from(new Set(stations.flatMap((s) => s.purchase.map((p) => p.supplier)))).sort()
  const agg = (rows: StationBalance[], get: (s: StationBalance) => { kwh: number; rub: number }) =>
    rows.reduce((a, s) => { const v = get(s); return { kwh: a.kwh + v.kwh, rub: a.rub + v.rub } }, { kwh: 0, rub: 0 })
  const lossPctOf = (rows: StationBalance[]) => { const b = agg(rows, sumBuy).kwh; const l = rows.reduce((a, s) => a + lossKwh(s), 0); return b > 0 ? (l / b) * 100 : 0 }
  const overOf = (rows: StationBalance[]) => rows.filter(overNorm).length
  const isGrand = (i: number) => grouped && i === columns.length - 1

  interface RowDef { label: string; level: 0 | 1; kind: 'group' | 'sub' | 'total'; get: (s: StationBalance) => { kwh: number; rub: number } }
  const rows: RowDef[] = [
    { label: 'Покупка итого', level: 0, kind: 'group', get: sumBuy },
    ...allSuppliers.map((sup) => ({
      label: sup, level: 1 as const, kind: 'sub' as const,
      get: (s: StationBalance) => { const p = s.purchase.find((x) => x.supplier === sup); return { kwh: p?.kwh ?? 0, rub: p?.rub ?? 0 } },
    })),
    { label: 'Отпуск итого', level: 0, kind: 'group', get: sumRelease },
    ...mod.categories.map((c) => ({
      label: c.label, level: 1 as const, kind: 'sub' as const,
      get: (s: StationBalance) => s.release[c.id] ?? { kwh: 0, rub: 0 },
    })),
    { label: 'в т.ч. неоплаченная (холд < факт)', level: 1, kind: 'sub', get: (s) => s.unpaid },
    { label: 'Потери итого', level: 0, kind: 'group', get: (s) => ({ kwh: lossKwh(s), rub: lossRub(s) }) },
    // Балансовое тождество §5: ПОЛЕЗНЫЙ ОТПУСК = Поступление − Потери (= Отпуск, баланс сходится).
    { label: 'ПОЛЕЗНЫЙ ОТПУСК', level: 0, kind: 'total', get: (s) => ({ kwh: sumBuy(s).kwh - lossKwh(s), rub: sumRelease(s).rub }) },
  ]

  return (
    <Card>
      <CardContent className="overflow-x-auto pt-5">
        <p className="mb-3 text-xs text-muted-foreground">
          Итоги по {grouped ? `группам (${groups.length})` : 'всей выборке'} в структуре Табл.2 ТЗ — по фильтрам и группировке из «Сводки» ({stations.length} {mod.objectLabel}). ПОЛЕЗНЫЙ ОТПУСК = Поступление − Потери (баланс сходится с Отпуском).
        </p>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead rowSpan={2} className="sticky left-0 bg-card align-bottom">Показатель</TableHead>
              {columns.map((c, i) => (
                <TableHead key={c.key} colSpan={2} className={`text-center ${isGrand(i) ? 'border-l-2 border-border' : 'border-l border-border/40'}`}>
                  <div className="flex items-center justify-center gap-1.5">
                    <span className="font-medium">{c.label}</span>
                    <Badge variant="secondary" className="text-[9px]">{c.rows.length}</Badge>
                  </div>
                </TableHead>
              ))}
            </TableRow>
            <TableRow>
              {columns.map((c, i) => <SubCols key={c.key} unit={u} bold={isGrand(i)} />)}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r, i) => (
              <TableRow key={i} className={r.kind === 'total' ? 'border-t-2 border-border font-semibold' : r.kind === 'group' ? 'font-medium' : ''}>
                <TableCell className={`sticky left-0 bg-card ${r.level === 1 ? 'pl-6 font-normal text-muted-foreground' : ''}`}>{r.label}</TableCell>
                {columns.map((c, ci) => { const v = agg(c.rows, r.get); return (
                  <Fragment key={c.key}>
                    <TableCell className={`text-right tabular-nums ${isGrand(ci) ? 'border-l-2 border-border font-medium' : 'border-l border-border/40'}`}>{fmtN(v.kwh)}</TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">{fmtN(v.rub)}</TableCell>
                  </Fragment>
                ) })}
              </TableRow>
            ))}
            <TableRow className="border-t border-border/60">
              <TableCell className="sticky left-0 bg-card text-xs text-muted-foreground">% потерь · вне нормы</TableCell>
              {columns.map((c, ci) => { const pct = lossPctOf(c.rows); const over = overOf(c.rows); return (
                <TableCell key={c.key} colSpan={2} className={`text-center text-xs ${isGrand(ci) ? 'border-l-2 border-border' : 'border-l border-border/40'}`}>
                  <span className={over > 0 ? 'text-red-600 dark:text-red-400' : ''}>{pct.toFixed(1)}%{over > 0 ? ` · ${over} ✗` : ''}</span>
                </TableCell>
              ) })}
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function SubCols({ unit, bold }: { unit: string; bold?: boolean }) {
  return (
    <>
      <TableHead className="h-7 border-l border-border/40 text-right text-[10px] font-normal text-muted-foreground">{unit}</TableHead>
      <TableHead className={`h-7 text-right text-[10px] font-normal text-muted-foreground ${bold ? 'font-medium' : ''}`}>руб</TableHead>
    </>
  )
}

function Kpi({ label, value, accent }: { label: string; value: string; accent?: 'default' | 'warn' | 'danger' }) {
  const tone = accent === 'danger' ? 'text-red-600 dark:text-red-400'
    : accent === 'warn' ? 'text-amber-600 dark:text-amber-400' : 'text-foreground'
  return (
    <Card><CardContent className="pt-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
    </CardContent></Card>
  )
}

function Gate({ icon: Icon, title, text }: { icon: typeof Scale; title: string; text: string }) {
  return (
    <div className="px-6 py-6">
      <Card><CardContent className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <Icon className="h-10 w-10 text-muted-foreground/50" />
        <p className="font-medium">{title}</p>
        <p className="max-w-md text-sm text-muted-foreground">{text}</p>
      </CardContent></Card>
    </div>
  )
}
