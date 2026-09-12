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
