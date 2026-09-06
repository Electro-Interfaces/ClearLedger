import type {
  SalesCategory,
  SalesGroupBy,
  SalesMarked,
  SkuDetailData,
  StoreExchangeData,
  StoreExchangeStationDetail,
  StoreOverviewData,
  CateringMenuData,
  StoreSalesData,
  StoreStockData,
  StoreVisitsData,
} from './storeService'

export const STORE_DEMO_STATIONS = [
  { id: '101', name: 'АЗС 101', city: 'Санкт-Петербург', address: 'Московское шоссе, 18' },
  { id: '208', name: 'АЗС 208', city: 'Великий Новгород', address: 'Большая Санкт-Петербургская, 82' },
  { id: '315', name: 'АЗС 315', city: 'Псков', address: 'Ленинградское шоссе, 21' },
] as const

type DemoSku = {
  guid: string
  name: string
  article: string
  barcode: string
  vat: string
  marked: boolean
  weighed: boolean
  unit: string
  kind: string
  category: 'Сопутка' | 'Общепит'
  price: number
  cost: number
  dailyQty: number
  stock: Record<string, number>
}

const STATION_FACTOR: Record<string, number> = { '101': 1, '208': 1.28, '315': 0.76 }

const SKUS: DemoSku[] = [
  {
    guid: 'demo-water-05', name: 'Вода минеральная 0,5 л', article: 'ВОД-050',
    barcode: '4601234567001', vat: '20%', marked: false, weighed: false, unit: 'шт',
    kind: 'Товар', category: 'Сопутка', price: 89, cost: 48, dailyQty: 18,
    stock: { '101': 42, '208': 58, '315': 21 },
  },
  {
    guid: 'demo-coffee', name: 'Кофе американо 300 мл', article: 'КОФ-300',
    barcode: '2000000000101', vat: '20%', marked: false, weighed: false, unit: 'шт',
    kind: 'Блюдо', category: 'Общепит', price: 149, cost: 43, dailyQty: 24,
    stock: { '101': 96, '208': 121, '315': 64 },
  },
  {
    guid: 'demo-hotdog', name: 'Хот-дог классический', article: 'ХД-КЛАСС',
    barcode: '2000000000102', vat: '20%', marked: false, weighed: false, unit: 'шт',
    kind: 'Блюдо', category: 'Общепит', price: 229, cost: 91, dailyQty: 11,
    stock: { '101': 34, '208': 47, '315': 18 },
  },
  {
    guid: 'demo-chocolate', name: 'Шоколад молочный 90 г', article: 'ШОК-090',
    barcode: '4601234567002', vat: '20%', marked: false, weighed: false, unit: 'шт',
    kind: 'Товар', category: 'Сопутка', price: 139, cost: 86, dailyQty: 9,
    stock: { '101': 27, '208': 31, '315': 14 },
  },
  {
    guid: 'demo-chips', name: 'Чипсы картофельные 140 г', article: 'ЧИП-140',
    barcode: '4601234567003', vat: '20%', marked: false, weighed: false, unit: 'шт',
    kind: 'Товар', category: 'Сопутка', price: 179, cost: 108, dailyQty: 8,
    stock: { '101': 19, '208': 26, '315': 12 },
  },
  {
    guid: 'demo-milk', name: 'Молоко ультрапастеризованное 1 л', article: 'МОЛ-100',
    barcode: '4601234567004', vat: '10%', marked: true, weighed: false, unit: 'шт',
    kind: 'Товар', category: 'Сопутка', price: 119, cost: 77, dailyQty: 5,
    stock: { '101': 11, '208': 17, '315': -3 },
  },
  {
    guid: 'demo-oil', name: 'Масло моторное 5W-30, 1 л', article: 'МАС-530',
    barcode: '4601234567005', vat: '20%', marked: true, weighed: false, unit: 'шт',
    kind: 'Автотовар', category: 'Сопутка', price: 899, cost: 642, dailyQty: 1.6,
    stock: { '101': 8, '208': 12, '315': 4 },
  },
  {
    guid: 'demo-washer', name: 'Стеклоомывающая жидкость 4 л', article: 'ОМЫ-004',
    barcode: '4601234567006', vat: '20%', marked: false, weighed: false, unit: 'шт',
    kind: 'Автотовар', category: 'Сопутка', price: 329, cost: 208, dailyQty: 3.2,
    stock: { '101': 15, '208': 23, '315': 9 },
  },
]

const round = (value: number, digits = 2) => Number(value.toFixed(digits))

function dateRange(from: string, to: string): string[] {
  const start = new Date(`${from}T00:00:00Z`)
  const end = new Date(`${to}T00:00:00Z`)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start > end) return []
  const days: string[] = []
  for (let current = start; current <= end; current = new Date(current.getTime() + 86_400_000)) {
    days.push(current.toISOString().slice(0, 10))
  }
  return days
}

function stationIds(stations?: string[]): string[] {
  const available = new Set<string>(STORE_DEMO_STATIONS.map((station) => station.id))
  const selected = stations?.filter((station) => available.has(station)) ?? []
  return selected.length ? selected : [...available]
}

function dayFactor(index: number): number {
  return [0.91, 0.96, 1.04, 1.08, 1.16, 1.23, 0.88][index % 7]
}

function vatRate(vat: string): number {
  return vat === '10%' ? 0.1 : 0.2
}

function netOfVat(amount: number, vat: string): number {
  return amount / (1 + vatRate(vat))
}

function skuTotals(sku: DemoSku, days: string[], stations?: string[]) {
  const ids = stationIds(stations)
  let qty = 0
  for (const id of ids) {
    for (let index = 0; index < days.length; index += 1) {
      qty += sku.dailyQty * STATION_FACTOR[id] * dayFactor(index)
    }
  }
  qty = round(qty, 3)
  const revenue = round(qty * sku.price)
  const revenueNet = round(netOfVat(revenue, sku.vat))
  const cogs = round(qty * sku.cost)
  return { qty, revenue, revenueNet, vat: round(revenue - revenueNet), cogs }
}

function visitsFor(dateFrom: string, dateTo: string, stations?: string[]): StoreVisitsData {
  const days = dateRange(dateFrom, dateTo)
  const ids = stationIds(stations)
  const fuelOps = Math.round(days.length * ids.reduce((sum, id) => sum + 176 * STATION_FACTOR[id], 0))
  const shopCheques = Math.round(days.length * ids.reduce((sum, id) => sum + 59 * STATION_FACTOR[id], 0))
  const mixed = Math.min(fuelOps, shopCheques)
  const revenue = round(SKUS.reduce((sum, sku) => sum + skuTotals(sku, days, ids).revenue, 0))
  const visits = fuelOps
  return {
    visits,
    fuel_ops: fuelOps,
    shop_cheques: shopCheques,
    mixed,
    fuel_only: Math.max(0, fuelOps - mixed),
    conversion: visits ? round((shopCheques / visits) * 100, 1) : 0,
    revenue,
    per_visit: visits ? round(revenue / visits) : 0,
    avg_cheque: shopCheques ? round(revenue / shopCheques) : 0,
    basis: {
      days: days.length, period_days: days.length, shifts: days.length * ids.length * 2,
      stations: ids.length, from: days[0] ?? null, to: days.at(-1) ?? null, partial: false,
    },
  }
}

export async function getDemoStoreOverview(
  dateFrom: string,
  dateTo: string,
  stations?: string[],
): Promise<StoreOverviewData> {
  const days = dateRange(dateFrom, dateTo)
  const ids = stationIds(stations)
  const totals = SKUS.map((sku) => ({ sku, ...skuTotals(sku, days, ids) }))
  const totalRevenue = round(totals.reduce((sum, row) => sum + row.revenue, 0))
  const revenueNet = round(totals.reduce((sum, row) => sum + row.revenueNet, 0))
  const cogs = round(totals.reduce((sum, row) => sum + row.cogs, 0))
  const categories = (['Сопутка', 'Общепит'] as const).map((category) => {
    const rows = totals.filter((row) => row.sku.category === category)
    const revenue = round(rows.reduce((sum, row) => sum + row.revenue, 0))
    return {
      category,
      revenue,
      positions: Math.round(rows.reduce((sum, row) => sum + row.qty * 0.72, 0)),
      units: round(rows.reduce((sum, row) => sum + row.qty, 0), 1),
      percent: totalRevenue ? round((revenue / totalRevenue) * 100, 1) : 0,
    }
  })
  const daily = days.map((date, index) => {
    const factor = dayFactor(index)
    const dayRevenue = (category: DemoSku['category']) => round(
      SKUS.filter((sku) => sku.category === category).reduce((sum, sku) => (
        sum + ids.reduce((stationSum, id) => stationSum + sku.dailyQty * STATION_FACTOR[id] * factor * sku.price, 0)
      ), 0),
    )
    const soputka = dayRevenue('Сопутка')
    const obshepit = dayRevenue('Общепит')
    return { date, revenue: round(soputka + obshepit), soputka, obshepit }
  })
  const byStation = ids.map((id) => {
    const revenue = round(SKUS.reduce((sum, sku) => sum + skuTotals(sku, days, [id]).revenue, 0))
    return {
      station: STORE_DEMO_STATIONS.find((station) => station.id === id)?.name ?? `АЗС ${id}`,
      revenue,
      positions: Math.round(SKUS.reduce((sum, sku) => sum + skuTotals(sku, days, [id]).qty * 0.72, 0)),
      shifts: days.length * 2,
    }
  })
  const shifts = days.length * ids.length * 2
  const positions = Math.round(totals.reduce((sum, row) => sum + row.qty * 0.72, 0))
  const margin = round(totalRevenue - cogs)
  const trend = (current: number, percent: number) => {
    const previous = round(current / (1 + percent / 100))
    return { current, previous, delta: round(current - previous), percent, direction: 'up' as const }
  }
  return {
    period: { from: dateFrom, to: dateTo, days: days.length },
    financial: {
      total_revenue: totalRevenue,
      returns: round(totalRevenue * 0.006),
      vat: round(totalRevenue - revenueNet),
      net_revenue: revenueNet,
      avg_check_approx: shifts ? round(totalRevenue / shifts) : 0,
      payments: { cash: round(totalRevenue * 0.27), card: round(totalRevenue * 0.73) },
      payments_detail: [
        { name: 'Банковская карта', value: round(totalRevenue * 0.66) },
        { name: 'СБП', value: round(totalRevenue * 0.07) },
        { name: 'Наличные', value: round(totalRevenue * 0.27) },
      ],
    },
    units: {
      total_positions: positions,
      total_units: round(totals.reduce((sum, row) => sum + row.qty, 0), 1),
      by_category: categories,
    },
    operational: { shifts_count: shifts, stations_count: ids.length },
    visits: visitsFor(dateFrom, dateTo, ids),
    margin: {
      sku_count: SKUS.length, sku_costed: SKUS.length, revenue: totalRevenue,
      revenue_net: revenueNet, cogs, margin,
      margin_pct: totalRevenue ? round((margin / totalRevenue) * 100, 1) : 0,
      markup_pct: cogs ? round((margin / cogs) * 100, 1) : 0,
      loss_makers: 0,
    },
    charts: { daily },
    by_station: byStation,
    trends: {
      revenue: trend(totalRevenue, 6.8),
      avg_check: trend(shifts ? totalRevenue / shifts : 0, 3.2),
      shifts: trend(shifts, 2.1),
    },
  }
}

export async function getDemoStoreVisits(
  dateFrom: string,
  dateTo: string,
  stations?: string[],
): Promise<StoreVisitsData> {
  return visitsFor(dateFrom, dateTo, stations)
}

type SalesRow = StoreSalesData['groups'][number]

export async function getDemoStoreSales(
  dateFrom: string,
  dateTo: string,
  opts: { groupBy: SalesGroupBy; category: SalesCategory; marked: SalesMarked; q?: string; stations?: string[] },
): Promise<StoreSalesData> {
  const days = dateRange(dateFrom, dateTo)
  const ids = stationIds(opts.stations)
  const query = opts.q?.trim().toLowerCase() ?? ''
  const skus = SKUS.filter((sku) => (
    (opts.category === 'all' || sku.category.toLowerCase() === opts.category)
    && (opts.marked === 'all' || (opts.marked === 'marked' ? sku.marked : !sku.marked))
    && (!query || `${sku.name} ${sku.article} ${sku.barcode}`.toLowerCase().includes(query))
  ))
  const skuRows = skus.map((sku) => ({ sku, ...skuTotals(sku, days, ids) }))
  const makeRow = (key: string, label: string, rows: typeof skuRows): SalesRow => {
    const revenue = round(rows.reduce((sum, row) => sum + row.revenue, 0))
    return {
      key, label, revenue,
      revenue_net: round(rows.reduce((sum, row) => sum + row.revenueNet, 0)),
      vat: round(rows.reduce((sum, row) => sum + row.vat, 0)),
      qty: round(rows.reduce((sum, row) => sum + row.qty, 0), 1),
      sku_count: rows.length,
      share: 0,
    }
  }
  let groups: SalesRow[]
  if (opts.groupBy === 'sku') {
    groups = skuRows.map((row) => makeRow(row.sku.guid, row.sku.name, [row]))
  } else if (opts.groupBy === 'day') {
    groups = days.map((date, index) => {
      const factor = dayFactor(index)
      const rows = skus.map((sku) => {
        const qty = round(ids.reduce((sum, id) => sum + sku.dailyQty * STATION_FACTOR[id] * factor, 0), 3)
        const revenue = round(qty * sku.price)
        const revenueNet = round(netOfVat(revenue, sku.vat))
        return { sku, qty, revenue, revenueNet, vat: round(revenue - revenueNet), cogs: round(qty * sku.cost) }
      })
      return makeRow(date, date, rows)
    })
  } else if (opts.groupBy === 'shift') {
    groups = ids.flatMap((id, stationIndex) => [1, 2].map((shift) => {
      const ratio = shift === 1 ? 0.46 : 0.54
      const rows = skuRows.map((row) => ({
        ...row,
        qty: round(row.qty * ratio / Math.max(1, ids.length), 2),
        revenue: round(row.revenue * ratio / Math.max(1, ids.length)),
        revenueNet: round(row.revenueNet * ratio / Math.max(1, ids.length)),
        vat: round(row.vat * ratio / Math.max(1, ids.length)),
      }))
      const number = 6400 + stationIndex * 20 + shift
      return makeRow(`demo-shift-${id}-${number}`, `АЗС ${id} · смена ${number}`, rows)
    }))
  } else if (opts.groupBy === 'payment') {
    const total = makeRow('all', 'Все оплаты', skuRows)
    groups = [
      { ...total, key: 'card', label: 'Банковская карта', revenue: round(total.revenue * 0.66), revenue_net: round(total.revenue_net * 0.66), vat: round(total.vat * 0.66), qty: 0, sku_count: 0 },
      { ...total, key: 'sbp', label: 'СБП', revenue: round(total.revenue * 0.07), revenue_net: round(total.revenue_net * 0.07), vat: round(total.vat * 0.07), qty: 0, sku_count: 0 },
      { ...total, key: 'cash', label: 'Наличные', revenue: round(total.revenue * 0.27), revenue_net: round(total.revenue_net * 0.27), vat: round(total.vat * 0.27), qty: 0, sku_count: 0 },
    ]
  } else {
    const keyFor = (sku: DemoSku) => {
      if (opts.groupBy === 'category') return sku.category
      if (opts.groupBy === 'kind') return sku.kind
      if (opts.groupBy === 'marking') return sku.marked ? 'Маркированные' : 'Обычные'
      return sku.vat
    }
    const grouped = new Map<string, typeof skuRows>()
    for (const row of skuRows) {
      const key = keyFor(row.sku)
      grouped.set(key, [...(grouped.get(key) ?? []), row])
    }
    groups = [...grouped.entries()].map(([key, rows]) => makeRow(key, key, rows))
  }
  const revenue = round(groups.reduce((sum, row) => sum + row.revenue, 0))
  groups = groups.map((row) => ({ ...row, share: revenue ? round((row.revenue / revenue) * 100, 1) : 0 }))
    .sort((a, b) => b.revenue - a.revenue)
  const summaryRows = opts.groupBy === 'payment' ? skuRows : skuRows
  return {
    period: { from: dateFrom, to: dateTo },
    group_by: opts.groupBy,
    filters: { category: opts.category, marked: opts.marked, q: opts.q ?? '' },
    filters_ignored: opts.groupBy === 'payment' && (opts.category !== 'all' || opts.marked !== 'all' || query)
      ? ['категория', 'маркировка', 'поиск']
      : undefined,
    groups,
    summary: {
      revenue,
      revenue_net: round(summaryRows.reduce((sum, row) => sum + row.revenueNet, 0)),
      vat: round(summaryRows.reduce((sum, row) => sum + row.vat, 0)),
      qty: round(summaryRows.reduce((sum, row) => sum + row.qty, 0), 1),
      sku_count: summaryRows.length,
      shifts: days.length * ids.length * 2,
      groups_count: groups.length,
    },
  }
}

export async function getDemoStoreSkuDetail(
  guid: string,
  dateFrom: string,
  dateTo: string,
  stations?: string[],
): Promise<SkuDetailData> {
  const sku = SKUS.find((item) => item.guid === guid) ?? SKUS[0]
  const days = dateRange(dateFrom, dateTo)
  const ids = stationIds(stations)
  const totals = skuTotals(sku, days, ids)
  const margin = round(totals.revenue - totals.cogs)
  return {
    guid: sku.guid,
    name: sku.name,
    article: sku.article,
    vat: sku.vat,
    marked: sku.marked,
    weighed: sku.weighed,
    unit: sku.unit,
    kind: sku.kind,
    category: sku.category,
    full_name: sku.name,
    main_supplier: sku.category === 'Общепит' ? 'Демо Фуд Сервис' : 'Демо Дистрибуция',
    metrics: {
      qty: totals.qty, revenue: totals.revenue, revenue_net: totals.revenueNet,
      avg_price: sku.price, avg_cost: sku.cost, cogs: totals.cogs, margin,
      margin_pct: totals.revenue ? round((margin / totals.revenue) * 100, 1) : null,
      markup_pct: totals.cogs ? round((margin / totals.cogs) * 100, 1) : null,
      purch_qty: round(totals.qty * 1.14, 1),
    },
    daily: days.map((date, index) => {
      const qty = round(ids.reduce((sum, id) => sum + sku.dailyQty * STATION_FACTOR[id] * dayFactor(index), 0), 2)
      return { date, qty, revenue: round(qty * sku.price) }
    }),
    purchases: [
      { date: days[Math.max(0, days.length - 8)] ?? dateFrom, supplier: 'Демо Дистрибуция', qty: 48, price_net: sku.cost, amount_net: sku.cost * 48 },
      { date: days[Math.max(0, days.length - 3)] ?? dateTo, supplier: 'Демо Дистрибуция', qty: 36, price_net: sku.cost, amount_net: sku.cost * 36 },
    ],
    price_history: [
      { date: days[Math.max(0, days.length - 5)] ?? dateFrom, old: round(sku.price * 0.94), new: sku.price, delta: round(sku.price * 0.06), pct: 6.4 },
    ],
    stock: ids.map((id) => ({ warehouse: `АЗС ${id} · Торговый зал`, qty: sku.stock[id] ?? 0, retail_price: sku.price, cost_unit: sku.cost })),
  }
}

export async function getDemoStoreStock(opts?: {
  warehouse?: string
  stations?: string[]
}): Promise<StoreStockData> {
  const ids = stationIds(opts?.stations)
  const selectedWarehouse = opts?.warehouse && opts.warehouse !== 'all' ? opts.warehouse : undefined
  const selectedStation = selectedWarehouse?.split(':')[0]
  const scope = selectedStation && ids.includes(selectedStation) ? [selectedStation] : ids
  const snapshot = '2026-08-24T16:42:00+03:00'
  const warehouses = ids.map((id) => {
    const items = SKUS.map((sku) => sku.stock[id] ?? 0)
    return {
      code: `${id}:SHOP`, name: `АЗС ${id}, торговый зал`, station_id: Number(id), place_code: 'SHOP',
      sku: SKUS.length, positive: items.filter((qty) => qty > 0).length,
      retail_value: round(SKUS.reduce((sum, sku) => sum + Math.max(0, sku.stock[id] ?? 0) * sku.price, 0)),
    }
  })
  const items = scope.flatMap((id) => SKUS.map((sku) => {
    const qty = sku.stock[id] ?? 0
    const retailValue = round(qty * sku.price)
    const costAmount = round(qty * sku.cost)
    const margin = round(retailValue - costAmount)
    return {
      guid: sku.guid, name: sku.name, article: sku.article, vat: sku.vat,
      station_id: Number(id), place_code: 'SHOP', place_name: `АЗС ${id}, торговый зал`,
      marked: sku.marked, weighed: sku.weighed, barcode: sku.barcode,
      qty, negative: qty < 0, retail_price: sku.price, retail_value: retailValue,
      cost_unit: sku.cost, cost_amount: costAmount, margin,
      margin_pct: retailValue ? round((margin / retailValue) * 100, 1) : null,
      unit: sku.unit, cost_doubt: null, buy_unit: sku.cost,
    }
  })).sort((a, b) => b.retail_value - a.retail_value)
  const stationSummary = ids.map((id) => {
    const stationItems = items.filter((item) => item.station_id === Number(id))
    const allItems = SKUS.map((sku) => ({ qty: sku.stock[id] ?? 0, price: sku.price }))
    return {
      station_id: Number(id), places: 1, sku: SKUS.length,
      positive: allItems.filter((item) => item.qty > 0).length,
      negative: allItems.filter((item) => item.qty < 0).length,
      retail_value: round(stationItems.reduce((sum, item) => sum + Math.max(0, item.retail_value ?? 0), 0)),
      snapshot_at: snapshot,
    }
  })
  const positive = items.filter((item) => item.qty > 0)
  const retailPositive = round(positive.reduce((sum, item) => sum + (item.retail_value ?? 0), 0))
  const costValue = round(positive.reduce((sum, item) => sum + (item.cost_amount ?? 0), 0))
  return {
    stations: stationSummary,
    source: 'edge_agent',
    warehouse: selectedWarehouse ?? null,
    warehouses,
    items,
    snapshot_at: snapshot,
    summary: {
      sku_count: items.length,
      positive: positive.length,
      negative: items.filter((item) => item.negative).length,
      retail_value_positive: retailPositive,
      retail_value_all: round(items.reduce((sum, item) => sum + (item.retail_value ?? 0), 0)),
      cost_value: costValue,
      costed_count: positive.length,
      margin_value: round(retailPositive - costValue),
      margin_pct: retailPositive ? round(((retailPositive - costValue) / retailPositive) * 100, 1) : null,
      marked_count: items.filter((item) => item.marked).length,
      units_positive: round(positive.reduce((sum, item) => sum + item.qty, 0), 1),
    },
  }
}

type ExchangeSeed = {
  id: number
  state: string
  silence: number
  version: string
  packets: number
  sessions: number
  queue: number
  queueFailing: number
  uptime: number
  shift: number
}

const EXCHANGE: ExchangeSeed[] = [
  { id: 101, state: 'онлайн', silence: 42, version: '1.8.4', packets: 184, sessions: 28, queue: 0, queueFailing: 0, uptime: 99.7, shift: 6418 },
  { id: 208, state: 'онлайн', silence: 76, version: '1.8.4', packets: 231, sessions: 31, queue: 2, queueFailing: 0, uptime: 98.9, shift: 6721 },
  { id: 315, state: 'молчит', silence: 10_920, version: '1.8.2', packets: 96, sessions: 17, queue: 12, queueFailing: 1, uptime: 91.8, shift: 5884 },
]

function at(date: string, time: string): string {
  return `${date}T${time}+03:00`
}

function exchangeRows(dateTo: string, stations?: string[]) {
  const ids = new Set(stationIds(stations).map(Number))
  return EXCHANGE.filter((station) => ids.has(station.id)).map((station) => ({
    station_id: station.id,
    state: station.state,
    silence_seconds: station.silence,
    last_seen: at(dateTo, station.state === 'онлайн' ? '16:44:00' : '13:42:00'),
    version: station.version,
    queue_pending: station.queue,
    queue_sent: station.packets * 3,
    queue_bytes: station.queue * 41_000,
    queue_wire_bytes: station.queue * 12_400,
    queue_oldest_at: station.queue ? at(dateTo, '12:18:00') : null,
    queue_failing: station.queueFailing,
    queue_sent_24: Math.round(station.packets / 4),
    sent_24_bytes: Math.round(station.packets * 15_400),
    sent_24_wire_bytes: Math.round(station.packets * 4_800),
    last_sent_at: at(dateTo, station.state === 'онлайн' ? '16:43:00' : '13:41:00'),
    last_attempt_at: at(dateTo, station.state === 'онлайн' ? '16:43:00' : '16:39:00'),
    last_error: station.queueFailing ? 'Нет связи с хабом, повтор через 5 минут' : null,
    clock_skew_seconds: station.id === 315 ? 94 : 12,
    last_shift: station.shift,
    snapshot_at: at(dateTo, station.state === 'онлайн' ? '16:35:00' : '12:55:00'),
    packets: station.packets,
    bytes: station.packets * 47_000,
    wire_bytes: station.packets * 14_600,
    wire_packets: station.packets,
    sessions: station.sessions,
    last_packet_at: at(dateTo, station.state === 'онлайн' ? '16:43:00' : '13:41:00'),
    down_waiting: station.id === 315 ? 2 : 0,
    down_unacked: station.id === 208 ? 1 : 0,
    down_acked: station.sessions + 4,
    down_pending_bytes: station.id === 315 ? 18_400 : station.id === 208 ? 4_200 : 0,
    down_oldest_pending_at: station.id === 315 ? at(dateTo, '11:20:00') : null,
    down_avg_ack_seconds: station.id === 315 ? 1_480 : 64,
    down_max_ack_seconds: station.id === 315 ? 4_800 : 190,
    uptime_pct: station.uptime,
  }))
}

export async function getDemoStoreExchange(
  dateFrom: string,
  dateTo: string,
  stations?: string[],
): Promise<StoreExchangeData> {
  const rows = exchangeRows(dateTo, stations)
  const days = dateRange(dateFrom, dateTo).slice(-8)
  const packets = rows.reduce((sum, station) => sum + station.packets, 0)
  const bytes = rows.reduce((sum, station) => sum + station.bytes, 0)
  const wireBytes = rows.reduce((sum, station) => sum + station.wire_bytes, 0)
  const sessions = rows.reduce((sum, station) => sum + station.sessions, 0)
  const recent = rows.flatMap((station, index) => [
    { at: at(dateTo, `${16 - index}:43:00`), station_id: station.station_id, kind: 'shift', label: 'Смена', size_bytes: 148_000, wire_size_bytes: 43_000, direction: 'вверх' as const, note: `смена ${station.last_shift}` },
    { at: at(dateTo, `${15 - index}:18:00`), station_id: station.station_id, kind: 'stock', label: 'Снимок остатков', size_bytes: 512_000, wire_size_bytes: 122_000, direction: 'вверх' as const, note: null },
  ]).sort((a, b) => b.at.localeCompare(a.at))
  return {
    from: dateFrom,
    to: dateTo,
    session_gap_minutes: 15,
    totals: {
      packets, bytes, wire_bytes: wireBytes, wire_packets: packets, sessions,
      online: rows.filter((station) => station.state === 'онлайн').length,
      stations: rows.length,
      queue_pending: rows.reduce((sum, station) => sum + station.queue_pending, 0),
      queue_bytes: rows.reduce((sum, station) => sum + station.queue_bytes, 0),
      queue_wire_bytes: rows.reduce((sum, station) => sum + station.queue_wire_bytes, 0),
      queue_failing: rows.reduce((sum, station) => sum + station.queue_failing, 0),
      down_waiting: rows.reduce((sum, station) => sum + station.down_waiting, 0),
      down_unacked: rows.reduce((sum, station) => sum + station.down_unacked, 0),
      down_pending_bytes: rows.reduce((sum, station) => sum + station.down_pending_bytes, 0),
      last_packet_at: rows[0]?.last_packet_at ?? null,
    },
    by_kind: [
      { kind: 'shift', label: 'Смены', packets: Math.round(packets * 0.36), bytes: Math.round(bytes * 0.28), wire_bytes: Math.round(wireBytes * 0.26), wire_packets: Math.round(packets * 0.36), last_at: at(dateTo, '16:43:00') },
      { kind: 'stock', label: 'Снимки остатков', packets: Math.round(packets * 0.45), bytes: Math.round(bytes * 0.62), wire_bytes: Math.round(wireBytes * 0.64), wire_packets: Math.round(packets * 0.45), last_at: at(dateTo, '16:35:00') },
      { kind: 'documents', label: 'Документы станции', packets: Math.round(packets * 0.19), bytes: Math.round(bytes * 0.1), wire_bytes: Math.round(wireBytes * 0.1), wire_packets: Math.round(packets * 0.19), last_at: at(dateTo, '15:58:00') },
    ],
    by_day: days.map((day, index) => ({
      day, packets: Math.round((packets / Math.max(1, days.length)) * dayFactor(index)),
      bytes: Math.round((bytes / Math.max(1, days.length)) * dayFactor(index)),
      wire_bytes: Math.round((wireBytes / Math.max(1, days.length)) * dayFactor(index)),
      wire_packets: Math.round((packets / Math.max(1, days.length)) * dayFactor(index)),
    })),
    stations: rows,
    recent,
    nsi: { 'черновики товаров': 3, 'новые контрагенты': 1 },
    ingest: [
      { kind: 'shift', label: 'Смены', packets: Math.round(packets * 0.36), projected: Math.round(packets * 0.36), entries: Math.round(packets * 0.36), unprojected: 0, projects_docs: true },
      { kind: 'stock', label: 'Снимки остатков', packets: Math.round(packets * 0.45), projected: 0, entries: 0, unprojected: 0, projects_docs: false },
      { kind: 'documents', label: 'Документы станции', packets: Math.round(packets * 0.19), projected: Math.max(0, Math.round(packets * 0.19) - 1), entries: Math.max(0, Math.round(packets * 0.19) - 1), unprojected: 1, projects_docs: true },
    ],
  }
}

export async function getDemoStoreExchangeStation(
  stationId: number,
  dateFrom: string,
  dateTo: string,
): Promise<StoreExchangeStationDetail> {
  const row = exchangeRows(dateTo, [String(stationId)])[0]
  const seed = EXCHANGE.find((station) => station.id === stationId) ?? EXCHANGE[0]
  const isProblem = seed.state !== 'онлайн'
  return {
    station_id: stationId,
    from: dateFrom,
    to: dateTo,
    session_gap_minutes: 15,
    agent: row ? {
      state: row.state, silence_seconds: row.silence_seconds, version: row.version,
      version_ok: row.version === '1.8.4', queue_pending: row.queue_pending,
      queue_sent: row.queue_sent, last_shift: row.last_shift, queue_bytes: row.queue_bytes,
      queue_wire_bytes: row.queue_wire_bytes, queue_oldest_at: row.queue_oldest_at,
      queue_failing: row.queue_failing, queue_sent_24: row.queue_sent_24,
      sent_24_bytes: row.sent_24_bytes, sent_24_wire_bytes: row.sent_24_wire_bytes,
      last_sent_at: row.last_sent_at, last_attempt_at: row.last_attempt_at,
      last_error: row.last_error, clock_skew_seconds: row.clock_skew_seconds,
      snapshot_at: row.snapshot_at, onec_ok: true, stock_source: 'edge_agent',
      first_seen: at(dateFrom, '08:00:00'), last_seen: row.last_seen ?? at(dateTo, '12:00:00'),
    } : null,
    totals: {
      sessions: seed.sessions, packets: seed.packets, bytes: seed.packets * 47_000,
      wire_bytes: seed.packets * 14_600, wire_packets: seed.packets,
      avg_silence_min: isProblem ? 37 : 8, max_silence_min: isProblem ? 182 : 24,
      down_waiting: stationId === 315 ? 2 : 0, down_unacked: stationId === 208 ? 1 : 0,
      down_acked: seed.sessions + 4, down_bytes: stationId === 315 ? 18_400 : 4_200,
      down_avg_ack_seconds: isProblem ? 1_480 : 64,
    },
    availability: {
      minutes_seen: Math.round(dateRange(dateFrom, dateTo).length * 1_440 * seed.uptime / 100),
      minutes_total: dateRange(dateFrom, dateTo).length * 1_440,
      pct: seed.uptime,
      first_at: at(dateFrom, '08:00:00'),
      last_at: at(dateTo, seed.state === 'онлайн' ? '16:44:00' : '13:42:00'),
      outage_minutes: isProblem ? 212 : 18,
      outages: isProblem ? [
        { started: at(dateTo, '13:42:00'), ended: null, minutes: 182, ongoing: true },
        { started: at(dateTo, '09:12:00'), ended: at(dateTo, '09:42:00'), minutes: 30, ongoing: false },
      ] : [
        { started: at(dateTo, '11:04:00'), ended: at(dateTo, '11:22:00'), minutes: 18, ongoing: false },
      ],
    },
    sessions: [
      { session_no: 1, started: at(dateTo, '16:38:00'), finished: at(dateTo, '16:43:00'), duration_min: 5, packets: 12, bytes: 624_000, wire_bytes: 184_000, wire_packets: 12, kinds: ['shift', 'stock'], silence_before_min: isProblem ? 182 : 9 },
      { session_no: 2, started: at(dateTo, '12:50:00'), finished: at(dateTo, '12:56:00'), duration_min: 6, packets: 9, bytes: 448_000, wire_bytes: 131_000, wire_packets: 9, kinds: ['documents', 'stock'], silence_before_min: 14 },
      { session_no: 3, started: at(dateTo, '08:10:00'), finished: at(dateTo, '08:14:00'), duration_min: 4, packets: 7, bytes: 312_000, wire_bytes: 92_000, wire_packets: 7, kinds: ['shift'], silence_before_min: 22 },
    ],
    by_kind: [
      { kind: 'shift', label: 'Смены', packets: 12, bytes: 560_000, wire_bytes: 168_000, wire_packets: 12, last_at: at(dateTo, '16:43:00') },
      { kind: 'stock', label: 'Снимки остатков', packets: 11, bytes: 620_000, wire_bytes: 181_000, wire_packets: 11, last_at: at(dateTo, '16:41:00') },
      { kind: 'documents', label: 'Документы станции', packets: 5, bytes: 204_000, wire_bytes: 58_000, wire_packets: 5, last_at: at(dateTo, '12:55:00') },
    ],
    downlink: [
      { kind: 'price', label: 'Новые цены', note: 'пакет 24.08', state: stationId === 315 ? 'ждёт станции' : 'применено', created_at: at(dateTo, '11:20:00'), delivered_at: stationId === 315 ? null : at(dateTo, '11:21:00'), acked_at: stationId === 315 ? null : at(dateTo, '11:22:00'), size_bytes: 8_600, delivery_seconds: stationId === 315 ? null : 54, ack_seconds: stationId === 315 ? null : 112 },
      { kind: 'nsi', label: 'Карточки НСИ', note: '3 позиции', state: 'применено', created_at: at(dateTo, '09:05:00'), delivered_at: at(dateTo, '09:06:00'), acked_at: at(dateTo, '09:07:00'), size_bytes: 4_200, delivery_seconds: 48, ack_seconds: 96 },
    ],
  }
}

export async function getDemoStoreCateringMenu(
  dateFrom: string,
  dateTo: string,
  stations?: string[],
): Promise<CateringMenuData> {
  const selected = (stations?.length ? stations : STORE_DEMO_STATIONS.map((station) => station.id))
    .filter((station) => STATION_FACTOR[station])
  const stationIds = selected.length ? selected : STORE_DEMO_STATIONS.map((station) => station.id)
  const allFactor = Object.values(STATION_FACTOR).reduce((sum, value) => sum + value, 0)
  const scale = stationIds.reduce((sum, station) => sum + STATION_FACTOR[station], 0) / allFactor
  const hasPartial = stationIds.includes('315')
  const end = new Date(`${dateTo}T00:00:00Z`)
  const monday = new Date(end)
  monday.setUTCDate(end.getUTCDate() - ((end.getUTCDay() + 6) % 7))
  const iso = (value: Date) => value.toISOString().slice(0, 10)
  const weekStarts = [14, 7, 0].map((offset) => {
    const value = new Date(monday)
    value.setUTCDate(value.getUTCDate() - offset)
    return value
  })
  const comparison = stationIds.flatMap((station, stationIndex) => weekStarts.map((week, weekIndex) => {
    const factor = STATION_FACTOR[station] * [0.91, 1, 1.08][weekIndex]
    const salesGross = round(54_800 * factor)
    const customerReturns = round(salesGross * (station === '315' ? 0.021 : 0.011))
    const vat = round((salesGross - customerReturns) * 22 / 122)
    const netRevenue = round(salesGross - customerReturns - vat)
    const ingredientCost = round(netRevenue * (station === '315' ? 0.43 : 0.34 + stationIndex * 0.012))
    const writeoffs = round(1_020 * factor)
    const shortages = round((station === '315' ? 890 : 330) * factor)
    const preliminaryContribution = round(netRevenue - ingredientCost - writeoffs - shortages)
    const weekTo = new Date(week)
    weekTo.setUTCDate(weekTo.getUTCDate() + 6)
    const costStatus = station === '315' ? 'partial' as const : 'exact' as const
    return {
      station_id: station,
      week_from: iso(week),
      week_to: iso(weekTo),
      sales_gross: salesGross,
      customer_returns: customerReturns,
      vat,
      net_revenue: netRevenue,
      ingredient_cost: ingredientCost,
      writeoffs,
      shortages,
      direct_losses: round(writeoffs + shortages),
      operating_contribution: costStatus === 'exact' ? preliminaryContribution : null,
      preliminary_contribution: preliminaryContribution,
      cost_status: costStatus,
      exact_coverage_pct: costStatus === 'exact' ? 100 : 73,
      food_cost_pct: round(ingredientCost / netRevenue * 100, 1),
      attach_rate: round((station === '208' ? 12.8 : station === '101' ? 10.4 : 7.1) + weekIndex * 0.4, 1),
    }
  }))
  const scaled = (value: number) => round(value * scale)
  const salesGross = scaled(527_640)
  const customerReturns = scaled(6_840)
  const vat = round((salesGross - customerReturns) * 22 / 122)
  const netRevenue = round(salesGross - customerReturns - vat)
  const ingredientCost = scaled(181_240)
  const writeoffs = scaled(12_840)
  const shortages = scaled(6_340)
  const preliminaryContribution = round(netRevenue - ingredientCost - writeoffs - shortages)
  const daily = (qty: number, revenue: number) => [2, 1, 0].map((offset, index) => {
    const value = new Date(end)
    value.setUTCDate(value.getUTCDate() - offset)
    const factor = [0.31, 0.34, 0.35][index]
    return { date: iso(value), qty: round(qty * factor, 1), revenue: round(revenue * factor) }
  })
  const dish = (
    guid: string, name: string, qty: number, revenue: number, returns: number,
    vatValue: number, cost: number | null, menuClass: CateringMenuData['dishes'][number]['menu_class'],
    ingredients: CateringMenuData['dishes'][number]['ingredients'],
    status: CateringMenuData['dishes'][number]['cost_status'] = 'exact',
  ): CateringMenuData['dishes'][number] => {
    const scaledQty = round(qty * scale, 1)
    const scaledRevenue = scaled(revenue)
    const scaledReturns = scaled(returns)
    const scaledVat = scaled(vatValue)
    const scaledCost = cost == null ? null : scaled(cost)
    const revenueNet = round(scaledRevenue - scaledReturns - scaledVat)
    const margin = scaledCost == null ? null : round(revenueNet - scaledCost)
    const costPerPortion = scaledCost == null || scaledQty === 0 ? null : round(scaledCost / scaledQty, 2)
    return {
      guid, name, qty: scaledQty, revenue: scaledRevenue, returns: scaledReturns, vat: scaledVat,
      revenue_net: revenueNet, avg_price: round(scaledRevenue / scaledQty, 2),
      cost: scaledCost, cost_per_portion: costPerPortion, margin,
      food_cost_pct: scaledCost == null ? null : round(scaledCost / revenueNet * 100, 1),
      margin_pct: margin == null ? null : round(margin / revenueNet * 100, 1),
      cm_unit: margin == null ? null : round(margin / scaledQty, 2),
      share: round(scaledRevenue / salesGross * 100, 1), popularity_pct: round(scaledQty / scaled(2_946) * 100, 1),
      menu_class: status === 'exact' ? menuClass : 'unknown', coverage: status === 'exact' ? 1 : 0.73,
      ing_count: ingredients.length, ingredients, daily: daily(scaledQty, scaledRevenue),
      cost_source: status === 'exact' ? 'edge_exact' : status === 'estimate' ? 'edge_estimate' : null,
      cost_status: status, preliminary: status !== 'exact',
    }
  }
  const ingredients = {
    coffee: [
      { ref: 'demo-coffee-beans', name: 'Кофе зерновой', marked: false, qty_total: scaled(18.4), qty_per_portion: 0.016, cost_total: scaled(32_180), cost_per_portion: 28 },
      { ref: 'demo-cup', name: 'Стакан 300 мл с крышкой', marked: false, qty_total: scaled(1_149), qty_per_portion: 1, cost_total: scaled(13_790), cost_per_portion: 12 },
    ],
    hotdog: [
      { ref: 'demo-sausage', name: 'Сосиска для хот-дога', marked: false, qty_total: scaled(742), qty_per_portion: 1, cost_total: scaled(49_850), cost_per_portion: 67.2 },
      { ref: 'demo-bun', name: 'Булочка для хот-дога', marked: false, qty_total: scaled(742), qty_per_portion: 1, cost_total: scaled(17_810), cost_per_portion: 24 },
    ],
    croissant: [
      { ref: 'demo-croissant', name: 'Круассан замороженный', marked: false, qty_total: scaled(611), qty_per_portion: 1, cost_total: scaled(35_440), cost_per_portion: 58 },
    ],
    cappuccino: [
      { ref: 'demo-milk', name: 'Молоко', marked: true, qty_total: scaled(94), qty_per_portion: 0.18, cost_total: hasPartial ? null : scaled(14_100), cost_per_portion: hasPartial ? null : 27 },
      { ref: 'demo-coffee-beans', name: 'Кофе зерновой', marked: false, qty_total: scaled(8.4), qty_per_portion: 0.016, cost_total: scaled(14_730), cost_per_portion: 28 },
    ],
  }
  const dishes = [
    dish('demo-americano', 'Кофе американо 300 мл', 1_149, 171_201, 1_192, 30_662, 45_970, 'star', ingredients.coffee),
    dish('demo-hotdog', 'Хот-дог классический', 742, 169_918, 2_061, 30_223, 67_660, 'star', ingredients.hotdog),
    dish('demo-croissant', 'Круассан с шоколадом', 611, 97_149, 1_194, 17_272, 35_440, 'plowhorse', ingredients.croissant),
    dish('demo-cappuccino', 'Капучино 300 мл', 444, 89_372, 2_393, 15_718, hasPartial ? null : 30_480, 'puzzle', ingredients.cappuccino, hasPartial ? 'partial' : 'exact'),
  ]
  return {
    period: { from: dateFrom, to: dateTo },
    summary: {
      dishes_count: dishes.length, dishes_costed: hasPartial ? 3 : 4,
      revenue: salesGross, revenue_costed: dishes.filter((item) => item.cost != null).reduce((sum, item) => sum + item.revenue, 0),
      revenue_net: netRevenue, portions: dishes.reduce((sum, item) => sum + item.qty, 0),
      cost: ingredientCost, margin: preliminaryContribution,
      food_cost_pct: round(ingredientCost / netRevenue * 100, 1), margin_pct: round(preliminaryContribution / netRevenue * 100, 1),
      sales_gross: salesGross, customer_returns: customerReturns, gross_revenue: round(salesGross - customerReturns), vat,
      net_revenue: netRevenue, ingredient_cost: ingredientCost,
      ingredient_cost_exact: hasPartial ? round(ingredientCost * 0.87) : ingredientCost,
      ingredient_cost_estimated: hasPartial ? round(ingredientCost * 0.13) : 0,
      writeoffs, shortages, direct_losses: round(writeoffs + shortages),
      operating_contribution: hasPartial ? null : preliminaryContribution,
      preliminary_contribution: preliminaryContribution,
      cost_status: hasPartial ? 'partial' : 'exact', exact_coverage_pct: hasPartial ? 87 : 100,
      missing_loss_documents: hasPartial ? 2 : 0,
    },
    matrix: {
      star: { count: 2, revenue: dishes[0].revenue + dishes[1].revenue },
      plowhorse: { count: 1, revenue: dishes[2].revenue },
      unknown: { count: hasPartial ? 1 : 0, revenue: hasPartial ? dishes[3].revenue : 0 },
    },
    dishes,
    comparison,
    cross_sell: {
      available: true, cheques: scaled(5_824), kitchen_cheques: scaled(2_214), fuel_cheques: scaled(4_781),
      fuel_with_kitchen: scaled(524), attach_rate: 11, kitchen_in_fuel: scaled(119_840), avg_kitchen_in_fuel: 228.7,
      pairs: [
        { dish: 'Кофе американо 300 мл', with_item: 'Вода минеральная 0,5 л', cheques: scaled(164), with_item_amount: scaled(14_596) },
        { dish: 'Хот-дог классический', with_item: 'Напиток газированный 0,5 л', cheques: scaled(132), with_item_amount: scaled(18_348) },
        { dish: 'Капучино 300 мл', with_item: 'Круассан с шоколадом', cheques: scaled(96), with_item_amount: scaled(15_264) },
      ],
    },
    recommendations: [
      { title: 'Закрыть пробелы себестоимости', evidence: hasPartial ? '87% затрат подтверждено; 2 документа потерь без полной оценки.' : 'Все затраты периода подтверждены.', action: hasPartial ? 'Проверить цены молока и два документа АЗС 315 перед сравнением вклада.' : 'Сохранить контроль полноты при закрытии следующей недели.' },
      { title: 'Разобрать недостачи АЗС 315', evidence: 'Недостачи станции выше медианы сети в 2,6 раза.', action: 'Сверить пересчёты, выпуск кухни и возвраты по неделе 17–23 августа.' },
      { title: 'Проверить пару кофе + вода', evidence: '164 совместных чека; наблюдение без вывода о причине.', action: 'Сравнить долю пары по сменам и выкладке, не создавая задачу автоматически.' },
    ],
  }
}
