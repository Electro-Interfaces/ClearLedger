/**
 * Тонкий роутер продукта «Продажи» (energy): раздаёт пункты (cs_*) по панелям.
 * Пункт живёт в одном из трёх разделов («Сеть», «Сессии», «Коммерция»), но какая
 * панель его рисует — от раздела не зависит, поэтому роутер один.
 *
 * Листовые панели — напрямую; виды сессий и «Надёжность» (нужен общий стейт типа
 * клиента ФЛ/ЮЛ) — в `SessionsPanel`.
 *
 * Вынесен из монолита `ChargeSessionsPanel.tsx`, чтобы правка внутренностей
 * «Сессий» не задевала диспетчеризацию всех подразделов (и наоборот).
 */
import { CorporatePanel } from './CorporatePanel'
import { RetailPanel } from './RetailPanel'
import { TariffsPanel } from './TariffsPanel'
import { OverviewDashboardPanel } from './OverviewDashboardPanel'
import { ChargeListPanel } from './ChargeListPanel'
import { ChargeMapPanel } from './ChargeMapPanel'
import { ChargeTrendPanel } from './ChargeTrendPanel'
import { AbcXyzPanel } from './AbcXyzPanel'
import { SessionsPanel } from './ChargeSessionsPanel'

export function ChargeSalesRouter({ tab, companyId, dateFrom, dateTo }: {
  tab: string; companyId: string; dateFrom: string; dateTo: string
}) {
  const p = { companyId, dateFrom, dateTo }
  switch (tab) {
    case 'cs_dashboard':   return <OverviewDashboardPanel {...p} />
    case 'cs_map':         return <ChargeMapPanel {...p} />
    case 'cs_trend':       return <ChargeTrendPanel {...p} />
    case 'cs_abcxyz':      return <AbcXyzPanel {...p} />
    case 'cs_list':        return <ChargeListPanel {...p} />
    // Виды сессий — свои пункты раздела «Сессии»; `cs_sessions` — старая ссылка.
    case 'cs_breakdown':
    case 'cs_time':
    case 'cs_dynamics':
    case 'cs_compare':
    case 'cs_sessions':
    case 'cs_reliability': return <SessionsPanel tab={tab} {...p} />
    case 'cs_clients':     return <TariffsPanel {...p} />
    case 'cs_corporate':   return <CorporatePanel {...p} />
    case 'cs_retail':      return <RetailPanel {...p} />
    case 'cs_segments':    return <RetailPanel {...p} group="segments" />
    default:               return null
  }
}
