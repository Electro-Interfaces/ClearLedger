/**
 * Типы данных STS API и нормализованные структуры для GIG Fuel Ledger.
 */

// ─── STS API Raw Types ──────────────────────────────────────

export interface StsShift {
  shift: number
  dt_open: string
  dt_close: string | null
}

export interface StsShiftInfo {
  shift_number: number
  station_id: number
  dt_open: string
  dt_close: string | null
  operator: string
}

export interface StsTank {
  tank_number: number
  fuel_type: string
  fuel_code: number
  volume_start: number
  volume_end: number
  receipts: number
  sales: number
  density: number
}

export interface StsPump {
  pump_number: number
  nozzle: string
  fuel_type: string
  counter_start: number
  counter_end: number
  sales_volume: number
  sales_mass: number
  price: number
  amount: number
}

export interface StsPayments {
  cash: number
  card: number
  voucher: number
  total: number
}

export interface StsCashOp {
  operation: string
  amount: number
}

export interface StsShiftReport {
  shift_info: StsShiftInfo
  tanks: StsTank[]
  pumps: StsPump[]
  payments: StsPayments
  cash_operations: StsCashOp[]
}

export interface StsReceipt {
  shift: number
  tank: number
  ttn: string
  base: { id: number; name: string }
  doc: { volume: string; amount: string; cost: string }
  fact: { volume: string; amount: string; cost: string }
  dt: string
  fuel: number
  service: { service_code: number; service_name: string }
}

export interface StsPrice {
  station: number
  services: { id: number; name: string; price: number }[]
}

// ─── Normalized Types ────────────────────────────────────────

export interface ShiftRecord {
  id: string
  stationId: number
  stationName: string
  shiftNumber: number
  openedAt: string
  closedAt: string | null
  operator: string
  tanks: StsTank[]
  pumps: StsPump[]
  payments: StsPayments
  cashOperations: StsCashOp[]
  totalSalesLiters: number
  totalSalesAmount: number
  status: 'open' | 'closed'
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
