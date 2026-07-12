/**
 * Клиент аналитики раздела «Магазин» (сопутка/общепит).
 * Пока — «Обзор магазина» (/api/store/overview → GoodsDashboardService).
 */
import { get } from './apiClient'

export interface StoreCategory {
  category: string
  revenue: number
  positions: number
  units: number
  percent: number
}

export interface StoreTrend {
  current: number
  previous: number
  delta: number
  percent: number
  direction: 'up' | 'down' | 'neutral'
}

export interface StoreOverviewData {
  period: { from: string; to: string; days: number }
  financial: {
    total_revenue: number
    returns: number
    vat: number
    net_revenue: number
    avg_check_approx: number
    payments: { cash: number; card: number }
  }
  units: {
    total_positions: number
    total_units: number
    by_category: StoreCategory[]
  }
  operational: { shifts_count: number; stations_count: number }
  charts: { daily: { date: string; revenue: number; soputka: number; obshepit: number }[] }
  by_station: { station: string; revenue: number; positions: number; shifts: number }[]
  trends?: Record<string, StoreTrend>
}

export const getStoreOverview = (
  dateFrom: string,
  dateTo: string,
  opts?: { stations?: string[]; compare?: boolean },
) =>
  get<StoreOverviewData>('/api/store/overview', {
    date_from: dateFrom,
    date_to: dateTo,
    stations: opts?.stations?.length ? opts.stations.join(',') : undefined,
    compare: opts?.compare ? 'true' : undefined,
  })

// ── Реестр SKU (Ассортимент / Цены-маржа / Номенклатура / Продажи) ──
export interface StoreSku {
  guid: string
  name: string
  article: string | null
  vat: string | null
  marked: boolean
  weighed: boolean
  category: string | null
  revenue: number
  revenue_net: number
  qty: number
  avg_price: number
  cost_net: number | null
  cost_source: string | null
  cost_reliable: boolean
  cogs: number | null
  margin: number | null
  margin_pct: number | null
  markup_pct: number | null
  purch_qty: number
  stock_est: number
  abc: 'A' | 'B' | 'C'
}

export interface StoreSkusData {
  period: { from: string; to: string }
  summary: {
    sku_count: number
    sku_costed: number
    revenue: number
    revenue_net: number
    cogs_costed: number
    margin_costed: number
    margin_pct_costed: number | null
    marked_count: number
  }
  abc: Record<'A' | 'B' | 'C', { count: number; revenue: number; share: number }>
  skus: StoreSku[]
}

export const getStoreSkus = (
  dateFrom: string,
  dateTo: string,
  opts?: { stations?: string[] },
) =>
  get<StoreSkusData>('/api/store/skus', {
    date_from: dateFrom,
    date_to: dateTo,
    stations: opts?.stations?.length ? opts.stations.join(',') : undefined,
  })

// ── Отчёты: Приёмка / Поставщики / Общепит / Категории ──
export interface StoreReceiptsData {
  period: { from: string; to: string }
  docs: { date: string; number: string; supplier: string; positions: number; amount: number; vat: number; amount_net: number }[]
  summary: { count: number; amount_net: number; vat: number }
}
export interface StoreSuppliersData {
  period: { from: string; to: string }
  suppliers: { name: string; amount_net: number; docs: number; sku_count: number }[]
  summary: { count: number; amount_net: number }
}
export interface StoreCateringData {
  period: { from: string; to: string }
  dishes: { guid: string; name: string; qty: number; revenue: number; revenue_net: number; cost: number | null; food_cost_pct: number | null }[]
  summary: { count: number; revenue: number }
}
export interface StoreCategoriesData {
  period: { from: string; to: string }
  categories: { category: string; revenue: number; revenue_net: number; sku_count: number; qty: number; share: number; margin: number | null; margin_pct: number | null }[]
  summary: { count: number; revenue: number }
}
export interface StoreBarcodesData {
  total: number
  by_type: Record<string, number>
  items: { barcode: string; owner_name: string; type: string | null; main: boolean }[]
}
export interface StoreRecipesData {
  period: { from: string; to: string }
  recipes: { name: string; ingredients: { name: string; qty: number }[]; ing_count: number }[]
  summary: { count: number }
}

export const getStoreReport = <T>(report: string, dateFrom: string, dateTo: string, stations?: string[]) =>
  get<T>(`/api/store/${report}`, {
    date_from: dateFrom,
    date_to: dateTo,
    stations: stations?.length ? stations.join(',') : undefined,
  })

// ── Продажи: гибкая группировка (инструмент менеджера) ──
export type SalesGroupBy = 'sku' | 'category' | 'kind' | 'marking' | 'vat' | 'day' | 'payment'
export type SalesCategory = 'all' | 'soputka' | 'obshepit'
export type SalesMarked = 'all' | 'marked' | 'plain'

export interface StoreSalesGroup {
  key: string; label: string
  revenue: number; revenue_net: number; vat: number
  qty: number; sku_count: number; share: number
}
export interface StoreSalesData {
  period: { from: string; to: string }
  group_by: SalesGroupBy
  filters: { category: string; marked: string; q: string }
  groups: StoreSalesGroup[]
  summary: {
    revenue: number; revenue_net: number; vat: number; qty: number
    sku_count: number; shifts: number; groups_count: number
  }
}

export const getStoreSales = (
  dateFrom: string, dateTo: string,
  opts: { groupBy: SalesGroupBy; category: SalesCategory; marked: SalesMarked; q?: string; stations?: string[] },
) =>
  get<StoreSalesData>('/api/store/sales', {
    date_from: dateFrom,
    date_to: dateTo,
    group_by: opts.groupBy,
    category: opts.category,
    marked: opts.marked,
    q: opts.q || undefined,
    stations: opts.stations?.length ? opts.stations.join(',') : undefined,
  })

// ── Остатки: достоверный остаток из регистров ЦБ (снимок, не оценка) ──
export interface StoreStockItem {
  guid: string; name: string; article: string | null; vat: string | null
  marked: boolean; weighed: boolean; barcode: string | null
  qty: number; negative: boolean
  retail_price: number | null; retail_value: number | null
  cost_unit: number | null; cost_amount: number | null
  margin: number | null; margin_pct: number | null
}
export interface StoreStockWarehouse { code: string; name: string | null; sku: number; retail_value: number }
export interface StoreStockData {
  warehouse: string | null
  warehouses: StoreStockWarehouse[]
  items: StoreStockItem[]
  summary: {
    sku_count: number; positive: number; negative: number
    retail_value_positive: number; retail_value_all: number
    cost_value: number; costed_count: number; margin_value: number; margin_pct: number | null
    marked_count: number; units_positive: number
  }
}

export const getStoreStock = (opts?: {
  warehouse?: string; q?: string; marked?: SalesMarked; onlyNegative?: boolean
}) =>
  get<StoreStockData>('/api/store/stock', {
    warehouse: opts?.warehouse || undefined,
    q: opts?.q || undefined,
    marked: opts?.marked && opts.marked !== 'all' ? opts.marked : undefined,
    only_negative: opts?.onlyNegative ? 'true' : undefined,
  })

// ── Инвентаризация: реестр + отклонения (недостачи/излишки, shrinkage) ──
export interface StoreInventoryLine {
  ref: string; name: string
  fact: number; uchet: number; dev: number; amount_dev: number
}
export interface StoreInventoryDoc {
  ref: string; number: string | null; date: string | null
  warehouse_code: string; warehouse_name: string | null; comment: string | null
  dev_positions: number
  shortage_qty: number; shortage_amount: number
  surplus_qty: number; surplus_amount: number; net_amount: number
  lines: StoreInventoryLine[]
}
export interface StoreInventoryData {
  warehouse: string | null
  warehouses: { code: string; name: string | null; count: number }[]
  docs: StoreInventoryDoc[]
  top_shortage: { name: string; qty: number; amount: number; docs: number }[]
  summary: {
    docs_count: number; docs_with_dev: number
    shortage_amount: number; surplus_amount: number; net_amount: number
    period_from: string | null; period_to: string | null
  }
}

export const getStoreInventory = (opts?: { warehouse?: string; onlyDev?: boolean }) =>
  get<StoreInventoryData>('/api/store/inventory', {
    warehouse: opts?.warehouse || undefined,
    only_dev: opts?.onlyDev ? 'true' : undefined,
  })

// ── Списания: реестр + причины (недостача/брак/срок/…) + топ SKU ──
export interface StoreWriteoffLine { ref: string; name: string; qty: number; amount: number; price: number }
export interface StoreWriteoffDoc {
  ref: string; number: string | null; date: string | null
  warehouse_code: string; warehouse_name: string | null
  reason: string | null; from_inventory: boolean; comment: string | null
  positions: number; total_qty: number; total_amount: number
  lines: StoreWriteoffLine[]
}
export interface StoreWriteoffData {
  warehouse: string | null
  warehouses: { code: string; name: string | null; count: number }[]
  docs: StoreWriteoffDoc[]
  by_reason: { reason: string; count: number; amount: number }[]
  top_sku: { name: string; qty: number; amount: number; docs: number }[]
  summary: {
    docs_count: number; total_amount: number
    from_inventory_amount: number; other_amount: number
    period_from: string | null; period_to: string | null
  }
}

export const getStoreWriteoffs = (opts?: { warehouse?: string; reason?: string }) =>
  get<StoreWriteoffData>('/api/store/writeoffs', {
    warehouse: opts?.warehouse || undefined,
    reason: opts?.reason || undefined,
  })

// ── Перемещения: реестр откуда→куда + направления ──
export interface StoreTransferLine { ref: string; name: string; qty: number; price: number; amount: number }
export interface StoreTransferDoc {
  ref: string; number: string | null; date: string | null
  from_code: string; from_name: string | null; to_code: string | null; to_name: string | null
  direction: string | null; comment: string | null
  positions: number; total_qty: number; total_amount: number
  lines: StoreTransferLine[]
}
export interface StoreTransferData {
  direction: string | null
  docs: StoreTransferDoc[]
  by_direction: { direction: string; count: number; amount: number }[]
  top_sku: { name: string; qty: number; amount: number; docs: number }[]
  summary: {
    docs_count: number; total_amount: number
    inbound_amount: number; outbound_amount: number; internal_amount: number
    period_from: string | null; period_to: string | null
  }
}

export const getStoreTransfers = (opts?: { direction?: string }) =>
  get<StoreTransferData>('/api/store/transfers', {
    direction: opts?.direction || undefined,
  })

// ── Переоценка: изменения цен (старая→новая, Δ%) + подорожания/удешевления ──
export interface StoreRevalLine { ref: string; name: string; old: number; new: number; delta: number; pct: number | null; qty: number }
export interface StoreRevalMove { name: string; old: number; new: number; delta: number; pct: number | null }
export interface StoreRevalDoc {
  ref: string; number: string | null; date: string | null
  warehouse_code: string; warehouse_name: string | null
  reason: string | null; comment: string | null
  positions: number; up_count: number; value_impact: number
  lines: StoreRevalLine[]
}
export interface StoreRevaluationData {
  reason: string | null
  docs: StoreRevalDoc[]
  by_reason: { reason: string; count: number }[]
  top_up: StoreRevalMove[]
  top_down: StoreRevalMove[]
  summary: {
    docs_count: number; up_lines: number; down_lines: number
    avg_pct: number | null; value_impact: number
    period_from: string | null; period_to: string | null
  }
}

export const getStoreRevaluation = (opts?: { reason?: string }) =>
  get<StoreRevaluationData>('/api/store/revaluation', {
    reason: opts?.reason || undefined,
  })

// ── Общепит: инжиниринг меню (продажи блюд + состав ТТК + динамика) ──
export type MenuClass = 'star' | 'plowhorse' | 'puzzle' | 'dog' | 'unknown'
export interface CateringIngredient {
  ref: string; name: string; marked: boolean
  qty_total: number; qty_per_portion: number | null
  cost_total: number | null; cost_per_portion: number | null
}
export interface CateringDaily { date: string; qty: number; revenue: number }
export interface CateringDish {
  guid: string; name: string
  qty: number; revenue: number; revenue_net: number; avg_price: number
  cost: number | null; cost_per_portion: number | null
  margin: number | null; food_cost_pct: number | null; margin_pct: number | null; cm_unit: number | null
  share: number; popularity_pct: number; menu_class: MenuClass
  ing_count: number; ingredients: CateringIngredient[]; daily: CateringDaily[]
}
export interface CateringMenuData {
  period: { from: string; to: string }
  summary: {
    dishes_count: number; dishes_costed: number
    revenue: number; revenue_net: number; portions: number
    cost: number; margin: number; food_cost_pct: number | null; margin_pct: number | null
  }
  matrix: Partial<Record<MenuClass, { count: number; revenue: number }>>
  dishes: CateringDish[]
}

export const getStoreCateringMenu = (dateFrom: string, dateTo: string, stations?: string[]) =>
  get<CateringMenuData>('/api/store/catering', {
    date_from: dateFrom, date_to: dateTo,
    stations: stations?.length ? stations.join(',') : undefined,
  })

// ── Цены и маржа: сегмент + группы + реестр SKU + детализация товара ──
export interface PricingSku extends StoreSku { kind: string }
export interface PricingGroup {
  group: string; revenue: number; revenue_net: number; qty: number
  sku_count: number; share: number; margin: number | null; margin_pct: number | null
}
export interface PricingData {
  period: { from: string; to: string }
  category: string
  summary: {
    sku_count: number; sku_costed: number; revenue: number; revenue_net: number
    cogs: number; margin: number; margin_pct: number | null; markup_pct: number | null; loss_makers: number
  }
  by_category: PricingGroup[]
  by_kind: PricingGroup[]
  skus: PricingSku[]
}

export const getStorePricing = (dateFrom: string, dateTo: string, category: PriceCategory = 'all') =>
  get<PricingData>('/api/store/pricing', { date_from: dateFrom, date_to: dateTo, category })

export type PriceCategory = 'all' | 'soputka' | 'obshepit'

// ── Ассортимент: ABC×XYZ + оборачиваемость/запасы + GMROI + action-list ──
export type StockStatus = 'ok' | 'dead' | 'out_of_stock' | 'overstock'
export interface AssortmentSku {
  guid: string; name: string; category: string | null
  revenue: number; qty: number; avg_price: number
  margin: number | null; margin_pct: number | null; marked: boolean
  abc: 'A' | 'B' | 'C'; xyz: 'X' | 'Y' | 'Z'; cv: number | null; abc_xyz: string
  stock_qty: number; stock_cost: number; stock_retail: number
  days_of_supply: number | null; gmroi: number | null; status: StockStatus; action: string
}
export interface AssortmentData {
  period: { from: string; to: string }
  category: string
  summary: {
    sku_count: number; stock_cost: number; stock_retail: number; gmroi: number | null
    dead_count: number; dead_cost: number; oos_count: number
    overstock_count: number; overstock_cost: number
  }
  abc: Record<'A' | 'B' | 'C', { count: number; revenue: number; share: number }>
  matrix: Record<string, { count: number; revenue: number }>
  skus: AssortmentSku[]
}

export const getStoreAssortment = (dateFrom: string, dateTo: string, category: PriceCategory = 'all') =>
  get<AssortmentData>('/api/store/assortment', { date_from: dateFrom, date_to: dateTo, category })

export interface SkuDetailData {
  guid: string; name: string; article: string | null; vat: string | null
  marked: boolean; weighed: boolean; kind: string | null; category: string | null
  metrics: {
    qty: number; revenue: number; revenue_net: number; avg_price: number | null
    avg_cost: number | null; cogs: number | null; margin: number | null
    margin_pct: number | null; markup_pct: number | null; purch_qty: number
  }
  daily: { date: string; qty: number; revenue: number }[]
  purchases: { date: string; supplier: string; qty: number; price_net: number | null; amount_net: number }[]
  price_history: { date: string | null; old: number; new: number; delta: number; pct: number | null }[]
  stock: { warehouse: string; qty: number; retail_price: number | null; cost_unit: number | null }[]
}

export const getStoreSkuDetail = (guid: string, dateFrom: string, dateTo: string) =>
  get<SkuDetailData>(`/api/store/sku/${encodeURIComponent(guid)}`, { date_from: dateFrom, date_to: dateTo })

// ── Номенклатура: полный справочник НСИ + фильтры ──
export interface StoreNomenclatureItem {
  guid: string; name: string; article: string | null; vat: string | null
  marked: boolean; weighed: boolean; kind: string; has_barcode: boolean
  revenue: number; qty: number
}
export interface StoreNomenclatureData {
  items: StoreNomenclatureItem[]
  summary: { total: number; marked: number; weighed: number; with_sales: number; with_barcode: number }
  kinds: string[]
}

export const getStoreNomenclature = (
  dateFrom: string, dateTo: string,
  opts: { kind?: string; marked?: SalesMarked; weighed?: string; hasSales?: string; q?: string; stations?: string[] },
) =>
  get<StoreNomenclatureData>('/api/store/nomenclature', {
    date_from: dateFrom,
    date_to: dateTo,
    kind: opts.kind && opts.kind !== 'all' ? opts.kind : undefined,
    marked: opts.marked && opts.marked !== 'all' ? opts.marked : undefined,
    weighed: opts.weighed && opts.weighed !== 'all' ? opts.weighed : undefined,
    has_sales: opts.hasSales && opts.hasSales !== 'all' ? opts.hasSales : undefined,
    q: opts.q || undefined,
    stations: opts.stations?.length ? opts.stations.join(',') : undefined,
  })
