/**
 * Клиент API «Банк ЗУ» (/api/sites/*) — площадки под установку ЭЗС.
 *
 * Раздел «Управленческий» → группа «Площадки» (energy/РусГидро): девелоперский
 * пайплайн развития сети. НЕ путать с /equipment (склад железа).
 */
import { get, upload } from './apiClient'

/**
 * Стадии — воронка подбора недвижимости с гейтами. Порядок = порядок гейтов;
 * дешёвые проверки раньше дорогих. Обоснование — docs/SITES_LAND_BANK_BLUEPRINT.md.
 */
export type SiteStage =
  | 'lead' | 'screening' | 'negotiation' | 'dd' | 'decision'
  | 'contracting' | 'construction' | 'live' | 'on_hold' | 'archive'

/** Активная часть воронки, в порядке движения. */
export const FUNNEL_STAGES: SiteStage[] = [
  'lead', 'screening', 'negotiation', 'dd', 'decision', 'contracting', 'construction', 'live',
]

// Цвет по семантике: холодный на входе → тёплый в работе → зелёный на выходе,
// нейтральный для паузы и архива (см. палитру badges в CLAUDE.md).
export const STAGE_META: Record<SiteStage, { label: string; hint: string; cls: string; dot: string }> = {
  lead: { label: 'Лид', hint: 'адрес и источник', cls: 'border-slate-400/50 text-slate-600 dark:text-slate-300/80', dot: 'bg-slate-400' },
  screening: { label: 'Скрининг', hint: 'быстрый отсев без затрат', cls: 'border-sky-400/50 text-sky-600 dark:text-sky-300/80', dot: 'bg-sky-500' },
  negotiation: { label: 'Переговоры', hint: 'выход на собственника, условия', cls: 'border-blue-400/50 text-blue-600 dark:text-blue-300/80', dot: 'bg-blue-500' },
  dd: { label: 'Проработка', hint: 'ТУ · право · коммерция', cls: 'border-amber-400/50 text-amber-600 dark:text-amber-300/80', dot: 'bg-amber-500' },
  decision: { label: 'Решение', hint: 'экономика и вердикт', cls: 'border-orange-400/50 text-orange-600 dark:text-orange-300/80', dot: 'bg-orange-500' },
  contracting: { label: 'Оформление', hint: 'договор / сервитут', cls: 'border-violet-400/50 text-violet-600 dark:text-violet-300/80', dot: 'bg-violet-500' },
  construction: { label: 'В стройке', hint: 'ПИР, СМР, техприсоединение', cls: 'border-teal-400/50 text-teal-600 dark:text-teal-300/80', dot: 'bg-teal-500' },
  live: { label: 'Введена', hint: 'объект работает в сети', cls: 'bg-emerald-600/80 text-white border-transparent', dot: 'bg-emerald-500' },
  on_hold: { label: 'Заморожена', hint: 'пауза с датой пересмотра', cls: 'border-zinc-500/60 text-zinc-500', dot: 'bg-zinc-400' },
  archive: { label: 'Архив', hint: 'отклонена, с причиной', cls: 'border-zinc-600 text-zinc-500', dot: 'bg-zinc-500' },
}

export interface SiteRow {
  id: string
  stage: SiteStage
  stageLabel: string
  stageSince: string | null
  prevStage: SiteStage | null
  archiveReason: string | null
  cadastralNo: string | null
  statusRaw: string | null
  receivedDate: string | null
  region: string | null
  regionRaw: string | null
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
  firstSeenAt: string | null
  lastSeenAt: string | null
}

export interface SitesOverview {
  total: number
  active: number
  onHold: number
  archived: number
  funnel: { stage: SiteStage; label: string; hint: string; count: number }[]
  byStage: { stage: SiteStage; label: string; hint: string; count: number }[]
  byRegion: { region: string; count: number }[]
  withCoords: number
  plannedEzs: number
  plannedPowerKwt: number
  withKnownCost: number
  connectionCostSum: number
  quality: { withCadastral: number; regionMatched: number; withCoords: number }
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
  /** UPSERT: файл дополняет банк, а не заменяет его. */
  created: number
  updated: number
  unchanged: number
  stageMoved: number
  reactivated: number
  archived: number
  withCadastral: number
  /** Строки без адреса, координат и собственника — опознать место нечем. */
  skippedNoKey: number
  /** Две строки файла на одну площадку. */
  fileDuplicates: { sheet: string; row: number; key: string; address: string; first: string }[]
  /** Координаты в 50 м от известной площадки, но адрес другой — вероятная ошибка координат. */
  nearConflicts: { sheet: string; row: number; address: string; near: string }[]
  /** Регионы, которых нет в справочнике сети (сеть туда ещё не пришла). */
  regionsUnmatched: { value: string; count: number }[]
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
