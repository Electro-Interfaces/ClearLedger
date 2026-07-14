/**
 * Тонкий роутер раздела «Продажи» ГИГ (fuel): раздаёт подразделы MGMT_MENU по
 * панелям. Группы меню: Сеть · Аналитика · Коммерция · Товародвижение.
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
import { ReceiptsSection } from '@/components/fuel/ReceiptsSection'

export function FuelSalesRouter({ tab, companyId, dateFrom, dateTo, stationCode }: {
  tab: string; companyId: string; dateFrom: string; dateTo: string; stationCode: string
}) {
  const p = { companyId, dateFrom, dateTo }
  switch (tab) {
    // Сеть
    case 'overview':       return <FuelOverviewPanel {...p} />
    case 'map':            return <FuelMapPanel {...p} />
    // Аналитика
    case 'fills':          return <FuelFillsPanel {...p} />
    case 'transactions':   return <FuelTransactionsPanel {...p} />
    case 'channels':       return <SalesChannelsPanel {...p} />
    case 'online-orders':  return <OnlineOrdersPanel {...p} stationCode={stationCode} />
    // Коммерция
    case 'fuel-tariffs':   return <FuelTariffsPanel {...p} />
    case 'fuel-corporate': return <FuelCorporatePanel {...p} />
    case 'fuel-retail':    return <FuelRetailPanel {...p} />
    // Товародвижение
    case 'margin':         return <MarginDecisionPanel {...p} />
    case 'purchases':      return <ReceiptsSection />
    case 'tanks':          return <FuelBalancePanel {...p} />
    default:               return null
  }
}
