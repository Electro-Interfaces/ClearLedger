/**
 * Модуль агрегации результатов трёхсторонней сверки
 *
 * Группировка по трём источникам (MSTO, TF, Смена):
 * - По станциям
 * - По сменам
 * - По агрегаторам (Яндекс, FuelUp и др.)
 * - По видам топлива
 */

import type {
  MSTOTransaction,
  TFOnlineTransaction,
  MSTOReconciliationByStation,
  MSTOReconciliationByShift,
  MSTOReconciliationByAggregator,
  MSTOReconciliationByFuel,
  MSTOReconciliationStatus
} from '@/types/mstoReconciliation';
import type { MSTOShiftInfo } from './dataFetcher';
import { UI_SUM_DISCREPANCY_TOLERANCE, UI_VOLUME_DISCREPANCY_TOLERANCE } from './constants';
import { round, getStationName, formatDate, normalizeAggregatorName, isDateInShift } from './utils';

/**
 * Агрегировать данные по станциям, сменам и агрегаторам (три источника)
 */
export function aggregateByStationAndShift(
  mstoTransactions: MSTOTransaction[],
  tfTransactions: TFOnlineTransaction[],
  shiftsInfo: MSTOShiftInfo[],
  stationNameMap: Map<number, string>,
  stationMapping: Map<number, number>,
  showAllShifts?: boolean
): MSTOReconciliationByStation[] {
  const byStation: MSTOReconciliationByStation[] = [];

  // Обратный маппинг: MSTO servicePointId -> TF station ID
  const reversedMapping = new Map<number, number>();
  for (const [tfId, mstoId] of stationMapping) {
    reversedMapping.set(mstoId, tfId);
  }

  // Группируем транзакции MSTO по станции
  const mstoByStation = new Map<number, MSTOTransaction[]>();
  for (const tx of mstoTransactions) {
    // ВАЖНО: servicePointId должен быть числом для правильного маппинга
    const spId = typeof tx.servicePointId === 'number' ? tx.servicePointId : parseInt(String(tx.servicePointId), 10) || 0;
    const tfStationId = reversedMapping.get(spId);

    const finalStationId = tfStationId !== undefined ? tfStationId : spId;
    const existing = mstoByStation.get(finalStationId) || [];
    existing.push(tx);
    mstoByStation.set(finalStationId, existing);
  }

  // Группируем транзакции TF по станции
  const tfByStation = new Map<number, TFOnlineTransaction[]>();
  for (const tx of tfTransactions) {
    const existing = tfByStation.get(tx.stationId) || [];
    existing.push(tx);
    tfByStation.set(tx.stationId, existing);
  }

  // Группируем смены по станции
  const shiftsByStation = new Map<number, MSTOShiftInfo[]>();
  for (const shift of shiftsInfo) {
    const existing = shiftsByStation.get(shift.stationId) || [];
    existing.push(shift);
    shiftsByStation.set(shift.stationId, existing);
  }


  // Собираем все уникальные станции
  const allStationIds = new Set<number>([
    ...mstoByStation.keys(),
    ...tfByStation.keys(),
    ...shiftsByStation.keys()
  ]);

  // Обрабатываем каждую станцию
  for (const stationId of allStationIds) {
    const stationMstoTxs = mstoByStation.get(stationId) || [];
    const stationTfTxs = tfByStation.get(stationId) || [];
    const stationShifts = shiftsByStation.get(stationId) || [];

    // Пропускаем станцию без данных (если не showAllShifts)
    if (!showAllShifts && stationMstoTxs.length === 0 && stationTfTxs.length === 0 && stationShifts.length === 0) {
      continue;
    }

    const stationName = getStationName(stationId, stationNameMap);

    // Агрегируем по сменам
    const byShift = aggregateByShift(stationMstoTxs, stationTfTxs, stationShifts, showAllShifts);

    // Подсчёт итогов по станции
    let mstoSumTotal = 0;
    let mstoVolumeTotal = 0;
    let mstoCountTotal = 0;
    let tfSumTotal = 0;
    let tfVolumeTotal = 0;
    let tfCountTotal = 0;
    let shiftSbpRevenueTotal = 0;
    let shiftNonCashVolumeTotal = 0;

    for (const shift of byShift) {
      mstoSumTotal += shift.mstoSum;
      mstoVolumeTotal += shift.mstoVolume;
      mstoCountTotal += shift.mstoCount;
      tfSumTotal += shift.tfSum;
      tfVolumeTotal += shift.tfVolume;
      tfCountTotal += shift.tfCount;
      shiftSbpRevenueTotal += shift.shiftSbpRevenue;
      shiftNonCashVolumeTotal += shift.shiftNonCashVolume;
    }

    // Расхождения
    const mstoVsTfSumDiffTotal = round(mstoSumTotal - tfSumTotal);
    const mstoVsTfVolumeDiffTotal = round(mstoVolumeTotal - tfVolumeTotal);
    const tfVsShiftSumDiffTotal = round(tfSumTotal - shiftSbpRevenueTotal);
    const tfVsShiftVolumeDiffTotal = round(tfVolumeTotal - shiftNonCashVolumeTotal);
    const sumDiffTotal = round(mstoSumTotal - shiftSbpRevenueTotal);
    const volumeDiffTotal = round(mstoVolumeTotal - shiftNonCashVolumeTotal);

    // Определяем статус станции
    const status: MSTOReconciliationStatus =
      Math.abs(mstoVsTfSumDiffTotal) > UI_SUM_DISCREPANCY_TOLERANCE ||
      Math.abs(mstoVsTfVolumeDiffTotal) > UI_VOLUME_DISCREPANCY_TOLERANCE ||
      Math.abs(tfVsShiftSumDiffTotal) > UI_SUM_DISCREPANCY_TOLERANCE ||
      Math.abs(tfVsShiftVolumeDiffTotal) > UI_VOLUME_DISCREPANCY_TOLERANCE ||
      byShift.some(s => s.status === 'error')
        ? 'error'
        : 'ok';

    byStation.push({
      stationId,
      stationName,
      mstoServicePointId: stationMapping.get(stationId),
      byShift,
      // Итоги MSTO
      mstoSumTotal: round(mstoSumTotal),
      mstoVolumeTotal: round(mstoVolumeTotal),
      mstoCountTotal,
      // Итоги TF
      tfSumTotal: round(tfSumTotal),
      tfVolumeTotal: round(tfVolumeTotal),
      tfCountTotal,
      // Итоги смены
      shiftSbpRevenueTotal: round(shiftSbpRevenueTotal),
      shiftNonCashVolumeTotal: round(shiftNonCashVolumeTotal),
      // Расхождения
      mstoVsTfSumDiffTotal,
      mstoVsTfVolumeDiffTotal,
      tfVsShiftSumDiffTotal,
      tfVsShiftVolumeDiffTotal,
      sumDiffTotal,
      volumeDiffTotal,
      status
    });
  }

  // Сортируем по номеру станции
  byStation.sort((a, b) => a.stationId - b.stationId);

  return byStation;
}

/**
 * Агрегировать данные по сменам для одной станции (три источника)
 */
function aggregateByShift(
  mstoTransactions: MSTOTransaction[],
  tfTransactions: TFOnlineTransaction[],
  shiftsInfo: MSTOShiftInfo[],
  showAllShifts?: boolean
): MSTOReconciliationByShift[] {
  const byShift: MSTOReconciliationByShift[] = [];

  // Группируем MSTO транзакции по смене
  const mstoByShift = groupMstoByShift(mstoTransactions, shiftsInfo);

  // Группируем TF транзакции по смене
  const tfByShift = groupTfByShift(tfTransactions, shiftsInfo);

  // Собираем транзакции, которые не попали ни в одну смену
  const allMstoInShifts = new Set<MSTOTransaction>();
  const allTfInShifts = new Set<TFOnlineTransaction>();

  // Обрабатываем каждую смену
  for (const shift of shiftsInfo) {
    const shiftMstoTxs = mstoByShift.get(shift.id) || [];
    const shiftTfTxs = tfByShift.get(shift.id) || [];

    // Запоминаем транзакции, которые попали в смены
    shiftMstoTxs.forEach(tx => allMstoInShifts.add(tx));
    shiftTfTxs.forEach(tx => allTfInShifts.add(tx));

    // Пропускаем смену без данных (если не showAllShifts)
    if (!showAllShifts && shiftMstoTxs.length === 0 && shiftTfTxs.length === 0 && shift.sbpRevenue === 0) {
      continue;
    }

    // Агрегируем MSTO данные
    let mstoSum = 0;
    let mstoVolume = 0;
    for (const tx of shiftMstoTxs) {
      mstoSum += tx.resultSum;
      mstoVolume += tx.resultValue;
    }

    // Агрегируем TF данные
    let tfSum = 0;
    let tfVolume = 0;
    for (const tx of shiftTfTxs) {
      tfSum += tx.total;
      tfVolume += tx.volume;
    }

    // Расхождения
    const mstoVsTfSumDiff = round(mstoSum - tfSum);
    const mstoVsTfVolumeDiff = round(mstoVolume - tfVolume);
    const tfVsShiftSumDiff = round(tfSum - shift.sbpRevenue);
    const tfVsShiftVolumeDiff = round(tfVolume - shift.nonCashVolume);
    const sumDiff = round(mstoSum - shift.sbpRevenue);
    const volumeDiff = round(mstoVolume - shift.nonCashVolume);

    // Группировка по агрегаторам
    const byAggregator = aggregateByAggregator(shiftMstoTxs, shiftTfTxs);

    // Группировка по топливу
    const byFuel = aggregateByFuel(shiftMstoTxs, shiftTfTxs, shift);

    // Определяем статус смены
    const status: MSTOReconciliationStatus =
      Math.abs(mstoVsTfSumDiff) > UI_SUM_DISCREPANCY_TOLERANCE ||
      Math.abs(mstoVsTfVolumeDiff) > UI_VOLUME_DISCREPANCY_TOLERANCE ||
      Math.abs(tfVsShiftSumDiff) > UI_SUM_DISCREPANCY_TOLERANCE ||
      Math.abs(tfVsShiftVolumeDiff) > UI_VOLUME_DISCREPANCY_TOLERANCE
        ? 'error'
        : 'ok';

    byShift.push({
      shiftId: shift.id,
      shiftDate: formatDate(shift.openedAt),
      shiftOpenedAt: shift.openedAt,
      shiftClosedAt: shift.closedAt,
      // MSTO данные
      mstoSum: round(mstoSum),
      mstoVolume: round(mstoVolume),
      mstoCount: shiftMstoTxs.length,
      // TF данные
      tfSum: round(tfSum),
      tfVolume: round(tfVolume),
      tfCount: shiftTfTxs.length,
      // Смена данные
      shiftSbpRevenue: round(shift.sbpRevenue),
      shiftNonCashVolume: round(shift.nonCashVolume),
      // Расхождения
      mstoVsTfSumDiff,
      mstoVsTfVolumeDiff,
      tfVsShiftSumDiff,
      tfVsShiftVolumeDiff,
      sumDiff,
      volumeDiff,
      byAggregator,
      byFuel,
      status
    });
  }

  // Обрабатываем несопоставленные транзакции (не попавшие ни в одну смену)
  const unmatchedMsto = mstoTransactions.filter(tx => !allMstoInShifts.has(tx));
  const unmatchedTf = tfTransactions.filter(tx => !allTfInShifts.has(tx));

  if (unmatchedMsto.length > 0 || unmatchedTf.length > 0) {
    // Агрегируем несопоставленные MSTO данные
    let mstoSum = 0;
    let mstoVolume = 0;
    for (const tx of unmatchedMsto) {
      mstoSum += tx.resultSum;
      mstoVolume += tx.resultValue;
    }

    // Агрегируем несопоставленные TF данные
    let tfSum = 0;
    let tfVolume = 0;
    for (const tx of unmatchedTf) {
      tfSum += tx.total;
      tfVolume += tx.volume;
    }

    // Расхождения
    const mstoVsTfSumDiff = round(mstoSum - tfSum);
    const mstoVsTfVolumeDiff = round(mstoVolume - tfVolume);

    // Группировка по агрегаторам и топливу
    const byAggregator = aggregateByAggregator(unmatchedMsto, unmatchedTf);

    // Для несопоставленных создаём пустой byFuel (нет данных смены)
    const byFuel: MSTOReconciliationByFuel[] = [];

    // Определяем статус
    const status: MSTOReconciliationStatus =
      Math.abs(mstoVsTfSumDiff) > UI_SUM_DISCREPANCY_TOLERANCE ||
      Math.abs(mstoVsTfVolumeDiff) > UI_VOLUME_DISCREPANCY_TOLERANCE
        ? 'error'
        : 'ok';

    // Определяем дату для "виртуальной" смены
    const sampleDate = unmatchedMsto[0]?.orderDate || unmatchedTf[0]?.date || new Date().toISOString();

    byShift.push({
      shiftId: -1, // Виртуальный ID для несопоставленных
      shiftDate: 'Без смены',
      shiftOpenedAt: sampleDate,
      shiftClosedAt: null,
      // MSTO данные
      mstoSum: round(mstoSum),
      mstoVolume: round(mstoVolume),
      mstoCount: unmatchedMsto.length,
      // TF данные
      tfSum: round(tfSum),
      tfVolume: round(tfVolume),
      tfCount: unmatchedTf.length,
      // Смена данные (нет смены)
      shiftSbpRevenue: 0,
      shiftNonCashVolume: 0,
      // Расхождения
      mstoVsTfSumDiff,
      mstoVsTfVolumeDiff,
      tfVsShiftSumDiff: round(tfSum), // TF минус 0
      tfVsShiftVolumeDiff: round(tfVolume),
      sumDiff: round(mstoSum), // MSTO минус 0
      volumeDiff: round(mstoVolume),
      byAggregator,
      byFuel,
      status
    });
  }

  // Сортируем по дате
  byShift.sort((a, b) => a.shiftOpenedAt.localeCompare(b.shiftOpenedAt));

  return byShift;
}

/**
 * Группировка MSTO транзакций по сменам
 */
function groupMstoByShift(
  mstoTransactions: MSTOTransaction[],
  shiftsInfo: MSTOShiftInfo[]
): Map<number, MSTOTransaction[]> {
  const result = new Map<number, MSTOTransaction[]>();

  for (const tx of mstoTransactions) {
    const txDate = tx.completedAt || tx.orderDate;

    for (const shift of shiftsInfo) {
      if (isDateInShift(txDate, shift.openedAt, shift.closedAt)) {
        const existing = result.get(shift.id) || [];
        existing.push(tx);
        result.set(shift.id, existing);
        break;
      }
    }
  }

  return result;
}

/**
 * Группировка TF транзакций по сменам
 */
function groupTfByShift(
  tfTransactions: TFOnlineTransaction[],
  shiftsInfo: MSTOShiftInfo[]
): Map<number, TFOnlineTransaction[]> {
  const result = new Map<number, TFOnlineTransaction[]>();

  for (const tx of tfTransactions) {
    // Если у транзакции есть shiftId, используем его
    if (tx.shiftId) {
      const existing = result.get(tx.shiftId) || [];
      existing.push(tx);
      result.set(tx.shiftId, existing);
      continue;
    }

    // Иначе ищем смену по времени
    for (const shift of shiftsInfo) {
      if (tx.stationId !== shift.stationId) continue;

      if (isDateInShift(tx.date, shift.openedAt, shift.closedAt)) {
        const existing = result.get(shift.id) || [];
        existing.push(tx);
        result.set(shift.id, existing);
        break;
      }
    }
  }

  return result;
}

/**
 * Агрегация по агрегаторам (три источника)
 */
function aggregateByAggregator(
  mstoTransactions: MSTOTransaction[],
  tfTransactions: TFOnlineTransaction[]
): MSTOReconciliationByAggregator[] {
  const byAggregator = new Map<number, {
    id: number;
    name: string;
    mstoSum: number;
    mstoVolume: number;
    mstoCount: number;
    tfSum: number;
    tfVolume: number;
    tfCount: number;
  }>();

  // Агрегируем MSTO
  for (const tx of mstoTransactions) {
    const tariffId = tx.tariffId || 0;
    const tariffName = tx.tariffName || normalizeAggregatorName('');

    const existing = byAggregator.get(tariffId) || {
      id: tariffId,
      name: tariffName,
      mstoSum: 0,
      mstoVolume: 0,
      mstoCount: 0,
      tfSum: 0,
      tfVolume: 0,
      tfCount: 0
    };

    existing.mstoSum += tx.resultSum;
    existing.mstoVolume += tx.resultValue;
    existing.mstoCount++;

    byAggregator.set(tariffId, existing);
  }

  // TF транзакции не имеют информации об агрегаторе,
  // поэтому добавляем их в общую категорию "Неизвестный" если есть
  const unknownTfSum = tfTransactions.reduce((sum, tx) => sum + tx.total, 0);
  const unknownTfVolume = tfTransactions.reduce((sum, tx) => sum + tx.volume, 0);

  // Если есть TF без агрегатора, добавляем к "Неизвестный"
  if (tfTransactions.length > 0 && !byAggregator.has(0)) {
    byAggregator.set(0, {
      id: 0,
      name: 'Неизвестный',
      mstoSum: 0,
      mstoVolume: 0,
      mstoCount: 0,
      tfSum: unknownTfSum,
      tfVolume: unknownTfVolume,
      tfCount: tfTransactions.length
    });
  } else if (tfTransactions.length > 0) {
    const existing = byAggregator.get(0)!;
    existing.tfSum += unknownTfSum;
    existing.tfVolume += unknownTfVolume;
    existing.tfCount += tfTransactions.length;
  }

  // Преобразуем в массив
  const result: MSTOReconciliationByAggregator[] = [];
  for (const agg of byAggregator.values()) {
    const mstoVsTfSumDiff = round(agg.mstoSum - agg.tfSum);
    const mstoVsTfVolumeDiff = round(agg.mstoVolume - agg.tfVolume);

    const status: MSTOReconciliationStatus =
      Math.abs(mstoVsTfSumDiff) > UI_SUM_DISCREPANCY_TOLERANCE ||
      Math.abs(mstoVsTfVolumeDiff) > UI_VOLUME_DISCREPANCY_TOLERANCE
        ? 'error'
        : 'ok';

    result.push({
      aggregatorId: agg.id,
      aggregatorName: agg.name,
      // MSTO данные
      mstoSum: round(agg.mstoSum),
      mstoVolume: round(agg.mstoVolume),
      mstoCount: agg.mstoCount,
      // TF данные
      tfSum: round(agg.tfSum),
      tfVolume: round(agg.tfVolume),
      tfCount: agg.tfCount,
      // Смена (не разбивается по агрегаторам)
      shiftSum: 0,
      shiftVolume: 0,
      // Расхождения
      mstoVsTfSumDiff,
      mstoVsTfVolumeDiff,
      sumDiff: mstoVsTfSumDiff,
      volumeDiff: mstoVsTfVolumeDiff,
      transactionCount: agg.mstoCount + agg.tfCount,
      status
    });
  }

  // Сортируем по сумме (по убыванию)
  result.sort((a, b) => b.mstoSum - a.mstoSum);

  return result;
}

/**
 * Агрегация по видам топлива (три источника)
 */
function aggregateByFuel(
  mstoTransactions: MSTOTransaction[],
  tfTransactions: TFOnlineTransaction[],
  shift: MSTOShiftInfo
): MSTOReconciliationByFuel[] {
  // Группируем MSTO по топливу
  const mstoByFuel = new Map<string, { sum: number; volume: number }>();
  for (const tx of mstoTransactions) {
    const fuelName = tx.fuelName || 'Неизвестно';
    const existing = mstoByFuel.get(fuelName) || { sum: 0, volume: 0 };
    existing.sum += tx.resultSum;
    existing.volume += tx.resultValue;
    mstoByFuel.set(fuelName, existing);
  }

  // Группируем TF по топливу
  const tfByFuel = new Map<string, { sum: number; volume: number }>();
  for (const tx of tfTransactions) {
    const fuelName = tx.fuelType || 'Неизвестно';
    const existing = tfByFuel.get(fuelName) || { sum: 0, volume: 0 };
    existing.sum += tx.total;
    existing.volume += tx.volume;
    tfByFuel.set(fuelName, existing);
  }

  // Группируем данные смены по топливу
  const shiftByFuel = new Map<string, { sum: number; volume: number }>();
  for (const fb of shift.fuelBreakdown) {
    const fuelName = fb.fuelName || 'Неизвестно';
    const existing = shiftByFuel.get(fuelName) || { sum: 0, volume: 0 };
    existing.sum += fb.revenue;
    existing.volume += fb.volume;
    shiftByFuel.set(fuelName, existing);
  }

  // Объединяем все виды топлива
  const allFuels = new Set<string>([
    ...mstoByFuel.keys(),
    ...tfByFuel.keys(),
    ...shiftByFuel.keys()
  ]);

  const result: MSTOReconciliationByFuel[] = [];

  for (const fuelName of allFuels) {
    const msto = mstoByFuel.get(fuelName) || { sum: 0, volume: 0 };
    const tf = tfByFuel.get(fuelName) || { sum: 0, volume: 0 };
    const shiftData = shiftByFuel.get(fuelName) || { sum: 0, volume: 0 };

    // Расхождения
    const mstoVsTfSumDiff = round(msto.sum - tf.sum);
    const mstoVsTfVolumeDiff = round(msto.volume - tf.volume);
    const tfVsShiftSumDiff = round(tf.sum - shiftData.sum);
    const tfVsShiftVolumeDiff = round(tf.volume - shiftData.volume);
    const sumDiff = round(msto.sum - shiftData.sum);
    const volumeDiff = round(msto.volume - shiftData.volume);

    const status: MSTOReconciliationStatus =
      Math.abs(mstoVsTfSumDiff) > UI_SUM_DISCREPANCY_TOLERANCE ||
      Math.abs(mstoVsTfVolumeDiff) > UI_VOLUME_DISCREPANCY_TOLERANCE ||
      Math.abs(tfVsShiftSumDiff) > UI_SUM_DISCREPANCY_TOLERANCE ||
      Math.abs(tfVsShiftVolumeDiff) > UI_VOLUME_DISCREPANCY_TOLERANCE
        ? 'error'
        : 'ok';

    result.push({
      fuelName,
      // MSTO данные
      mstoSum: round(msto.sum),
      mstoVolume: round(msto.volume),
      // TF данные
      tfSum: round(tf.sum),
      tfVolume: round(tf.volume),
      // Смена данные
      shiftSum: round(shiftData.sum),
      shiftVolume: round(shiftData.volume),
      // Расхождения
      mstoVsTfSumDiff,
      mstoVsTfVolumeDiff,
      tfVsShiftSumDiff,
      tfVsShiftVolumeDiff,
      sumDiff,
      volumeDiff,
      status
    });
  }

  // Сортируем по имени
  result.sort((a, b) => a.fuelName.localeCompare(b.fuelName));

  return result;
}

/**
 * Агрегация ВСЕХ транзакций по агрегаторам (общая статистика)
 */
export function aggregateAllByAggregator(
  mstoTransactions: MSTOTransaction[],
  tfTransactions: TFOnlineTransaction[]
): MSTOReconciliationByAggregator[] {
  return aggregateByAggregator(mstoTransactions, tfTransactions);
}
