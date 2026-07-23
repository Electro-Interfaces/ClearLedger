/**
 * Клиент API «Банк ЗУ» (/api/sites/*) — площадки под установку ЭЗС.
 *
 * Раздел «Управленческий» → группа «Площадки» (energy/РусГидро): девелоперский
 * пайплайн развития сети. НЕ путать с /equipment (склад железа).
 */
import { get, post, patch, upload } from './apiClient'

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
  /** Ведение (Волна 2): кто отвечает, что дальше и когда. */
  ownerName?: string | null
  nextAction?: string | null
  nextActionDue?: string | null
  lastTouchAt?: string | null
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

/** Пункт чек-листа гейта: `manual` — проверяется глазами, остальное — по полям. */
export interface GateItem { key: string; label: string; manual: boolean; done: boolean }
export interface GateState {
  stage: SiteStage; stageLabel: string; items: GateItem[]; done: number; total: number
}

export interface SiteDetail extends SiteRow {
  raw: Record<string, string>
  sourceSheet: string | null
  firstSeenAt: string | null
  lastSeenAt: string | null
  // ведение
  ownerUserId: string | null
  holdUntil: string | null
  gate: GateState
  manualFields: string[]
  // право на землю
  controlForm: string | null
  landCategory: string | null
  permittedUse: string | null
  encumbrances: string | null
  rentRate: number | null
  contractStart: string | null
  contractEnd: string | null
  // техприсоединение
  freePowerNum: number | null
  distanceToTpM: number | null
  tpCost: number | null
  tpTermMonths: number | null
  locationId: string | null
}

export interface SiteEvent {
  id: string
  kind: 'stage' | 'touch' | 'note' | 'edit' | 'import' | 'gate'
  text: string | null
  fromStage: string | null
  toStage: string | null
  fromLabel: string | null
  toLabel: string | null
  author: string | null
  createdAt: string | null
}

export interface SiteMember { id: string; name: string }

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
  /** Управляемость активной части: без ответственного, без шага, просрочено, забыто. */
  work: { noOwner: number; noNextAction: number; overdue: number; stale: number; staleDays: number }
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
  companyId: string; stage?: string; region?: string; search?: string
  ownerId?: string; overdue?: boolean; page?: number; pageSize?: number
}): Promise<SitesList> {
  return get('/api/sites', {
    company_id: p.companyId, stage: p.stage || undefined, region: p.region || undefined,
    search: p.search || undefined, owner_id: p.ownerId || undefined,
    overdue: p.overdue ? 1 : undefined,
    page: p.page ?? 1, page_size: p.pageSize ?? 300,
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

// ── Ведение площадки (Волна 2) ─────────────────────────────────────────────

/** Кого можно назначить ответственным (члены компании, без прав админа). */
export async function getSiteMembers(companyId: string): Promise<SiteMember[]> {
  return get('/api/sites/meta/members', { company_id: companyId })
}

/** Правка карточки. Изменённые поля станут «ручными» — импорт их не тронет. */
export async function patchSite(
  companyId: string, id: string, payload: Record<string, unknown>,
): Promise<{ changed: string[]; site: SiteDetail }> {
  return patch(`/api/sites/${id}?company_id=${companyId}`, payload)
}

/** Перевод по воронке. Незакрытый гейт не блокирует — возвращается в `missing`. */
export async function moveSiteStage(
  companyId: string, id: string, stage: SiteStage, reason?: string,
): Promise<{ moved: boolean; missing?: string[]; gate: GateState; site: SiteDetail }> {
  return post(`/api/sites/${id}/stage?company_id=${companyId}`, { stage, reason })
}

/** Отметка пункта гейта, который проверяется глазами. */
export async function markSiteGate(
  companyId: string, id: string, key: string, done: boolean,
): Promise<{ ok: boolean; gate?: GateState; message?: string }> {
  return post(`/api/sites/${id}/gate?company_id=${companyId}`, { key, done })
}

export async function getSiteEvents(companyId: string, id: string): Promise<SiteEvent[]> {
  return get(`/api/sites/${id}/events`, { company_id: companyId })
}

export async function addSiteEvent(
  companyId: string, id: string, text: string, kind: 'touch' | 'note' = 'touch',
): Promise<{ id: string }> {
  return post(`/api/sites/${id}/events?company_id=${companyId}`, { text, kind })
}

/** Завести площадку руками — лид, пришедший не файлом. */
export async function createSite(
  companyId: string, payload: Record<string, unknown>,
): Promise<SiteDetail> {
  return post(`/api/sites?company_id=${companyId}`, payload)
}

// ── Приоритеты и экономика (Волна 3) ───────────────────────────────────────

/** Квадрант решения. `need_data` — не приговор, а «сначала добрать факты». */
export type Quadrant = 'do_now' | 'unblock' | 'option' | 'drop' | 'need_data'

export const QUADRANT_META: Record<Quadrant, { label: string; hint: string; cls: string; dot: string }> = {
  do_now: { label: 'Делать сейчас', hint: 'спрос есть и реализуемо', cls: 'border-emerald-400/50 text-emerald-600 dark:text-emerald-300/80', dot: 'bg-emerald-500' },
  unblock: { label: 'Расшивать узкое место', hint: 'место хорошее, мешает техника или право', cls: 'border-amber-400/50 text-amber-600 dark:text-amber-300/80', dot: 'bg-amber-500' },
  option: { label: 'Дешёвый опцион', hint: 'сделать легко, но спрос слабый', cls: 'border-sky-400/50 text-sky-600 dark:text-sky-300/80', dot: 'bg-sky-500' },
  drop: { label: 'Кандидат на отказ', hint: 'и спрос слабый, и делать тяжело', cls: 'border-red-400/50 text-red-600 dark:text-red-400/80', dot: 'bg-red-400' },
  need_data: { label: 'Не хватает данных', hint: 'сначала добрать факты, потом решать', cls: 'border-zinc-500/60 text-zinc-500', dot: 'bg-zinc-400' },
}

export interface MatrixItem {
  id: string
  stage: SiteStage
  stageLabel: string
  region: string | null
  city: string | null
  address: string | null
  owner: string | null
  attract: number | null
  feasible: number | null
  confidence: number
  quadrant: Quadrant
  nearestStationKm: number | null
  cannibalization: boolean
  unknown: string[]
}

export interface SitesMatrix {
  total: number
  quadrants: { key: Quadrant; label: string; hint: string; count: number }[]
  items: MatrixItem[]
  benchmark: {
    network: { kwhMonth: number | null; kwhP75: number | null; tariff: number | null; stations: number }
    byRegion: Record<string, { kwhMonth: number | null; kwhP75: number | null; tariff: number | null; stations: number }>
    months: number
  }
  thresholds: { cannibalKm: number; nearKm: number; gapKm: number }
}

export interface SitesGaps {
  regions: { region: string; stations: number; sites: number }[]
  networkNoPipeline: { region: string; stations: number }[]
  pipelineNoNetwork: { region: string; sites: number }[]
  cannibalization: { id: string; region: string | null; city: string | null; address: string | null; stage: SiteStage; stageLabel: string; km: number }[]
  withoutCoords: number
  thresholds: { cannibalKm: number; gapKm: number }
}

export interface SiteScenario {
  kwhMonth: number
  revenueMonth: number
  energyCostMonth: number
  marginMonth: number
  paybackMonths: number | null
}

export interface SiteEconomics {
  ok: boolean
  message?: string
  tariff?: number
  inputPrice?: number
  marginPerKwh?: number
  rentMonth?: number
  capex?: number | null
  base?: SiteScenario
  good?: SiteScenario
  assumptions: string[]
  benchmarkSource?: 'region' | 'network'
}

export async function getSitesMatrix(
  companyId: string, p?: { stage?: string; region?: string },
): Promise<SitesMatrix> {
  return get('/api/sites/analysis/matrix', {
    company_id: companyId, stage: p?.stage || undefined, region: p?.region || undefined,
  })
}

export async function getSitesGaps(companyId: string): Promise<SitesGaps> {
  return get('/api/sites/analysis/gaps', { company_id: companyId })
}

export async function getSitesMapPoints(
  companyId: string,
): Promise<{ points: (MatrixItem & { lat: number; lon: number })[]; thresholds: SitesMatrix['thresholds'] }> {
  return get('/api/sites/analysis/map', { company_id: companyId })
}

export async function getSiteEconomics(
  companyId: string, id: string,
): Promise<{ economics: SiteEconomics; score: { attract: number | null; feasible: number | null; confidence: number; quadrant: Quadrant; factors: { attract: { name: string; score: number }[]; feasible: { name: string; score: number }[] }; unknown: string[]; nearestStationKm: number | null; cannibalization: boolean } }> {
  return get(`/api/sites/${id}/economics`, { company_id: companyId })
}
