/**
 * Клиент API «Банк ЗУ» (/api/sites/*) — площадки под установку ЭЗС.
 *
 * Раздел «Управленческий» → группа «Площадки» (energy/РусГидро): девелоперский
 * пайплайн развития сети. НЕ путать с /equipment (склад железа).
 */
import { get, post, patch, put, del, upload } from './apiClient'

/**
 * Стадии — воронка подбора недвижимости с гейтами. Порядок = порядок гейтов;
 * дешёвые проверки раньше дорогих. Обоснование — docs/SITES_LAND_BANK_BLUEPRINT.md.
 */
export type SiteStage =
  | 'lead' | 'screening' | 'negotiation' | 'dd' | 'decision'
  | 'contracting' | 'construction' | 'commissioning' | 'live' | 'on_hold' | 'archive'

/** Активная часть воронки, в порядке движения. */
export const FUNNEL_STAGES: SiteStage[] = [
  'lead', 'screening', 'negotiation', 'dd', 'decision',
  'contracting', 'construction', 'commissioning', 'live',
]

// Цвет по семантике: холодный на входе → тёплый в работе → зелёный на выходе,
// нейтральный для паузы и архива (см. палитру badges в CLAUDE.md).
export const STAGE_META: Record<SiteStage, { label: string; hint: string; cls: string; dot: string }> = {
  lead: { label: 'Лид', hint: 'адрес и источник', cls: 'border-slate-400/50 text-slate-600 dark:text-slate-300/80', dot: 'bg-slate-400' },
  screening: { label: 'Скрининг', hint: 'быстрый отсев без затрат', cls: 'border-sky-400/50 text-sky-600 dark:text-sky-300/80', dot: 'bg-sky-500' },
  negotiation: { label: 'Переговоры', hint: 'выход на собственника, условия', cls: 'border-blue-400/50 text-blue-600 dark:text-blue-300/80', dot: 'bg-blue-500' },
  dd: { label: 'Проработка', hint: 'ТУ · право · коммерция', cls: 'border-amber-400/50 text-amber-600 dark:text-amber-300/80', dot: 'bg-amber-500' },
  decision: { label: 'Решение', hint: 'экономика и вердикт', cls: 'border-orange-400/50 text-orange-600 dark:text-orange-300/80', dot: 'bg-orange-500' },
  contracting: { label: 'Оформление земли', hint: 'договор / сервитут / разрешение', cls: 'border-violet-400/50 text-violet-600 dark:text-violet-300/80', dot: 'bg-violet-500' },
  construction: { label: 'Реализация', hint: 'присоединение ‖ оборудование ‖ монтаж', cls: 'border-teal-400/50 text-teal-600 dark:text-teal-300/80', dot: 'bg-teal-500' },
  commissioning: { label: 'Пусконаладка', hint: 'пусконаладка и приёмка', cls: 'border-cyan-400/50 text-cyan-600 dark:text-cyan-300/80', dot: 'bg-cyan-500' },
  live: { label: 'В эксплуатации', hint: 'объект работает в сети', cls: 'bg-emerald-600/80 text-white border-transparent', dot: 'bg-emerald-500' },
  on_hold: { label: 'Заморожен', hint: 'пауза с датой пересмотра', cls: 'border-zinc-500/60 text-zinc-500', dot: 'bg-zinc-400' },
  archive: { label: 'Архив', hint: 'отклонён, с причиной', cls: 'border-zinc-600 text-zinc-500', dot: 'bg-zinc-500' },
}

export interface SiteRow {
  id: string
  projectNo?: string | null
  title?: string | null
  phase?: string | null
  phaseLabel?: string | null
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
export interface GateItem { key: string; label: string; manual: boolean; done: boolean; required: boolean; doc: string | null; equipment?: boolean }
export interface GateState {
  stage: SiteStage; stageLabel: string; items: GateItem[]; done: number; total: number
  /** Обязательные незакрытые пункты — они держат переход вперёд. */
  blocking: string[]
  canAdvance: boolean
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
  ownerId?: string; overdue?: boolean; risk?: string; page?: number; pageSize?: number
}): Promise<SitesList> {
  return get('/api/sites', {
    company_id: p.companyId, stage: p.stage || undefined, region: p.region || undefined,
    search: p.search || undefined, owner_id: p.ownerId || undefined,
    overdue: p.overdue ? 1 : undefined, risk: p.risk || undefined,
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
  companyId: string, id: string, stage: SiteStage, reason?: string, override?: boolean,
): Promise<{
  moved: boolean; blocked?: boolean; blocking?: string[]; message?: string
  mayOverride?: boolean; overridden?: boolean; missing?: string[]
  gate: GateState; site?: SiteDetail
}> {
  return post(`/api/sites/${id}/stage?company_id=${companyId}`, { stage, reason, override })
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
  projectNo: string | null
  title: string | null
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

// ── Проект: этапы, документы, присоединение, бюджет, учёт (Волны 4–8) ──────

export const PHASE_META: Record<string, { label: string; cls: string; dot: string }> = {
  select: { label: 'Подбор', cls: 'border-blue-400/50 text-blue-600 dark:text-blue-300/80', dot: 'bg-blue-500' },
  land: { label: 'Земля', cls: 'border-violet-400/50 text-violet-600 dark:text-violet-300/80', dot: 'bg-violet-500' },
  build: { label: 'Реализация', cls: 'border-amber-400/50 text-amber-600 dark:text-amber-300/80', dot: 'bg-amber-500' },
  operate: { label: 'Эксплуатация', cls: 'bg-emerald-600/80 text-white border-transparent', dot: 'bg-emerald-500' },
  closed: { label: 'Не в работе', cls: 'border-zinc-600 text-zinc-500', dot: 'bg-zinc-500' },
}

export interface SiteDoc {
  id: string; kind: string; kindLabel: string; title: string | null; note: string | null
  stage: string | null; stageLabel: string | null
  fileId: string | null; fileName: string | null; fileSize: number | null
  uploadedBy: string | null; createdAt: string | null
}

export interface TechConnection {
  id: string; siteId: string; status: string; statusLabel: string
  gridOperator: string | null
  applicationNo: string | null; applicationDate: string | null
  specsNo: string | null; specsDate: string | null
  contractNo: string | null; contractDate: string | null
  powerKwt: number | null; voltage: string | null; cost: number | null
  dueDate: string | null; doneDate: string | null
  needsReconstruction: boolean | null; note: string | null; overdue: boolean
  // в реестре присоединений добавляются поля проекта
  projectNo?: string | null; title?: string | null; region?: string | null
  city?: string | null; address?: string | null; stage?: string; stageLabel?: string
}

export interface SiteEquipment {
  id: string; siteId: string; status: string; statusLabel: string
  title: string | null; manufacturer: string | null; powerKwt: number | null
  connectors: string | null; qty: number; supplier: string | null; price: number | null
  orderDate: string | null; dueDate: string | null
  suppliedDate: string | null; installedDate: string | null
  note: string | null; overdue: boolean
  projectNo?: string | null; projectTitle?: string | null; city?: string | null
  address?: string | null; stage?: string; stageLabel?: string
}

export interface SiteCost {
  id: string; kind: string; kindLabel: string; title: string | null
  plan: number | null; fact: number | null; docRef: string | null; note: string | null
}

export interface SubsidyCheck {
  planned: boolean; amount: number | null
  items: { key: string; label: string; done: boolean; value: string | null }[]
  done: number; total: number; eligible: boolean
  commissionedOn: string | null; obligationUntil: string | null; obligationYears: number
}

export interface ProjectContext {
  phase: string
  phases: { key: string; label: string; hint: string; stages: { stage: SiteStage; label: string }[] }[]
  techConnection: TechConnection | null
  equipment: { items: SiteEquipment[]; priceTotal: number; allSupplied: boolean; allInstalled: boolean }
  costs: { items: SiteCost[]; planTotal: number; factTotal: number }
  subsidy: SubsidyCheck
  contract: { id: string; number: string; date: string; basis: string | null; validUntil: string | null; type: string | null } | null
  location: { id: string; name: string; code: string; status: string | null } | null
  docKinds: { key: string; label: string }[]
  tcStatuses: { key: string; label: string }[]
  eqStatuses: { key: string; label: string }[]
  costKinds: { key: string; label: string }[]
}

export interface Portfolio {
  phases: { key: string; label: string; hint: string; count: number
            stages: { stage: SiteStage; label: string; count: number }[] }[]
  active: number; total: number; realized: number
  budget: { plan: number; fact: number }
  techConnections: { total: number; done: number; overdue: number }
  equipment: { total: number; supplied: number; overdue: number }
  docs: number
}

export interface AwaitingAccounting {
  contractMissing: { id: string; projectNo: string | null; title: string | null; region: string | null; city: string | null; address: string | null; stage: string; stageLabel: string }[]
  locationMissing: AwaitingAccounting['contractMissing']
  supplyMissing: { id: string; projectNo: string | null; city: string | null; address: string | null }[]
}


/** Рабочий обзор портфеля: что горит, где затык, когда станции, что изменилось. */
export interface PortfolioOverview {
  active: number
  total: number
  live: number
  archived: number
  onHold: number
  /** Проекты со сорванным сроком (шаг, ТП, поставка). */
  atRisk: number
  attention: { key: string; label: string; count: number; hint: string; filter: string }[]
  attentionAll: PortfolioOverview['attention']
  funnel: {
    stage: SiteStage; label: string; phase: string | null; count: number
    medianDays: number; visited: number; advanced: number
    conversion: number | null; stuck: number
  }[]
  bottleneck: PortfolioOverview['funnel'][number] | null
  forecast: { bucket: string; count: number }[]
  commissioned: { bucket: string; count: number }[]
  movement: {
    added_30: number; added_90: number; moved_30: number
    archived_30: number; live_90: number; touches_30: number
  }
  owners: { owner: string; projects: number; overdue: number }[]
  budget: { plan: number; fact: number; sites: number; equipment: number }
  phases: { key: string; label: string; hint: string; count: number }[]
}

export async function getPortfolioOverview(companyId: string): Promise<PortfolioOverview> {
  return get('/api/sites/portfolio/overview', { company_id: companyId })
}

export async function getPortfolio(companyId: string): Promise<Portfolio> {
  return get('/api/sites/portfolio', { company_id: companyId })
}

export async function getTechConnections(companyId: string): Promise<{
  total: number; overdue: number; costSum: number
  byStatus: { key: string; label: string; count: number }[]; items: TechConnection[]
}> {
  return get('/api/sites/tech-connections', { company_id: companyId })
}

export interface PhaseDurations {
  stages: { stage: SiteStage; label: string; count: number; medianDays: number; open: number }[]
  note: string
}

export async function getPhaseDurations(companyId: string): Promise<PhaseDurations> {
  return get('/api/sites/phase-durations', { company_id: companyId })
}

/** Выгрузка портфеля в xlsx — то, что уходит на совещание. */
export async function exportPortfolioXlsx(companyId: string): Promise<void> {
  const { getToken } = await import('./apiClient')
  const token = getToken()
  const base = import.meta.env.VITE_API_URL ?? ''
  const res = await fetch(`${base}/api/sites/export/portfolio?company_id=${companyId}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new Error(`Выгрузка не удалась (${res.status})`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'projects_portfolio.xlsx'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export async function getAwaitingAccounting(companyId: string): Promise<AwaitingAccounting> {
  return get('/api/sites/awaiting-accounting', { company_id: companyId })
}


/** Схема реализации: путь проекта одной лентой (стадии + параллельные треки). */
export interface ProjectRoadmap {
  stage: SiteStage
  stageLabel: string
  phase: string | null
  offPath: boolean
  unknownProgress: boolean
  stoppedAt: string | null
  progress: number | null
  phases: { key: string; label: string; hint: string }[]
  steps: {
    key: SiteStage; kind: 'stage'; label: string
    phase: string | null; phaseLabel: string
    state: 'done' | 'current' | 'stopped' | 'waiting' | 'unknown'
    date: string | null
    gateDone: number; gateTotal: number; blocking: string[]
    items: { label: string; done: boolean; required: boolean }[]
  }[]
  tracks: {
    key: string; kind: 'track'; phase: string; label: string
    state: 'done' | 'current' | 'waiting' | 'overdue' | 'failed' | 'empty'
    status: string; date: string | null; detail: string | null; note: string | null
  }[]
  docs: { count: number; kinds: string[] }
  subsidy: SubsidyCheck
}

export async function getProjectRoadmap(companyId: string, id: string): Promise<ProjectRoadmap> {
  return get(`/api/sites/${id}/roadmap`, { company_id: companyId })
}

export async function getProjectContext(companyId: string, id: string): Promise<ProjectContext> {
  return get(`/api/sites/${id}/project`, { company_id: companyId })
}

export async function getSiteDocs(companyId: string, id: string): Promise<SiteDoc[]> {
  return get(`/api/sites/${id}/docs`, { company_id: companyId })
}

export async function uploadSiteDoc(
  companyId: string, id: string, file: File, kind: string, title?: string,
): Promise<{ id: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const q = new URLSearchParams({ company_id: companyId, kind })
  if (title) q.set('title', title)
  return upload(`/api/sites/${id}/docs?${q.toString()}`, fd)
}

export async function deleteSiteDoc(companyId: string, id: string, docId: string): Promise<unknown> {
  return del(`/api/sites/${id}/docs/${docId}?company_id=${companyId}`)
}

export async function saveTechConnection(
  companyId: string, id: string, payload: Record<string, unknown>,
): Promise<TechConnection> {
  return put(`/api/sites/${id}/tech-connection?company_id=${companyId}`, payload)
}

export async function getEquipmentReport(companyId: string): Promise<{
  total: number; overdue: number; qty: number; priceTotal: number
  byStatus: { key: string; label: string; count: number }[]; items: SiteEquipment[]
}> {
  return get('/api/sites/equipment', { company_id: companyId })
}

export async function saveEquipment(
  companyId: string, id: string, payload: Record<string, unknown>,
): Promise<SiteEquipment> {
  return put(`/api/sites/${id}/equipment?company_id=${companyId}`, payload)
}

export async function deleteEquipment(companyId: string, id: string, eqId: string): Promise<unknown> {
  return del(`/api/sites/${id}/equipment/${eqId}?company_id=${companyId}`)
}

export async function saveCost(
  companyId: string, id: string, payload: Record<string, unknown>,
): Promise<{ id: string }> {
  return put(`/api/sites/${id}/costs?company_id=${companyId}`, payload)
}

export async function deleteCost(companyId: string, id: string, costId: string): Promise<unknown> {
  return del(`/api/sites/${id}/costs/${costId}?company_id=${companyId}`)
}

export async function linkContract(companyId: string, id: string, contractId: string): Promise<unknown> {
  return post(`/api/sites/${id}/link-contract?company_id=${companyId}`, { contract_id: contractId })
}

export async function linkLocation(companyId: string, id: string, locationId: string): Promise<unknown> {
  return post(`/api/sites/${id}/link-location?company_id=${companyId}`, { location_id: locationId })
}

export async function getSiteEconomics(
  companyId: string, id: string,
): Promise<{ economics: SiteEconomics; score: { attract: number | null; feasible: number | null; confidence: number; quadrant: Quadrant; factors: { attract: { name: string; score: number }[]; feasible: { name: string; score: number }[] }; unknown: string[]; nearestStationKm: number | null; cannibalization: boolean } }> {
  return get(`/api/sites/${id}/economics`, { company_id: companyId })
}
