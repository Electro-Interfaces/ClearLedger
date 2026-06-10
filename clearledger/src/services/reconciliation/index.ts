/**
 * Сервис трёхсторонней сверки корпоративного процессинга
 *
 * Модульная структура:
 * - constants.ts    - константы (TIME_TOLERANCE_MS и др.)
 * - utils.ts        - утилиты (normalizeFuelName, round, mapTradecorpStationToSts)
 * - dataFetcher.ts  - получение данных из API (Corp, TF, Shifts)
 * - matcher.ts      - построчная сверка Corp ↔ TF
 * - aggregator.ts   - агрегация по станциям, топливу, сменам
 * - orchestrator.ts - главная логика (executeReconciliation)
 *
 * Использование:
 * ```typescript
 * import { executeReconciliation } from '@/services/reconciliation';
 *
 * const result = await executeReconciliation({
 *   dateFrom: '2025-01-01',
 *   dateTo: '2025-01-07',
 *   stationIds: [3],
 *   showAllShifts: false
 * });
 * ```
 */

// Главная функция сверки
export { executeReconciliation } from './orchestrator';

// Константы (для использования в UI)
export {
  TIME_TOLERANCE_MS,
  LITERS_TOLERANCE,
  UI_DISCREPANCY_TOLERANCE,
  TRANSACTION_STATUS_ORDER
} from './constants';

// Утилиты (для использования в компонентах)
export {
  normalizeFuelName,
  round,
  mapTradecorpStationToSts,
  normalizeStationIds,
  getStationName,
  buildStationNameMap
} from './utils';

// Функции получения данных (для тестирования и отладки)
export {
  getCorpTransactions,
  getTfTransactions,
  getShiftsWithReports,
  getAvailableStations
} from './dataFetcher';

// Функции сверки (для тестирования)
export {
  performLineByLineReconciliation,
  findShiftForTransaction
} from './matcher';

export type { MatchingResult } from './matcher';

// Функции агрегации (для тестирования)
export {
  aggregateByStationAndShift,
  aggregateByFuel
} from './aggregator';
