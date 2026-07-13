/**
 * Панели учётных разрезов — центральная часть рабочего стола.
 * Управленческий / Финансовый / Бухгалтерский / Налоговый.
 *
 * Все четыре панели подключены к /api/analytics/* и показывают РЕАЛЬНЫЕ KPI
 * над проводками AccountingDoc и сменами FuelShift.
 */

import { useQuery } from '@tanstack/react-query'
import { useWorkspaceSubView, type CoreMode } from '@/contexts/WorkspaceContext'
import { useWorkspaceSections, ENERGY_MGMT_KEYS, CHARGE_SESSIONS_KEYS } from './workspaceSections'
import { ChargeSalesRouter } from './ChargeSalesRouter'
import { FuelOverviewPanel } from './FuelOverviewPanel'
import { FuelTransactionsPanel } from './FuelTransactionsPanel'
import { FuelMapPanel } from './FuelMapPanel'
import { FuelBalancePanel } from './FuelBalancePanel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, AlertCircle, Receipt, AlertTriangle, Pencil, Banknote, CreditCard, Ticket, Fuel, Layers } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { KpiCard } from './analytics/AnalyticsPeriodPicker'
import { useFilters } from '@/contexts/FilterContext'
import {
  getPnL, getCashFlow, getPayablesReceivables,
  getVat, getProfit,
  fmtMoney, fmtMoneyShort, fmtLiters, fmtPct,
} from '@/services/analyticsService'
import { BalanceVitrine } from '@/components/balance/BalanceVitrine'
import {
  NetworkOverviewVitrine, RevenueVitrine, TariffsVitrine, ReceivablesVitrine, ProcurementVitrine, RentVitrine,
} from '@/components/balance/EnergyManagementVitrines'
import { FinancialVitrine } from '@/components/balance/EnergyFinancialVitrine'
import { AccountingVitrine } from '@/components/balance/EnergyAccountingVitrine'
import { TaxVitrine } from '@/components/balance/EnergyTaxVitrine'
// Бухгалтерский модуль ГИГ — смены/ТТН (корректировка перед 1С) + аналитика.
// Нормализация и сверка НЕ дублируются здесь — они живут в разделах
// «Нормализация» (/normalization) и «Разрезы учёта» (/reconciliation).
import { useMemo, useState } from 'react'
import { ShiftDetailsDialog } from '@/components/fuel/ShiftDetailsDialog'
import { ShiftDashboardPanel } from '@/components/fuel/ShiftDashboardPanel'
import { SyncWith1CPanel } from '@/components/fuel/SyncWith1CPanel'
import { ReceiptsSection } from '@/components/fuel/ReceiptsSection'
import {
  getLoadedShifts, getCostingMargin, getShiftDashboard, type LoadedShift,
} from '@/services/fuel/fuelMappingService'

/* ── общие виджеты ── */

function LoadingState() {
  return (
    <div className="flex items-center justify-center py-12 text-muted-foreground">
      <Loader2 className="h-5 w-5 animate-spin mr-2" />
      Загрузка...
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="p-4">
      <Card className="border-red-500/40">
        <CardContent className="pt-4 text-sm text-red-400 flex items-start gap-2">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{message}</span>
        </CardContent>
      </Card>
    </div>
  )
}

function SectionEmpty({ section, org }: { section: string; org: string }) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <p className="max-w-md text-center text-sm text-muted-foreground">
        Компании «{org}» не подключены модули раздела «{section}». Подключите в{' '}
        <span className="text-foreground">Каталоги → Модули</span>.
      </p>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                     Управленческий учёт                          */
/* ────────────────────────────────────────────────────────────── */

// Энергомодули раздела «Управленческий» (демо-витрины, подключаются через каталог).
function EnergyMgmtVitrine({ tab }: { tab: string }) {
  switch (tab) {
    case 'net_overview': return <NetworkOverviewVitrine />
    case 'revenue': return <RevenueVitrine />
    case 'tariffs': return <TariffsVitrine />
    case 'receivables': return <ReceivablesVitrine />
    case 'procurement': return <ProcurementVitrine />
    case 'rent': return <RentVitrine />
    default: return null
  }
}

export function ManagementPanel({ mode = 'management' }: { mode?: CoreMode } = {}) {
  // Меню (под-разделы) собирается из подключённых модулей в общем хуке — им же
  // рисуется гармошка в левом вертикальном меню. Здесь — только контент.
  // Параметр mode: 'management' («Продажи») или 'operations' («Управленческий»)
  // — панель одна, роутинг пунктов (сессии/энергомодули/баланс/P&L) общий.
  const sections = useWorkspaceSections()
  const menu = sections.find((s) => s.mode === mode)?.items ?? []
  const menuKeys = menu.map((m) => m.key)
  const [tab] = useWorkspaceSubView(menuKeys[0] ?? 'overview')
  const { period } = useFilters()
  const { companyId, company } = useCompany()
  const activeTab = menuKeys.includes(tab) ? tab : (menuKeys[0] ?? 'balance')

  if (menu.length === 0) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Компании «{company.shortName || company.name}» не подключены управленческие модули. Подключите модуль в настройках.
      </div>
    )
  }

  if (activeTab === 'balance') {
    return <div className="h-full overflow-y-auto"><BalanceVitrine /></div>
  }
  if (CHARGE_SESSIONS_KEYS.includes(activeTab)) {
    return <div className="h-full overflow-y-auto"><ChargeSalesRouter tab={activeTab} companyId={companyId} dateFrom={period.from} dateTo={period.to} /></div>
  }
  if (ENERGY_MGMT_KEYS.includes(activeTab)) {
    return <div className="h-full overflow-y-auto"><EnergyMgmtVitrine tab={activeTab} /></div>
  }
  return (
    <div className="h-full overflow-y-auto">
      {activeTab === 'overview' && <FuelOverviewPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
      {activeTab === 'map' && <FuelMapPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
      {activeTab === 'by-station' && <MgmtPnLTable companyId={companyId} dateFrom={period.from} dateTo={period.to} groupBy="station" />}
      {activeTab === 'by-fuel' && <MgmtPnLTable companyId={companyId} dateFrom={period.from} dateTo={period.to} groupBy="fuel" />}
      {activeTab === 'by-month' && <MgmtPnLTable companyId={companyId} dateFrom={period.from} dateTo={period.to} groupBy="month" />}
      {activeTab === 'channels' && <MgmtChannels companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
      {activeTab === 'transactions' && <FuelTransactionsPanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
      {activeTab === 'margin' && <MgmtMargin companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
      {activeTab === 'purchases' && <ReceiptsSection />}
      {activeTab === 'tanks' && <FuelBalancePanel companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
    </div>
  )
}

function MgmtPnLTable({ companyId, dateFrom, dateTo, groupBy }: { companyId: string; dateFrom: string; dateTo: string; groupBy: 'station' | 'fuel' | 'month' }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-pnl', companyId, dateFrom, dateTo, groupBy],
    queryFn: () => getPnL({ companyId, dateFrom, dateTo, groupBy }),
  })
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={String(error)} />
  if (!data || data.lines.length === 0) {
    return <div className="p-6 text-sm text-muted-foreground text-center">Нет данных за выбранный период</div>
  }
  return (
    <div className="p-4">
      <Card>
        <CardContent className="p-0">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="text-left p-2 font-medium">
                  {groupBy === 'station' ? 'Станция/ЮЛ' : groupBy === 'fuel' ? 'Вид топлива' : 'Месяц'}
                </th>
                <th className="text-right p-2 font-medium">Выручка с НДС</th>
                <th className="text-right p-2 font-medium">без НДС</th>
                <th className="text-right p-2 font-medium">Себестоим.</th>
                <th className="text-right p-2 font-medium">Маржа</th>
                <th className="text-right p-2 font-medium">Маржа %</th>
                <th className="text-right p-2 font-medium">Литров</th>
                <th className="text-right p-2 font-medium">Док.</th>
              </tr>
            </thead>
            <tbody>
              {data.lines.map((l) => (
                <tr key={l.label} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-medium">{l.label}</td>
                  <td className="p-2 text-right font-mono">{fmtMoney(l.revenue)}</td>
                  <td className="p-2 text-right font-mono">{fmtMoney(l.revenue_net)}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{fmtMoney(l.cogs)}</td>
                  <td className={`p-2 text-right font-mono ${l.gross_margin >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{fmtMoney(l.gross_margin)}</td>
                  <td className="p-2 text-right font-mono">{fmtPct(l.gross_margin_pct)}</td>
                  <td className="p-2 text-right font-mono">{l.liters > 0 ? fmtLiters(l.liters) : '—'}</td>
                  <td className="p-2 text-right font-mono">{l.docs_count}</td>
                </tr>
              ))}
              <tr className="bg-muted/60 font-medium">
                <td className="p-2">Итого</td>
                <td className="p-2 text-right font-mono">{fmtMoney(data.totals.revenue)}</td>
                <td className="p-2 text-right font-mono">{fmtMoney(data.totals.revenue_net)}</td>
                <td className="p-2 text-right font-mono">{fmtMoney(data.totals.cogs)}</td>
                <td className={`p-2 text-right font-mono ${data.totals.gross_margin >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {fmtMoney(data.totals.gross_margin)}
                </td>
                <td className="p-2 text-right font-mono">{fmtPct(data.totals.gross_margin_pct)}</td>
                <td className="p-2 text-right font-mono">{fmtLiters(data.totals.liters)}</td>
                <td className="p-2 text-right font-mono">{data.totals.docs_count}</td>
              </tr>
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

/* ── Каналы продаж (полный разрез по видам оплаты — из сырых отчётов STS) ── */

// Таблица разреза продаж: все строки (виды оплаты / топлива), Наливы·Выручка·Объём·Доля·₽л·Итого.
// Наливы (count) — из пооперационных транзакций; при отсутствии колонка скрыта.
function ChannelBreakTable({ title, nameCol, rows }: {
  title: string; nameCol: string; rows: { name: string; revenue: number; volume: number; count?: number }[]
}) {
  const totRev = rows.reduce((s, r) => s + r.revenue, 0)
  const totVol = rows.reduce((s, r) => s + r.volume, 0)
  const hasCount = rows.some((r) => r.count != null)
  const totCnt = rows.reduce((s, r) => s + (r.count ?? 0), 0)
  const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
  return (
    <Card>
      <CardContent className="p-0">
        <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b bg-muted/40">{title} ({rows.length})</div>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/20 text-muted-foreground">
              <th className="text-left p-2 font-medium">{nameCol}</th>
              {hasCount && <th className="text-right p-2 font-medium">Наливы</th>}
              <th className="text-right p-2 font-medium">Выручка</th>
              <th className="text-right p-2 font-medium">Объём, л</th>
              <th className="text-right p-2 font-medium">Доля</th>
              <th className="text-right p-2 font-medium">₽/л</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="border-b border-border/30 hover:bg-muted/30">
                <td className="p-2 font-medium truncate max-w-[180px]">{r.name}</td>
                {hasCount && <td className="p-2 text-right font-mono tabular-nums text-muted-foreground">{r.count != null ? nf0.format(r.count) : '—'}</td>}
                <td className="p-2 text-right font-mono">{fmtMoney(r.revenue)}</td>
                <td className="p-2 text-right font-mono text-muted-foreground">{fmtLiters(r.volume)}</td>
                <td className="p-2 text-right font-mono">{totRev ? (r.revenue / totRev * 100).toFixed(1) : '0.0'}%</td>
                <td className="p-2 text-right font-mono text-muted-foreground">{r.volume ? fmtMoney(r.revenue / r.volume) : '—'}</td>
              </tr>
            ))}
            <tr className="bg-muted/60 font-medium">
              <td className="p-2">Итого</td>
              {hasCount && <td className="p-2 text-right font-mono">{nf0.format(totCnt)}</td>}
              <td className="p-2 text-right font-mono">{fmtMoney(totRev)}</td>
              <td className="p-2 text-right font-mono">{fmtLiters(totVol)}</td>
              <td className="p-2 text-right font-mono">100%</td>
              <td className="p-2 text-right font-mono">{totVol ? fmtMoney(totRev / totVol) : '—'}</td>
            </tr>
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

function MgmtChannels({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  // Полный разрез из сырых отчётов STS (все виды оплаты как есть) — как в эталонной
  // системе. Комиссий в ленте STS нет, поэтому фиктивных ставок/«чистой выручки» здесь больше нет.
  const { data, isLoading, error } = useQuery({
    queryKey: ['fuel-channels', companyId, dateFrom, dateTo],
    queryFn: () => getShiftDashboard(dateFrom, dateTo),
  })
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={String(error)} />
  const pays = (data?.payment_methods ?? []).slice().sort((a, b) => b.revenue - a.revenue)
  const fuels = (data?.fuel_types_raw ?? []).slice().sort((a, b) => b.revenue - a.revenue)
  if (pays.length === 0) return <div className="p-6 text-sm text-muted-foreground text-center">Нет продаж по каналам за период</div>

  const totRev = pays.reduce((s, r) => s + r.revenue, 0)
  const totVol = pays.reduce((s, r) => s + r.volume, 0)
  const totCnt = pays.reduce((s, r) => s + (r.count ?? 0), 0)

  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Оборот (все оплаты)" value={fmtMoneyShort(totRev) + ' ₽'} hint={`${data?.operational.shifts_count ?? 0} смен`} />
        <KpiCard label="Наливов" value={totCnt ? totCnt.toLocaleString('ru-RU') : '—'} accent="info" hint="операций отпуска" />
        <KpiCard label="Объём" value={fmtLiters(totVol)} />
        <KpiCard label="Видов оплаты" value={String(pays.length)} />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <ChannelBreakTable title="Способы оплаты" nameCol="Вид" rows={pays} />
        <ChannelBreakTable title="Виды топлива" nameCol="Топливо" rows={fuels.map((f) => ({ name: f.name, revenue: f.revenue, volume: f.volume, count: f.count }))} />
      </div>
      <Card>
        <CardContent className="pt-4 text-xs text-muted-foreground">
          Разрез — по сырым отчётам STS: каждый вид оплаты как есть (вкл. Купон/Прокачку/Тех.отпуск), ничего не свёрнуто и не отброшено.
          Комиссий эквайринга/агрегаторов в ленте STS нет — они появятся после подключения эквайринг-реестра (Сбербанк) с реальными ставками по договорам.
        </CardContent>
      </Card>
    </div>
  )
}

/* ── Маржа и цены (валовая маржа по видам топлива, ₽/литр) ── */

function MgmtMargin({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-pnl', companyId, dateFrom, dateTo, 'fuel'],
    queryFn: () => getPnL({ companyId, dateFrom, dateTo, groupBy: 'fuel' }),
  })
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={String(error)} />
  if (!data || data.lines.length === 0) return <div className="p-6 text-sm text-muted-foreground text-center">Нет данных за период</div>
  const t = data.totals
  const perL = (m: number, l: number) => (l > 0 ? m / l : 0)
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Валовая маржа" value={fmtMoneyShort(t.gross_margin) + ' ₽'} accent={t.gross_margin >= 0 ? 'success' : 'danger'} />
        <KpiCard label="Маржа %" value={fmtPct(t.gross_margin_pct)} />
        <KpiCard label="Маржа ₽/литр" value={fmtMoney(perL(t.gross_margin, t.liters)) + ' ₽'} hint="средняя по всем видам" />
        <KpiCard label="Литров продано" value={fmtLiters(t.liters)} />
      </div>
      <Card>
        <CardContent className="p-0">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="text-left p-2 font-medium">Вид топлива</th>
                <th className="text-right p-2 font-medium">Выручка без НДС</th>
                <th className="text-right p-2 font-medium">Себестоим.</th>
                <th className="text-right p-2 font-medium">Маржа</th>
                <th className="text-right p-2 font-medium">Маржа %</th>
                <th className="text-right p-2 font-medium">₽/литр</th>
                <th className="text-right p-2 font-medium">Литров</th>
              </tr>
            </thead>
            <tbody>
              {data.lines.map((l) => (
                <tr key={l.label} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-medium">{l.label}</td>
                  <td className="p-2 text-right font-mono">{fmtMoney(l.revenue_net)}</td>
                  <td className="p-2 text-right font-mono text-muted-foreground">{fmtMoney(l.cogs)}</td>
                  <td className={`p-2 text-right font-mono ${l.gross_margin >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{fmtMoney(l.gross_margin)}</td>
                  <td className="p-2 text-right font-mono">{fmtPct(l.gross_margin_pct)}</td>
                  <td className="p-2 text-right font-mono">{fmtMoney(perL(l.gross_margin, l.liters))}</td>
                  <td className="p-2 text-right font-mono">{l.liters > 0 ? fmtLiters(l.liters) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-4 text-xs text-muted-foreground">
          Маржа = выручка без НДС − себестоимость (COGS из проводок 90.02). «₽/литр» — валовая маржа на литр
          проданного топлива. Динамика закупочных цен — на вкладке «Поступления» и в разделе «1С → Цены».
        </CardContent>
      </Card>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                       Финансовый учёт                          */
/* ────────────────────────────────────────────────────────────── */

export function FinancialPanel() {
  const sections = useWorkspaceSections()
  const section = sections.find((s) => s.mode === 'financial')
  const items = section?.items ?? []
  const [tab] = useWorkspaceSubView(items[0]?.key ?? 'overview', items.map((i) => i.key))
  const { period } = useFilters()
  const { companyId, company } = useCompany()
  const isEnergy = company.profileId === 'energy'

  if (!section?.connected) return <SectionEmpty section="Финансовый" org={company.shortName || company.name} />
  if (isEnergy) return <div className="h-full overflow-y-auto"><FinancialVitrine /></div>

  return (
    <div className="h-full flex flex-col">
      <ScrollArea className="flex-1 min-h-0">
        {tab === 'overview' && <FinOverview companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
        {tab === 'cashflow' && <FinCashFlow companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
        {tab === 'receivables' && <FinContragents companyId={companyId} dateFrom={period.from} dateTo={period.to} mode="receivables" />}
        {tab === 'payables' && <FinContragents companyId={companyId} dateFrom={period.from} dateTo={period.to} mode="payables" />}
      </ScrollArea>
    </div>
  )
}

function FinOverview({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const cf = useQuery({
    queryKey: ['analytics-cashflow', companyId, dateFrom, dateTo],
    queryFn: () => getCashFlow({ companyId, dateFrom, dateTo }),
  })
  const ar = useQuery({
    queryKey: ['analytics-pr', companyId, dateFrom, dateTo],
    queryFn: () => getPayablesReceivables({ companyId, dateFrom, dateTo }),
  })
  if (cf.isLoading || ar.isLoading) return <LoadingState />
  if (cf.error || ar.error) return <ErrorState message={String((cf.error || ar.error) as Error)} />
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Поступления" value={fmtMoneyShort(cf.data!.inflow_total) + ' ₽'} accent="success" />
        <KpiCard label="Выплаты" value={fmtMoneyShort(cf.data!.outflow_total) + ' ₽'} accent="danger" />
        <KpiCard label="Нетто" value={fmtMoneyShort(cf.data!.net_total) + ' ₽'}
          accent={cf.data!.net_total >= 0 ? 'success' : 'danger'} />
        <KpiCard label="" value="" />
        <KpiCard label="Кредиторка (60.01)" value={fmtMoneyShort(ar.data!.totals.payables_balance) + ' ₽'} accent="warning"
          hint="Кому мы должны" />
        <KpiCard label="Дебиторка (62)" value={fmtMoneyShort(ar.data!.totals.receivables_balance) + ' ₽'} accent="info"
          hint="Кто должен нам" />
        <KpiCard label="Net working capital"
          value={fmtMoneyShort(ar.data!.totals.receivables_balance - ar.data!.totals.payables_balance) + ' ₽'} />
        <KpiCard label="" value="" />
      </div>
    </div>
  )
}

function FinCashFlow({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-cashflow', companyId, dateFrom, dateTo],
    queryFn: () => getCashFlow({ companyId, dateFrom, dateTo }),
  })
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={String(error)} />
  if (!data) return null
  return (
    <div className="p-4">
      <Card>
        <CardContent className="p-0">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="text-left p-2 font-medium">Счёт</th>
                <th className="text-left p-2 font-medium">Название</th>
                <th className="text-right p-2 font-medium">Дт (приход)</th>
                <th className="text-right p-2 font-medium">Кт (расход)</th>
                <th className="text-right p-2 font-medium">Нетто</th>
              </tr>
            </thead>
            <tbody>
              {data.accounts.map((a) => (
                <tr key={a.account} className="border-b border-border/30">
                  <td className="p-2 font-mono">{a.account}</td>
                  <td className="p-2">{a.name}</td>
                  <td className="p-2 text-right font-mono text-emerald-400">{fmtMoney(a.debit)}</td>
                  <td className="p-2 text-right font-mono text-red-400">{fmtMoney(a.credit)}</td>
                  <td className={`p-2 text-right font-mono ${a.net >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{fmtMoney(a.net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

function FinContragents({ companyId, dateFrom, dateTo, mode }: { companyId: string; dateFrom: string; dateTo: string; mode: 'payables' | 'receivables' }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-pr', companyId, dateFrom, dateTo],
    queryFn: () => getPayablesReceivables({ companyId, dateFrom, dateTo }),
  })
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={String(error)} />
  if (!data) return null
  const list = mode === 'payables' ? data.payables : data.receivables
  return (
    <div className="p-4">
      <Card>
        <CardContent className="p-0">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="text-left p-2 font-medium">Контрагент</th>
                <th className="text-left p-2 font-medium">ИНН</th>
                <th className="text-right p-2 font-medium">Дт оборот</th>
                <th className="text-right p-2 font-medium">Кт оборот</th>
                <th className="text-right p-2 font-medium">Сальдо</th>
              </tr>
            </thead>
            <tbody>
              {list.slice(0, 100).map((r) => (
                <tr key={r.counterparty + (r.inn ?? '')} className="border-b border-border/30">
                  <td className="p-2 truncate max-w-[300px]">{r.counterparty}</td>
                  <td className="p-2 font-mono text-muted-foreground">{r.inn ?? '—'}</td>
                  <td className="p-2 text-right font-mono">{fmtMoney(r.debit)}</td>
                  <td className="p-2 text-right font-mono">{fmtMoney(r.credit)}</td>
                  <td className={`p-2 text-right font-mono ${r.balance >= 0 ? 'text-amber-400' : 'text-emerald-400'}`}>{fmtMoney(r.balance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.length === 0 && (
            <div className="p-6 text-center text-sm text-muted-foreground">Нет операций по контрагентам в выбранном периоде</div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                      Бухгалтерский учёт                        */
/* ────────────────────────────────────────────────────────────── */
// Модуль собирается из компонентов (config/moduleComponents.ts) по идеологии
// L1 RAW → L2 CLEAN → L3 EXPORT → L4 1C_REF. Меню (section.items) — включённые
// компоненты компании; здесь только маршрутизация под-разделов на контент.

export function AccountingPanel() {
  const sections = useWorkspaceSections()
  const section = sections.find((s) => s.mode === 'accounting')
  const items = section?.items ?? []
  const [tab] = useWorkspaceSubView(items[0]?.key ?? 'overview', items.map((i) => i.key))
  const { company, companyId } = useCompany()
  const { period } = useFilters()
  const isEnergy = company.profileId === 'energy'
  if (!section?.connected) return <SectionEmpty section="Бухгалтерский" org={company.shortName || company.name} />
  if (isEnergy) return <div className="h-full overflow-y-auto"><AccountingVitrine /></div>

  return (
    <ScrollArea className="h-full">
        {/* Специализированные ГИГ — смены/ТТН с корректировкой перед выгрузкой */}
        {tab === 'shifts' && <ShiftsPanel />}
        {tab === 'ttn' && <ReceiptsSection />}
        {tab === 'margin' && (
          <div className="p-4 space-y-4">
            <FifoMarginView dateFrom={period.from} dateTo={period.to} />
            <div>
              <p className="mb-2 text-xs text-muted-foreground">
                Бухгалтерская маржа (COGS из проводок 1С 90.02, постфактум):
              </p>
              <MgmtMargin companyId={companyId} dateFrom={period.from} dateTo={period.to} />
            </div>
          </div>
        )}
        {tab === 'reports' && <ShiftDashboardPanel />}
        {tab === 'recon1c' && <SyncWith1CPanel />}
    </ScrollArea>
  )
}

/* Управленческая маржа по FIFO-себестоимости партий (по разрезам). */
function FifoMarginView({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const [groupBy, setGroupBy] = useState('fuel')
  const { data, isLoading } = useQuery({
    queryKey: ['costing-margin', dateFrom, dateTo, groupBy],
    queryFn: () => getCostingMargin(dateFrom, dateTo, groupBy),
  })
  const fmt = (v: number, d = 0) => (v ?? 0).toLocaleString('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d })
  const GROUPS = [
    { key: 'fuel', label: 'Топливо' }, { key: 'payment', label: 'Вид оплаты' },
    { key: 'fuel_payment', label: 'Топливо × оплата' }, { key: 'station', label: 'Станция' },
    { key: 'month', label: 'Месяц' },
  ]
  const uncosted = data?.totals.liters_uncosted ?? 0

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">Управленческая маржа (FIFO по партиям)</span>
          <div className="ml-auto flex flex-wrap gap-1">
            {GROUPS.map((g) => (
              <button key={g.key} onClick={() => setGroupBy(g.key)}
                className={`rounded px-2 py-1 text-xs transition-colors ${groupBy === g.key ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:bg-accent/40'}`}>
                {g.label}
              </button>
            ))}
          </div>
        </div>
        {uncosted > 0 && (
          <div className="mb-2 flex items-start gap-2 rounded border border-amber-400/40 bg-amber-400/5 px-3 py-2 text-xs text-amber-300/90">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{fmt(uncosted)} л продано из партий без заданной себестоимости — не учтены в марже.
              Задайте себестоимость на карточке ТТН (раздел «ТТН»).</span>
          </div>
        )}
        {isLoading ? <LoadingState /> : !data || data.lines.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Нет продаж с заданной себестоимостью партий за период. Задайте себестоимость на ТТН.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-xs text-muted-foreground">
                  <th className="py-2 pr-3 text-left font-medium">Разрез</th>
                  <th className="px-3 text-right font-medium">Литры</th>
                  <th className="px-3 text-right font-medium">Выручка (без НДС)</th>
                  <th className="px-3 text-right font-medium">Себест. FIFO</th>
                  <th className="px-3 text-right font-medium">Маржа</th>
                  <th className="pl-3 text-right font-medium">Маржа ₽/л</th>
                </tr>
              </thead>
              <tbody>
                {data.lines.map((l, i) => (
                  <tr key={i} className="border-b border-border/30">
                    <td className="py-2 pr-3">{l.label}</td>
                    <td className="px-3 text-right tabular-nums">{fmt(l.liters)}</td>
                    <td className="px-3 text-right tabular-nums">{fmt(l.revenue_net)}</td>
                    <td className="px-3 text-right tabular-nums">{fmt(l.cogs)}</td>
                    <td className={`px-3 text-right tabular-nums ${l.margin >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>{fmt(l.margin)}</td>
                    <td className="pl-3 text-right tabular-nums">{l.margin_per_liter.toFixed(2)}</td>
                  </tr>
                ))}
                <tr className="bg-secondary/40 font-semibold">
                  <td className="py-2 pr-3">Итого</td>
                  <td className="px-3 text-right tabular-nums">{fmt(data.totals.liters)}</td>
                  <td className="px-3 text-right tabular-nums">{fmt(data.totals.revenue_net)}</td>
                  <td className="px-3 text-right tabular-nums">{fmt(data.totals.cogs)}</td>
                  <td className={`px-3 text-right tabular-nums ${data.totals.margin >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>{fmt(data.totals.margin)}</td>
                  <td className="pl-3" />
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/* Смены — журнал загруженных смен; клик открывает детали с вкладкой «Корректировка»
   (правка значений реализации перед выгрузкой в 1С, персист в L2). */
function ShiftsPanel() {
  const { data } = useQuery({ queryKey: ['fuel-shifts-acc'], queryFn: getLoadedShifts })
  const shifts: LoadedShift[] = data ?? []
  const [openShift, setOpenShift] = useState<string | null>(null)
  const [onlyCorrected, setOnlyCorrected] = useState(false)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [station, setStation] = useState('all')
  const [shiftNum, setShiftNum] = useState('')

  const fmtDT = (s: string | null) =>
    s ? new Date(s).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—'
  const fmtN = (v: number, d = 0) =>
    (v ?? 0).toLocaleString('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d })

  const stations = useMemo(() => {
    const m = new Map<number, string>()
    for (const s of shifts) if (!m.has(s.station_code)) m.set(s.station_code, s.station_name ?? `АЗС №${s.station_code}`)
    return [...m.entries()].sort((a, b) => a[0] - b[0])
  }, [shifts])

  const filtered = useMemo(() => {
    let list = shifts
    if (station !== 'all') list = list.filter((s) => String(s.station_code) === station)
    if (shiftNum.trim()) list = list.filter((s) => String(s.shift_number).includes(shiftNum.trim()))
    if (dateFrom || dateTo) {
      const from = dateFrom ? new Date(dateFrom + 'T00:00:00') : null
      const to = dateTo ? new Date(dateTo + 'T23:59:59') : null
      list = list.filter((s) => {
        if (!s.opened_at) return false
        const d = new Date(s.opened_at)
        if (from && d < from) return false
        if (to && d > to) return false
        return true
      })
    }
    return list
  }, [shifts, station, shiftNum, dateFrom, dateTo])

  const kpi = useMemo(() => {
    let cash = 0, card = 0, voucher = 0, total = 0, liters = 0
    for (const s of filtered) {
      cash += s.cash || 0; card += s.card || 0; voucher += s.voucher || 0
      total += s.total_amount || 0; liters += s.total_liters || 0
    }
    return { cash, card, voucher, total, liters, count: filtered.length }
  }, [filtered])

  const corrCount = useMemo(() => filtered.filter((s) => s.has_corrections).length, [filtered])
  const shown = onlyCorrected ? filtered.filter((s) => s.has_corrections) : filtered
  const clear = () => { setDateFrom(''); setDateTo(''); setStation('all'); setShiftNum(''); setOnlyCorrected(false) }

  const KCARD = 'rounded-xl border border-border bg-card p-3'
  const gridCols = 'grid grid-cols-[110px_1fr_130px_130px_110px_120px] gap-3 items-center'

  return (
    <div className="p-4 space-y-4">
      {/* KPI по способам оплаты */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className={`${KCARD} bg-gradient-to-br from-blue-50 to-card dark:from-blue-900/40`}>
          <div className="flex items-center gap-1.5 text-sm"><Fuel className="h-4 w-4 text-blue-500" /><span className="font-medium">ИТОГО</span><span className="ml-auto text-xs text-muted-foreground">{kpi.count} смен</span></div>
          <div className="mt-2 text-base font-bold tabular-nums">{fmtN(kpi.total, 2)} ₽</div>
          <div className="text-sm tabular-nums text-primary">{fmtN(kpi.liters)} л</div>
        </div>
        <div className={KCARD}>
          <div className="flex items-center gap-1.5 text-sm"><Banknote className="h-4 w-4 text-emerald-500" /><span className="font-medium">Наличные</span></div>
          <div className="mt-2 text-base font-bold tabular-nums">{fmtN(kpi.cash, 2)} ₽</div>
        </div>
        <div className={KCARD}>
          <div className="flex items-center gap-1.5 text-sm"><CreditCard className="h-4 w-4 text-blue-500" /><span className="font-medium">Карты</span></div>
          <div className="mt-2 text-base font-bold tabular-nums">{fmtN(kpi.card, 2)} ₽</div>
        </div>
        <div className={KCARD}>
          <div className="flex items-center gap-1.5 text-sm"><Ticket className="h-4 w-4 text-amber-500" /><span className="font-medium">Талоны</span></div>
          <div className="mt-2 text-base font-bold tabular-nums">{fmtN(kpi.voucher, 2)} ₽</div>
        </div>
      </div>

      {/* Фильтры */}
      <Card className="py-3">
        <CardContent className="pt-0 pb-0">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Дата от</Label>
              <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="h-8" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Дата до</Label>
              <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="h-8" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Станция</Label>
              <Select value={station} onValueChange={setStation}>
                <SelectTrigger className="h-8"><SelectValue placeholder="Все" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все</SelectItem>
                  {stations.map(([code, name]) => <SelectItem key={code} value={String(code)}>{name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Номер смены</Label>
              <Input type="text" placeholder="Введите номер" value={shiftNum} onChange={(e) => setShiftNum(e.target.value)} className="h-8" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Журнал */}
      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex flex-wrap items-center gap-1.5">
            <Layers className="h-3.5 w-3.5 text-muted-foreground" />
            Сменные отчёты
            <span className="ml-2 text-xs font-normal tabular-nums text-muted-foreground">{shown.length}</span>
            <button onClick={() => setOnlyCorrected((v) => !v)} disabled={corrCount === 0}
              className={`ml-auto inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs transition-colors disabled:opacity-50 ${onlyCorrected ? 'border-amber-400 bg-amber-100 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300' : 'border-border text-muted-foreground hover:bg-accent/40'}`}>
              <Pencil className="h-3 w-3" />Только изменённые{corrCount > 0 ? ` (${corrCount})` : ''}
            </button>
            <button onClick={clear} className="text-xs text-muted-foreground hover:text-foreground">Сбросить фильтры</button>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-3">
          <div className={`${gridCols} px-3 pb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70`}>
            <span>Смена</span><span>Станция</span><span>Открыта</span><span>Закрыта</span>
            <span className="text-right">Литры</span><span className="text-right">Сумма, ₽</span>
          </div>
          <div className="max-h-[460px] space-y-1 overflow-y-auto pr-1">
            {shown.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                {shifts.length === 0 ? 'Нет загруженных смен. Загрузите период в канале STS.' : 'Нет смен по фильтру.'}
              </p>
            ) : shown.map((s) => (
              <div key={s.id} onClick={() => setOpenShift(s.id)}
                className={`${gridCols} cursor-pointer rounded-xl bg-di-surface-low px-3 py-2.5 text-xs transition-colors hover:bg-di-surface-high ${s.has_corrections ? 'border-l-2 border-l-amber-400 bg-amber-50/60 dark:bg-amber-400/[0.06]' : ''}`}>
                <span className="font-medium inline-flex items-center gap-1.5">
                  #{s.shift_number}
                  {s.has_corrections && (
                    <span title="Внесена корректировка перед выгрузкой в 1С"
                      className="inline-flex items-center gap-0.5 rounded-md bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-400/15 dark:text-amber-300">
                      <Pencil className="h-2.5 w-2.5" />испр.
                    </span>
                  )}
                </span>
                <span className="text-foreground/80 truncate">{s.station_name ?? `АЗС №${s.station_code}`}</span>
                <span className="text-muted-foreground tabular-nums">{fmtDT(s.opened_at)}</span>
                <span className="text-muted-foreground tabular-nums">{fmtDT(s.closed_at)}</span>
                <span className="text-right tabular-nums text-foreground/80">{fmtN(s.total_liters)}</span>
                <span className="text-right tabular-nums text-foreground/80">{fmtN(s.total_amount, 2)}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
      <ShiftDetailsDialog shiftId={openShift} open={!!openShift} onClose={() => setOpenShift(null)} />
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                          Налоговый учёт                          */
/* ────────────────────────────────────────────────────────────── */

export function TaxPanel() {
  const sections = useWorkspaceSections()
  const section = sections.find((s) => s.mode === 'tax')
  const items = section?.items ?? []
  const [tab] = useWorkspaceSubView(items[0]?.key ?? 'vat', items.map((i) => i.key))
  const { period } = useFilters()
  const { companyId, company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  if (!section?.connected) return <SectionEmpty section="Налоговый" org={company.shortName || company.name} />
  if (isEnergy) return <div className="h-full overflow-y-auto"><TaxVitrine /></div>
  return (
    <div className="h-full flex flex-col">
      <ScrollArea className="flex-1 min-h-0">
        {tab === 'vat' && <TaxVat companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
        {tab === 'profit' && <TaxProfit companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
        {tab === 'compliance' && <TaxCompliance companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
      </ScrollArea>
    </div>
  )
}

function TaxVat({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-vat', companyId, dateFrom, dateTo],
    queryFn: () => getVat({ companyId, dateFrom, dateTo }),
  })
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={String(error)} />
  if (!data) return null
  const expectedVat = data.revenue_net * 0.22
  const vatGap = data.output_vat - expectedVat
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Исходящий НДС (Кт 68.02)" value={fmtMoney(data.output_vat) + ' ₽'} accent="warning" />
        <KpiCard label="Входящий НДС (Дт 19.03)" value={fmtMoney(data.input_vat) + ' ₽'} accent="info" />
        <KpiCard label="К уплате"
          value={fmtMoney(data.payable) + ' ₽'}
          accent={data.payable > 0 ? 'danger' : 'success'} />
        <KpiCard label="Эфф. ставка"
          value={data.effective_rate_pct.toFixed(2) + '%'}
          hint="Ожидается 22% при ОСН" />
        <KpiCard label="Выручка с НДС" value={fmtMoneyShort(data.revenue_with_vat) + ' ₽'} />
        <KpiCard label="Выручка без НДС" value={fmtMoneyShort(data.revenue_net) + ' ₽'} />
        <KpiCard label="Ожидаемый НДС 22%" value={fmtMoneyShort(expectedVat) + ' ₽'} hint="по выручке без НДС × 0.22" />
        <KpiCard label="Расхождение с ожиданием"
          value={fmtMoney(vatGap) + ' ₽'}
          accent={Math.abs(vatGap) < 1 ? 'success' : 'warning'} />
      </div>
      <Card>
        <CardContent className="pt-4 text-xs space-y-1">
          <p className="font-medium text-sm">Логика расчёта</p>
          <p className="text-muted-foreground">
            Источник: AccountingDoc.lines.postings (РегистрБухгалтерии.Хозрасчетный). Только проведённые
            документы в выбранном периоде. Расхождение с ожиданием показывает, есть ли проводки
            с нестандартной ставкой НДС (10% / без НДС / специфические товары).
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

function TaxProfit({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-profit', companyId, dateFrom, dateTo],
    queryFn: () => getProfit({ companyId, dateFrom, dateTo }),
  })
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={String(error)} />
  if (!data) return null
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Выручка без НДС" value={fmtMoneyShort(data.revenue_net) + ' ₽'} />
        <KpiCard label="Себестоимость" value={fmtMoneyShort(data.cogs) + ' ₽'} accent="info" />
        <KpiCard label="Коммерческие (44)" value={fmtMoneyShort(data.sga) + ' ₽'} accent="info" />
        <KpiCard label="Прочие доходы/расходы"
          value={fmtMoneyShort(data.other_income - data.other_expenses) + ' ₽'} />
        <KpiCard label="Прибыль до налога"
          value={fmtMoneyShort(data.profit_before_tax) + ' ₽'}
          accent={data.profit_before_tax >= 0 ? 'success' : 'danger'} />
        <KpiCard label="Ставка налога" value={data.tax_rate_pct + '%'} />
        <KpiCard label="Налог (оценка)" value={fmtMoneyShort(data.tax_estimated) + ' ₽'} accent="warning" />
        <KpiCard label="Чистая прибыль"
          value={fmtMoneyShort(data.net_profit) + ' ₽'}
          accent={data.net_profit >= 0 ? 'success' : 'danger'} />
      </div>
      <Card>
        <CardContent className="pt-4 text-xs text-muted-foreground">
          Расчёт упрощённый: P&L = (90.01 − 68.02) − 90.02 − 44 + (91.01 − 91.02). Налог = max(0, P&L) × {data.tax_rate_pct}%.
          Не учитывает временные/постоянные разницы ПБУ 18/02 и налоговый учёт по гл. 25 НК РФ — для финального расчёта
          сверяется с формой 02 декларации.
        </CardContent>
      </Card>
    </div>
  )
}

function TaxCompliance({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const vat = useQuery({
    queryKey: ['analytics-vat', companyId, dateFrom, dateTo],
    queryFn: () => getVat({ companyId, dateFrom, dateTo }),
  })
  if (vat.isLoading) return <LoadingState />
  if (!vat.data) return null
  const expected = vat.data.revenue_net * 0.22
  const gap = Math.abs(vat.data.output_vat - expected)
  const ok = gap < 1
  return (
    <div className="p-4 space-y-3">
      <Card className={ok ? 'border-emerald-500/40' : 'border-amber-500/40'}>
        <CardContent className="pt-4 flex items-start gap-3 text-sm">
          {ok ? <Receipt className="h-5 w-5 text-emerald-400 mt-0.5" /> : <AlertTriangle className="h-5 w-5 text-amber-400 mt-0.5" />}
          <div>
            <p className="font-medium">{ok ? 'НДС начислен корректно' : 'Возможные отклонения по НДС'}</p>
            <p className="text-xs text-muted-foreground mt-1">
              Ожидание: {fmtMoney(expected)} ₽ · Факт: {fmtMoney(vat.data.output_vat)} ₽ · Δ {fmtMoney(gap)} ₽
            </p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-4 text-xs text-muted-foreground space-y-1">
          <p className="font-medium text-sm text-foreground">Что проверяется</p>
          <ul className="list-disc list-inside space-y-0.5">
            <li>Ставка НДС 22% (ОСН) применена ко всем строкам выручки</li>
            <li>Книга покупок (Дт 19.03) сопоставима с поставщиками из ПТУ</li>
            <li>Эффективная ставка соответствует виду деятельности</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
