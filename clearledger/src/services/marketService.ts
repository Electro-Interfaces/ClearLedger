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
  name: string
  operatorId: string | null
  operatorName: string | null
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
export interface MarketOperatorCard {
  id: string
  name: string
  relation: string
  siteUrl: string | null
  inn: string | null
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

export const listMarketSites = (companyId: string, params?: { kind?: string; city?: string }) =>
  get<{ sites: MarketSite[]; total: number }>('/api/market/sites', { company_id: companyId, ...params })

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
export type MarketSiteClass = 'network' | 'home' | 'unknown'

export const SITE_CLASS_LABEL: Record<MarketSiteClass, string> = {
  network: 'сеть оператора',
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
}

/** Паспорт места под новую станцию: окружение, каннибализация, прогноз по аналогам. */
export interface MarketSiteScore {
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
  forecast: {
    method: string; analogues: number; days: number
    sessionsPerPeriod: number | null; revenuePerPeriod: number | null
    /** Разброс похожих объектов: половина лежит между low и high. */
    sessionsLow: number | null; sessionsHigh: number | null
    revenueLow: number | null; revenueHigh: number | null
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
  get<{ level: string; spots: MarketTerritory[]; total: number; basis: string }>(
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
