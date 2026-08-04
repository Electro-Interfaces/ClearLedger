/**
 * Клиент аналитики раздела «Магазин» (сопутка/общепит).
 * Пока — «Обзор магазина» (/api/store/overview → GoodsDashboardService).
 */
import { get, put, post, upload } from './apiClient'

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
    payments_detail: { name: string; value: number }[]
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
  docs: {
    date: string; number: string; supplier: string; positions: number
    /** Номер смены: поступления приезжают из ЦБ вместе со сменным отчётом. */
    shift_number?: string | null
    amount: number; vat: number; amount_net: number
    lines: ShiftDocLine[]   // состав накладной — расшифровка строки реестра и поставщика
  }[]
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
  items: { barcode: string; owner_name: string; type: string | null; main: boolean; owner_guid: string | null }[]
}
export interface StoreRecipesData {
  period: { from: string; to: string }
  recipes: { guid: string; name: string; ingredients: { name: string; qty: number }[]; ing_count: number }[]
  summary: { count: number }
}

export const getStoreReport = <T>(report: string, dateFrom: string, dateTo: string, stations?: string[]) =>
  get<T>(`/api/store/${report}`, {
    date_from: dateFrom,
    date_to: dateTo,
    stations: stations?.length ? stations.join(',') : undefined,
  })

/** Штрихкоды — справочник-снимок НСИ: ни периода, ни станций у сущности нет. */
export const getStoreBarcodes = () => get<StoreBarcodesData>('/api/store/barcodes')

// ── Продажи: гибкая группировка (инструмент менеджера) ──
export type SalesGroupBy = 'sku' | 'category' | 'kind' | 'marking' | 'vat' | 'day' | 'shift' | 'payment'
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
  /** Что РЕАЛЬНО применено к выборке (может отличаться от запрошенного). */
  filters: { category: string; marked: string; q: string }
  /** Запрошенные, но неприменимые в этом разрезе фильтры (напр. товарные в разрезе «форма оплаты»). */
  filters_ignored?: string[]
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
  /** Базовая единица регистра: остаток весового товара хранится в мл/г, не в упаковках. */
  unit: string | null
  /** Заполнено, если партийной себестоимости верить нельзя (причина словами). */
  cost_doubt: string | null
  /** Средняя закупка по накладным — то, с чем сверялась партия. */
  buy_unit: number | null
}
export interface StoreStockWarehouse {
  code: string; name: string | null; sku: number
  station_id?: number; place_code?: string
  positive: number   // сколько позиций реально на полке — остальное отрицательные хвосты
  retail_value: number
}
export interface StoreStockData {
  source?: 'edge_agent' | 'legacy_cb_snapshot'
  warehouse: string | null
  warehouses: StoreStockWarehouse[]
  items: StoreStockItem[]
  /** F3: дата последнего снимка данных (ISO) — для индикации свежести. */
  snapshot_at?: string | null
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
  /** Смена(ы) дня, к которым относится документ (у витринных есть только дата). */
  shift_number?: string | null; shift_key?: string | null
  shift_count?: number; shift_reason?: string | null
  warehouse_code: string; warehouse_name: string | null; comment: string | null
  dev_positions: number
  shortage_qty: number; shortage_amount: number
  surplus_qty: number; surplus_amount: number; net_amount: number
  lines: StoreInventoryLine[]
}
export interface StoreInventoryData {
  /** F3: дата последнего снимка данных (ISO). */
  snapshot_at?: string | null
  warehouse: string | null
  warehouses: { code: string; name: string | null; count: number }[]
  docs: StoreInventoryDoc[]
  top_shortage: { ref?: string | null; name: string; qty: number; amount: number; docs: number }[]
  summary: {
    docs_count: number; docs_with_dev: number
    shortage_amount: number; surplus_amount: number; net_amount: number
    period_from: string | null; period_to: string | null
  }
}

export const getStoreInventory = (opts?: { warehouse?: string; onlyDev?: boolean; dateFrom?: string; dateTo?: string }) =>
  get<StoreInventoryData>('/api/store/inventory', {
    warehouse: opts?.warehouse || undefined,
    only_dev: opts?.onlyDev ? 'true' : undefined,
    date_from: opts?.dateFrom || undefined, date_to: opts?.dateTo || undefined,
  })

// ── Списания: реестр + причины (недостача/брак/срок/…) + топ SKU ──
export interface StoreWriteoffLine { ref: string; name: string; qty: number; amount: number; price: number }
export interface StoreWriteoffDoc {
  ref: string; number: string | null; date: string | null
  /** Смена(ы) дня, к которым относится документ (у витринных есть только дата). */
  shift_number?: string | null; shift_key?: string | null
  shift_count?: number; shift_reason?: string | null
  warehouse_code: string; warehouse_name: string | null
  reason: string | null; from_inventory: boolean; comment: string | null
  positions: number; total_qty: number; total_amount: number
  lines: StoreWriteoffLine[]
}
export interface StoreWriteoffData {
  /** F3: дата последнего снимка данных (ISO). */
  snapshot_at?: string | null
  warehouse: string | null
  warehouses: { code: string; name: string | null; count: number }[]
  docs: StoreWriteoffDoc[]
  by_reason: { reason: string; count: number; amount: number }[]
  top_sku: { ref?: string | null; name: string; qty: number; amount: number; docs: number }[]
  summary: {
    docs_count: number; total_amount: number
    from_inventory_amount: number; other_amount: number
    period_from: string | null; period_to: string | null
  }
}

export const getStoreWriteoffs = (opts?: { warehouse?: string; reason?: string; dateFrom?: string; dateTo?: string }) =>
  get<StoreWriteoffData>('/api/store/writeoffs', {
    warehouse: opts?.warehouse || undefined,
    reason: opts?.reason || undefined,
    date_from: opts?.dateFrom || undefined, date_to: opts?.dateTo || undefined,
  })

// ── Перемещения: реестр откуда→куда + направления ──
export interface StoreTransferLine { ref: string; name: string; qty: number; price: number; amount: number }
export interface StoreTransferDoc {
  ref: string; number: string | null; date: string | null
  /** Смена(ы) дня, к которым относится документ (у витринных есть только дата). */
  shift_number?: string | null; shift_key?: string | null
  shift_count?: number; shift_reason?: string | null
  from_code: string; from_name: string | null; to_code: string | null; to_name: string | null
  direction: string | null; comment: string | null
  positions: number; total_qty: number; total_amount: number
  lines: StoreTransferLine[]
}
export interface StoreTransferData {
  /** F3: дата последнего снимка данных (ISO). */
  snapshot_at?: string | null
  direction: string | null
  docs: StoreTransferDoc[]
  by_direction: { direction: string; count: number; amount: number }[]
  top_sku: { ref?: string | null; name: string; qty: number; amount: number; docs: number }[]
  summary: {
    docs_count: number; total_amount: number
    inbound_amount: number; outbound_amount: number; internal_amount: number
    period_from: string | null; period_to: string | null
  }
}

export const getStoreTransfers = (opts?: { direction?: string; dateFrom?: string; dateTo?: string }) =>
  get<StoreTransferData>('/api/store/transfers', {
    direction: opts?.direction || undefined,
    date_from: opts?.dateFrom || undefined, date_to: opts?.dateTo || undefined,
  })

// ── Переоценка: изменения цен (старая→новая, Δ%) + подорожания/удешевления ──
export interface StoreRevalLine { ref: string; name: string; old: number; new: number; delta: number; pct: number | null; qty: number }
export interface StoreRevalMove {
  name: string; old: number; new: number; delta: number; pct: number | null
  /** GUID номенклатуры — ключ строки и вход в карточку товара. */
  ref?: string | null
  /** Базовая единица: у весового товара это грамм, без неё цена читается неверно. */
  unit?: string | null
  /** Во сколько обошлась переоценка: разница цены × количество в документе. */
  amount?: number | null
}
export interface StoreRevalDoc {
  ref: string; number: string | null; date: string | null
  warehouse_code: string; warehouse_name: string | null
  reason: string | null; comment: string | null
  positions: number; up_count: number; value_impact: number
  lines: StoreRevalLine[]
}
export interface StoreRevaluationData {
  /** F3: дата последнего снимка данных (ISO). */
  snapshot_at?: string | null
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

export const getStoreRevaluation = (opts?: { reason?: string; dateFrom?: string; dateTo?: string }) =>
  get<StoreRevaluationData>('/api/store/revaluation', {
    reason: opts?.reason || undefined,
    date_from: opts?.dateFrom || undefined, date_to: opts?.dateTo || undefined,
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
  coverage: number; ing_count: number; ingredients: CateringIngredient[]; daily: CateringDaily[]
  /** Откуда себестоимость: 'release' — выпуск 1С (рецептура в момент продажи, готовая
   *  цифра), 'ttk' — сборка из средних закупок по составу. Покрытие ТТК к release
   *  отношения не имеет: 80% состава с ценой не делают цифру 1С неполной. */
  cost_source: 'release' | 'ttk' | null
  preliminary: boolean
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

export const getStorePricing = (dateFrom: string, dateTo: string, category: PriceCategory = 'all', stations?: string[]) =>
  get<PricingData>('/api/store/pricing', {
    date_from: dateFrom, date_to: dateTo, category,
    stations: stations?.length ? stations.join(',') : undefined,
  })

export type PriceCategory = 'all' | 'soputka' | 'obshepit'

// ── Ассортимент: ABC×XYZ + оборачиваемость/запасы + GMROI + action-list ──
export type StockStatus = 'ok' | 'dead' | 'out_of_stock' | 'overstock'
export interface AssortmentSku {
  guid: string; name: string; category: string | null
  revenue: number; qty: number; avg_price: number
  margin: number | null; margin_pct: number | null; marked: boolean
  cost_reliable: boolean
  abc: 'A' | 'B' | 'C'; xyz: 'X' | 'Y' | 'Z'; cv: number | null; abc_xyz: string
  stock_qty: number; stock_cost: number; stock_retail: number
  days_of_supply: number | null; gmroi: number | null; status: StockStatus; loss: boolean; action: string
}
export interface AssortmentData {
  period: { from: string; to: string }
  category: string
  summary: {
    sku_count: number; stock_cost: number; stock_retail: number; gmroi: number | null
    dead_count: number; dead_cost: number; oos_count: number; loss_count: number
    overstock_count: number; overstock_cost: number
  }
  abc: Record<'A' | 'B' | 'C', { count: number; revenue: number; share: number }>
  matrix: Record<string, { count: number; revenue: number }>
  skus: AssortmentSku[]
}

export const getStoreAssortment = (dateFrom: string, dateTo: string, category: PriceCategory = 'all', stations?: string[]) =>
  get<AssortmentData>('/api/store/assortment', {
    date_from: dateFrom, date_to: dateTo, category,
    stations: stations?.length ? stations.join(',') : undefined,
  })

export interface SkuDetailData {
  guid: string; name: string; article: string | null; vat: string | null
  marked: boolean; weighed: boolean; unit: string | null; kind: string | null; category: string | null
  full_name?: string | null; main_supplier?: string | null
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
  marked: boolean; weighed: boolean; kind: string; unit: string | null; has_barcode: boolean
  revenue: number; qty: number
  stock_qty: number; retail_price: number | null
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

// ── Слой политик: план продаж + план-факт-светофор (О-1) ──
export type PlanScopeKind = 'total' | 'category' | 'station'
export type PlanMetric = 'revenue' | 'qty'
export type PlanTraffic = 'green' | 'amber' | 'red'

export interface PlanRow {
  scope_kind: PlanScopeKind
  scope_key: string
  metric: PlanMetric
  plan_value: number
}
export interface StorePlanData { period: string; plans: PlanRow[] }

export interface PlanFactCard {
  scope_kind: PlanScopeKind
  scope_key: string
  label: string
  metric: PlanMetric
  fact: number
  plan: number | null
  pct: number | null
  traffic: PlanTraffic | null
  delta: number | null
  sparkline?: { date: string; value: number }[]
}
export interface PlanFactsData {
  period: { ym: string; from: string; to: string }
  total: PlanFactCard
  units: PlanFactCard
  by_category: PlanFactCard[]
  by_station: PlanFactCard[]
  has_plan: boolean
  planned_count: number
}

/** Месяц 'YYYY-MM' из ISO-даты (для привязки монитора к периоду фильтра). */
export const monthOf = (iso: string): string => (iso || '').slice(0, 7)

export const getStorePlanFacts = (period: string) =>
  get<PlanFactsData>('/api/store/plan-facts', { period })

export const getStorePlan = (period: string) =>
  get<StorePlanData>('/api/store/plan', { period })

export const saveStorePlan = (period: string, items: PlanRow[]) =>
  put<StorePlanData>('/api/store/plan', { period, items })

// ── МРЦ табака: регуляторный контроль «продажа выше МРЦ» (О-3) ──
export interface MrcItem {
  ref: string
  name: string
  barcode: string | null
  mrc: number
  retail_price: number | null
  over: boolean
  diff: number | null
}
export interface MrcData {
  items: MrcItem[]
  summary: { controlled: number; violations: number; missing_price: number; missing_mrc: number }
}
export interface MrcImportRow { barcode?: string; article?: string; name?: string; mrc: number | string }
export interface MrcImportResult { imported: number; unresolved_count: number; unresolved: MrcImportRow[] }

export const getStoreMrc = () => get<MrcData>('/api/store/mrc')

export const importStoreMrc = (rows: MrcImportRow[]) =>
  post<MrcImportResult>('/api/store/mrc/import', { rows })

// ── Смены как составной документ: роллап операций на смену (архитектура) ──
export interface ShiftComposite {
  shift_key: string
  date: string
  station: string
  number: string | null
  open: string | null
  close: string | null
  revenue: number
  soputka: number
  obshepit: number
  positions: number
  returns: number
  receipts_amount: number
  receipts_count: number
  inventory_count: number
  inventory_net: number
  writeoff_amount: number
  writeoff_count: number
  transfer_count: number
  transfer_amount: number
  reval_count: number
}
export interface ShiftsData {
  period: { from: string; to: string }
  shifts: ShiftComposite[]
  summary: {
    count: number; revenue: number; returns: number
    receipts_amount: number; inventory_docs: number; inventory_net: number; writeoff_amount: number
    transfer_docs: number; reval_docs: number
  }
}

export const getStoreShifts = (dateFrom: string, dateTo: string, stations?: string[]) =>
  get<ShiftsData>('/api/store/shifts', {
    date_from: dateFrom, date_to: dateTo,
    stations: stations?.length ? stations.join(',') : undefined,
  })

// ── Выгрузка пакетов ЦБ→БП (эмиттер Ledger — замена TL_ЭкспортБП) ──
// Приёмник TradeLedger.cfe (TL_СопуткаСервис.ОбработатьПакетИзСтроки) не меняется.
export interface BpPackageDoc {
  Тип: string
  ИсточникUUID?: string
  Номер?: string
  СуммаДокумента?: number
  [k: string]: unknown
}
export interface BpNsiItem { Тип: string; [k: string]: unknown }
export interface BpPackage {
  ВерсияФормата: string
  ВремяВыгрузки?: string
  ИдентификаторПакета: string
  Источник?: string
  Смена: Record<string, unknown>
  Документы: BpPackageDoc[]
  НСИ: BpNsiItem[]
  ХешПакета: string
}
export interface BpEmitResult {
  file: string; path: string; hash: string
  documents: Record<string, number>; nsi: number
}
export const getBpPackage = (shiftKey: string) =>
  get<BpPackage>('/api/store/bp-package', { shift_key: shiftKey })
export const emitBpPackage = (shiftKey: string) =>
  // каталог задаёт сервер (BP_EXPORT_DIR), клиент путь не передаёт (directory-injection закрыта)
  post<BpEmitResult>(`/api/store/bp-package/emit?shift_key=${encodeURIComponent(shiftKey)}`)

export interface BpVerifyCheck { Проверка: string; ok: boolean; Детали: string }
export interface BpVerifyResult {
  shift_key: string; ok: boolean; passed: number; total: number
  Документов: number; НСИ: number; ХешПакета: string; КодАЗС?: string | number
  checks: BpVerifyCheck[]
}
export const getBpPackageVerify = (shiftKey: string) =>
  get<BpVerifyResult>('/api/store/bp-package/verify', { shift_key: shiftKey })

// ── Смена-детализация (модалка): операции одной смены ──
export interface ShiftSaleLine { guid: string; name: string; category: string | null; marked: boolean; qty: number; revenue: number }
export interface ShiftPayment { form: string; amount: number }
export interface ShiftDocLine {
  /** GUID товара — есть не у всех документов; по нему строка открывает карточку. */
  ref?: string | null
  name: string | null; qty?: number | null; price?: number | null; amount?: number | null
  fact?: number | null; uchet?: number | null; dev?: number | null; old?: number | null; new?: number | null; pct?: number | null
}
export interface ShiftReceipt { number: string | null; supplier: string; positions: number; amount_net: number; lines: ShiftDocLine[] }
export interface ShiftInventory { number: string | null; dev_positions: number; net: number; lines: ShiftDocLine[] }
export interface ShiftWriteoff { number: string | null; reason: string | null; positions: number; amount: number; lines: ShiftDocLine[] }
export interface ShiftTransfer { number: string | null; to: string | null; positions: number; amount: number; lines: ShiftDocLine[] }
export interface ShiftReval { number: string | null; positions: number; lines: ShiftDocLine[] }
export interface ShiftDetailData {
  found: boolean
  shift_key?: string
  shift?: {
    shift_key: string; date: string; station: string; number: string | null
    open: string | null; close: string | null
    revenue: number; soputka: number; obshepit: number; positions: number; returns: number
  }
  sales?: ShiftSaleLine[]
  payments?: ShiftPayment[]
  receipts?: ShiftReceipt[]
  inventory?: ShiftInventory[]
  writeoffs?: ShiftWriteoff[]
  transfers?: ShiftTransfer[]
  revaluations?: ShiftReval[]
}

export const getStoreShiftDetail = (key: string) =>
  get<ShiftDetailData>('/api/store/shift', { key })

// ── Полная карточка номенклатуры (товаровед): sku_detail + паспорт/ШК/движение/ТТК/МРЦ ──
export interface SkuBarcode { barcode: string; type: string | null; main: boolean }
export interface SkuMovementRow {
  kind: 'writeoff' | 'transfer' | 'inventory'
  date: string | null; number: string | null
  qty: number | null; amount: number | null; reason: string | null
}
export interface SkuCardData extends SkuDetailData {
  group: string | null
  barcodes: SkuBarcode[]
  mrc: { mrc: number; retail_price: number | null; over: boolean } | null
  recipe: { name: string; qty: number }[]
  movement: SkuMovementRow[]
}

export const getStoreSkuCard = (guid: string, dateFrom: string, dateTo: string) =>
  get<SkuCardData>(`/api/store/sku-card/${encodeURIComponent(guid)}`, { date_from: dateFrom, date_to: dateTo })

/* ─────────────────────────── Контроль дублей ──────────────────────────── */
export interface DedupSummary {
  cardsTotal: number; cardsMarked: number; byPrefix: Record<string, number>
  dupGroups: number; excessCards: number; liveDupGroups: number; assortmentCards: number
  scopedGroups: number; outOfScopeGroups: number
  priceDesyncGroups: number
  nsActive: number; nsOnMarked: number; multiCodeCards: number; cbLinked: number
  /** Аномалии связи с ЦБ: карточка заведена локально и не уехала / код разошёлся. */
  cbMissing: number; cbCodeDiff: number
  /** Групп в архиве (снята с продажи — не удаление, история сохраняется). Статус not_used. */
  notUsedGroups: number
  /** Групп контура 208 с принятым решением (любой статус, кроме pending/in_progress). */
  scopedResolved: number
  /** Факты эры/остатка загружены (иначе era/ostatok = null, бейджи скрыты). */
  factsLoaded: boolean
  /** Карточек по эре продаж (День X): при ГИГ / только Норд-Лайн / никогда (фантом). */
  eraGig: number; eraNl: number; eraNever: number
  updatedAt: string | null
}
/** Код кассы живёт в разрезе склада: один и тот же код на другом складе — другой товар. */
export interface DedupNsCode { nsCode: string; wh: string | null; active: boolean; price: number | null }
export interface DedupMember {
  guid: string; code: string | null; prefix: string | null; name: string
  marked: boolean; group: string | null; price: number | null
  soldQty: number | null; sellsNow: boolean
  nsCodes: DedupNsCode[]; nsActive: boolean; inCb: boolean
  /** База 208 — узел РИБ центральной, поэтому «есть в ЦБ» верно для 99,96%.
   *  Значение несёт только аномалия. */
  cbStatus: 'ok' | 'missing' | 'code_diff'
  /** Эра продаж относительно Дня X (11.06.2026): gig — при ГИГ, nl — только под
   *  Норд-Лайн (наследие), never — не торговалось (фантом РИБ). null — факты не загружены. */
  era: 'gig' | 'nl' | 'never' | null
  /** Текущий остаток на складе 208. null — факты не загружены. */
  ostatok: number | null
}
export interface DedupGroup {
  key: string; title: string; count: number; live: number; assortment: boolean
  prefixes: string[]
  /** Касса 208 работает через группу (активный код склада 208 либо продажи). */
  inScope208: boolean
  /** Настоящий конфликт: касса 208 бьёт 2+ карточки группы по разным ценам. */
  priceSpread: number[]
  /** Цены на карточках без кодов кассы — застывшее наследие, на чек не влияет. */
  stalePrices: number[]
  sellingCount: number; recommendedCanon: string | null
  members: DedupMember[]
  status: string; canonGuid: string | null; note: string | null
  /** Имя карточки-канона (в т.ч. если канон в соседней группе). */
  canonName?: string | null
  /** Канон-хозяин лежит вне этой группы (нормализация имени развела дубли). */
  canonExternal?: boolean
  /** Эра группы = самая «живая» среди карточек (gig>nl>never). null — факты не загружены. */
  era?: 'gig' | 'nl' | 'never' | null
  /** Суммарный остаток карточек группы на складе 208. */
  ostatok?: number | null
}
export interface DedupBridgeRow {
  nsCode?: string; warehouse?: string; cardGuid?: string; cardName?: string
  price?: number | null; barcode?: string; codes?: number; nsCodes?: string[]
  prices?: number[]; marked?: boolean
}
export interface DedupExportRow {
  group: string; status: string; priceSpread: string
  dupGuid: string; dupCode: string | null; dupName: string; dupMarked: boolean
  dupPrice: number | null; dupNsCodes: string[]
  canonGuid: string; canonCode: string | null; canonName: string | null; canonPrice: number | null
}

export const getDedupSummary = () => get<DedupSummary>('/api/store/dedup/summary')
export const getDedupGroups = (p?: { q?: string; includeAssortment?: boolean; onlyLive?: boolean; priceDesync?: boolean; onlyScope208?: boolean; status?: string; era?: string }) =>
  get<DedupGroup[]>('/api/store/dedup/groups', {
    q: p?.q || undefined,
    include_assortment: p?.includeAssortment ? 'true' : undefined,
    only_live: p?.onlyLive ? 'true' : undefined,
    price_desync: p?.priceDesync ? 'true' : undefined,
    // бэкенд по умолчанию режет не-208 — гасим явно, когда менеджер снял галку
    only_scope_208: p?.onlyScope208 === false ? 'false' : undefined,
    status: p?.status || undefined,
    era: p?.era || undefined,
  })
export const loadDedupFacts = (file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return upload<{ cards: number; gig: number; never: number; ost: number }>('/api/store/dedup/facts', fd)
}
export const reloadDedup = (file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return upload<{ cards: number; bindings: number; prices: number; cb: number }>('/api/store/dedup/reload', fd)
}
export const getDedupBridge = (kind: 'on_marked' | 'multi' | 'price_split') =>
  get<DedupBridgeRow[]>('/api/store/dedup/bridge', { kind })
export const setDedupStatus = (body: { entityType: 'group' | 'card'; entityKey: string; status?: string; canonGuid?: string | null; note?: string }) =>
  post<{ status: string; canonGuid: string | null; note: string | null; history: unknown[] }>('/api/store/dedup/status', body)
export const getDedupExport = () => get<DedupExportRow[]>('/api/store/dedup/export')

export interface DedupJob {
  id: string; kind: string; status: string; dryRun: boolean
  warehouse: string | null; groups: number; codes: number; titles: string[]
  result: { done?: number; failed?: number; log?: string[]; error?: string } | null
  createdBy: string | null; createdAt: string | null; executedAt: string | null
}
export interface DedupMergeRow {
  dupGuid: string; dupCode: string | null; dupName: string
  canonGuid: string; canonCode: string | null; canonName: string | null
}
/** Команда менеджера: станция сама снимет свежий срез с локальной 1С и зальёт его сюда. */
export const refreshDedup = () =>
  post<{ jobId: string; already: boolean; note?: string }>('/api/store/dedup/refresh', {})
/** Команда менеджера: перецеп кодов кассы на канон по выбранным группам (нода 208 выполнит). */
export const correctDedup = (body: { groupKeys: string[]; dryRun: boolean }) =>
  post<{ jobId?: string; groups?: number; codes?: number; skipped?: { key: string; why: string }[]; error?: string }>(
    '/api/store/dedup/correct', body)
export const getDedupJobs = () => get<DedupJob[]>('/api/store/dedup/jobs')
export const cancelDedupJob = (id: string) => post<{ ok: boolean }>(`/api/store/dedup/jobs/${id}/cancel`, {})
export const getDedupMergeMap = (groupKeys?: string[]) =>
  get<DedupMergeRow[]>('/api/store/dedup/merge-map', groupKeys?.length ? { group_keys: groupKeys.join('|') } : undefined)

/** Строка плана «снять с продажи»: код кассы 208 на деактивацию по архивной карточке. */
export interface DedupDeactivationRow {
  group: string; note: string | null
  cardGuid: string; cardCode: string | null; cardName: string
  nsCode: string; price: number | null
  ostatok: number | null; era: 'gig' | 'nl' | 'never' | null
  marked: boolean
}
export const getDedupDeactivationPlan = () =>
  get<DedupDeactivationRow[]>('/api/store/dedup/deactivation-plan')


/** Станция глазами центра: связь агента, версия кода, очередь пакетов. */
export interface StoreStation {
  station_id: number
  /** «онлайн» — отвечал в последние 3 минуты; «офлайн» — молчит; «молчит» — больше часа. */
  state: string
  silence_seconds: number | null
  version: string | null
  version_ok: boolean
  queue_pending: number
  queue_sent: number
  last_shift: number | null
  snapshot_at: string | null
  onec_ok: boolean | null
  ledger_stock_ok: boolean
  stock_source: string | null
  cash_policy: {
    policy_id: string; checked_at: string; mode: 'dry-run'; ready: boolean
    missing: number; extra: number; price_diff: number; code_diff: number; skipped: number
  } | null
  last_seen: string
  first_seen: string
}

export interface StoreStationsData {
  desired_version: string
  total: number
  online: number
  queue_total: number
  version_mismatch: number
  stations: StoreStation[]
}

export const getStoreStations = () => get<StoreStationsData>('/api/store/stations')

/** Обмен станции с центром за период: сеансы, пакеты, объём, очередь вниз. */
export interface StoreExchangeStation {
  station_id: number
  state: string
  silence_seconds: number | null
  version: string | null
  queue_pending: number
  queue_sent: number
  last_shift: number | null
  snapshot_at: string | null
  packets: number
  bytes: number
  sessions: number
  last_packet_at: string | null
  down_waiting: number
  down_unacked: number
  down_acked: number
}

export interface StoreExchangeData {
  from: string
  to: string
  session_gap_minutes: number
  totals: {
    packets: number; bytes: number; sessions: number; online: number; stations: number
    queue_pending: number; down_waiting: number; down_unacked: number
    last_packet_at: string | null
  }
  by_kind: { kind: string; label: string; packets: number; bytes: number; last_at: string }[]
  by_day: { day: string; packets: number; bytes: number }[]
  stations: StoreExchangeStation[]
  recent: {
    at: string; station_id: number; kind: string; label: string
    size_bytes: number; direction: 'вверх' | 'вниз'; note: string | null
  }[]
}

export const getStoreExchange = (dateFrom: string, dateTo: string) =>
  get<StoreExchangeData>(`/api/store/exchange?date_from=${dateFrom}&date_to=${dateTo}`)

/** Детализация обмена одной станции: сеансы поимённо, состав, канал вниз. */
export interface StoreExchangeSession {
  session_no: number
  started: string
  finished: string
  duration_min: number
  packets: number
  bytes: number
  kinds: string[]
  /** Сколько станция молчала перед этим выходом на связь, минут. */
  silence_before_min: number | null
}

export interface StoreExchangeStationDetail {
  station_id: number
  from: string
  to: string
  session_gap_minutes: number
  agent: {
    state: string; silence_seconds: number | null; version: string | null; version_ok: boolean
    queue_pending: number; queue_sent: number; last_shift: number | null
    snapshot_at: string | null; onec_ok: boolean | null; stock_source: string | null
    first_seen: string; last_seen: string
  } | null
  totals: {
    sessions: number; packets: number; bytes: number
    avg_silence_min: number | null; max_silence_min: number | null
    down_waiting: number; down_unacked: number; down_acked: number
  }
  sessions: StoreExchangeSession[]
  by_kind: { kind: string; label: string; packets: number; bytes: number; last_at: string }[]
  downlink: {
    kind: string; label: string; note: string | null; state: string
    created_at: string; delivered_at: string | null; acked_at: string | null
  }[]
}

export const getStoreExchangeStation = (stationId: number, dateFrom: string, dateTo: string) =>
  get<StoreExchangeStationDetail>(
    `/api/store/exchange/${stationId}?date_from=${dateFrom}&date_to=${dateTo}`)

export interface StoreAssortmentRule {
  item_uuid: string
  name: string
  active: boolean
  valid_from: string | null
  valid_to: string | null
  reason: string | null
  updated_at: string
}

export const getStoreAssortmentRules = (stationId: number) =>
  get<{ station_id: number; rules: StoreAssortmentRule[] }>(`/api/store/assortment/${stationId}`)

export const setStoreAssortmentRule = (
  stationId: number,
  itemUuid: string,
  body: { active: boolean; valid_from?: string | null; valid_to?: string | null; reason?: string | null },
) => put<{ ok: boolean }>(`/api/store/assortment/${stationId}/${encodeURIComponent(itemUuid)}`, body)

export const publishStoreAssortment = (stationId: number, defaultActive = true) =>
  post<{ ok: boolean; policy_id: string; task_id?: string; mode: 'dry-run'; rules: number }>(
    `/api/store/assortment/${stationId}/publish?default_active=${defaultActive ? 'true' : 'false'}`, {})

export const mergeEdgeItems = (body: { alias_id: number; canonical_id: number; reason?: string }) =>
  post<{ ok: boolean; stats: Record<string, number>; stations_queued: number }>(
    '/api/store/nsi/merge-items', body)


/** Строка приёмки: заявленное и фактическое ведутся раздельно — платим за факт. */
export interface StoreReceiptLine {
  nomenclature_ref: string | null
  name: string
  barcode: string | null
  qty_expected: number
  qty_fact: number
  price: number
  vat_rate: string | null
  vat_amount?: number
  amount: number
  unit?: string | null
  retail_price?: number
  markup?: number
  pack_factor?: number
  purpose?: string | null
  series?: string | null
  expiry?: string | null
  upd_codes?: string[]
  mark_codes?: string[]
  pack_codes?: string[]
  requires_mark?: boolean
  no_card?: boolean
}

export interface ResolvedStoreBarcode {
  item_uuid: string
  name: string
  unit: string | null
  vat_rate: string | null
  barcode: string
  retail_price: number | null
}

export type StoreDeliveryScheme = 'supplier_to_station' | 'central_warehouse'
export type StoreSigningMode = 'office_director' | 'station_mchd'
export interface StoreReceiptDistribution {
  id: string
  station_id: number
  created_at: string
  lines: { line_index: number; qty: number }[]
}

/** Документ приёмки. Статусы — ордерная схема 1С:Розница. */
export interface StoreReceipt {
  id: string
  station_id: number | null
  number: string
  doc_date: string
  supplier: string | null
  contract: string | null
  incoming_number: string | null
  incoming_date: string | null
  /** draft — набирается; expected — к поступлению; accepted — принят. */
  status: string
  /** center | station | edo — кто завёл документ. */
  origin: string
  comment: string | null
  delivery_scheme: StoreDeliveryScheme
  receiving_warehouse: string | null
  signing_mode: StoreSigningMode
  signer_name: string | null
  mchd_guid: string | null
  mchd_registry: string | null
  mchd_valid_until: string | null
  signature_status: 'pending' | 'signed'
  signature_ref: string | null
  signed_at: string | null
  distribution: StoreReceiptDistribution[]
  lines: StoreReceiptLine[]
  lines_count: number
  diff_count: number
  total_amount: number
  vat_amount: number
  created_at: string
  updated_at: string
  accepted_at: string | null
}

export interface StoreReceiptInput {
  station_id: number | null
  number?: string | null
  doc_date?: string | null
  supplier?: string | null
  contract?: string | null
  incoming_number?: string | null
  incoming_date?: string | null
  comment?: string | null
  delivery_scheme?: StoreDeliveryScheme
  receiving_warehouse?: string | null
  signing_mode?: StoreSigningMode
  signer_name?: string | null
  mchd_guid?: string | null
  mchd_registry?: string | null
  mchd_valid_until?: string | null
  signature_status?: 'pending' | 'signed'
  signature_ref?: string | null
  lines: StoreReceiptLine[]
}

export const getStoreReceipts = (opts?: { stationId?: number; status?: string }) =>
  get<{ receipts: StoreReceipt[]; total: number }>('/api/store/receipts', {
    ...(opts?.stationId ? { station_id: String(opts.stationId) } : {}),
    ...(opts?.status ? { status: opts.status } : {}),
  })

export const createStoreReceipt = (body: StoreReceiptInput) =>
  post<StoreReceipt>('/api/store/receipts', body)

export const updateStoreReceipt = (id: string, body: StoreReceiptInput) =>
  put<StoreReceipt>(`/api/store/receipts/${id}`, body)

export const setStoreReceiptStatus = (id: string, status: 'expected' | 'accepted') =>
  post<StoreReceipt>(`/api/store/receipts/${id}/status?status=${status}`, {})

export const sendStoreReceiptToStation = (id: string) =>
  post<{ ok: boolean; station_id: number; number: string; lines: number }>(
    `/api/store/receipts/${id}/send-to-station`, {})

export const recordStoreReceiptSignature = (
  id: string,
  body: Pick<StoreReceiptInput, 'signature_status' | 'signature_ref' | 'signer_name' |
    'mchd_guid' | 'mchd_registry' | 'mchd_valid_until'>,
) => post<StoreReceipt>(`/api/store/receipts/${id}/signature`, body)

export const distributeStoreReceipt = (
  id: string, stationId: number, lines: { line_index: number; qty: number }[],
) => post<{ ok: boolean; task_id: string; station_id: number; lines: number }>(
  `/api/store/receipts/${id}/distribute`, { station_id: stationId, lines })

export interface StoreReceiptScanResult extends StoreReceipt {
  scan: { type: string; barcode: string; line_index: number; qty_added: number; name: string }
}

export const scanStoreReceipt = (
  id: string, code: string, qty = 1, lines?: StoreReceiptLine[],
) => post<StoreReceiptScanResult>(`/api/store/receipts/${id}/scan`, { code, qty, lines })

export const createStoreReceiptFromUPD = (
  file: File,
  options: Pick<StoreReceiptInput, 'station_id' | 'delivery_scheme' | 'receiving_warehouse' |
    'signing_mode' | 'signer_name' | 'mchd_guid' | 'mchd_registry' | 'mchd_valid_until'>,
) => {
  const query = new URLSearchParams()
  Object.entries(options).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') query.set(key, String(value))
  })
  const form = new FormData()
  form.append('file', file)
  return upload<StoreReceipt>(`/api/store/receipts/from-upd?${query.toString()}`, form)
}

export const resolveStoreBarcode = (code: string, stationId = 208) =>
  get<ResolvedStoreBarcode>('/api/store/nsi/resolve-barcode', {
    code, station_id: String(stationId),
  })

/* ───────────────── Мастер-НСИ: правка карточки, цены, штрихкодов ─────────────────
 * Собственный справочник Ledger (схема edge), а не зеркало 1С. Ключ — GUID
 * карточки: карточку открывают из справочника, где ключ именно он.
 */
export interface NsiBarcode {
  id: number; code: string; status: 'active' | 'historical' | 'rejected'
  note: string | null; first_seen: string; ns_code: number | null; qty: number | null
}

export type StoreRecipeKind = 'dish' | 'semi' | 'combo'

export interface StoreRecipeLine {
  item: string
  name: string
  qty: number
  unit: string
}

export interface StoreRecipeVersion {
  id: string
  dish_uuid: string
  dish_name: string
  recipe_kind: StoreRecipeKind
  version: number
  status: 'draft' | 'active' | 'archived'
  output_qty: number
  output_unit: string
  lines: StoreRecipeLine[]
  content_hash: string
	source: 'center' | 'station' | 'import'
	source_station_id: number | null
	change_note: string | null
	source_bundle_id: string | null
  valid_from: string | null
  valid_to: string | null
  activated_at: string | null
  created_at: string
  updated_at: string
}

export interface StoreRecipeEntry {
  dish_uuid: string
  dish_name: string
  recipe_kind: StoreRecipeKind
  active: StoreRecipeVersion | null
  draft: StoreRecipeVersion | null
  history: StoreRecipeVersion[]
}

export interface StoreRecipeDelivery {
  station_id: number
  state: 'applied' | 'queued' | 'delivered' | 'mismatch' | 'outdated' | 'not_sent'
  desired_bundle: string | null
  queued_bundle: string | null
  applied_bundle: string | null
  created_at: string | null
  delivered_at: string | null
  acked_at: string | null
  agent_last_seen: string | null
  recipe_bundle: { bundle_id?: string; applied_at?: string; recipes?: number } | null
  readiness: {
    ready?: boolean
    checked_at?: string
    bundle_id?: string
    critical?: number
    warnings?: number
    issues?: Array<{ code: string; message: string; dish?: string }>
  } | null
}

export interface StoreRecipeWorkspace {
  bundle: {
    bundle_id: string
    schema_version: number
    generated_at: string
    effective_from: string
    content_hash: string
    recipes: unknown[]
  } | null
  legacy_available: number
  summary: { recipes: number; active: number; drafts: number }
  recipes: StoreRecipeEntry[]
  deliveries: StoreRecipeDelivery[]
}

export interface StoreRecipeDraftInput {
  dish_uuid: string
  dish_name?: string
  recipe_kind?: StoreRecipeKind
  output_qty?: number
  output_unit?: string
  lines?: StoreRecipeLine[]
}

export const getStoreRecipeWorkspace = () =>
  get<StoreRecipeWorkspace>('/api/store/recipes/versions')

export const bootstrapStoreRecipes = () =>
  post<{ ok: boolean; created: number }>('/api/store/recipes/bootstrap')

export const createStoreRecipeDraft = (input: StoreRecipeDraftInput) =>
  post<StoreRecipeVersion>('/api/store/recipes/draft', input)

export const updateStoreRecipeDraft = (id: string, input: Omit<StoreRecipeDraftInput, 'dish_uuid'>) =>
  put<StoreRecipeVersion>(`/api/store/recipes/${id}`, input)

export const activateStoreRecipe = (id: string, validFrom?: string) =>
  post<StoreRecipeVersion>(`/api/store/recipes/${id}/activate`, validFrom ? { valid_from: validFrom } : {})

export const pushStoreRecipes = (stationId: number) =>
  post<{ ok: boolean; bundle_id: string; already_current?: boolean; already_queued?: boolean }>(
    `/api/store/nsi/push-recipes/${stationId}`,
  )
export interface NsiPriceRow {
  id: number; station_id: number; price: number
  valid_from: string; valid_to: string | null; author: string | null
}
export interface NsiListItem {
  id: number
  external_uuid: string
  name: string
  unit: string
  vat_rate: string
  price: number | null
  qty: number
  barcodes: number
  collisions: number
}
export interface NsiCard {
  item: {
    id: number; external_uuid: string; code_1c: string | null
    name: string; name_full: string | null; unit: string; vat_rate: string
    kind: string | null; sku_class: string | null; is_dish: boolean
    price_owner: 'master' | 'station'; deleted: boolean
    created_at: string; updated_at: string
  }
  barcodes: NsiBarcode[]
  prices: NsiPriceRow[]
  station_id: number
}

export const NSI_VAT_CODES = ['НДС22', 'НДС10', 'НДС20', 'НДС18_118', 'НДС5', 'БезНДС'] as const

export const getNsiCard = (ident: string, stationId = 208) =>
  get<NsiCard>(`/api/store/nsi/items/${encodeURIComponent(ident)}`, { station_id: stationId })

export const findNsiItems = (query: string, stationId = 208, limit = 20) =>
  get<{ items: NsiListItem[]; total: number }>('/api/store/nsi/items', {
    q: query, station_id: stationId, limit,
  })

export const saveNsiCard = (ident: string, patch: Partial<NsiCard['item']>) =>
  put<{ ok: boolean; changed: string[] }>(`/api/store/nsi/items/${encodeURIComponent(ident)}`, patch)

export const setNsiPrice = (ident: string, stationId: number, price: number) =>
  post<{ ok: boolean; note: string }>(`/api/store/nsi/items/${encodeURIComponent(ident)}/price`,
    { station_id: stationId, price })

export const addNsiBarcode = (ident: string, code: string) =>
  post<{ ok: boolean; already?: boolean }>(`/api/store/nsi/items/${encodeURIComponent(ident)}/barcode`, { code })

export const retireNsiBarcode = (barcodeId: number) =>
  post<{ ok: boolean }>(`/api/store/nsi/barcodes/${barcodeId}/retire`, {})


/* ── Очередь признания: что станции решили сами ───────────────────────────
 *
 * Карточки и контрагенты, заведённые на местах, и цены, назначенные станциями.
 * Первые два ждут решения человека в центре: каноном карточку делает он,
 * сопоставляя по штрихкоду — дедуп возможен только там, где виден справочник
 * всей сети. Цены не подтверждают: это журнал, по нему видно, кто и почему
 * поменял цену на полке.
 */
export interface StationItemDraft {
  station_id: number
  source_uuid: string
  name: string
  unit: string
  vat_rate: string | null
  barcodes: string[]
  created_at: string
  id?: number
}

export interface StationPartnerDraft {
  station_id: number
  source_uuid: string
  name: string
  inn: string | null
  kpp: string | null
  role: string
  comment: string | null
  created_at: string
  id?: number
}

export interface StationPriceChange {
  station_id: number
  item_uuid: string
  barcode: string | null
  old_price: number | null
  new_price: number
  author: string
  reason: string | null
  changed_at: string
}

/** Заявка станции: в сетевой карточке ошибка, вот как должно быть. */
export interface StationNSIProposal {
  id: number
  station_id: number
  item_uuid: string
  item_name: string | null
  field: string
  current: string
  proposed: string
  author: string
  comment: string
  created_at: string
}

export interface StationDrafts {
  items: StationItemDraft[]
  partners: StationPartnerDraft[]
  prices: StationPriceChange[]
  proposals: StationNSIProposal[]
}

/** Карточка сети, на которую похож черновик (совпал штрихкод). */
export interface DraftCandidate {
  item_id: number
  uuid: string
  name: string
  unit: string
  vat_rate: string
  barcode: string
  barcode_status: string
}

export const getStationDrafts = (stationId?: number) =>
  get<StationDrafts>(`/api/store/station-drafts${stationId ? `?station_id=${stationId}` : ''}`)

export const getDraftCandidates = (barcodes: string[]) =>
  get<{ candidates: DraftCandidate[] }>(
    `/api/store/station-drafts/candidates?barcodes=${encodeURIComponent(barcodes.join(','))}`)

export const resolveItemDraft = (
  draftId: number, body: { action: 'link' | 'create' | 'reject'; item_id?: number; note?: string },
) => post<Record<string, unknown>>(`/api/store/station-drafts/item/${draftId}`, body)

/**
 * Открыть сессию работы на станции.
 *
 * Рамка рабочего места ходит на мастер обычной навигацией, а токен приложения
 * живёт в localStorage и уходит только заголовком — которого у навигации нет.
 * Поэтому вход делается один раз: токен обменивается на короткую cookie,
 * привязанную к этой АЗС.
 */
export const openStationSession = (stationId: number) =>
  post<void>(`/api/store/station/${stationId}/session`)

export const resolveNSIProposal = (
  proposalId: number, body: { action: 'accept' | 'reject'; note?: string },
) => post<Record<string, unknown>>(`/api/store/station-drafts/proposal/${proposalId}`, body)

export const resolvePartnerDraft = (
  draftId: number, body: { action: 'accept' | 'reject'; note?: string },
) => post<Record<string, unknown>>(`/api/store/station-drafts/partner/${draftId}`, body)


/* ── Коллизии штрихкодов ──────────────────────────────────────────────────
 *
 * Один код не может быть активен у двух карточек: касса ищет товар по нему, и
 * при двойной привязке продаётся та позиция, что выгрузилась последней, —
 * вторая «исчезает с полки», хотя лежит.
 */
export interface BarcodeCollision {
  claim_id: number
  code: string
  claim_note: string | null
  claimed_at: string
  claimant_id: number
  claimant_name: string
  claimant_unit: string
  claimant_source: string
  holder_barcode_id: number
  holder_id: number
  holder_name: string
  holder_unit: string
  holder_last_sold: string | null
  holder_ns_codes: number
  holder_stock: number
}

export const getBarcodeCollisions = () =>
  get<{ collisions: BarcodeCollision[] }>('/api/store/barcode-collisions')

export const resolveBarcodeCollision = (
  claimId: number, body: { action: 'move' | 'drop'; note?: string },
) => post<Record<string, unknown>>(`/api/store/barcode-collisions/${claimId}`, body)
