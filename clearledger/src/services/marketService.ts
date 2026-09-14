/**
 * Клиент рынка (продукт «Маркетинг», docs/MARKET.md).
 *
 * Внешний мир вокруг сети: чужие станции, торговые центры, парковки, АЗС и наблюдения
 * по ним. Наши объекты сюда не копируются — карта складывается из двух реестров.
 */
import { get, post, patch } from './apiClient'

/** Вид точки рынка. Не только ЭЗС: ТЦ и парковки объясняют спрос и служат кандидатами. */
export type MarketSiteKind = 'ezs' | 'mall' | 'parking' | 'fuel' | 'hotel' | 'office' | 'other'

export const SITE_KIND_LABEL: Record<MarketSiteKind, string> = {
  ezs: 'Зарядная станция',
  mall: 'Торговый центр',
  parking: 'Парковка',
  fuel: 'АЗС',
  hotel: 'Отель',
  office: 'Офисный центр',
  other: 'Другое',
}

/** Канал наблюдения — чьими глазами получен факт (принцип 2 docs/MARKET.md). */
export const CHANNEL_LABEL: Record<string, string> = {
  manual: 'вручную',
  service_visit: 'выезд сервиса',
  marketing: 'маркетинг',
  partner: 'партнёр',
  import: 'импорт',
  parser: 'парсер',
}

export interface MarketPrice {
  value: number | null
  unit: string | null
  basis: string | null
  observedOn: string
  channel: string
  confidence: string
}

export interface MarketSite {
  id: string
  kind: MarketSiteKind
  /** Сеть, независимая точка или домашняя розетка — слой карты выбирают по нему. */
  siteClass: MarketSiteClass
  currentType: string | null
  lastSessionAt: string | null
  name: string
  /** Кто эксплуатирует: под чьим именем точка пришла в выгрузке. */
  operatorId: string | null
  operatorName: string | null
  /** Чей это актив. Совпадает с эксплуатантом не всегда — см. MarketOwnerRow. */
  ownerId: string | null
  ownerName: string | null
  ownerChecked: boolean
  /** Та же станция, уже заведённая другой записью: из счёта уходит. */
  duplicateOfId: string | null
  address: string | null
  city: string | null
  region: string | null
  lat: number | null
  lon: number | null
  ports: number | null
  maxPowerKw: number | null
  connectors: string | null
  status: string
  openedOn: string | null
  isOurs: boolean
  locationId: string | null
  /** Разъёмы с их мощностями: по ним видно, какая машина сюда вообще подъедет. */
  connectorsJson: { type?: string; power_kw?: number }[] | null
  connectorsTotal: number | null
  quality24h: number | null
  successPct: number | null
  rating: number | null
  reviews: number | null
  closedConfirmations: number | null
  isAlive: boolean | null
  currency: string | null
  externalId: string | null
  vendor: string | null
  firstSeenAt: string | null
  /** Снимки площадки: ссылки внешние, файлы лежат у источника. */
  photos: string[] | null
  photoCount: number | null
  photoAuthors: string | null
  source: string
  sourceRank: number
  lastSeenAt: string | null
  verifiedAt: string | null
  price: MarketPrice | null
  notes: string | null
}

export interface MarketOperator {
  id: string
  name: string
  shortName: string | null
  relation: string
  siteUrl: string | null
  inn: string | null
  notes: string | null
  /** Точки СЕТИ: домашние розетки под тем же именем в счёт не идут. */
  sites: number
  /** Из них заряжали за 90 дней — сорок мёртвых розеток не равны десяти живым DC. */
  alive: number
  ports: number
  maxPowerKw: number | null
  medianPricePerKwh: number | null
  pricedSites: number
  quality: number | null
  success: number | null
  rating: number | null
  reviews: number
}

/** Карточка компании: где стоит, чем оснащена, почём заряжает, как её оценивают. */
/**
 * Что известно о компании помимо её точек: чем она является, на чьей платформе
 * работает, как называется юридически и с кем говорить. Каждое утверждение идёт со
 * своей достоверностью — реквизиты с формулировкой источника, модель с признаком
 * ручной проверки, число точек с числом подтвердивших источников.
 */
export interface OperatorFacts {
  class: string | null
  classChecked: boolean
  /**
   * Три роли, которые рынок смешивает: владеть станцией, эксплуатировать её и
   * поставлять для неё ИТ-систему. Не исключают друг друга — «Пункт Е» делает всё
   * три, ItCharge для чужих сетей только платформа.
   */
  isOwner: boolean
  isOperator: boolean
  isPlatform: boolean
  rolesChecked: boolean
  /**
   * Уровень достоверности записи (Marketing/research/data-quality.md):
   * 1 — можно ссылаться во внешних материалах; 2 — внутренняя оценка;
   * 3 — только сигнал, требует проверки. Смешивать уровни в одном утверждении
   * нельзя: один спорный показатель ставит под сомнение всю работу.
   */
  dataLevel: 1 | 2 | 3 | null
  baseCity: string | null
  citiesCount: number | null
  districts: number | null
  platformCode: string | null
  platformOwner: string | null
  ownPlatform: boolean | null
  roaming: boolean | null
  roamingPct: number | null
  appName: string | null
  appPackage: string | null
  appDeveloper: string | null
  appRating: number | null
  appReviews: number | null
  publicRating: number | null
  publicReviews: number | null
  publicAddress: string | null
  legalName: string | null
  inn: string | null
  ogrn: string | null
  director: string | null
  legalAddress: string | null
  legalStatus: string | null
  legalConfidence: string | null
  legalTrusted: boolean
  phone: string | null
  siteUrl: string | null
  contacts: Record<string, unknown> | null
  pointsTotal: number | null
  pointsRegistry: number | null
  pointsOsm: number | null
  cardsYandex: number | null
  sources: string | null
  sourceCount: number | null
  alivePct: number | null
  paidPct: number | null
  avgPowerKw: number | null
}

export interface MarketOperatorCard extends OperatorFacts {
  id: string
  name: string
  relation: string
  notes: string | null
  totals: {
    sites: number; homeSockets: number; ports: number; alive: number
    closed: number; planned: number
    medianPricePerKwh: number | null; pricedSites: number
    quality: number | null; success: number | null
    rating: number | null; reviews: number
  }
  cities: { name: string; sites: number }[]
  power: { bucket: string; sites: number }[]
  months: { month: string; sites: number }[]
  sites: {
    id: string; name: string; city: string | null
    ports: number | null; maxPowerKw: number | null; currentType: string | null
    status: string; rating: number | null; quality: number | null
    lastSessionAt: string | null; alive: boolean
  }[]
}

export interface MarketObservation {
  id: string
  siteId: string
  siteName?: string
  kind: string
  observedOn: string
  price: number | null
  priceUnit: string | null
  pricePerKwh: number | null
  basis: string | null
  connectorType: string | null
  powerKw: number | null
  channel: string
  confidence: string
  sourceRef: string | null
  snapshotUrl: string | null
  author: string | null
  note: string | null
}

export const listMarketSites = (
  companyId: string,
  params?: {
    kind?: string; city?: string; bbox?: string; limit?: number; offset?: number
    site_class?: string; current_type?: string; operator_id?: string
    min_power?: number; alive?: string; search?: string
  },
) => get<{ sites: MarketSite[]; total: number; returned: number; offset: number; limit: number }>(
  '/api/market/sites', { company_id: companyId, ...params })

/** Разрез рынка по точкам: строка группы с покрытием цены рядом. */
export type BreakdownRow = {
  name: string; sites: number; alive: number; ports: number
  medianPrice: number | null; pricedSites: number
}

export const getSitesBreakdown = (
  companyId: string,
  params?: { city?: string; region?: string; operator_id?: string },
) => get<{
  total: number; homeSockets: number; message?: string
  byPower: BreakdownRow[]; byCurrent: BreakdownRow[]; byClass: BreakdownRow[]
  byOperator: BreakdownRow[]; byRegion: BreakdownRow[]
  byConnector: { name: string; count: number; sites: number
                 medianPowerKw: number | null; withPower: number }[]
  quality: {
    alive: number; aliveDays: number; neverSeenCharging: number
    withoutOperator: number; ourSites: number
    medianQuality: number | null; qualityCoverage: number
    medianSuccess: number | null; successCoverage: number
    medianRating: number | null; ratingCoverage: number
    closedConfirmed: number
  }
  note: string
}>('/api/market/sites/breakdown', { company_id: companyId, ...params })

export const listMarketOperators = (companyId: string) =>
  get<{ operators: MarketOperator[] }>('/api/market/operators', { company_id: companyId })

export const getMarketOperatorCard = (companyId: string, operatorId: string) =>
  get<MarketOperatorCard>(`/api/market/operators/${operatorId}`, { company_id: companyId })

export const listMarketObservations = (companyId: string, siteId?: string) =>
  get<{ observations: MarketObservation[]; total: number }>('/api/market/observations',
    { company_id: companyId, ...(siteId ? { site_id: siteId } : {}) })

export const getMarketSummary = (companyId: string) =>
  get<{ byKind: Record<string, number>; competitors: number; observations: number; lastObservedOn: string | null }>(
    '/api/market/summary', { company_id: companyId })

export const createMarketSite = (companyId: string, body: Record<string, unknown>) =>
  post<{ id: string; name: string; duplicate: boolean }>(
    `/api/market/sites?company_id=${encodeURIComponent(companyId)}`, body)

export const createMarketOperator = (companyId: string, body: Record<string, unknown>) =>
  post<{ id: string; name: string }>(
    `/api/market/operators?company_id=${encodeURIComponent(companyId)}`, body)

export const createMarketObservation = (companyId: string, body: Record<string, unknown>) =>
  post<{ id: string }>(
    `/api/market/observations?company_id=${encodeURIComponent(companyId)}`, body)

export const patchMarketSite = (companyId: string, siteId: string, body: Record<string, unknown>) =>
  patch<{ id: string; verifiedAt: string }>(
    `/api/market/sites/${siteId}?company_id=${encodeURIComponent(companyId)}`, body)

/** Класс точки: сеть оператора или домашняя розетка частника. */
export type MarketSiteClass = 'network' | 'independent' | 'home' | 'unknown'

export const SITE_CLASS_LABEL: Record<MarketSiteClass, string> = {
  network: 'сеть оператора',
  independent: 'независимая точка',
  home: 'домашняя розетка',
  unknown: 'класс неизвестен',
}

/** Сосед по окружению объекта: чужая точка в радиусе с её ценой и расстоянием. */
export interface MarketNeighbour {
  id: string
  name: string
  kind: MarketSiteKind
  siteClass: MarketSiteClass
  operatorName: string | null
  relation: string | null
  distanceKm: number
  ports: number | null
  maxPowerKw: number | null
  pricePerKwh: number | null
  observedOn: string | null
  /** Дата последней зарядки в источнике — единственный честный признак спроса. */
  lastSessionAt: string | null
  alive: boolean
}

/** Строка «Позиции»: наш объект + наши продажи + рынок вокруг него. */
export interface MarketPositionRow {
  locationId: string
  name: string
  code: string
  city: string | null
  lat: number | null
  lon: number | null
  hasGeo: boolean
  sessions: number
  energyKwh: number
  revenue: number
  ourPricePerKwh: number | null
  rivals: number
  /** Из них живые: заряжали за последние 90 дней. */
  rivalsAlive: number
  rivalPorts: number
  homeSockets: number
  attractors: number
  marketPricePerKwh: number | null
  priceGapPct: number | null
  neighbours: MarketNeighbour[]
}

export const getMarketPosition = (companyId: string, params?: { days?: number; radius_km?: number }) =>
  get<{ days: number; radiusKm: number; objects: MarketPositionRow[]; total: number }>(
    '/api/market/position', { company_id: companyId, ...params })

/** Источник рынка: сколько точек принёс, когда виделся, что в нём заполнено. */
export interface MarketSource {
  source: string
  rank: number
  sites: number
  lastSeenAt: string | null
  closed: number
  homeSockets: number
  coverage: { geo: number; power: number; vendor: number; successPct: number; lastSession: number }
}

export interface MarketSourcesReply {
  sources: MarketSource[]
  snapshots: { date: string; sites: number }[]
  totals: { sites: number; priced: number; conflicts: number; alive: number; aliveDays: number }
}

export const SOURCE_LABEL: Record<string, string> = {
  registry_ru: 'Реестр ЭЗС России',
  api: 'Open Charge Map',
  partner: 'Партнёрский обмен',
  manual: 'Заведено вручную',
  import: 'Импорт списком',
  parser: 'Парсер',
  service_visit: 'Выезд сервиса',
}

/** Точка в списке изменений между срезами. */
export interface MarketChangeCard {
  id: string
  name: string
  city: string | null
  siteClass: MarketSiteClass
  was?: number
  now?: number
}

export interface MarketChangesReply {
  base: string | null
  current: string | null
  available: string[]
  appeared: MarketChangeCard[]
  gone: MarketChangeCard[]
  priceMoves: MarketChangeCard[]
  qualityDrops: MarketChangeCard[]
  counts: { appeared?: number; gone?: number; priceMoves?: number; qualityDrops?: number }
  message?: string
}

export const getMarketSources = (companyId: string) =>
  get<MarketSourcesReply>('/api/market/sources', { company_id: companyId })

export const getMarketChanges = (companyId: string, params?: { base?: string; current?: string }) =>
  get<MarketChangesReply>('/api/market/changes', { company_id: companyId, ...params })

/** Строка территории: наше и чужое в одной рамке. */
export interface MarketTerritory {
  name: string
  ourSites: number
  ourSessions: number
  ourRevenue: number
  ourEnergyKwh: number
  rivalSites: number
  rivalAlive: number
  rivalPorts: number
  homeSockets: number
  marketPricePerKwh: number | null
  ourPricePerKwh: number | null
  sharePct: number | null
  priceGapPct: number | null
  /** Площадки «Проектов» в работе на этой территории: работа уже идёт. */
  projectsInWork?: number
  projectStages?: Record<string, number>
  projectNumbers?: string[]
}

/** Паспорт места под новую станцию: окружение, каннибализация, прогноз по аналогам. */
export interface MarketSiteScore {
  /**
   * Где это место: регион и город, определённые по ближайшей известной точке
   * (геокодера у нас нет), и статистика территории — парк машин, рынок целиком,
   * наша сеть, площадки в работе. Соседние станции отвечают на «кто рядом», а это
   * на «что за территория» — без второго решение принимают вслепую.
   */
  area: {
    region: string | null; city: string | null
    byPointKm: number | null; byPointName: string | null
    evCars?: number | null; evSource?: string | null; evAsOf?: string | null
    marketSites?: number; marketAlive?: number; carsPerAlive?: number | null
    ourSites?: number
    projectsInWork?: number; projectNumbers?: string[]
  }
  point: { lat: number; lon: number }
  radiusKm: number
  days: number
  /** Город или трасса: от этого зависит, с какими нашими объектами сравнивать. */
  placeClass: 'city' | 'highway'
  placeGuessed: boolean
  rivals: {
    total: number; alive: number; ports: number; marketPricePerKwh: number | null
    list: {
      id: string; name: string; operatorName: string | null; distanceKm: number
      ports: number | null; maxPowerKw: number | null; pricePerKwh: number | null
      alive: boolean
    }[]
  }
  cannibalization: {
    ourNearby: number
    list: { locationId: string; name: string; city: string | null
            distanceKm: number; sessions: number; revenue: number }[]
  }
  /** Чего стоит вход: мощность и присоединение по опыту соседних площадок. */
  entry: {
    projectsNearby: number
    tpCostMedian: number | null
    tpTermMonthsMedian: number | null
    freePowerKwtMedian: number | null
    rentMonthMedian: number | null
    smrCostMedian: number | null
    capexEstimate: number | null
    samples: { tpCost: number; tpTerm: number; freePower: number; rent: number; smr: number }
    paybackPeriods: number | null
    basis: string
  }
  forecast: {
    method: string; analogues: number; days: number
    sessionsPerPeriod: number | null; revenuePerPeriod: number | null
    /** Разброс похожих объектов: половина лежит между low и high. */
    sessionsLow: number | null; sessionsHigh: number | null
    revenueLow: number | null; revenueHigh: number | null
    /** Сколько похожих объектов заряжают вовсе и медиана с учётом молчащих. */
    working: number; zeroDemand: number
    sessionsAllMedian: number | null; revenueAllMedian: number | null
    sample: { locationId: string; name: string; city: string | null
              rivals: number; rivalsTotal?: number
              locationClass?: string | null; speedClass?: string | null
              sessions: number; revenue: number }[]
  }
}

export const getMarketTerritories = (companyId: string, params?: { level?: string; days?: number }) =>
  get<{ level: string; days: number; territories: MarketTerritory[]; total: number }>(
    '/api/market/territories', { company_id: companyId, ...params })

export const getMarketWhitespots = (companyId: string, params?: { level?: string }) =>
  get<{ level: string; spots: MarketTerritory[]; total: number; basis: string
        withProject: number }>(
    '/api/market/whitespots', { company_id: companyId, ...params })

export const getMarketSiteScore = (
  companyId: string,
  params: { lat: number; lon: number; radius_km?: number; days?: number; place?: string },
) => get<MarketSiteScore>('/api/market/site-score', { company_id: companyId, ...params })

/** Ценовой ландшафт: почём рынок по классам мощности и где в нём мы. */
export interface MarketPriceLandscape {
  days: number
  buckets: { bucket: string; sites: number; median: number | null
             low: number | null; high: number | null }[]
  unknownPower: number
  pricedSites: number
  ourPricePerKwh: number | null
  marketMedianPerKwh: number | null
  gapPct: number | null
}

/** Давление конкурента: кто появился рядом и что стало с нашими сессиями. */
export interface MarketPressureRow {
  locationId: string; name: string; city: string | null
  rivalName: string; rivalOperator: string | null
  distanceKm: number; appearedOn: string
  sessionsBefore: number; sessionsAfter: number
  changePct: number | null; rivalsNearby: number
}

/** Случай изменения нашей цены и отклик спроса на него. */
export interface MarketElasticityCase {
  locationId: string; name: string; week: string
  priceWas: number; priceNow: number; pricePct: number
  sessionsWas: number; sessionsNow: number; sessionsPct: number
  elasticity: number | null
}

export const getMarketPriceLandscape = (companyId: string, params?: { days?: number }) =>
  get<MarketPriceLandscape>('/api/market/price-landscape', { company_id: companyId, ...params })

export const getMarketPressure = (companyId: string, params?: { months?: number; radius_km?: number }) =>
  get<{ months: number; radiusKm: number; rows: MarketPressureRow[]; total: number; note: string }>(
    '/api/market/pressure', { company_id: companyId, ...params })

export const getMarketElasticity = (companyId: string, params?: { weeks?: number }) =>
  get<{ weeks: number; cases: MarketElasticityCase[]; total: number
        medianElasticity: number | null; note: string }>(
    '/api/market/elasticity', { company_id: companyId, ...params })

/** Сценарий: гипотеза с ценой, контрольной группой и замером. */
export interface MarketScenario {
  id: string
  title: string
  actionKind: string
  description: string | null
  status: string
  scope: string[]
  control: string[]
  expect: Record<string, unknown>
  cost: number | null
  risk: string | null
  startedOn: string | null
  checkOn: string | null
  ownerName: string | null
  measure: {
    measuredOn: string
    didSessions: number | null
    didRevenue: number | null
    verdict: string | null
    note: string | null
    fact: {
      weeks?: number; startedOn?: string
      scope?: { sessionsPct: number | null; revenuePct: number | null; objects: number }
      control?: { sessionsPct: number | null; revenuePct: number | null; objects: number }
    }
  } | null
}

export const listMarketScenarios = (companyId: string) =>
  get<{ scenarios: MarketScenario[] }>('/api/market/scenarios', { company_id: companyId })

export const createMarketScenario = (companyId: string, body: Record<string, unknown>) =>
  post<{ id: string; title: string }>(
    `/api/market/scenarios?company_id=${encodeURIComponent(companyId)}`, body)

export const patchMarketScenario = (companyId: string, id: string, body: Record<string, unknown>) =>
  patch<{ id: string; status: string }>(
    `/api/market/scenarios/${id}?company_id=${encodeURIComponent(companyId)}`, body)

/** Подбор контроля + проверка, шли ли тренды рядом ДО вмешательства. */
export const suggestScenarioControl = (companyId: string, scope: string[]) =>
  get<{
    control: string[]
    candidates: { locationId: string; name: string; city: string | null
                  rivals: number; sessions: number }[]
    targetProfile: { rivals: number | null; sessions: number | null; class: string | null }
    parallel: { weeks: number; scopeTrendPct: number | null; controlTrendPct: number | null
                gapPct: number | null; ok: boolean; note: string }
  }>('/api/market/scenarios/control-suggest',
     { company_id: companyId, scope: scope.join(',') })

export const measureMarketScenario = (companyId: string, id: string, weeks = 8) =>
  post<{ scenarioId: string; verdict: string; didSessions: number | null; didRevenue: number | null }>(
    `/api/market/scenarios/${id}/measure?company_id=${encodeURIComponent(companyId)}&weeks=${weeks}`, {})

/** Сеть-кандидат на роуминг: чем дополняет нашу, чем дублирует. */
export interface MarketPartner {
  id: string
  name: string
  relation: string
  notes: string | null
  sites: number
  alive: number
  ports: number
  overlapSites: number
  complementSites: number
  complementPct: number | null
  newCities: string[]
  newCitiesTotal: number
  sharedCities: string[]
  sharedCitiesTotal: number
}

export const getMarketPartners = (companyId: string, params?: { min_sites?: number }) =>
  get<{ partners: MarketPartner[]; total: number; ourCities: number; note: string }>(
    '/api/market/partners', { company_id: companyId, ...params })

export const patchMarketOperator = (companyId: string, id: string, body: Record<string, unknown>) =>
  patch<{ id: string; relation: string }>(
    `/api/market/operators/${id}?company_id=${encodeURIComponent(companyId)}`, body)

/** Регион глазами компании: кто мы здесь и чем тут расти. */
export interface GrowthPresenceRow {
  name: string
  presence: 'monopoly' | 'strong' | 'contested' | 'weak' | 'absent' | 'unknown'
  presenceLabel: string
  sharePct: number | null
  suggestedTracks: string[]
  ourSites: number
  ourSessions: number
  ourRevenue: number
  rivalSites: number
  rivalAlive: number
  marketPricePerKwh: number | null
  ourPricePerKwh: number | null
  /** Сколько площадок «Проектов» уже в работе на этой территории. */
  projectsInWork: number
  projectStages: Record<string, number>
  /** Нас здесь нет, но мы уже входим: работа идёт. */
  entering: boolean
}

export interface GrowthGroup {
  presence: string
  label: string
  regions: number
  ourSites: number
  rivalSites: number
  ourSessions: number
  ourRevenue: number
  tracks: string[]
}

export interface GrowthTrack {
  track: string
  label: string
  headline: string
  metrics: { label: string; value: number }[]
  leads: Record<string, number>
}

export interface GrowthLead {
  id: string
  track: string
  trackLabel: string
  title: string
  subjectKind: string | null
  subjectRef: string | null
  evidence: Record<string, unknown>
  status: string
  rejectReason: string | null
  note: string | null
  siteId: string | null
  scenarioId: string | null
  ownerName: string | null
  createdAt: string | null
}

export const getGrowthOverview = (companyId: string, params?: { days?: number }) =>
  get<{ days: number; tracks: GrowthTrack[]; presence: GrowthGroup[]
        trackLabels: Record<string, string> }>(
    '/api/market/growth/overview', { company_id: companyId, ...params })

export const getGrowthPresence = (companyId: string, params?: { days?: number }) =>
  get<{ days: number; regions: GrowthPresenceRow[]; groups: GrowthGroup[]
        thresholds: { monopoly: number; weak: number }; note: string
        geoCoverage: number | null; sitesWithoutRegion: number
        enteringRegions: number; projectsInWork: number }>(
    '/api/market/growth/presence', { company_id: companyId, ...params })

/** Город воронки: наша работа и рынок вокруг неё в одной строке. */
export type PipelineCity = {
  city: string; region: string | null; projects: number
  stages: Record<string, number>; weAreThere: boolean
  marketSites: number; marketAlive: number; marketKnown: boolean
}

export type PipelineStage = {
  stage: string; label: string; projects: number
  withCity: number; withCoords: number
  plannedPoints: number; plannedPowerKwt: number; withPlan: number
}

export const getGrowthPipeline = (companyId: string) =>
  get<{
    projects: number; message?: string
    stages: PipelineStage[]
    cities: PipelineCity[]; citiesTotal: number
    entering: PipelineCity[]; enteringTotal: number
    unseenByMarket: PipelineCity[]; unseenTotal: number
    regions: { region: string; projects: number; cities: number
               ourSites: number; entering: boolean }[]
    enteringRegions: number
    plan: { points: number; withPlan: number; coverage: number | null; powerKwt: number }
    note: string
  }>('/api/market/growth/pipeline', { company_id: companyId })

export const listGrowthLeads = (companyId: string, params?: { track?: string }) =>
  get<{ leads: GrowthLead[] }>('/api/market/growth/leads', { company_id: companyId, ...params })

export const createGrowthLead = (companyId: string, body: Record<string, unknown>) =>
  post<{ id: string; track: string; title: string }>(
    `/api/market/growth/leads?company_id=${encodeURIComponent(companyId)}`, body)

export const patchGrowthLead = (companyId: string, id: string, body: Record<string, unknown>) =>
  patch<{ id: string; status: string }>(
    `/api/market/growth/leads/${id}?company_id=${encodeURIComponent(companyId)}`, body)

export const leadToProject = (companyId: string, leadId: string) =>
  post<{ siteId: string; projectNo?: string; created: boolean; message: string }>(
    `/api/market/growth/leads/${leadId}/to-project?company_id=${encodeURIComponent(companyId)}`, {})

/** Наш публичный профиль: как нас видит клиент и что видим мы. */
export interface MarketSelfView {
  days: number
  matchKm: number
  totals: {
    inMarket: number; matchedToRegistry: number
    quality: number | null; success: number | null; rating: number | null
    reviews: number; aliveByMarket: number; silentButWorking: number
  }
  peers: { name: string; sites: number; quality: number | null
           success: number | null; rating: number | null }[]
  sites: {
    siteId: string; marketName: string; city: string | null
    locationId: string | null; ourName: string | null; matchKm: number | null
    quality: number | null; successPct: number | null; rating: number | null
    reviews: number | null; publicPricePerKwh: number | null
    lastSessionAt: string | null; aliveByMarket: boolean
    ourSessions: number | null; ourRevenue: number | null
  }[]
  note: string
  /**
   * Что знаем о себе мы сами. Рынок не публикует про нас успешность зарядок ни по
   * одной из 429 точек, но у нас есть собственный журнал сессий с результатом
   * каждой — и писать «нет данных» о себе, когда данные лежат рядом, нельзя.
   */
  ours: {
    sessions: number; successful: number; failed: number
    successPct: number | null
    energyKwh: number; revenue: number
  }
}

export const getMarketSelfView = (companyId: string, params?: { days?: number; match_km?: number }) =>
  get<MarketSelfView>('/api/market/self', { company_id: companyId, ...params })

/** Профиль территории: наша сеть во всей полноте плюс рынок рядом. */
export interface TerritoryProfile {
  name: string
  level: string
  days: number
  message?: string
  ours: {
    objects: number; ports: number
    powerKwtTotal: number | null; powerKwtMax: number | null
    bySpeed: Record<string, number>; byBrand: Record<string, number>
    byStatus: Record<string, number>; connectorTypes: Record<string, number>
    sessions: number; energyKwh: number; revenue: number
    avgDurationMin: number; clients: number; avgCheck: number | null
    pricePerKwh: number | null
    sessionsPerPortDay: number | null; kwhPerPortDay: number | null
    byUserType: Record<string, { sessions: number; revenue: number }>
    byConnector: Record<string, number>; byResult: Record<string, number>
    hours: { hour: number; sessions: number }[]
    trend: { prevSessions: number; prevRevenue: number
             sessionsPct: number | null; revenuePct: number | null }
    objectsList: {
      locationId: string; name: string; city: string | null
      powerKwt: number | null; ports: number | null; speedClass: string | null
      brand: string | null; status: string | null
      sessions: number; revenue: number
    }[]
  } | null
  market: {
    rivalSites: number; independentSites: number; homeSockets: number
    rivalPorts: number; aliveRivals: number
    marketPricePerKwh: number | null; pricedSites: number; sharePct: number | null
  }
}

export const getTerritoryProfile = (
  companyId: string, params: { name: string; level?: string; days?: number },
) => get<TerritoryProfile>('/api/market/territory-profile',
  { company_id: companyId, ...params })

/** Наша станция на карте — со всем, по чему её отбирают на нашем слое. */
export interface OurMapPoint {
  id: string
  name: string
  code: string
  city: string | null
  region: string | null
  lat: number
  lon: number
  powerKwt: number | null
  ports: number | null
  speedClass: string | null
  locationClass: string | null
  brand: string | null
  status: string | null
  commissionedOn: string | null
  sessions: number
  energyKwh: number
  revenue: number
  clients: number
  errorPct: number | null
  sessionsPerPortDay: number | null
}

export const getOurMapPoints = (companyId: string, params?: { days?: number }) =>
  get<{ days: number; points: OurMapPoint[]; total: number
        brands: string[]; statuses: string[]; regions: string[] }>(
    '/api/market/our-map', { company_id: companyId, ...params })

/** Сеть в раскладе сил: размер, охват, платформа, роуминг, сервис, реквизиты. */
export interface MarketNetworkRow {
  id: string
  name: string
  relation: string
  isOurs: boolean
  sites: number
  ports: number
  alive: number
  silentHalfYear: number
  sharePct: number
  quality: number | null
  success: number | null
  medianPricePerKwh: number | null
  baseCity: string | null
  /** Городов у сети. Имя с суффиксом: в карточке компании `cities` — это список
   *  городов, и одно имя на два разных смысла уже ломало экран. */
  citiesCount: number | null
  districts: number | null
  avgPowerKw: number | null
  paidPct: number | null
  platformOwner: string | null
  platformCode: string | null
  ownPlatform: boolean | null
  roaming: boolean | null
  roamingPct: number | null
  appName: string | null
  appRating: number | null
  appReviews: number | null
  appInstalls: string | null
  appDeveloper: string | null
  siteUrl: string | null
  legalName: string | null
  inn: string | null
  ogrn: string | null
  director: string | null
  legalAddress: string | null
  legalConfidence: string | null
  legalTrusted: boolean
  /** Чем компания является и чем это подтверждено — см. OperatorFacts. */
  class: string | null
  classChecked: boolean
  sourceCount: number | null
  sources: string | null
  pointsTotal: number | null
  legalStatus: string | null
  phone: string | null
}

export interface MarketPlatform {
  owner: string
  networks: number
  sites: number
  ownSites: number
  clientSites: number
  ownerIsNetwork: boolean
  clients: { name: string; sites: number }[]
}

/**
 * Владелец ЭЗС: чей актив стоит на земле — в отличие от эксплуатанта, под чьим
 * именем точка приходит в выгрузке. Разговор об интеграции, выкупе и обслуживании
 * идёт с владельцем (замечание РусГидро 14.09.2026).
 */
export interface MarketOwnerRow {
  id: string
  name: string
  isOurs: boolean
  relation: string
  isOwner: boolean
  isOperator: boolean
  isPlatform: boolean
  rolesChecked: boolean
  sites: number
  ports: number
  alive: number
  sharePct: number
  /** Сколько своих точек он же и обслуживает. */
  operatedSelf: number
  /** Сколько его точек работает под чужим именем — это и есть повод для разговора. */
  operatedByOthers: number
  platformOwner: string | null
  platformCode: string | null
  legalName: string | null
  inn: string | null
  legalTrusted: boolean
  siteUrl: string | null
  phone: string | null
}

export const getMarketLandscape = (companyId: string) =>
  get<{
    operators: MarketNetworkRow[]
    networks: MarketNetworkRow[]
    owners: MarketOwnerRow[]
    platforms: MarketPlatform[]
    totals: {
      networks: number; networkSites: number; withProfile: number; ownPlatform: number
      platformKnownSites: number; roamingNetworks: number; roamingSites: number
      closedNetworks: number; closedSites: number; withApp: number; legalTrusted: number
      owners: number; ownerSites: number; ownerUnclear: number
      ownersConfirmed: number; splitOwnership: number
    }
    note: string
  }>('/api/market/landscape', { company_id: companyId })

/** Бренд, видный в названиях точек платформы, но не заведённый компанией. */
export interface OwnerCandidate {
  brand: string
  key: string
  sites: number
  cities: string[]
  citiesTotal: number
  siteIds: string[]
  operatorId: string
  operatorName: string
  /** Компания с таким именем уже есть — точки надо привязать, а не заводить её заново. */
  existing: boolean
}

export const getOwnerCandidates = (companyId: string) =>
  get<{
    candidates: OwnerCandidate[]
    platforms: { id: string; name: string }[]
    sitesOnPlatforms: number
    ownersKnown: number
    note: string
  }>('/api/market/owner-candidates', { company_id: companyId })

export const applyOwnerCandidate = (companyId: string, brand: string, siteIds: string[]) =>
  post<{ ownerId: string; name: string; created: boolean; sites: number }>(
    `/api/market/owner-candidates/apply?company_id=${encodeURIComponent(companyId)}`,
    { brand, siteIds })

/** Пара точек разных компаний, стоящих почти в одном месте. */
export interface DuplicatePair {
  distanceM: number
  city: string | null
  a: DuplicateSide
  b: DuplicateSide
}

export interface DuplicateSide {
  id: string
  name: string
  operator: string | null
  ports: number | null
  source: string
  address: string | null
  isOurs: boolean
}

export const getMarketDuplicates = (companyId: string, radiusM = 150) =>
  get<{ pairs: DuplicatePair[]; total: number; radiusM: number; merged: number; note: string }>(
    '/api/market/duplicates', { company_id: companyId, radius_m: radiusM })

export const resolveDuplicate = (
  companyId: string, keepId: string, dropId: string, same = true,
) => post<{ merged: boolean }>(
  `/api/market/duplicates/resolve?company_id=${encodeURIComponent(companyId)}`,
  { keepId, dropId, same })

/** Обеспеченность региона: машин на зарядку и на работающую зарядку. */
export interface MarketCoverageRow {
  region: string
  evCars: number | null
  evSharePct: number | null
  stations: number | null
  stationsDc: number | null
  stationsAlive: number | null
  carsPerStation: number | null
  carsPerDc: number | null
  carsPerAlive: number | null
  deadGapRatio: number | null
  deadStations: number | null
  ourSites: number
  ourWorking: number
  ourSharePct: number | null
  marketSitesNow: number | null
  marketAliveNow: number | null
  /** Парк машин в регионе известен. Без него обеспеченность не считается. */
  carsKnown: boolean
  /** Откуда взято число станций: «статистика» или свежий «реестр». */
  stationsSource: string
  source: string | null
  asOf: string | null
}

export const getMarketCoverage = (companyId: string) =>
  get<{ regions: MarketCoverageRow[]; total: number; withCars: number
        note?: string; message?: string }>(
    '/api/market/coverage', { company_id: companyId })

/** Игрок рынка: тот, кто борется за водителя — со станциями или без. */
export interface MarketPlayer {
  id: string
  app: string
  package: string | null
  class: string
  classChecked: boolean
  adjacent: boolean
  ownStations: number | null
  assetLight: boolean | null
  operatorId: string | null
  operatorName: string | null
  brand: string | null
  developer: string | null
  developerInn: string | null
  rating: number | null
  reviews: number | null
  modelNote: string | null
  note: string | null
  source: string | null
  /** Приложение работает. Закрытое остаётся в списке, но не считается сетью. */
  isActive: boolean
  statusNote: string | null
}

export const getMarketPlayers = (companyId: string) =>
  get<{
    players: MarketPlayer[]
    total: number
    quadrants: { key: string; label: string; hint: string; count: number
                 networks?: number; stations: number; players: MarketPlayer[] }[]
    classes: { class: string; players: number; assetLight: number; stations: number
               adjacent: boolean; medianRating: number | null; withRating: number
               examples: string[] }[]
    quality: MarketPlayer[]
    shops: {
      brand: string; host: string | null; url: string | null
      hasShop: boolean | null; goods: string | null
      priceMin: number | null; priceMax: number | null
      pricesFound: number | null; note: string | null
      checkedOn: string | null; sites: number | null
    }[]
    totals: { withStations: number; assetLight: number; adjacent: number
              medianRating: number | null; withRating: number; unchecked: number
              withShop: number; shopsChecked: number; multiApp: string[] }
    note?: string
    message?: string
  }>('/api/market/players', { company_id: companyId })

export const bulkMarketSites = (companyId: string, items: Record<string, unknown>[], source = 'import') =>
  post<{ created: number; updated: number; observations: number }>(
    `/api/market/sites/bulk?company_id=${encodeURIComponent(companyId)}&source=${source}`, { items })

/** Импорт из Open Charge Map — открытого реестра ЭЗС с официальным API. */
export const ocmStatus = (companyId: string) =>
  get<{ configured: boolean }>('/api/market/ocm/status', { company_id: companyId })

export const ocmImportNetwork = (companyId: string, padding = 0.15) =>
  post<{ areas: number; cities: number; found: number; created: number; updated: number
         prices: number; skippedOurs: number; problems: string[] }>(
    `/api/market/ocm/import-network?company_id=${encodeURIComponent(companyId)}&padding=${padding}`, {})
