/**
 * Клиент API «Банк ЗУ» (/api/sites/*) — площадки под установку ЭЗС.
 *
 * Раздел «Управленческий» → группа «Площадки» (energy/РусГидро): девелоперский
 * пайплайн развития сети. НЕ путать с /equipment (склад железа).
 */
import { get, upload } from './apiClient'

export type SiteStage = 'prospect' | 'in_work' | 'archive'

export const STAGE_META: Record<SiteStage, { label: string; cls: string; dot: string }> = {
  prospect: { label: 'В проработке', cls: 'border-blue-400/50 text-blue-600 dark:text-blue-300/80', dot: 'bg-blue-500' },
  in_work: { label: 'В работе', cls: 'border-amber-400/50 text-amber-600 dark:text-amber-300/80', dot: 'bg-amber-500' },
  archive: { label: 'В архиве', cls: 'border-zinc-600 text-zinc-500', dot: 'bg-zinc-500' },
}

export interface SiteRow {
  id: string
  stage: SiteStage
  stageLabel: string
  statusRaw: string | null
  receivedDate: string | null
  region: string | null
  city: string | null
  address: string | null
  fullAddress: string | null
  placeKind: string | null
  installPlace: string | null
  route: string | null
  lat: number | null
  lon: number | null
  mapUrl: string | null
  owner: string | null
  brand: string | null
  areaM2: number | null
  ownership: string | null
  freePowerKwt: string | null
  connectionCost: number | null
  rentCostMonth: number | null
  plannedPowerKwt: number | null
  plannedEzsCount: number | null
  portsGbt: string | null
  portsCcs: string | null
  portsChademo: string | null
  portsType: string | null
  supplier: string | null
  contractor: string | null
  tuStatus: string | null
  techConnType: string | null
  dopService: string | null
  comment: string | null
}

export interface SiteDetail extends SiteRow {
  raw: Record<string, string>
  sourceSheet: string | null
}

export interface SitesOverview {
  total: number
  byStage: { stage: SiteStage; label: string; count: number }[]
  byRegion: { region: string; count: number }[]
  withCoords: number
  plannedEzs: number
  plannedPowerKwt: number
  withKnownCost: number
  connectionCostSum: number
}

export interface SitesList {
  total: number
  page: number
  pageSize: number
  items: SiteRow[]
}

export interface SitesImportReport {
  dryRun: boolean
  total: number
  withCoords: number
  sheets: { sheet: string; stage: string; rows: number; note?: string }[]
  unknownSheets: string[]
}

export async function getSitesOverview(companyId: string): Promise<SitesOverview> {
  return get('/api/sites/overview', { company_id: companyId })
}

export async function getSites(p: {
  companyId: string; stage?: string; region?: string; search?: string; page?: number; pageSize?: number
}): Promise<SitesList> {
  return get('/api/sites', {
    company_id: p.companyId, stage: p.stage || undefined, region: p.region || undefined,
    search: p.search || undefined, page: p.page ?? 1, page_size: p.pageSize ?? 300,
  })
}

export async function getSite(companyId: string, id: string): Promise<SiteDetail> {
  return get(`/api/sites/${id}`, { company_id: companyId })
}

export async function importSitesXlsx(companyId: string, file: File, dryRun: boolean): Promise<SitesImportReport> {
  const fd = new FormData()
  fd.append('file', file)
  return upload(`/api/sites/import?company_id=${companyId}&dry_run=${dryRun}`, fd)
}
