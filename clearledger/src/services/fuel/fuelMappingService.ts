/**
 * Клиент API маппингов топливных каналов STS → 1С (TradeLedger).
 * Каналы оплаты, маппинг видов оплат, виды топлива + предпросмотр документов.
 */
import { get, post, put, del } from '@/services/apiClient'

export interface PaymentChannel {
  id: string
  code: string
  name: string
  warehouse_name: string | null
  requires_transfer: boolean
  counterparty_name: string | null
  sort_order: number
}

export interface PaymentMapping {
  id: string
  pattern: string
  channel_code: string
  warehouse_override: string | null
  sort_order: number
}

export interface FuelMapping {
  id: string
  service_code: number
  fuel_name: string
  nomenclature_tonnes: string | null
  nomenclature_liters: string | null
  nomenclature_t_ref?: string | null
  nomenclature_l_ref?: string | null
  density: number | null
  sort_order: number
}

export interface FuelMappingsAll {
  payment_channels: PaymentChannel[]
  payment_mappings: PaymentMapping[]
  fuel_mappings: FuelMapping[]
}

export interface FuelDocument {
  kind: string
  idem_key: string
  payload: Record<string, unknown>
}

export interface FuelDocumentsResponse {
  shift_id?: string
  receipt_id?: string
  count: number
  documents: FuelDocument[]
}

// ─── Загруженные смены/ТТН из БД (API) — для отображения «Загружено» канала ───
export interface LoadedShift {
  id: string
  station_id: string
  station_code: number
  station_name: string | null
  shift_number: number
  opened_at: string | null
  closed_at: string | null
  status: string
  total_liters: number
  total_amount: number
  cash: number
  card: number
  voucher: number
  created_at: string
}

export interface LoadedReceipt {
  id: string
  station_id: string
  station_code: number
  station_name: string | null
  ttn: string
  fuel_name: string
  fuel_code?: number | null
  supplier: string
  shift_number?: number | null
  tank?: number | null
  doc_volume_liters: number
  fact_volume_liters: number
  diff_volume: number
  doc_mass_kg?: number
  fact_mass_kg?: number
  diff_mass?: number
  density: number | null
  fact_density?: number | null
  doc_temp?: number | null
  fact_temp?: number | null
  status: string
  received_at?: string | null
  created_at: string
}

// ─── Детали смены (5 секций как TradeFrame) ───
export interface TankDetail {
  tank_number: number; fuel_type: string; fuel_code: number | null
  volume_start: number; volume_end: number; sales: number; volume_received: number
  density: number | null; density_beg: number | null; temp_end: number | null
  level_end: number | null; water_level: number | null; water_volume: number | null
}
export interface PumpDetail {
  pump_number: number; nozzle: string | null; fuel_type: string; fuel_code: number | null
  tank_number: number | null; sales_volume: number; amount: number
  psm_beg: number | null; psm_end: number | null; price: number | null; density: number | null
}
export interface CashMovement {
  operation_id: number; operation_name: string; amount: number; pos_number: number | null
}
export interface ShiftSale {
  payment_channel: string; fuel_code: number; liters: number; amount: number
  discount: number; warehouse_name: string | null
}
export interface ShiftDetail extends LoadedShift {
  operator: string | null
  tanks: TankDetail[]
  pumps: PumpDetail[]
  cash_movements: CashMovement[]
  sales: ShiftSale[]
  receipts: LoadedReceipt[]
  /** Сырой сменный отчёт STS — вход эталонного просмотрщика. null у старых смен. */
  raw_report?: Record<string, any> | null
}
export const getShiftDetail = (id: string) => get<ShiftDetail>(`/api/fuel/shifts/${id}`)

// ─── Удаление загруженных смен/ТТН за период по станциям ───
export interface DeletePeriodBody {
  kind: 'shift' | 'receipt'
  station_codes?: number[]
  date_from?: string
  date_to?: string
}
export const deleteFuelPeriod = (body: DeletePeriodBody) =>
  post<{ deleted: number; kind: string }>(`/api/fuel/delete-period`, body)

// Станции, по которым есть загруженные данные (для диалога удаления/обновления)
export const getLoadedStations = () =>
  get<{ code: number; name: string }[]>(`/api/fuel/loaded-stations`)

export const getLoadedShifts = () => get<LoadedShift[]>('/api/fuel/shifts')
export const getLoadedReceipts = () => get<LoadedReceipt[]>('/api/fuel/receipts')
/** Реальное число загруженных смен/ТТН (без limit) — для карточки «Загружено». */
export const getLoadedCount = () => get<{ shifts: number; receipts: number }>('/api/fuel/count')

// ─── Свод ───
export const getFuelMappings = () => get<FuelMappingsAll>('/api/fuel-mappings')
// Справочник видов топлива (для канонического наименования по fuel_code).
export const getFuelTypes = () => get<FuelMapping[]>('/api/fuel-mappings/fuel-types')

// ─── payment_mappings (образец → канал) ───
export const createPaymentMapping = (body: Partial<PaymentMapping>) =>
  post<PaymentMapping>('/api/fuel-mappings/payment-mappings', body)
export const updatePaymentMapping = (id: string, body: Partial<PaymentMapping>) =>
  put<PaymentMapping>(`/api/fuel-mappings/payment-mappings/${id}`, body)
export const deletePaymentMapping = (id: string) =>
  del(`/api/fuel-mappings/payment-mappings/${id}`)

// ─── payment_channels ───
export const updatePaymentChannel = (id: string, body: Partial<PaymentChannel>) =>
  put<PaymentChannel>(`/api/fuel-mappings/payment-channels/${id}`, body)

// ─── fuel_mappings ───
export const updateFuelMapping = (id: string, body: Partial<FuelMapping>) =>
  put<FuelMapping>(`/api/fuel-mappings/fuel-types/${id}`, body)

// ─── Документы 1С (предпросмотр + материализация) ───
export const getShiftDocuments = (shiftId: string) =>
  get<FuelDocumentsResponse>(`/api/fuel/shifts/${shiftId}/documents`)
export const buildShiftPackets = (shiftId: string) =>
  post<{ created: number; updated: number; total: number }>(`/api/fuel/shifts/${shiftId}/build-packets`)
export const getReceiptDocuments = (receiptId: string) =>
  get<FuelDocumentsResponse>(`/api/fuel/receipts/${receiptId}/documents`)
export const buildReceiptPackets = (receiptId: string) =>
  post<{ created: number; updated: number; total: number }>(`/api/fuel/receipts/${receiptId}/build-packets`)
