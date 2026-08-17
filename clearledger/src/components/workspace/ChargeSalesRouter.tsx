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
import { ChargeReconciliationPanel } from './ChargeReconciliationPanel'
import { PaymentsPanel } from './PaymentsPanel'
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
  let content = null
  switch (tab) {
    case 'cs_dashboard':   content = <OverviewDashboardPanel {...p} />; break
    case 'cs_map':         content = <ChargeMapPanel {...p} />; break
    case 'cs_trend':       content = <ChargeTrendPanel {...p} />; break
    case 'cs_abcxyz':      content = <AbcXyzPanel {...p} />; break
    case 'cs_list':        content = <ChargeListPanel {...p} />; break
    // Виды сессий — свои пункты раздела «Сессии»; `cs_sessions` — старая ссылка.
    case 'cs_breakdown':
    case 'cs_time':
    case 'cs_dynamics':
    case 'cs_compare':
    case 'cs_sessions':
    case 'cs_reliability': content = <SessionsPanel tab={tab} {...p} />; break
    case 'cs_clients':     content = <TariffsPanel {...p} />; break
    case 'cs_corporate':   content = <CorporatePanel {...p} />; break
    case 'cs_retail':      content = <RetailPanel {...p} />; break
    case 'cs_segments':    content = <RetailPanel {...p} group="segments" />; break
    case 'cs_payments':    content = <PaymentsPanel {...p} />; break
    case 'cs_recon':       content = <ChargeReconciliationPanel {...p} />; break
    default:               break
  }
  return <div data-sales-surface className="h-full min-w-0">{content}</div>
}
