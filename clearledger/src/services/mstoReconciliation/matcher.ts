/**
 * Модуль сопоставления транзакций MSTO ↔ TF ↔ Смены
 *
 * Логика трёхсторонней сверки:
 * 1. Для каждой транзакции MSTO ищем соответствующую транзакцию TF
 * 2. Для каждой транзакции TF без пары MSTO создаём запись only_tf
 * 3. Для смен без транзакций создаём записи only_shift
 */

import type {
  MSTOTransaction,
  TFOnlineTransaction,
  MSTOReconciliationTransaction,
  MSTOReconciliationTransactionStatus
} from '@/types/mstoReconciliation';
import type { MSTOShiftInfo } from './dataFetcher';
import { SUM_TOLERANCE, VOLUME_TOLERANCE, TIME_TOLERANCE_MS } from './constants';
import { isDateInShift, generateTransactionId, round, getStationName, normalizeAggregatorName } from './utils';

/**
 * Результат построчного сопоставления
 */
export interface MatchingResult {
  transactions: MSTOReconciliationTransaction[];
  matched: number;
  mstoWaitDone: number;
  onlyMsto: number;
  onlyTf: number;
  onlyShift: number;
  mismatch: number;
}

/**
 * Выполнить построчное сопоставление MSTO ↔ TF ↔ Смены
 *
 * @param mstoTransactions - транзакции MSTO (агрегаторы)
 * @param tfTransactions - транзакции TF (факт отпуска)
 * @param shiftsInfo - информация о сменах
 * @param stationNameMap - карта имён станций
 * @param stationMapping - маппинг TF station ID -> MSTO servicePointId
 */
export function performLineByLineMatching(
  mstoTransactions: MSTOTransaction[],
  tfTransactions: TFOnlineTransaction[],
  shiftsInfo: MSTOShiftInfo[],
  stationNameMap: Map<number, string>,
  stationMapping: Map<number, number>
): MatchingResult {
  const transactions: MSTOReconciliationTransaction[] = [];
  let matched = 0;
  let mstoWaitDone = 0;
  let onlyMsto = 0;
  let onlyTf = 0;
  let onlyShift = 0;
  let mismatch = 0;

  // Обратный маппинг: MSTO servicePointId -> TF station ID
  const reversedMapping = new Map<number, number>();
  for (const [tfId, mstoId] of stationMapping) {
    reversedMapping.set(mstoId, tfId);
  }

  // Отслеживаем сопоставленные TF транзакции
  const matchedTfIds = new Set<number>();
  // Отслеживаем смены с транзакциями
  const matchedShiftIds = new Set<number>();

  // ==========================================
  // Этап 1: Сопоставляем MSTO → TF
  // ==========================================
  for (const mstoTx of mstoTransactions) {
    // Определяем TF station ID
    const tfStationId = reversedMapping.get(mstoTx.servicePointId) || mstoTx.servicePointId;
    const stationName = getStationName(tfStationId, stationNameMap);

    // Ищем смену для транзакции
    const matchingShift = findShiftForTransaction(
      mstoTx.completedAt || mstoTx.orderDate,
      tfStationId,
      shiftsInfo
    );

    if (matchingShift) {
      matchedShiftIds.add(matchingShift.id);
    }

    // Ищем соответствующую TF транзакцию
    const matchingTf = findMatchingTfTransaction(
      mstoTx,
      tfTransactions,
      tfStationId,
      matchedTfIds
    );

    // Определяем статус
    let status: MSTOReconciliationTransactionStatus;

    if (!matchingTf) {
      // Есть в MSTO, нет в TF - заказ создан, но не выполнен
      status = 'only_msto';
      onlyMsto++;
    } else {
      matchedTfIds.add(matchingTf.id);

      // Проверяем расхождения по объёму
      const volumeDiff = Math.abs((mstoTx.resultValue || 0) - (matchingTf.volume || 0));

      if (volumeDiff > VOLUME_TOLERANCE) {
        status = 'mismatch';
        mismatch++;
      } else if (mstoTx.operationResult === 'wait') {
        // MSTO показывает WAIT, но TF показывает выполнено
        status = 'msto_wait_done';
        mstoWaitDone++;
      } else {
        status = 'matched';
        matched++;
      }
    }

    transactions.push({
      id: generateTransactionId(mstoTx.orderDate, tfStationId, mstoTx.id, matchingShift?.id),
      date: mstoTx.completedAt || mstoTx.orderDate,
      stationId: tfStationId,
      stationName,
      mstoServicePointId: mstoTx.servicePointId,
      fuelType: mstoTx.fuelName,
      aggregatorName: mstoTx.tariffName || normalizeAggregatorName(''),
      shiftId: matchingShift?.id || null,
      // MSTO данные
      mstoSum: round(mstoTx.resultSum),
      mstoVolume: round(mstoTx.resultValue),
      mstoTransactionId: mstoTx.id,
      mstoOperationResult: mstoTx.operationResult,
      externalOrderId: mstoTx.externalId,
      // TF данные
      tfSum: matchingTf ? round(matchingTf.total) : null,
      tfVolume: matchingTf ? round(matchingTf.volume) : null,
      tfTransactionId: matchingTf?.id,
      // Смена данные
      shiftSum: matchingShift ? round(matchingShift.sbpRevenue) : null,
      shiftVolume: matchingShift ? round(matchingShift.nonCashVolume) : null,
      status
    });
  }

  // ==========================================
  // Этап 2: TF транзакции без пары MSTO
  // ==========================================
  for (const tfTx of tfTransactions) {
    if (matchedTfIds.has(tfTx.id)) continue;

    const stationName = getStationName(tfTx.stationId, stationNameMap);

    // Ищем смену для транзакции
    const matchingShift = findShiftForTransaction(
      tfTx.date,
      tfTx.stationId,
      shiftsInfo
    );

    if (matchingShift) {
      matchedShiftIds.add(matchingShift.id);
    }

    onlyTf++;

    transactions.push({
      id: generateTransactionId(tfTx.date, tfTx.stationId, undefined, matchingShift?.id, tfTx.id),
      date: tfTx.date,
      stationId: tfTx.stationId,
      stationName,
      fuelType: tfTx.fuelType,
      aggregatorName: 'Неизвестный',
      shiftId: matchingShift?.id || tfTx.shiftId || null,
      // MSTO данные (нет)
      mstoSum: null,
      mstoVolume: null,
      // TF данные
      tfSum: round(tfTx.total),
      tfVolume: round(tfTx.volume),
      tfTransactionId: tfTx.id,
      // Смена данные
      shiftSum: matchingShift ? round(matchingShift.sbpRevenue) : null,
      shiftVolume: matchingShift ? round(matchingShift.nonCashVolume) : null,
      status: 'only_tf'
    });
  }

  // ==========================================
  // Этап 3: Смены без транзакций MSTO и TF
  // ==========================================
  for (const shift of shiftsInfo) {
    if (!matchedShiftIds.has(shift.id) && shift.sbpRevenue > 0) {
      const stationName = getStationName(shift.stationId, stationNameMap);

      onlyShift++;

      transactions.push({
        id: generateTransactionId(shift.openedAt, shift.stationId, undefined, shift.id),
        date: shift.openedAt,
        stationId: shift.stationId,
        stationName,
        fuelType: 'Разные',
        aggregatorName: 'Неизвестный',
        shiftId: shift.id,
        // MSTO данные (нет)
        mstoSum: null,
        mstoVolume: null,
        // TF данные (нет)
        tfSum: null,
        tfVolume: null,
        // Смена данные
        shiftSum: round(shift.sbpRevenue),
        shiftVolume: round(shift.nonCashVolume),
        status: 'only_shift'
      });
    }
  }

  return {
    transactions,
    matched,
    mstoWaitDone,
    onlyMsto,
    onlyTf,
    onlyShift,
    mismatch
  };
}

/**
 * Найти смену для транзакции по времени и станции
 */
function findShiftForTransaction(
  txDate: string,
  tfStationId: number,
  shiftsInfo: MSTOShiftInfo[]
): MSTOShiftInfo | null {
  for (const shift of shiftsInfo) {
    if (shift.stationId !== tfStationId) continue;

    if (isDateInShift(txDate, shift.openedAt, shift.closedAt)) {
      return shift;
    }
  }
  return null;
}

/**
 * Найти соответствующую TF транзакцию для MSTO транзакции
 * Критерии сопоставления:
 * - Та же станция
 * - Тот же вид топлива (нормализованный)
 * - Близкое время (±30 минут)
 * - Близкий объём (±1 литр)
 */
function findMatchingTfTransaction(
  mstoTx: MSTOTransaction,
  tfTransactions: TFOnlineTransaction[],
  tfStationId: number,
  usedTfIds: Set<number>
): TFOnlineTransaction | null {
  const mstoDate = new Date(mstoTx.completedAt || mstoTx.orderDate).getTime();
  const mstoVolume = mstoTx.resultValue || 0;
  const mstoFuel = (mstoTx.fuelName || '').toLowerCase();

  let bestMatch: TFOnlineTransaction | null = null;
  let bestTimeDiff = Infinity;

  for (const tfTx of tfTransactions) {
    // Пропускаем уже сопоставленные
    if (usedTfIds.has(tfTx.id)) continue;

    // Проверяем станцию
    if (tfTx.stationId !== tfStationId) continue;

    // Проверяем вид топлива
    const tfFuel = (tfTx.fuelType || '').toLowerCase();
    if (!isFuelMatch(mstoFuel, tfFuel)) continue;

    // Проверяем время
    const tfDate = new Date(tfTx.date).getTime();
    const timeDiff = Math.abs(mstoDate - tfDate);
    if (timeDiff > TIME_TOLERANCE_MS) continue;

    // Проверяем объём
    const volumeDiff = Math.abs(mstoVolume - (tfTx.volume || 0));
    if (volumeDiff > VOLUME_TOLERANCE * 2) continue; // Допуск x2 для поиска

    // Выбираем ближайший по времени
    if (timeDiff < bestTimeDiff) {
      bestMatch = tfTx;
      bestTimeDiff = timeDiff;
    }
  }

  return bestMatch;
}

/**
 * Проверка совпадения вида топлива
 */
function isFuelMatch(fuel1: string, fuel2: string): boolean {
  // Нормализуем названия
  const normalize = (f: string) => f
    .replace(/[-\s]/g, '')
    .replace(/аи/g, '')
    .replace(/бензин/g, '')
    .replace(/дизель/g, 'дт')
    .replace(/diesel/g, 'дт');

  const f1 = normalize(fuel1);
  const f2 = normalize(fuel2);

  // Точное совпадение после нормализации
  if (f1 === f2) return true;

  // Частичное совпадение (92, 95, 98, 100, дт)
  const grades = ['92', '95', '98', '100', 'дт'];
  for (const grade of grades) {
    if (f1.includes(grade) && f2.includes(grade)) return true;
  }

  return false;
}

/**
 * Проверка расхождения по сумме
 */
export function hasSumMismatch(sum1: number, sum2: number): boolean {
  return Math.abs(sum1 - sum2) > SUM_TOLERANCE;
}

/**
 * Проверка расхождения по объему
 */
export function hasVolumeMismatch(volume1: number, volume2: number): boolean {
  return Math.abs(volume1 - volume2) > VOLUME_TOLERANCE;
}
