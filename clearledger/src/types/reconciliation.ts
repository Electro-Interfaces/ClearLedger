// Типы для трёхсторонней сверки корпоративного процессинга
// Corp (TradeCorp) ↔ TF (TradePoint /v2/transactions) ↔ Смена (shift_report)

/**
 * Параметры запуска сверки
 */
export interface ReconciliationParams {
  dateFrom: string; // YYYY-MM-DD
  dateTo: string;   // YYYY-MM-DD
  stationIds: number[]; // Пустой массив = все станции
  showAllShifts?: boolean; // Показать все смены (включая без корп. карт)
  systemId?: number; // ID эмитента (system) из настроек сети
}

/**
 * Статус строки сверки (построчная Corp ↔ TF)
 */
export type ReconciliationTransactionStatus =
  | 'matched'      // Corp и TF совпали по всем критериям
  | 'only_corp'    // Есть в Corp, нет в TF ("лишняя" в процессинге)
  | 'only_tf'      // Есть в TF, нет в Corp ("лишняя" в TradePoint)
  | 'mismatch';    // Найдено по времени/станции/топливу, но литры разные

/**
 * Статус сверки (ok/error)
 */
export type ReconciliationStatus = 'ok' | 'error';

/**
 * Строка построчной сверки Corp ↔ TF
 */
export interface ReconciliationTransaction {
  id: string;                              // Уникальный ID для React key
  date: string;                            // ISO datetime
  stationId: number;                       // ID станции
  stationName: string;                     // Название станции
  fuelType: string;                        // Название топлива
  cardNumber: string;                      // Номер карты
  shiftId: number | null;                  // Определённая смена
  corpLiters: number | null;               // Литры Corp
  tfLiters: number | null;                 // Литры TF
  corpTransactionId?: number;              // ID транзакции Corp
  tfTransactionId?: number;                // ID транзакции TF
  status: ReconciliationTransactionStatus; // Статус сопоставления
}

/**
 * Сверка по виду топлива (три источника)
 */
export interface ReconciliationByFuel {
  fuelName: string;
  // Три источника данных (литры)
  corpLiters: number;     // Сумма Corp за период
  tfLiters: number;       // Сумма TF за период
  shiftLiters: number;    // Из сменного отчёта
  // Расхождения
  corpVsTfDiff: number;   // Corp - TF
  tfVsShiftDiff: number;  // TF - Смена
  status: ReconciliationStatus;
}

/**
 * Данные по смене для конкретного топлива
 */
export interface ReconciliationShiftData {
  shiftId: number;
  shiftDate: string;           // Дата смены
  shiftOpenedAt: string;       // Время открытия
  shiftClosedAt: string | null; // Время закрытия (null = не закрыта)
  corpLiters: number;
  tfLiters: number;
  shiftLiters: number;
  status: ReconciliationStatus;
}

/**
 * Сверка по топливу с разбивкой по сменам (новая структура)
 */
export interface ReconciliationByFuelWithShifts {
  fuelName: string;
  byShift: ReconciliationShiftData[];  // Разбивка по сменам
  // Итоги по топливу
  corpLitersTotal: number;
  tfLitersTotal: number;
  shiftLitersTotal: number;
  status: ReconciliationStatus;
}

/**
 * Сверка по смене с разбивкой по топливу (старая структура, для совместимости)
 */
export interface ReconciliationByShift {
  stationId: number;
  stationName: string;
  shiftId: number;
  shiftDate: string;           // Дата смены
  shiftOpenedAt: string;       // Время открытия
  shiftClosedAt: string | null; // Время закрытия (null = не закрыта)
  byFuel: ReconciliationByFuel[];
  // Итоги по смене
  corpLitersTotal: number;     // Corp литры
  tfLitersTotal: number;       // TF литры
  shiftLitersTotal: number;    // Смена литры
  status: ReconciliationStatus;
}

/**
 * Сверка по станции (новая структура: АЗС → Топливо → Смены)
 */
export interface ReconciliationByStation {
  stationId: number;
  stationName: string;
  byFuel: ReconciliationByFuelWithShifts[];  // Разбивка по топливу
  byShift?: ReconciliationByShift[];  // Старая структура (для совместимости)
  // Итоги по станции
  corpLitersTotal: number;
  tfLitersTotal: number;
  shiftLitersTotal: number;
  status: ReconciliationStatus;
}

/**
 * Сводка результатов сверки
 */
export interface ReconciliationSummary {
  // Итого литров по источникам
  totalCorpLiters: number;
  totalTfLiters: number;
  totalShiftLiters: number;
  // Статистика транзакций
  matched: number;      // Совпавших транзакций Corp ↔ TF
  onlyCorp: number;     // Только в Corp
  onlyTf: number;       // Только в TF
  mismatch: number;     // С расхождением литров
  // Общий статус
  hasErrors: boolean;
}

/**
 * Полный результат сверки
 */
export interface ReconciliationResult {
  params: ReconciliationParams;              // Параметры запроса
  summary: ReconciliationSummary;            // Общая статистика
  byStation: ReconciliationByStation[];      // По станциям с разбивкой по сменам
  transactions: ReconciliationTransaction[]; // Построчная сверка Corp ↔ TF
  executedAt: string;                        // Время выполнения
  duration: number;                          // Длительность (мс)
}

// ============================================
// Типы для работы с источниками данных
// ============================================

/**
 * Транзакция Corp (TradeCorp API)
 */
export interface CorpTransaction {
  id: number;
  date: string;            // ISO datetime
  cardNumber: string;
  cardId: number;
  stationId: number;
  stationNumber: number;
  stationName: string;
  operationName: string;
  quantity: number;        // Литры
  cost: number;            // Сумма в рублях
  price: number;           // Цена за литр
  productName: string;     // Название топлива
  cheque: {
    productName: string;
    quantity: number;
    cost: number;
    price: number;
  }[];
}

/**
 * Транзакция TF (TradePoint /v2/transactions)
 */
export interface TfTransaction {
  id: number;
  transactionId: string;
  date: string;            // ISO datetime
  stationId: number;
  stationName: string;
  fuelType: string;        // Название топлива
  volume: number;          // Литры
  price: number;           // Цена за литр
  total: number;           // Сумма
  cardNumber?: string;     // Номер карты
  paymentMethod?: string;  // Способ оплаты (КР = корп.карта)
}

/**
 * Информация о смене
 */
export interface ShiftInfo {
  id: number;
  stationId: number;
  stationName: string;
  openedAt: string;        // ISO datetime
  closedAt: string | null; // ISO datetime или null если не закрыта
  // Данные из сменного отчёта по топливу
  fuelSales: {
    fuelName: string;
    quantity: number;      // Литры по корп. картам (КР)
  }[];
}

/**
 * Транзакция TradeCorp (как отдаёт backend-прокси /api/tradecorp/transactions).
 * По форме совпадает с CorpTransaction.
 */
export type TradecorpTransaction = CorpTransaction;

/**
 * Ответ от TradeCorp API
 */
export interface TradecorpTransactionsResponse {
  success: boolean;
  count: number;
  transactions: TradecorpTransaction[];
}

/**
 * Строка сводки по станции (агрегат TradeCorp)
 */
export interface TradecorpStationSummary {
  stationNumber: number;
  stationName: string;
  totalQuantity: number;
  totalCost: number;
  transactionsCount: number;
}

/**
 * Ответ сводки TradeCorp (/api/tradecorp/transactions/summary)
 */
export interface TradecorpSummaryResponse {
  success: boolean;
  summary: TradecorpStationSummary[];
}

/**
 * Нормализованное название топлива для сопоставления
 */
export type NormalizedFuelName = string;

// ============================================
// Константы (реэкспорт из constants.ts)
// ============================================

export { TIME_TOLERANCE_MS, COST_TOLERANCE, LITERS_TOLERANCE } from '@/services/reconciliation/constants';
