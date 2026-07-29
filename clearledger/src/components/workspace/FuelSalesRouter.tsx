/**
 * Тонкий роутер приложения «Топливо» (fuel, ГИГ): раздаёт пункты MGMT_MENU по
 * панелям. Разделы: Сеть · Аналитика · Коммерция · Товародвижение — каждый стоит в
 * рельсе приложения, роутер один на все четыре (ключ пункта однозначен).
 *
 * Вынесен из ManagementPanel (AccountingPanels.tsx) по прецеденту
 * ChargeSalesRouter — правка внутренностей панелей не задевает диспетчеризацию.
 */
import { FuelOverviewPanel } from './FuelOverviewPanel'
import { FuelMapPanel } from './FuelMapPanel'
import { FuelFillsPanel } from './FuelFillsPanel'
import { FuelTransactionsPanel } from './FuelTransactionsPanel'
import { SalesChannelsPanel } from './SalesChannelsPanel'
import { OnlineOrdersPanel } from './OnlineOrdersPanel'
import { FuelTariffsPanel } from './FuelTariffsPanel'
import { FuelCorporatePanel } from './FuelCorporatePanel'
import { FuelRetailPanel } from './FuelRetailPanel'
import { MarginDecisionPanel } from './MarginDecisionPanel'
import { FuelBalancePanel } from './FuelBalancePanel'
import {
  FuelAbcXyzPanel, FuelClientsPanel, FuelPumpsPanel, FuelVisitsPanel,
} from './FuelNetworkPanels'
import { ReceiptsSection } from '@/components/fuel/ReceiptsSection'

export function FuelSalesRouter({ tab, companyId, dateFrom, dateTo, stationCode }: {
  tab: string; companyId: string; dateFrom: string; dateTo: string; stationCode: string
}) {
  const p = { companyId, dateFrom, dateTo }
  switch (tab) {
    // Сеть
    case 'overview':       return <FuelOverviewPanel {...p} />
    case 'map':            return <FuelMapPanel {...p} />
    case 'pumps':          return <FuelPumpsPanel {...p} />
    case 'abcxyz':         return <FuelAbcXyzPanel {...p} />
    // Аналитика
    case 'fills':          return <FuelFillsPanel {...p} />
    case 'visits':         return <FuelVisitsPanel {...p} />
    case 'transactions':   return <FuelTransactionsPanel {...p} />
    case 'channels':       return <SalesChannelsPanel {...p} />
    case 'online-orders':  return <OnlineOrdersPanel {...p} stationCode={stationCode} />
    // Коммерция
    case 'fuel-tariffs':   return <FuelTariffsPanel {...p} />
    case 'fuel-corporate': return <FuelCorporatePanel {...p} />
    case 'fuel-retail':    return <FuelRetailPanel {...p} />
    case 'clients':        return <FuelClientsPanel {...p} />
    // Товародвижение. «Приёмка», «Расхождения» и «Инвентаризация» — те же экраны,
    // что раньше были табами «Контроля баланса»: панель одна (общий фильтр станций и
    // топлива, шапка баланса), различается набором видов (см. FuelBalancePanel).
    case 'margin':         return <MarginDecisionPanel {...p} />
    case 'purchases':      return <ReceiptsSection />
    case 'intake':         return <FuelBalancePanel {...p} view="intake" />
    case 'tanks':          return <FuelBalancePanel {...p} />
    case 'variances':      return <FuelBalancePanel {...p} view="variances" />
    case 'inventory':      return <FuelBalancePanel {...p} view="inventory" />
    default:               return null
  }
}
