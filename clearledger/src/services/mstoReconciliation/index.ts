/**
 * Модуль сверки MSTO онлайн-заказов
 *
 * MSTO IntegratorService ↔ Сменный отчет (STS API)
 *
 * Экспортируем:
 * - executeMstoReconciliation - главная функция сверки
 * - типы и утилиты
 */

// Главная функция сверки
export { executeMstoReconciliation } from './orchestrator';

// Получение данных
export {
  fetchMstoTransactions,
  fetchShiftsWithOnlineData,
  fetchMstoServicePoints,
  fetchMstoTariffs,
  buildStationMapping,
  getAvailableStations
} from './dataFetcher';
export type { MSTOShiftInfo, StationMapping } from './dataFetcher';

// Сопоставление
export {
  performLineByLineMatching,
  hasSumMismatch,
  hasVolumeMismatch
} from './matcher';
export type { MatchingResult } from './matcher';

// Агрегация
export {
  aggregateByStationAndShift,
  aggregateAllByAggregator
} from './aggregator';

// Константы
export {
  TIME_TOLERANCE_MS,
  SUM_TOLERANCE,
  VOLUME_TOLERANCE,
  UI_SUM_DISCREPANCY_TOLERANCE,
  UI_VOLUME_DISCREPANCY_TOLERANCE,
  SUCCESSFUL_OPERATION_RESULTS,
  TRANSACTION_STATUS_ORDER,
  AGGREGATOR_NAME_MAP,
  FUEL_NAME_MAP
} from './constants';

// Утилиты
export {
  round,
  normalizeAggregatorName,
  normalizeMstoFuelName,
  normalizeShiftFuelName,
  fuelNamesMatch,
  generateTransactionId,
  formatDate,
  formatDateTime,
  isDateInShift,
  normalizeStationIds,
  getStationName,
  buildStationNameMap,
  formatMoney,
  formatVolume
} from './utils';
