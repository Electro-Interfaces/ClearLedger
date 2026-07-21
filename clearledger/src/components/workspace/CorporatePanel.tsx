/**
 * Пункт «Корпоратив» — рабочее пространство ЮЛ-направления ЭЗС.
 * Внутренние табы: Обзор · Клиенты · Тарифы и договоры · Рентабельность и биллинг · Динамика.
 * Данные — /api/corporate/* (реестр corporate_clients + метрики/гэп) и timeseries (ЮЛ).
 * Двойная цена сессии: розница станции vs договор ЮЛ → скидка/наценка направления.
 */
import { useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Kpi } from './analytics/Kpi'
import { PanelViewTabs } from './PanelViewTabs'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, Download, AlertTriangle, Info, ArrowUp, ArrowDown, ChevronsUpDown, FileSpreadsheet } from 'lucide-react'
import { toast } from 'sonner'
import { useTabParams } from '@/hooks/useTabParams'
import { getCorporateOverview, getCorporateClients, exportCorporateBillingUpd, type CorpClient } from '@/services/corporateService'
import { CorpClientModal } from './CorpClientModal'
import { exportChargeSessionsXlsx } from '@/services/chargeSessionsService'
import { getChargeTimeseries, fmtMoneyShort } from '@/services/analyticsService'
import { useNetScope } from '@/hooks/useScopeReset'
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const money = (v: number) => nf0.format(Math.round(v || 0)) + ' ₽'
const moneyK = (v: number) => (Math.abs(v) >= 10000 ? nf1.format(v / 1000) + ' тыс' : nf0.format(v)) + ' ₽'
const pct = (v: number) => nf1.format(v) + '%'
const MODE_LABEL: Record<string, string> = { matrix: 'Матрица', flat: 'Плоский', retail: 'Розница' }

/** Цвет для скидки/наценки к рознице: скидка (<0, сеть недополучает) — amber; наценка — emerald. */
const gapCls = (v: number) => (v < -0.5 ? 'text-amber-600/90 dark:text-amber-400/90' : v > 0.5 ? 'text-emerald-600/90 dark:text-emerald-400/90' : 'text-muted-foreground')

function Loading() { return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div> }
function Empty({ text }: { text: string }) { return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div> }

// ── KPI карточка ──

// ── Сортируемая таблица клиентов (общая для Клиенты/Тарифы/Биллинг) ──
interface Col { key: string; label: string; left?: boolean; get: (c: CorpClient) => number | string; cell: (c: CorpClient) => ReactNode }

function ClientsTable({ rows, cols, initial = 'corp_revenue', onPick }: {
  rows: CorpClient[]; cols: Col[]; initial?: string; onPick?: (name: string) => void
}) {
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({ key: initial, dir: 'desc' })
  const col = useMemo(() => cols.find((c) => c.key === sort.key) ?? cols[0], [cols, sort.key])
  const sorted = useMemo(() => {
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const va = col.get(a), vb = col.get(b)
      if (typeof va === 'string' || typeof vb === 'string') return dir * String(va).localeCompare(String(vb), 'ru')
      return dir * (va - vb)
    })
  }, [rows, col, sort.dir])
  const toggle = (k: string) => setSort((s) => (s.key === k ? { key: k, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key: k, dir: 'desc' }))
  const H = ({ c }: { c: Col }) => {
    const on = sort.key === c.key
    const Ico = on ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
    const ariaSort: 'ascending' | 'descending' | 'none' = on ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'
    return (
      <th aria-sort={ariaSort} className={`p-2 font-medium ${c.left ? 'text-left' : 'text-right'}`}>
        <button onClick={() => toggle(c.key)} title="Сортировать"
          className={`group inline-flex items-center gap-1 cursor-pointer transition-colors hover:text-foreground ${c.left ? '' : 'flex-row-reverse'} ${on ? 'text-foreground' : ''}`}>
          <span className="whitespace-nowrap">{c.label}</span>
          <Ico className={`h-3 w-3 shrink-0 ${on ? 'text-primary opacity-100' : 'opacity-30 group-hover:opacity-70'}`} />
        </button>
      </th>
    )
  }
  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/40 text-muted-foreground">{cols.map((c) => <H key={c.key} c={c} />)}</tr>
          </thead>
          <tbody>
            {sorted.map((c) => (
              <tr key={c.phone + c.name}
                onClick={onPick ? () => onPick(c.name) : undefined}
                title={onPick ? 'Открыть карточку клиента' : undefined}
                className={`border-b border-border/30 hover:bg-muted/30 ${onPick ? 'cursor-pointer' : ''}`}>
                {cols.map((col2, i) => (
                  <td key={col2.key} className={`p-2 ${col2.left ? 'text-left font-medium truncate max-w-[260px]' : 'text-right tabular-nums'} ${i === 0 ? '' : 'text-muted-foreground'}`}>
                    {col2.cell(c)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

function useClients(companyId: string, dateFrom: string, dateTo: string) {
  const sc = useNetScope()
  return useQuery({
    queryKey: ['corp-clients', companyId, dateFrom, dateTo, sc.key],
    queryFn: () => getCorporateClients({ companyId, dateFrom, dateTo, stations: sc.stations, regions: sc.regions }),
  })
}

// ── Обзор: виджеты ──
function BarRow({ label, value, frac, sub }: { label: string; value: string; frac: number; sub?: string }) {
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between gap-2 text-xs">
        <span className="truncate">{label}</span>
        <span className="whitespace-nowrap tabular-nums text-muted-foreground">{value}{sub ? ` · ${sub}` : ''}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.max(2, Math.min(100, frac * 100))}%` }} /></div>
    </div>
  )
}
function Widget({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{title}</div>
      <Card className="h-full"><CardContent className="space-y-1.5 p-3">{children}</CardContent></Card>
    </div>
  )
}

// ── Таб: Обзор (дашборд) ──
function CorpOverview({ companyId, dateFrom, dateTo }: TabProps) {
  const sc = useNetScope()
  const ov = useQuery({ queryKey: ['corp-overview', companyId, dateFrom, dateTo, sc.key], queryFn: () => getCorporateOverview({ companyId, dateFrom, dateTo, stations: sc.stations, regions: sc.regions }) })
  const cl = useClients(companyId, dateFrom, dateTo)
  const trend = useQuery({
    queryKey: ['corp-dyn', companyId, dateFrom, dateTo, sc.key],
    queryFn: () => getChargeTimeseries({ companyId, dateFrom, dateTo, bucket: 'month', metric: 'amount', dim: 'user_type', dimVal: 'ЮЛ', stations: sc.stations, regions: sc.regions }),
  })
  if (ov.isLoading) return <Loading />
  if (!ov.data) return <Empty text="Нет данных" />

  const t = ov.data.totals
  const clients = cl.data?.clients ?? []
  const avgCheck = t.sessions ? t.corp_revenue / t.sessions : 0

  const topRev = ov.data.top_clients.slice(0, 6)
  const maxRev = Math.max(1, ...topRev.map((c) => c.corp_revenue))
  const trendRows = (trend.data?.data ?? []).map((r) => ({ b: String(r.bucket), v: Number((r as Record<string, unknown>)['Вся сеть'] ?? (r as Record<string, unknown>).value ?? 0) }))
  const maxRC = Math.max(1, t.retail_revenue, t.corp_revenue)

  const modeCount: Record<string, number> = {}
  for (const c of clients) modeCount[c.mode] = (modeCount[c.mode] ?? 0) + 1
  const modes = Object.entries(modeCount).sort((a, b) => b[1] - a[1])
  const maxMode = Math.max(1, ...modes.map(([, n]) => n))
  const withContract = clients.filter((c) => c.contract_start).length
  const noSessions = clients.filter((c) => c.sessions === 0).length
  const discounted = clients.filter((c) => c.discount < -0.5).length

  return (
    <div className="space-y-4">
      {/* KPI-полоса */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Договорная выручка" value={moneyK(t.corp_revenue)} sub={`ср.тариф ${nf1.format(t.avg_tariff)} ₽/кВтч`} />
        <Kpi label="Розница-эквивалент" value={moneyK(t.retail_revenue)} sub="energy × тариф станции" />
        <Kpi label="Скидка к рознице" value={money(t.discount)} sub={pct(t.discount_pct)} cls={gapCls(t.discount)} />
        <Kpi label="Ср. чек ЮЛ" value={money(avgCheck)} sub={`${nf0.format(t.sessions)} сессий`} />
        <Kpi label="Активных клиентов" value={`${t.active_clients} / ${t.clients}`} sub="с сессиями / в реестре" />
        <Kpi label="Энергия ЮЛ" value={`${nf0.format(t.energy_kwh)}`} sub="кВтч за период" />
      </div>

      {/* Алерты */}
      {ov.data.alerts.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {ov.data.alerts.map((a, i) => (
            <div key={i} className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs ${a.level === 'warn' ? 'border-amber-400/40 text-amber-300/90' : 'border-border text-muted-foreground'}`}>
              {a.level === 'warn' ? <AlertTriangle className="h-3.5 w-3.5" /> : <Info className="h-3.5 w-3.5" />}{a.message}
            </div>
          ))}
        </div>
      )}

      {/* Дашборд 2×2 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Widget title="Договорная выручка ЮЛ по месяцам">
          {trend.isLoading ? <Loading /> : trendRows.length === 0 ? <Empty text="Нет данных за период" />
            : (
              <div data-chart>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={trendRows} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                    <XAxis dataKey="b" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--muted-foreground))"
                      tickFormatter={(b: string) => (b.length === 7 ? `${b.slice(5)}.${b.slice(2, 4)}` : b)} />
                    <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--muted-foreground))"
                      width={52} tickFormatter={(v: number) => fmtMoneyShort(v)} />
                    <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }}
                      labelFormatter={(b) => String(b)} formatter={(v) => [`${moneyK(Number(v))}`, 'Выручка']} />
                    <Bar dataKey="v" fill="hsl(217, 91%, 60%)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
        </Widget>

        <Widget title="Топ клиентов по договорной выручке">
          {topRev.length === 0 ? <Empty text="Нет корп-выручки за период" />
            : topRev.map((c) => <BarRow key={c.phone} label={c.name} value={moneyK(c.corp_revenue)} frac={c.corp_revenue / maxRev} sub={`${nf0.format(c.sessions)} сес · ${nf1.format(c.avg_tariff)} ₽/кВтч`} />)}
        </Widget>

        <Widget title="Рентабельность: розница ↔ договор">
          <BarRow label="Розница-эквивалент" value={moneyK(t.retail_revenue)} frac={t.retail_revenue / maxRC} />
          <BarRow label="К выставлению (договор)" value={moneyK(t.corp_revenue)} frac={t.corp_revenue / maxRC} />
          <div className="flex justify-between border-t border-border/40 pt-1.5 text-xs">
            <span className="text-muted-foreground">Разница (скидка/наценка)</span>
            <span className={`tabular-nums ${gapCls(t.discount)}`}>{money(t.discount)} · {pct(t.discount_pct)}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">Клиентов со скидкой ≤ −0,5%</span>
            <span className="tabular-nums">{discounted}{clients.length ? ` / ${clients.length}` : ''}</span>
          </div>
        </Widget>

        <Widget title="Тарифные режимы и дисциплина">
          {cl.isLoading ? <Loading /> : (
            <>
              {modes.map(([m, n]) => (
                <BarRow key={m} label={MODE_LABEL[m] ?? m} value={`${n}`} frac={n / maxMode} sub={`${clients.length ? Math.round((n / clients.length) * 100) : 0}%`} />
              ))}
              <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-border/40 pt-1.5 text-xs text-muted-foreground">
                <span>С договором: <b className="text-foreground">{withContract}</b></span>
                <span>Без сессий: <b className="text-foreground">{noSessions}</b></span>
                <span>Всего: <b className="text-foreground">{clients.length}</b></span>
              </div>
            </>
          )}
        </Widget>
      </div>
    </div>
  )
}

// ── Таб: Клиенты (реестр) ──
function CorpClients({ companyId, dateFrom, dateTo }: TabProps) {
  const sc = useNetScope()
  const { data, isLoading } = useClients(companyId, dateFrom, dateTo)
  const [exporting, setExporting] = useState(false)
  // Клик по строке → карточка клиента (помесячная реализация + профиль).
  const [picked, setPicked] = useState<string | null>(null)
  if (isLoading) return <Loading />
  if (!data) return <Empty text="Нет данных" />
  async function dl() {
    setExporting(true)
    try { await exportChargeSessionsXlsx({ companyId, dateFrom, dateTo, userType: 'ЮЛ', stations: sc.stations, regions: sc.regions }) }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setExporting(false) }
  }
  const cols: Col[] = [
    { key: 'name', label: 'Клиент', left: true, get: (c) => c.name, cell: (c) => c.name },
    { key: 'mode', label: 'Тариф', get: (c) => c.mode, cell: (c) => MODE_LABEL[c.mode] ?? c.mode },
    { key: 'status', label: 'Договор', get: (c) => c.status ?? '', cell: (c) => <span className="text-[11px]">{c.contract_start ?? '—'}{c.status && c.status !== 'Действующая' ? ` · ${c.status}` : ''}</span> },
    { key: 'sessions', label: 'Сессий', get: (c) => c.sessions, cell: (c) => nf0.format(c.sessions) },
    { key: 'energy_kwh', label: 'Энергия кВтч', get: (c) => c.energy_kwh, cell: (c) => nf0.format(c.energy_kwh) },
    { key: 'corp_revenue', label: 'Дог. выручка', get: (c) => c.corp_revenue, cell: (c) => money(c.corp_revenue) },
    { key: 'avg_tariff', label: '₽/кВтч', get: (c) => c.avg_tariff, cell: (c) => nf1.format(c.avg_tariff) },
    { key: 'discount_pct', label: 'Скидка', get: (c) => c.discount_pct, cell: (c) => <span className={gapCls(c.discount)}>{pct(c.discount_pct)}</span> },
  ]
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-muted-foreground">
          Реестр: {data.totals.clients} организаций ({data.totals.active_clients} с сессиями за период)
          <span className="ml-2 text-muted-foreground/70">— строка открывает карточку клиента</span>
        </div>
        <Button size="sm" variant="outline" className="h-7 gap-1.5 text-xs" disabled={exporting} onClick={dl}>
          {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}Выгрузить сессии (xlsx)
        </Button>
      </div>
      <ClientsTable rows={data.clients} cols={cols} onPick={setPicked} />
      {picked && (
        <CorpClientModal client={picked} companyId={companyId}
          dateFrom={dateFrom} dateTo={dateTo} onClose={() => setPicked(null)} />
      )}
    </div>
  )
}

// ── Таб: Тарифы и договоры ──
function CorpTariffs({ companyId, dateFrom, dateTo }: TabProps) {
  const { data, isLoading } = useClients(companyId, dateFrom, dateTo)
  if (isLoading) return <Loading />
  if (!data) return <Empty text="Нет данных" />
  const tariffDesc = (c: CorpClient): string => {
    if (c.mode === 'flat') return `${nf1.format(c.rate ?? 0)} ₽/кВтч (все станции)`
    if (c.mode === 'matrix') return `матрица: ${Object.keys(c.matrix ?? {}).length} рег. × коннектор`
    return 'по тарифу станции'
  }
  const cols: Col[] = [
    { key: 'name', label: 'Клиент', left: true, get: (c) => c.name, cell: (c) => c.name },
    { key: 'mode', label: 'Режим', get: (c) => c.mode, cell: (c) => MODE_LABEL[c.mode] ?? c.mode },
    { key: 'tariff', label: 'Условие тарифа', left: true, get: (c) => c.mode, cell: (c) => <span className="text-[11px] text-muted-foreground">{tariffDesc(c)}</span> },
    { key: 'avg_tariff', label: 'Эфф. ₽/кВтч', get: (c) => c.avg_tariff, cell: (c) => nf1.format(c.avg_tariff) },
    { key: 'contract_start', label: 'Договор с', get: (c) => c.contract_start ?? '', cell: (c) => <span className="text-[11px]">{c.contract_start ?? '—'}</span> },
    { key: 'status', label: 'Статус', get: (c) => c.status ?? '', cell: (c) => <span className={`text-[11px] ${c.status && c.status !== 'Действующая' ? 'text-amber-600/90 dark:text-amber-400/90' : ''}`}>{c.status ?? '—'}</span> },
    { key: 'users', label: 'Юзеров', get: (c) => c.users ?? 0, cell: (c) => c.users ?? '—' },
  ]
  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">Договорная модель по клиенту. Изменение тарифов — перезагрузкой справочника «Организации (тарифы)» (правка из UI — на roadmap).</div>
      <ClientsTable rows={data.clients} cols={cols} initial="name" />
    </div>
  )
}

// ── Таб: Рентабельность и биллинг ──
function CorpBilling({ companyId, dateFrom, dateTo }: TabProps) {
  const sc = useNetScope()
  const { data, isLoading } = useClients(companyId, dateFrom, dateTo)
  const [exporting, setExporting] = useState(false)
  const [client, setClient] = useState('all')   // фильтр клиента для УПД (один клиент = один УПД)
  if (isLoading) return <Loading />
  if (!data) return <Empty text="Нет данных" />
  const t = data.totals
  const withRev = data.clients.filter((c) => c.corp_revenue > 0)
  async function dlUpd() {
    setExporting(true)
    // УПД сужается контуром: при выбранных станциях реестр охватывает только их
    // сессии (контур виден чипами наверху, экспорт печатает его в подписи).
    try { await exportCorporateBillingUpd({ companyId, dateFrom, dateTo, client: client === 'all' ? undefined : client, stations: sc.stations, regions: sc.regions }) }
    catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setExporting(false) }
  }
  const cols: Col[] = [
    { key: 'name', label: 'Клиент', left: true, get: (c) => c.name, cell: (c) => c.name },
    { key: 'retail_revenue', label: 'Розница-эквив.', get: (c) => c.retail_revenue, cell: (c) => money(c.retail_revenue) },
    { key: 'corp_revenue', label: 'К выставлению (с НДС)', get: (c) => c.corp_revenue, cell: (c) => <span className="font-medium text-foreground">{money(c.corp_revenue)}</span> },
    { key: 'discount', label: 'Разница', get: (c) => c.discount, cell: (c) => <span className={gapCls(c.discount)}>{money(c.discount)}</span> },
    { key: 'discount_pct', label: '%', get: (c) => c.discount_pct, cell: (c) => <span className={gapCls(c.discount)}>{pct(c.discount_pct)}</span> },
    { key: 'sessions', label: 'Сессий', get: (c) => c.sessions, cell: (c) => nf0.format(c.sessions) },
  ]
  const rows = client === 'all' ? withRev : withRev.filter((c) => c.name === client)
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <Kpi label="К выставлению (с НДС)" value={moneyK(t.corp_revenue)} sub={`${withRev.length} клиент(ов)`} />
        <Kpi label="Розница-эквивалент" value={moneyK(t.retail_revenue)} />
        <Kpi label="Разница (скидка/наценка)" value={money(t.discount)} sub={pct(t.discount_pct)} cls={gapCls(t.discount)} />
        <Kpi label="Ср. тариф ЮЛ" value={`${nf1.format(t.avg_tariff)} ₽/кВтч`} />
      </div>
      {/* Выгрузка под УПД: фильтр клиента (один клиент = один УПД) + xlsx с разбивкой НДС 20%. */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] text-muted-foreground">Реестр к выставлению под УПД:</span>
        <Select value={client} onValueChange={setClient}>
          <SelectTrigger className="h-7 w-[240px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">Все клиенты</SelectItem>
            {withRev.map((c) => <SelectItem key={c.phone} value={c.name} className="text-xs">{c.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Button size="sm" className="h-7 gap-1.5 text-xs" disabled={exporting} onClick={dlUpd}>
          {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileSpreadsheet className="h-3.5 w-3.5" />}
          Выгрузить под УПД (xlsx)
        </Button>
        <span className="text-[10px] text-muted-foreground/80">3 листа: Реестр + Номенклатура + Транзакции (приложение), НДС 20% выделен.</span>
      </div>
      <ClientsTable rows={rows} cols={cols} />
    </div>
  )
}

// ── Таб: Динамика (месячный тренд договорной выручки ЮЛ) ──
function CorpDynamics({ companyId, dateFrom, dateTo }: TabProps) {
  const sc = useNetScope()
  const { data, isLoading } = useQuery({
    queryKey: ['corp-dyn', companyId, dateFrom, dateTo, sc.key],
    queryFn: () => getChargeTimeseries({ companyId, dateFrom, dateTo, bucket: 'month', metric: 'amount', dim: 'user_type', dimVal: 'ЮЛ', stations: sc.stations, regions: sc.regions }),
  })
  if (isLoading) return <Loading />
  const rows = (data?.data ?? []).map((r) => ({ bucket: String(r.bucket), value: Number(r['Вся сеть'] ?? r.value ?? 0) }))
  if (rows.length === 0) return <Empty text="Нет данных за период" />
  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">Договорная выручка ЮЛ по месяцам.</div>
      <Card><CardContent className="p-3">
        <div data-chart>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={rows} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--muted-foreground))"
                tickFormatter={(b: string) => (b.length === 7 ? `${b.slice(5)}.${b.slice(2, 4)}` : b)} />
              <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} stroke="hsl(var(--muted-foreground))"
                width={52} tickFormatter={(v: number) => fmtMoneyShort(v)} />
              <Tooltip cursor={{ stroke: 'hsl(var(--muted-foreground))', strokeDasharray: '3 3' }}
                labelFormatter={(b) => String(b)} formatter={(v) => [moneyK(Number(v)), 'Выручка']} />
              <Line type="monotone" dataKey="value" stroke="hsl(217, 91%, 60%)" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent></Card>
    </div>
  )
}

interface TabProps { companyId: string; dateFrom: string; dateTo: string }

const CORP_TABS: { k: string; label: string }[] = [
  { k: 'overview', label: 'Обзор' },
  { k: 'clients', label: 'Клиенты' },
  { k: 'tariffs', label: 'Тарифы и договоры' },
  { k: 'billing', label: 'Рентабельность и биллинг' },
  { k: 'dynamics', label: 'Динамика' },
]

/** Контейнер пункта «Корпоратив» с внутренними табами. */
export function CorporatePanel({ companyId, dateFrom, dateTo }: TabProps) {
  const [t, patch] = useTabParams('corp', { sub: 'overview' })
  const p: TabProps = { companyId, dateFrom, dateTo }
  return (
    <div>
      <div className="flex items-center gap-3 border-b border-border px-4">
        <span className="text-[11px] rounded-md border border-primary/40 px-2 py-0.5 text-primary/80 shrink-0 my-2">Только ЮЛ</span>
        <PanelViewTabs tabs={CORP_TABS} value={t.sub} onChange={(k) => patch({ sub: k })} label={null} ariaLabel="Виды раздела «Корпоратив»" />
      </div>
      <div className="p-4">
        {t.sub === 'overview' && <CorpOverview {...p} />}
        {t.sub === 'clients' && <CorpClients {...p} />}
        {t.sub === 'tariffs' && <CorpTariffs {...p} />}
        {t.sub === 'billing' && <CorpBilling {...p} />}
        {t.sub === 'dynamics' && <CorpDynamics {...p} />}
      </div>
    </div>
  )
}
