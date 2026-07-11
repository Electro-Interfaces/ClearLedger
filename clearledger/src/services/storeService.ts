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
  retail_price: number | null; retail_value: number | null; cost_amount: number | null
}
export interface StoreStockWarehouse { code: string; name: string | null; sku: number; retail_value: number }
export interface StoreStockData {
  warehouse: string | null
  warehouses: StoreStockWarehouse[]
  items: StoreStockItem[]
  summary: {
    sku_count: number; positive: number; negative: number
    retail_value_positive: number; retail_value_all: number; marked_count: number; units_positive: number
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
