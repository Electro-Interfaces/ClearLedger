/**
 * Типы для трёхсторонней сверки онлайн-заказов
 *
 * Три источника данных:
 * 1. Сменный отчет (STS API) - итоговые суммы по смене
 * 2. MSTO IntegratorService - детальные транзакции агрегаторов
 * 3. TF транзакции (/v2/transactions) - факт отпуска на ТРК
 */

// ============================================
// Типы транзакций MSTO
// ============================================

/**
 * Статус операции MSTO
 */
export type MSTOOperationResult = 'success' | 'wait' | 'error' | 'cancel';

/**
 * Транзакция MSTO IntegratorService
 */
export interface MSTOTransaction {
  id: number;
  externalId: string;           // ID заказа из агрегатора
  servicePointId: number;       // ID станции в MSTO
  servicePointName?: string;    // Название станции
  tariffId: number;             // ID тарифа (агрегатора)
  tariffName?: string;          // Название агрегатора (Яндекс, FuelUp и др.)
  fuelName: string;             // Название топлива
  orderDate: string;            // ISO datetime - дата заказа
  completedAt?: string;         // ISO datetime - дата завершения
  orderSum: number;             // Заказанная сумма (рубли)
  orderValue: number;           // Заказанный объем (литры)
  resultSum: number;            // Фактическая сумма (рубли)
  resultValue: number;          // Фактический объем (литры)
  operationResult: MSTOOperationResult; // Статус операции
  price: number;                // Цена за литр
  columnNumber?: number;        // Номер колонки
  nozzleNumber?: number;        // Номер пистолета
}

/**
 * Точка обслуживания MSTO (станция)
 */
export interface MSTOServicePoint {
  id: number;
  name: string;
  address?: string;
  externalId?: string;          // ID во внешней системе
  isActive: boolean;
}

/**
 * Тариф MSTO (агрегатор)
 */
export interface MSTOTariff {
  id: number;
  name: string;                 // Название агрегатора (Яндекс, FuelUp и др.)
  isActive: boolean;
}

// ============================================
// Типы транзакций TF (факт отпуска)
// ============================================

/**
 * Транзакция TF (/v2/transactions) - факт отпуска на ТРК
 */
export interface TFOnlineTransaction {
  id: number;
  transactionId: string;        // Уникальный ID транзакции
  date: string;                 // ISO datetime
  stationId: number;            // ID станции
  stationName: string;          // Название станции
  fuelType: string;             // Название топлива
  volume: number;               // Отпущенный объем (литры)
  price: number;                // Цена за литр
  total: number;                // Сумма (рубли)
  paymentMethod: string;        // Тип оплаты (online_order)
  columnNumber?: number;        // Номер колонки
  nozzleNumber?: number;        // Номер пистолета
  shiftId?: number;             // ID смены
}

// ============================================
// Параметры и результаты сверки
// ============================================

/**
 * Параметры запуска сверки MSTO
 */
/**
 * Информация о станции для маппинга
 */
export interface StationInfo {
  code: string;                   // Код в TF (1, 2, 3, 4)
  name: string;                   // Название (АКАЗС №1)
  description?: string;           // Описание (Непокоренных)
  stsStationId: number;           // ID в STS API
  mstoServicePointId?: number;    // Основной ID в MSTO
  mstoServicePointIds?: number[]; // Все MSTO ID (включая альтернативные)
}

export interface MSTOReconciliationParams {
  dateFrom: string;             // YYYY-MM-DD
  dateTo: string;               // YYYY-MM-DD
  stationIds: number[];         // ID станций STS (пустой = все)
  mstoServicePointIds?: number[]; // ID станций MSTO (опционально)
  showAllShifts?: boolean;      // Показать все смены (включая без онлайн)
  stations?: StationInfo[];     // Информация о станциях из БД
  systemId?: number;            // ID эмитента (system) из настроек сети
}

/**
 * Статус строки трёхсторонней сверки
 */
export type MSTOReconciliationTransactionStatus =
  | 'matched'         // MSTO, TF и смена совпали
  | 'msto_wait_done'  // MSTO статус WAIT, но TF показывает выполнено
  | 'only_msto'       // Есть в MSTO, нет в TF (заказ не выполнен)
  | 'only_tf'         // Есть в TF, нет в MSTO (ручной отпуск или сбой)
  | 'only_shift'      // Есть в смене, нет в MSTO и TF
  | 'mismatch';       // Найдено, но суммы/объемы разные

/**
 * Статус сверки (ok/error)
 */
export type MSTOReconciliationStatus = 'ok' | 'error';

/**
 * Строка построчной сверки (три источника)
 */
export interface MSTOReconciliationTransaction {
  id: string;                   // Уникальный ID для React key
  date: string;                 // ISO datetime
  stationId: number;            // ID станции TF
  stationName: string;          // Название станции
  mstoServicePointId?: number;  // ID станции MSTO
  fuelType: string;             // Название топлива
  aggregatorName: string;       // Название агрегатора
  shiftId: number | null;       // Определённая смена
  // Данные MSTO (агрегатор)
  mstoSum: number | null;       // Сумма MSTO
  mstoVolume: number | null;    // Объем MSTO (литры)
  mstoTransactionId?: number;   // ID транзакции MSTO
  mstoOperationResult?: MSTOOperationResult; // Статус операции MSTO (success/wait/error/cancel)
  externalOrderId?: string;     // Внешний ID заказа
  // Данные TF (факт отпуска)
  tfSum: number | null;         // Сумма TF (факт)
  tfVolume: number | null;      // Объем TF (факт, литры)
  tfTransactionId?: number;     // ID транзакции TF
  // Данные смены (итог)
  shiftSum: number | null;      // Сумма из смены (SBP Revenue)
  shiftVolume: number | null;   // Объем из смены
  // Статус сверки
  status: MSTOReconciliationTransactionStatus;
}

/**
 * Сверка по агрегатору (три источника)
 */
export interface MSTOReconciliationByAggregator {
  aggregatorId: number;
  aggregatorName: string;       // Яндекс, FuelUp, СберПэй и др.
  // MSTO данные
  mstoSum: number;              // Сумма MSTO
  mstoVolume: number;           // Объем MSTO
  mstoCount: number;            // Количество транзакций MSTO
  // TF данные (факт отпуска)
  tfSum: number;                // Сумма TF
  tfVolume: number;             // Объем TF
  tfCount: number;              // Количество транзакций TF
  // Смена (для совместимости)
  shiftSum: number;             // Сумма из смены
  shiftVolume: number;          // Объем из смены
  // Расхождения
  mstoVsTfSumDiff: number;      // MSTO - TF (сумма)
  mstoVsTfVolumeDiff: number;   // MSTO - TF (объем)
  sumDiff: number;              // Общее расхождение (для совместимости)
  volumeDiff: number;           // Общее расхождение (для совместимости)
  transactionCount: number;     // Всего транзакций (для совместимости)
  status: MSTOReconciliationStatus;
}

/**
 * Сверка по виду топлива (три источника)
 */
export interface MSTOReconciliationByFuel {
  fuelName: string;
  // MSTO данные
  mstoSum: number;
  mstoVolume: number;
  // TF данные (факт отпуска)
  tfSum: number;
  tfVolume: number;
  // Смена данные
  shiftSum: number;
  shiftVolume: number;
  // Расхождения
  mstoVsTfSumDiff: number;      // MSTO - TF
  mstoVsTfVolumeDiff: number;   // MSTO - TF
  tfVsShiftSumDiff: number;     // TF - Смена
  tfVsShiftVolumeDiff: number;  // TF - Смена
  sumDiff: number;              // Общее (для совместимости)
  volumeDiff: number;           // Общее (для совместимости)
  status: MSTOReconciliationStatus;
}

/**
 * Сверка по смене (три источника)
 */
export interface MSTOReconciliationByShift {
  shiftId: number;
  shiftDate: string;            // Дата смены
  shiftOpenedAt: string;        // Время открытия
  shiftClosedAt: string | null; // Время закрытия
  // MSTO данные
  mstoSum: number;
  mstoVolume: number;
  mstoCount: number;            // Количество транзакций MSTO
  // TF данные (факт отпуска)
  tfSum: number;
  tfVolume: number;
  tfCount: number;              // Количество транзакций TF
  // Смена данные
  shiftSbpRevenue: number;      // sbpRevenue из payment_totals
  shiftNonCashVolume: number;   // Безналичный объем из salesBreakdown
  // Расхождения
  mstoVsTfSumDiff: number;      // MSTO - TF
  mstoVsTfVolumeDiff: number;   // MSTO - TF
  tfVsShiftSumDiff: number;     // TF - Смена
  tfVsShiftVolumeDiff: number;  // TF - Смена
  sumDiff: number;              // MSTO - Смена (для совместимости)
  volumeDiff: number;           // MSTO - Смена (для совместимости)
  // Группировки
  byAggregator: MSTOReconciliationByAggregator[];
  byFuel: MSTOReconciliationByFuel[];
  status: MSTOReconciliationStatus;
}

/**
 * Сверка по станции (три источника)
 */
export interface MSTOReconciliationByStation {
  stationId: number;
  stationName: string;
  mstoServicePointId?: number;  // ID в MSTO
  byShift: MSTOReconciliationByShift[];
  // Итоги MSTO
  mstoSumTotal: number;
  mstoVolumeTotal: number;
  mstoCountTotal: number;
  // Итоги TF (факт отпуска)
  tfSumTotal: number;
  tfVolumeTotal: number;
  tfCountTotal: number;
  // Итоги смены
  shiftSbpRevenueTotal: number;
  shiftNonCashVolumeTotal: number;
  // Расхождения
  mstoVsTfSumDiffTotal: number;
  mstoVsTfVolumeDiffTotal: number;
  tfVsShiftSumDiffTotal: number;
  tfVsShiftVolumeDiffTotal: number;
  sumDiffTotal: number;         // Для совместимости
  volumeDiffTotal: number;      // Для совместимости
  status: MSTOReconciliationStatus;
}

/**
 * Сводка результатов трёхсторонней сверки
 */
export interface MSTOReconciliationSummary {
  // Итого по MSTO (агрегаторы)
  totalMstoSum: number;         // Сумма всех транзакций MSTO
  totalMstoVolume: number;      // Объем всех транзакций MSTO
  totalMstoCount: number;       // Количество транзакций MSTO
  // Итого по TF (факт отпуска)
  totalTfSum: number;           // Сумма всех транзакций TF
  totalTfVolume: number;        // Объем всех транзакций TF
  totalTfCount: number;         // Количество транзакций TF
  // Итого по сменам
  totalShiftSbpRevenue: number; // Сумма SBP Revenue из смен
  totalShiftNonCashVolume: number; // Объем безналичных из смен
  // Расхождения MSTO ↔ TF
  mstoVsTfSumDiff: number;      // MSTO - TF (сумма)
  mstoVsTfVolumeDiff: number;   // MSTO - TF (объем)
  // Расхождения TF ↔ Смена
  tfVsShiftSumDiff: number;     // TF - Смена (сумма)
  tfVsShiftVolumeDiff: number;  // TF - Смена (объем)
  // Расхождения MSTO ↔ Смена (для совместимости)
  sumDiff: number;              // MSTO - Смена
  volumeDiff: number;           // MSTO - Смена
  // Статистика сопоставления
  matched: number;              // Совпавших (MSTO ↔ TF)
  mstoWaitDone: number;         // MSTO WAIT, но выполнено в TF
  onlyMsto: number;             // Только в MSTO (нет в TF)
  onlyTf: number;               // Только в TF (нет в MSTO)
  onlyShift: number;            // Только в смене
  mismatch: number;             // С расхождением
  // Общий статус
  hasErrors: boolean;
}

/**
 * Полный результат сверки MSTO
 */
export interface MSTOReconciliationResult {
  params: MSTOReconciliationParams;
  summary: MSTOReconciliationSummary;
  byStation: MSTOReconciliationByStation[];
  byAggregator: MSTOReconciliationByAggregator[]; // Общая группировка по агрегаторам
  transactions: MSTOReconciliationTransaction[];
  executedAt: string;           // Время выполнения
  duration: number;             // Длительность (мс)
}

// ============================================
// Маппинг станций
// ============================================

/**
 * Маппинг внешних систем в trading_points.external_mappings
 */
export interface ExternalMappings {
  msto?: {
    servicePointId: number;
    servicePointName?: string;
  };
  tradecorp?: {
    stationId: number;
    stationName?: string;
  };
}

/**
 * Маппинг видов топлива
 */
export interface FuelMapping {
  id: string;
  internalName: string;         // Наше название (АИ-95)
  externalSystem: string;       // Внешняя система (msto, tradecorp)
  externalName: string;         // Название во внешней системе
  isActive: boolean;
}

// ============================================
// API ответы
// ============================================

/**
 * Ответ API MSTO - список транзакций
 */
export interface MSTOTransactionsResponse {
  success: boolean;
  count: number;
  transactions: MSTOTransaction[];
}

/**
 * Ответ API MSTO - список станций
 */
export interface MSTOServicePointsResponse {
  success: boolean;
  servicePoints: MSTOServicePoint[];
}

/**
 * Ответ API MSTO - список тарифов
 */
export interface MSTOTariffsResponse {
  success: boolean;
  tariffs: MSTOTariff[];
}
