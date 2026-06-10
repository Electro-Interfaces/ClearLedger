/**
 * Оркестратор трёхсторонней сверки онлайн-заказов
 *
 * Главная функция executeMstoReconciliation координирует:
 * 1. Получение данных из трёх источников: Смена, MSTO, TF
 * 2. Построчную сверку MSTO ↔ TF ↔ Смены
 * 3. Агрегацию по станциям, сменам и агрегаторам
 * 4. Формирование итогового результата
 */

import type {
  MSTOReconciliationParams,
  MSTOReconciliationResult,
  MSTOReconciliationSummary
} from '@/types/mstoReconciliation';

import {
  fetchMstoTransactions,
  fetchTfOnlineTransactions,
  fetchShiftsWithOnlineData,
  fetchMstoServicePoints,
  buildStationMapping,
  getAllMstoServicePointIds
} from './dataFetcher';
import { performLineByLineMatching } from './matcher';
import { aggregateByStationAndShift, aggregateAllByAggregator } from './aggregator';
import { buildStationNameMap, round, normalizeMstoServicePointIds, normalizeStationIds } from './utils';

/**
 * Выполнить трёхстороннюю сверку онлайн-заказов
 *
 * Источники данных:
 * 1. Сменный отчёт - итоговые суммы (sbpRevenue)
 * 2. MSTO - детальные транзакции агрегаторов
 * 3. TF - факт отпуска на ТРК (/v2/transactions)
 *
 * @param params - параметры сверки (даты, станции, опции)
 * @returns результат сверки с детальными данными
 */
export async function executeMstoReconciliation(
  params: MSTOReconciliationParams
): Promise<MSTOReconciliationResult> {
  const startTime = Date.now();
  const { dateFrom, dateTo, stationIds, mstoServicePointIds, showAllShifts, systemId } = params;

  if (!systemId) {
    throw new Error('Не указан systemId — выберите сеть перед запуском сверки');
  }

  // Нормализуем ID станций
  const normalizedStationIds = normalizeStationIds(stationIds);

  // Строим маппинг станций TF -> MSTO (используя mstoServicePointId из настроек)
  const stationMapping = await buildStationMapping(normalizedStationIds, params.stations);

  // Определяем MSTO servicePointIds для запроса
  // Приоритет: явно переданные > из настроек станций > из маппинга
  const mstoIds = mstoServicePointIds?.length
    ? mstoServicePointIds
    : params.stations?.length
      ? getAllMstoServicePointIds(params.stations)
      : normalizedStationIds.length
        ? Array.from(stationMapping.values())
        : undefined;

  // Получаем данные параллельно из ЧЕТЫРЁХ источников
  // Используем Promise.allSettled для обработки отдельных ошибок
  // ВАЖНО: systemId передаётся из настроек сети для запросов к STS API
  const [mstoResult, tfResult, shiftsResult, servicePointsResult] = await Promise.allSettled([
    fetchMstoTransactions(dateFrom, dateTo, mstoIds),
    fetchTfOnlineTransactions(dateFrom, dateTo, normalizedStationIds, systemId),
    fetchShiftsWithOnlineData(dateFrom, dateTo, normalizedStationIds, showAllShifts, systemId),
    fetchMstoServicePoints()
  ]);

  // Извлекаем результаты с обработкой ошибок
  const mstoTransactions = mstoResult.status === 'fulfilled' ? mstoResult.value : [];
  const tfTransactions = tfResult.status === 'fulfilled' ? tfResult.value : [];
  const shiftsInfo = shiftsResult.status === 'fulfilled' ? shiftsResult.value : [];
  const mstoServicePoints = servicePointsResult.status === 'fulfilled' ? servicePointsResult.value : [];

  // Восстанавливаем servicePointId по названию станции (если MSTO его не передал)
  const normalizedMstoTransactions = normalizeMstoServicePointIds(
    mstoTransactions,
    stationMapping
  );

  // Если все источники пустые, выбрасываем ошибку
  if (normalizedMstoTransactions.length === 0 && tfTransactions.length === 0 && shiftsInfo.length === 0) {
    const errors: string[] = [];
    if (mstoResult.status === 'rejected') {
      errors.push(`MSTO: ${mstoResult.reason?.message || 'Неизвестная ошибка'}`);
    }
    if (tfResult.status === 'rejected') {
      errors.push(`TF: ${tfResult.reason?.message || 'Неизвестная ошибка'}`);
    }
    if (shiftsResult.status === 'rejected') {
      errors.push(`Смены: ${shiftsResult.reason?.message || 'Неизвестная ошибка'}`);
    }
    if (errors.length > 0) {
      throw new Error(`Ошибка получения данных: ${errors.join('; ')}`);
    }
    throw new Error('Нет данных для сверки за выбранный период');
  }

  // Создаём карту имён станций (приоритет: настройки приложения > MSTO > fallback)
  const stationNameMap = buildStationNameMap(
    normalizedMstoTransactions,
    shiftsInfo,
    mstoServicePoints,
    stationMapping,
    params.stations  // Передаём станции из параметров (настройки приложения)
  );

  // Этап 1: Построчная сверка MSTO ↔ TF ↔ Смены
  const { transactions, matched, mstoWaitDone, onlyMsto, onlyTf, onlyShift, mismatch } = performLineByLineMatching(
    normalizedMstoTransactions,
    tfTransactions,
    shiftsInfo,
    stationNameMap,
    stationMapping
  );

  // Этап 2: Агрегация по станциям и сменам
  const byStation = aggregateByStationAndShift(
    normalizedMstoTransactions,
    tfTransactions,
    shiftsInfo,
    stationNameMap,
    stationMapping,
    showAllShifts
  );

  // Этап 3: Общая агрегация по агрегаторам
  const byAggregator = aggregateAllByAggregator(normalizedMstoTransactions, tfTransactions);

  // Подсчёт итогов MSTO
  const totalMstoSum = normalizedMstoTransactions.reduce((sum, t) => sum + Math.abs(t.resultSum || 0), 0);
  const totalMstoVolume = normalizedMstoTransactions.reduce((sum, t) => sum + Math.abs(t.resultValue || 0), 0);
  const totalMstoCount = normalizedMstoTransactions.length;

  // Подсчёт итогов TF
  const totalTfSum = tfTransactions.reduce((sum, t) => sum + Math.abs(t.total || 0), 0);
  const totalTfVolume = tfTransactions.reduce((sum, t) => sum + Math.abs(t.volume || 0), 0);
  const totalTfCount = tfTransactions.length;

  // Подсчёт итогов смен
  const totalShiftSbpRevenue = shiftsInfo.reduce((sum, s) => sum + Math.abs(s.sbpRevenue || 0), 0);
  const totalShiftNonCashVolume = shiftsInfo.reduce((sum, s) => sum + Math.abs(s.nonCashVolume || 0), 0);

  // Расхождения MSTO ↔ TF
  const mstoVsTfSumDiff = round(totalMstoSum - totalTfSum);
  const mstoVsTfVolumeDiff = round(totalMstoVolume - totalTfVolume);

  // Расхождения TF ↔ Смена
  const tfVsShiftSumDiff = round(totalTfSum - totalShiftSbpRevenue);
  const tfVsShiftVolumeDiff = round(totalTfVolume - totalShiftNonCashVolume);

  // Расхождения MSTO ↔ Смена (для совместимости)
  const sumDiff = round(totalMstoSum - totalShiftSbpRevenue);
  const volumeDiff = round(totalMstoVolume - totalShiftNonCashVolume);

  // Определяем наличие ошибок
  const hasErrors = onlyMsto > 0 || onlyTf > 0 || onlyShift > 0 || mismatch > 0 ||
                    byStation.some(s => s.status === 'error') ||
                    Math.abs(mstoVsTfSumDiff) > 50 ||
                    Math.abs(mstoVsTfVolumeDiff) > 1 ||
                    Math.abs(tfVsShiftSumDiff) > 50 ||
                    Math.abs(tfVsShiftVolumeDiff) > 1;

  const summary: MSTOReconciliationSummary = {
    // MSTO итоги
    totalMstoSum: round(totalMstoSum),
    totalMstoVolume: round(totalMstoVolume),
    totalMstoCount,
    // TF итоги
    totalTfSum: round(totalTfSum),
    totalTfVolume: round(totalTfVolume),
    totalTfCount,
    // Смена итоги
    totalShiftSbpRevenue: round(totalShiftSbpRevenue),
    totalShiftNonCashVolume: round(totalShiftNonCashVolume),
    // Расхождения
    mstoVsTfSumDiff,
    mstoVsTfVolumeDiff,
    tfVsShiftSumDiff,
    tfVsShiftVolumeDiff,
    sumDiff,
    volumeDiff,
    // Статистика
    matched,
    mstoWaitDone,
    onlyMsto,
    onlyTf,
    onlyShift,
    mismatch,
    hasErrors
  };

  return {
    params,
    summary,
    byStation,
    byAggregator,
    transactions,
    executedAt: new Date().toISOString(),
    duration: Date.now() - startTime
  };
}
