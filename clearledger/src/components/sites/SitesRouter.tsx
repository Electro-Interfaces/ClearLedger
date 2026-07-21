/**
 * Роутер раздела «Площадки (Банк ЗУ)» — девелоперский пайплайн ЭЗС.
 * sites_overview → сводка пайплайна; sites_list → реестр площадок.
 */
import { SitesOverviewPanel } from './SitesOverviewPanel'
import { SitesListPanel } from './SitesListPanel'

export function SitesRouter({ tab, companyId }: { tab: string; companyId: string }) {
  if (tab === 'sites_list') return <SitesListPanel companyId={companyId} />
  return <SitesOverviewPanel companyId={companyId} />
}
