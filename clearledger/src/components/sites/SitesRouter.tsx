/**
 * Роутер раздела «Площадки (Банк ЗУ)» — девелоперский пайплайн ЭЗС.
 * sites_overview → сводка воронки; sites_list → реестр; sites_priority →
 * матрица решений; sites_map → площадки поверх действующей сети.
 */
import { SitesOverviewPanel } from './SitesOverviewPanel'
import { SitesListPanel } from './SitesListPanel'
import { SitesPriorityPanel } from './SitesPriorityPanel'
import { SitesMapPanel } from './SitesMapPanel'

export function SitesRouter({ tab, companyId }: { tab: string; companyId: string }) {
  if (tab === 'sites_list') return <SitesListPanel companyId={companyId} />
  if (tab === 'sites_priority') return <SitesPriorityPanel companyId={companyId} />
  if (tab === 'sites_map') return <SitesMapPanel companyId={companyId} />
  return <SitesOverviewPanel companyId={companyId} />
}
