/**
 * Типы данных STS API и нормализованные структуры для GIG Fuel Ledger.
 * Типы соответствуют реальному ответу pos.autooplata.ru/tms
 */

// ─── STS API: Список смен ──────────────────────────────────

export interface StsShift {
  shift: number
  dt_open: string
  dt_close: string | null
}

// ─── STS API: Сменный отчёт (shift_report) ─────────────────

/** Услуга (вид топлива) */
export interface StsService {
  service_code: number
  service_name: string
}

/** Отпуск (объём/масса/сумма) */
export interface StsRelease {
  volume: string
  amount: string
  cost: string
}

/** PSM итог по виду топлива */
export interface StsPsmTotal {
  service: StsService
  release: { quantity: number; cost: number; amount: number }
  tank: number
}

/** PSM данные по колонке/пистолету */
export interface StsPsmData {
  shift: number
  price: number
  tank: number
  density: number
  pump: number
  nozzle: string
  psm_beg: number
  psm_end: number
  release: StsRelease
  accuracy: number
  dt: string
  service: StsService
}

/** Резервуар — остатки и движение */
export interface StsTankRelease {
  shift: number
  tank: number
  density_beg: number
  density_end: number
  temp_beg: number
  temp_end: number
  doc_beg: { volume: string; amount: string }
  doc_end: { volume: string; amount: string }
  receipt: { volume: string; amount: string }
  release: { volume: string; amount: string }
  level_end: number
  volume_end: number
  water: { volume: number; level: number }
  rest: { volume: string; amount: string }
  dt: string
  service: StsService
}

/** ТТН внутри смены */
export interface StsShiftReceipt {
  tank: number
  ttn: string
  doc: { volume: string; amount: string; density: number; temp: number }
  fact: { volume: string; amount: string; density: number; temp: number }
  dt: string
  base: { id: number; name: string }
  shift: number
  service: StsService
}

/** Продажи по каналу оплаты */
export interface StsSalesChannel {
  pay_type: { id: number; name: string }
  fuel: {
    service: StsService
    release: { volume: string; cost: string; discount: number }
  }[]
}

/** Денежная операция */
export interface StsMoneyOp {
  pos: number
  shift: number
  volume: number
  operation: { id: number; name: string }
}

/** Полный сменный отчёт — как возвращает API */
export interface StsShiftReport {
  psm: {
    total: StsPsmTotal[]
    data: StsPsmData[]
  }
  release: StsTankRelease[]
  receipt: StsShiftReceipt[]
  sales: StsSalesChannel[]
  money: StsMoneyOp[]
}

// ─── STS API: Поступления (receipts) ───────────────────────

export interface StsReceipt {
  shift: number
  tank: number
  ttn: string
  base: { id: number; name: string }
  doc: { volume: string; amount: string; cost: string }
  fact: { volume: string; amount: string; cost: string }
  dt: string
  fuel: number
  service: StsService
}

export interface StsPrice {
  station: number
  services: { id: number; name: string; price: number }[]
}

// ─── STS API: Пооперационные транзакции (/v2/transactions) ──
//
// /v2/transactions возвращает массив по станциям:
//   [{ system, number, total, items: [ {dt, pay_type, fuel_name, quantity, ...}, ... ] }]
// Здесь — «плоская» строка-операция с добавленным stationNumber.
// Поля приходят как есть из STS (часть — строки), поэтому индексная сигнатура.

export interface StsTransaction {
  /** Номер станции (из обёртки {number, items}) */
  stationNumber: number
  /** Дата/время операции (ISO/строка STS) */
  dt?: string
  /** Канал оплаты */
  pay_type?: { id?: number; name?: string }
  /** Название топлива */
  fuel_name?: string
  /** Услуга (вид топлива) */
  service?: { service_code?: number; service_name?: string }
  /** Литры (строка или число) */
  quantity?: string | number
  /** Цена за литр */
  price?: string | number
  /** Сумма */
  cost?: string | number
  /** Отпуск (объём/цена/сумма) */
  release?: { volume?: string | number; price?: string | number; cost?: string | number }
  /** Номер карты (строка или объект) */
  card?: string | { number?: string }
  /** ID транзакции */
  id?: number
  /** Внутренний номер транзакции */
  transaction?: string
  number?: number
  /** Номер смены */
  shift?: number
  /** Колонка / пистолет */
  pos?: number
  nozzle?: number
  // Прочие поля STS
  [key: string]: unknown
}

// ─── Нормализованные типы ───────────────────────────────────

/** Итог продаж по виду топлива */
export interface FuelSaleSummary {
  fuelCode: number
  fuelName: string
  volumeLiters: number
  massKg: number
  amount: number
  tankNumber: number
}

/** Продажи по каналу оплаты */
export interface PaymentChannelSummary {
  channelId: number
  channelName: string
  fuels: {
    fuelCode: number
    fuelName: string
    volumeLiters: number
    amount: number
    discount: number
  }[]
  totalAmount: number
}

/** Остатки резервуара */
export interface TankSummary {
  tankNumber: number
  fuelCode: number
  fuelName: string
  densityStart: number
  densityEnd: number
  volumeStart: number
  volumeEnd: number
  received: number
  released: number
  rest: number
}

/** Нормализованный сменный отчёт */
export interface ShiftRecord {
  id: string
  stationId: number
  stationName: string
  shiftNumber: number
  openedAt: string
  closedAt: string | null
  status: 'open' | 'closed'
  /** Итоги по видам топлива */
  fuelSales: FuelSaleSummary[]
  /** Продажи по каналам оплаты */
  paymentChannels: PaymentChannelSummary[]
  /** Резервуары */
  tanks: TankSummary[]
  /** ТТН внутри смены */
  receiptsCount: number
  /** Денежные операции */
  moneyOps: StsMoneyOp[]
  /** Общие итоги */
  totalVolumeLiters: number
  totalAmount: number
  /** Сырой ответ API */
  raw: StsShiftReport
}

export interface ReceiptRecord {
  id: string
  stationId: number
  stationName: string
  shiftNumber: number
  ttn: string
  supplierName: string
  fuelName: string
  fuelCode: number
  tankNumber: number
  docVolumeLiters: number
  docMassKg: number
  docCost: number
  factVolumeLiters: number
  factMassKg: number
  factCost: number
  density: number
  receivedAt: string
  diffVolume: number
  diffMass: number
}

export interface FuelKpi {
  stationsCount: number
  shiftsTotal: number
  shiftsOpen: number
  totalSalesLiters: number
  totalSalesAmount: number
  receiptsCount: number
}
