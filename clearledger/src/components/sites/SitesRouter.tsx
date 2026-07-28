/**
 * Роутер раздела «Проекты» — жизненный цикл ЭЗС от участка до эксплуатации.
 *
 * Портфель: обзор по этапам и реестр проектов.
 * Подбор: воронка, банк площадок, приоритеты, карта — первый этап проекта.
 * Реализация: техприсоединение (оно определяет срок проекта) и мост в бухгалтерию.
 */
import { SitesOverviewPanel } from './SitesOverviewPanel'
import { SitesListPanel } from './SitesListPanel'
import { SitesPriorityPanel } from './SitesPriorityPanel'
import { SitesMapPanel } from './SitesMapPanel'
import { ProjectsPortfolioPanel } from './ProjectsPortfolioPanel'
import { ProjectWorkspacePanel } from './ProjectWorkspacePanel'
import { TechConnectionsPanel } from './TechConnectionsPanel'
import { ProjectEquipmentPanel } from './ProjectEquipmentPanel'
import { AwaitingAccountingPanel } from './AwaitingAccountingPanel'
import { ProjectBudgetPanel } from './ProjectBudgetPanel'

export function SitesRouter({ tab, companyId }: { tab: string; companyId: string }) {
  // Один пункт: без выбранного проекта — реестр, с выбранным — рабочий экран.
  if (tab === 'pr_project') return <ProjectWorkspacePanel companyId={companyId} />
  if (tab === 'pr_tp') return <TechConnectionsPanel companyId={companyId} />
  if (tab === 'pr_equipment') return <ProjectEquipmentPanel companyId={companyId} />
  if (tab === 'pr_budget') return <ProjectBudgetPanel companyId={companyId} />
  if (tab === 'pr_accounting') return <AwaitingAccountingPanel companyId={companyId} />
  if (tab === 'sites_overview') return <SitesOverviewPanel companyId={companyId} />
  if (tab === 'sites_list') return <SitesListPanel companyId={companyId} />
  if (tab === 'sites_priority') return <SitesPriorityPanel companyId={companyId} />
  if (tab === 'sites_map') return <SitesMapPanel companyId={companyId} />
  return <ProjectsPortfolioPanel companyId={companyId} />
}
