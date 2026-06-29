/**
 * UI-типы формы «Детали смены» (сменный отчёт АЗС).
 * Перенесено 1:1 из TradeFrame (shift-reports-v2) — эталон формы TradePoint.
 * Адаптер ShiftReportAdapterV2 строит ShiftDetails из сырого отчёта STS.
 */

// ============================================
// Базовые типы
// ============================================

/** Статус смены */
export type ShiftStatus = 'open' | 'closed' | 'synchronized';

/** Элемент списка смен (для таблицы/журнала) */
export interface ShiftListItem {
  id: string;
  shiftNumber: number;
  openedAt: string;
  closedAt: string | null;
  status: ShiftStatus;
  operator: string;
  posNumber: number;
  shift: number;
  stationName?: string;
  station?: number;

  // Итоговые показатели
  totalRevenue: number;
  totalVolume: number;
  transactionCount: number;

  // Разбивка по способам оплаты
  cashRevenue: number;
  cardRevenue: number;
  sbpRevenue: number;
  fuelCardRevenue: number;
  corporateCardRevenue: number;
  otherRevenue: number;

  // Флаги и метаданные
  hasDiscrepancies: boolean;
  averageCheck: number;
  stationCode: number;
}

// ============================================
// Детальная информация о смене
// ============================================

/** Показания счётного механизма (ТРК) */
export interface NozzleReading {
  pumpNumber: number;
  nozzle: string;
  startCounter: number;
  endCounter: number;
  volume: number;
  amount: number;
  price: number;
  cost: number;
  fuelCode: number;
  fuelName: string;
  tankNumber: number;
  density: number;
}

/** Продажи по топливу */
export interface FuelSalesItem {
  fuelCode: number;
  fuelName: string;
  quantity: number;
  cost: number;
  amount?: number;
}

/** Продажи по способам оплаты */
export interface PaymentSalesItem {
  paymentTypeId: number;
  paymentTypeName: string;
  quantity: number;
  cost: number;
  amount?: number;
}

/** Детализированные продажи по топливу и способам оплаты (Расшифровка реализации) */
export interface FuelSalesBreakdown {
  fuelCode: number;
  fuelName: string;
  pumpVolume: number;
  cardVolume: number;
  cardCost: number;
  discountCost: number;
  cashVolume: number;
  cashCost: number;
  nonCashVolume: number;
  totalVolume: number;
  difference: number;
  corporateVolume?: number;
  corporateCost?: number;
  byPayType?: Record<string, {
    displayName: string;
    category: 'cash' | 'card' | 'fuel_card' | 'corporate' | 'online' | 'coupon' | 'other';
    volume: number;
    cost: number;
    discount: number;
  }>;
}

/** Снимок состояния резервуара */
export interface TankSnapshot {
  tankNumber: number;
  fuelCode: number;
  fuelName: string;
  volumeBegin: number;
  volumeEnd: number;
  volumeDispensed: number;
  volumeReceived: number;
  volumeCalculated: number;
  volumeDifference: number;
  hasExcessError: boolean;
  level?: number;
  temperature?: number;
  density?: number;
  waterLevel?: number;
  waterVolume?: number;
}

/** Поступление нефтепродукта */
export interface ReceiptItem {
  id: string;
  datetime: string;
  tankNumber: number;
  fuelCode: number;
  fuelName: string;
  // По документу
  volume: number;
  amount?: number;
  density?: number;
  temperature?: number;
  // Фактически
  actualVolume?: number;
  actualAmount?: number;
  actualDensity?: number;
  actualTemperature?: number;
  // Метаданные
  documentNumber?: string;
  supplier?: string;
}

/** Движение наличных денежных средств */
export interface CashMovementItem {
  id: string;
  datetime: string;
  operationType: 'income' | 'expense' | 'opening' | 'closing';
  amount: number;
  description: string;
  posNumber?: number;
}

/** Информация о рабочем месте (ПСМ) */
export interface PosInfoItem {
  posNumber: number;
  shiftNumber: number;
  shiftStatus: number;
  shiftOpenedAt?: string;
  shiftClosedAt?: string;
  operator?: string;
  uptime?: string;
  lastUpdate?: string;
}

/** Детальная информация о смене */
export interface ShiftDetails extends ShiftListItem {
  posInfo: PosInfoItem[];
  nozzleReadings: NozzleReading[];
  tanks: TankSnapshot[];
  receipts: ReceiptItem[];
  fuelSales: FuelSalesItem[];
  paymentSales: PaymentSalesItem[];
  salesBreakdown: FuelSalesBreakdown[];
  cashMovements: CashMovementItem[];
  reportCreatedAt: string;
  /** Сырые данные продаж STS — для динамической таблицы «Безналичная реализация» */
  salesRaw?: any[];
  receiptsRaw?: any[];
}
