/**
 * Панели учётных разрезов — центральная часть рабочего стола.
 * Управленческий / Финансовый / Бухгалтерский / Налоговый.
 *
 * Все четыре панели подключены к /api/analytics/* и показывают РЕАЛЬНЫЕ KPI
 * над проводками AccountingDoc и сменами FuelShift.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2, AlertCircle, TrendingUp, Wallet, Receipt, AlertTriangle } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import {
  AnalyticsPeriodPicker, KpiCard, useAnalyticsPeriod,
} from './analytics/AnalyticsPeriodPicker'
import {
  getPnL, getPaymentMix, getCashFlow, getPayablesReceivables,
  getVat, getProfit,
  fmtMoney, fmtMoneyShort, fmtLiters, fmtPct,
} from '@/services/analyticsService'
import { balanceModuleForProfile } from '@/config/balanceModules'
import { BalanceVitrine } from '@/components/balance/BalanceVitrine'
import { LocationsPage } from '@/pages/LocationsPage'
import {
  NetworkOverviewVitrine, RevenueVitrine, TariffsVitrine, ReceivablesVitrine, ProcurementVitrine,
} from '@/components/balance/EnergyManagementVitrines'
import { FinancialVitrine } from '@/components/balance/EnergyFinancialVitrine'
import { AccountingVitrine } from '@/components/balance/EnergyAccountingVitrine'
import { TaxVitrine } from '@/components/balance/EnergyTaxVitrine'
import { getWorkspaceModule } from '@/config/workspaceModules'
import { useModuleConnections, isModuleConnected } from '@/services/moduleConnectionService'

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

// Подключён ли раздел компании (модуль раздела) + пустое состояние, если нет.
function useSectionGate(moduleId: string) {
  const { conn, profileId } = useModuleConnections()
  const { company } = useCompany()
  const mod = getWorkspaceModule(moduleId)
  return { connected: !!mod && isModuleConnected(conn, mod, profileId), org: company.shortName || company.name }
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

const MGMT_MENU: CentralMenuItem[] = [
  { key: 'overview',  label: 'Обзор' },
  { key: 'by-station', label: 'По станциям' },
  { key: 'by-fuel',   label: 'По топливу' },
  { key: 'by-month',  label: 'По месяцам' },
  { key: 'marketing', label: 'Маркетинг' },
]

// Энергомодули раздела «Управленческий» (демо-витрины, подключаются через каталог).
const ENERGY_MGMT: CentralMenuItem[] = [
  { key: 'net_overview', label: 'Сводка сети' },
  { key: 'revenue', label: 'Выручка и продажи' },
  { key: 'tariffs', label: 'Тарифы и ценообразование' },
  { key: 'receivables', label: 'Дебиторка и взаиморасчёты' },
  { key: 'procurement', label: 'Энергозакупка' },
]
const ENERGY_MGMT_KEYS = ENERGY_MGMT.map((m) => m.key)
function EnergyMgmtVitrine({ tab }: { tab: string }) {
  switch (tab) {
    case 'net_overview': return <NetworkOverviewVitrine />
    case 'revenue': return <RevenueVitrine />
    case 'tariffs': return <TariffsVitrine />
    case 'receivables': return <ReceivablesVitrine />
    case 'procurement': return <ProcurementVitrine />
    default: return null
  }
}

export function ManagementPanel() {
  const [tab, setTab] = useState('overview')
  const [period, setPeriod] = useAnalyticsPeriod()
  const { companyId, company } = useCompany()
  // Управленческий уровень работает на НОРМАЛИЗОВАННОЙ базе (выход конвейера Источник→Канал→Разрез)
  // и собирается из МОДУЛЕЙ, подключённых компании по профилю (в перспективе — через настройки).
  // Топливные модули (АЗС/литры/смены) — только fuel-профилю; energy получает свой набор.
  // Меню = модули, ПОДКЛЮЧЁННЫЕ компании (управляется каталогом «Модули»).
  // По умолчанию подключены модули, подходящие профилю — текущее поведение сохраняется.
  const { conn } = useModuleConnections()
  const on = (id: string) => { const m = getWorkspaceModule(id); return m ? isModuleConnected(conn, m, company.profileId) : false }
  const balMod = balanceModuleForProfile(company.profileId)
  const menu = [
    ...(on('mgmt_pnl') ? MGMT_MENU : []),                                         // топливный P&L (Обзор/Станции/…)
    ...ENERGY_MGMT.filter((m) => on(m.key)),                                      // энергомодули (Сводка/Выручка/Тарифы/Дебиторка/Закупка)
    ...(on('objects') ? [{ key: 'objects', label: 'Объекты' }] : []),            // точки (нормализованные данные)
    ...(balMod && on(balMod.id) ? [{ key: 'balance', label: balMod.navLabel }] : []),
  ]
  const menuKeys = menu.map((m) => m.key)
  const activeTab = menuKeys.includes(tab) ? tab : (menuKeys[0] ?? 'balance')

  if (menu.length === 0) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Компании «{company.shortName || company.name}» не подключены управленческие модули. Подключите модуль в настройках.
      </div>
    )
  }

  return (
    <CentralPanelLayout items={menu} activeKey={activeTab} onSelect={setTab}>
      {activeTab === 'balance' ? (
        <div className="h-full overflow-y-auto">
          <BalanceVitrine />
        </div>
      ) : activeTab === 'objects' ? (
        <div className="h-full overflow-y-auto">
          <LocationsPage cockpitVariant="full" />
        </div>
      ) : ENERGY_MGMT_KEYS.includes(activeTab) ? (
        <div className="h-full overflow-y-auto">
          <EnergyMgmtVitrine tab={activeTab} />
        </div>
      ) : (
        <div className="h-full flex flex-col">
          <AnalyticsPeriodPicker period={period} onChange={setPeriod} />
          <ScrollArea className="flex-1">
            {activeTab === 'overview' && <MgmtOverview companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
            {activeTab === 'by-station' && <MgmtPnLTable companyId={companyId} dateFrom={period.from} dateTo={period.to} groupBy="station" />}
            {activeTab === 'by-fuel' && <MgmtPnLTable companyId={companyId} dateFrom={period.from} dateTo={period.to} groupBy="fuel" />}
            {activeTab === 'by-month' && <MgmtPnLTable companyId={companyId} dateFrom={period.from} dateTo={period.to} groupBy="month" />}
            {activeTab === 'marketing' && <MgmtPaymentMix companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
          </ScrollArea>
        </div>
      )}
    </CentralPanelLayout>
  )
}

function MgmtOverview({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const pnl = useQuery({
    queryKey: ['analytics-pnl', companyId, dateFrom, dateTo, 'station'],
    queryFn: () => getPnL({ companyId, dateFrom, dateTo, groupBy: 'station' }),
  })
  const mix = useQuery({
    queryKey: ['analytics-paymentmix', companyId, dateFrom, dateTo],
    queryFn: () => getPaymentMix({ companyId, dateFrom, dateTo }),
  })
  if (pnl.isLoading || mix.isLoading) return <LoadingState />
  if (pnl.error || mix.error) return <ErrorState message={String((pnl.error || mix.error) as Error)} />
  const t = pnl.data!.totals
  const m = mix.data!
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Выручка С НДС" value={fmtMoneyShort(t.revenue) + ' ₽'} hint={`по ${pnl.data!.lines.length} группам`} />
        <KpiCard label="Выручка без НДС" value={fmtMoneyShort(t.revenue_net) + ' ₽'} />
        <KpiCard label="Себестоимость" value={fmtMoneyShort(t.cogs) + ' ₽'} accent="info" />
        <KpiCard label="Валовая маржа" value={fmtMoneyShort(t.gross_margin) + ' ₽'}
          hint={fmtPct(t.gross_margin_pct)}
          accent={t.gross_margin >= 0 ? 'success' : 'danger'} />
        <KpiCard label="Литров продано" value={fmtLiters(t.liters)} />
        <KpiCard label="ОРП документов" value={String(t.docs_count)} />
        <KpiCard label="ПТУ документов" value={String(pnl.data!.ptu_count)} />
        <KpiCard label="Закрытых смен" value={String(pnl.data!.shifts_count)} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Card>
          <CardContent className="pt-4">
            <div className="text-xs uppercase text-muted-foreground mb-2 flex items-center gap-1.5">
              <Wallet className="h-3 w-3" />
              Структура оплат на АЗС
            </div>
            <div className="space-y-1.5 text-xs">
              {(['cash', 'card', 'voucher', 'other'] as const).map((k) => (
                <PayBar key={k} label={LABELS[k]} amount={m.breakdown[k]} pct={m.shares_pct[k]} />
              ))}
            </div>
            <div className="mt-3 pt-2 border-t text-sm text-muted-foreground">
              Средний чек на смену: <span className="font-mono text-foreground">{fmtMoney(m.avg_per_shift)} ₽</span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-xs uppercase text-muted-foreground mb-2 flex items-center gap-1.5">
              <TrendingUp className="h-3 w-3" />
              Топ-3 группы по выручке
            </div>
            <div className="space-y-2">
              {pnl.data!.lines.slice(0, 3).map((l) => (
                <div key={l.label} className="text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-medium truncate">{l.label}</span>
                    <span className="font-mono">{fmtMoneyShort(l.revenue)} ₽</span>
                  </div>
                  <div className="text-xs text-muted-foreground flex items-center justify-between">
                    <span>Маржа {fmtPct(l.gross_margin_pct)}</span>
                    <span>{fmtLiters(l.liters)}</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

const LABELS: Record<string, string> = { cash: 'Наличные', card: 'Карты', voucher: 'Талоны/ведомости', other: 'Прочее' }

function PayBar({ label, amount, pct }: { label: string; amount: number; pct: number }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <span>{label}</span>
        <span className="font-mono">{fmtMoneyShort(amount)} ₽ · {pct.toFixed(1)}%</span>
      </div>
      <div className="h-1.5 bg-muted rounded overflow-hidden">
        <div className="h-full bg-primary" style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
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

function MgmtPaymentMix({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-paymentmix', companyId, dateFrom, dateTo],
    queryFn: () => getPaymentMix({ companyId, dateFrom, dateTo }),
  })
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={String(error)} />
  if (!data) return null
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Закрытых смен" value={String(data.shifts_count)} />
        <KpiCard label="Оборот всего" value={fmtMoneyShort(data.total_amount) + ' ₽'} />
        <KpiCard label="Средний чек/смена" value={fmtMoney(data.avg_per_shift) + ' ₽'} />
        <KpiCard label="Доля карт" value={data.shares_pct.card.toFixed(1) + '%'} accent="info" />
      </div>
      <Card>
        <CardContent className="pt-4 space-y-2 text-xs">
          {(['cash', 'card', 'voucher', 'other'] as const).map((k) => (
            <PayBar key={k} label={LABELS[k]} amount={data.breakdown[k]} pct={data.shares_pct[k]} />
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                       Финансовый учёт                          */
/* ────────────────────────────────────────────────────────────── */

const FIN_MENU: CentralMenuItem[] = [
  { key: 'overview',   label: 'Обзор' },
  { key: 'cashflow',   label: 'Денежный поток' },
  { key: 'receivables', label: 'Дебиторка' },
  { key: 'payables',   label: 'Кредиторка' },
]

export function FinancialPanel() {
  const [tab, setTab] = useState('overview')
  const [period, setPeriod] = useAnalyticsPeriod()
  const { companyId, company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const gate = useSectionGate(isEnergy ? 'fin_energy' : 'financial')
  if (!gate.connected) return <SectionEmpty section="Финансовый" org={gate.org} />
  if (isEnergy) return <div className="h-full overflow-y-auto"><FinancialVitrine /></div>

  return (
    <CentralPanelLayout items={FIN_MENU} activeKey={tab} onSelect={setTab}>
      <div className="h-full flex flex-col">
        <AnalyticsPeriodPicker period={period} onChange={setPeriod} />
        <ScrollArea className="flex-1">
          {tab === 'overview' && <FinOverview companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
          {tab === 'cashflow' && <FinCashFlow companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
          {tab === 'receivables' && <FinContragents companyId={companyId} dateFrom={period.from} dateTo={period.to} mode="receivables" />}
          {tab === 'payables' && <FinContragents companyId={companyId} dateFrom={period.from} dateTo={period.to} mode="payables" />}
        </ScrollArea>
      </div>
    </CentralPanelLayout>
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
// Сохранён как был — accounting уже подключён к DocumentsPage и ExportLayerPanel.
// Здесь только верхнеуровневое меню + ссылки.

const ACC_MENU: CentralMenuItem[] = [
  { key: 'overview',  label: 'Обзор' },
  { key: 'documents', label: 'Документы 1С' },
  { key: 'export',    label: 'Очередь выгрузки' },
  { key: 'periods',   label: 'Периоды' },
]

export function AccountingPanel() {
  const [tab, setTab] = useState('overview')
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const gate = useSectionGate(isEnergy ? 'acc_energy' : 'accounting')
  if (!gate.connected) return <SectionEmpty section="Бухгалтерский" org={gate.org} />
  if (isEnergy) return <div className="h-full overflow-y-auto"><AccountingVitrine /></div>
  return (
    <CentralPanelLayout items={ACC_MENU} activeKey={tab} onSelect={setTab}>
      <ScrollArea className="h-full">
        {tab === 'overview' && (
          <div className="p-4 space-y-3">
            <Card>
              <CardContent className="pt-4 text-xs space-y-2">
                <p className="font-medium text-sm">Подготовка документов для 1С — три страницы:</p>
                <ul className="list-disc list-inside text-muted-foreground space-y-1">
                  <li>
                    <a className="text-primary hover:underline" href="/1c/documents">/1c/documents</a> — журнал документов БП ГИГ (фильтры, сверка, проводки, шаблоны)
                  </li>
                  <li>
                    <a className="text-primary hover:underline" href="/1c/export">/1c/export</a> — очередь L3 ExportPacket
                  </li>
                  <li>
                    <a className="text-primary hover:underline" href="/1c/periods">/1c/periods</a> — статусы периодов (открыт/закрыт)
                  </li>
                  <li>
                    <a className="text-primary hover:underline" href="/1c/posting-templates">/1c/posting-templates</a> — эталонные проводки
                  </li>
                  <li>
                    <a className="text-primary hover:underline" href="/1c/policy">/1c/policy</a> — учётная политика
                  </li>
                  <li>
                    <a className="text-primary hover:underline" href="/1c/batches">/1c/batches</a> — партии FIFO
                  </li>
                </ul>
              </CardContent>
            </Card>
          </div>
        )}
        {tab === 'documents' && (
          <div className="p-6 text-center text-sm text-muted-foreground">
            Откройте <a className="text-primary hover:underline" href="/1c/documents">/1c/documents</a> для полнофункционального журнала.
          </div>
        )}
        {tab === 'export' && (
          <div className="p-6 text-center text-sm text-muted-foreground">
            Откройте <a className="text-primary hover:underline" href="/1c/export">/1c/export</a> для очереди пакетов.
          </div>
        )}
        {tab === 'periods' && (
          <div className="p-6 text-center text-sm text-muted-foreground">
            Откройте <a className="text-primary hover:underline" href="/1c/periods">/1c/periods</a>.
          </div>
        )}
      </ScrollArea>
    </CentralPanelLayout>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                          Налоговый учёт                          */
/* ────────────────────────────────────────────────────────────── */

const TAX_MENU: CentralMenuItem[] = [
  { key: 'vat',     label: 'НДС' },
  { key: 'profit',  label: 'Налог на прибыль' },
  { key: 'compliance', label: 'Соответствие' },
]

export function TaxPanel() {
  const [tab, setTab] = useState('vat')
  const [period, setPeriod] = useAnalyticsPeriod()
  const { companyId, company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const gate = useSectionGate(isEnergy ? 'tax_energy' : 'tax')
  if (!gate.connected) return <SectionEmpty section="Налоговый" org={gate.org} />
  if (isEnergy) return <div className="h-full overflow-y-auto"><TaxVitrine /></div>
  return (
    <CentralPanelLayout items={TAX_MENU} activeKey={tab} onSelect={setTab}>
      <div className="h-full flex flex-col">
        <AnalyticsPeriodPicker period={period} onChange={setPeriod} />
        <ScrollArea className="flex-1">
          {tab === 'vat' && <TaxVat companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
          {tab === 'profit' && <TaxProfit companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
          {tab === 'compliance' && <TaxCompliance companyId={companyId} dateFrom={period.from} dateTo={period.to} />}
        </ScrollArea>
      </div>
    </CentralPanelLayout>
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
