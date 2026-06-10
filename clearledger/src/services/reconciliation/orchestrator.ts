/**
 * Оркестратор сверки корпоративного процессинга
 *
 * Главная функция executeReconciliation координирует:
 * 1. Получение данных из трёх источников (Corp, TF, Shift)
 * 2. Построчную сверку Corp ↔ TF
 * 3. Агрегацию по станциям и сменам
 * 4. Формирование итогового результата
 */

import type {
  ReconciliationParams,
  ReconciliationResult,
  ReconciliationSummary
} from '@/types/reconciliation';

import { getCorpTransactions, getTfTransactions, getShiftsWithReports } from './dataFetcher';
import { performLineByLineReconciliation } from './matcher';
import { aggregateByStationAndShift } from './aggregator';
import { buildStationNameMap, round } from './utils';

/**
 * Выполнить трёхстороннюю сверку
 *
 * @param params - параметры сверки (даты, станции, опции)
 * @returns результат сверки с детальными данными
 */
export async function executeReconciliation(
  params: ReconciliationParams
): Promise<ReconciliationResult> {
  const startTime = Date.now();
  const { dateFrom, dateTo, stationIds, showAllShifts, systemId } = params;

  if (!systemId) {
    throw new Error('Не указан systemId — выберите сеть перед запуском сверки');
  }

  // Получаем данные параллельно из трёх источников
  // systemId передаётся из настроек сети для запросов к STS API
  const [corpTransactions, tfTransactions, shiftsInfo] = await Promise.all([
    getCorpTransactions(dateFrom, dateTo, stationIds),
    getTfTransactions(dateFrom, dateTo, stationIds, systemId),
    getShiftsWithReports(dateFrom, dateTo, stationIds, showAllShifts, systemId)
  ]);

  // Создаём унифицированную карту имён станций
  // Приоритет: TradeCorp > TF > Shifts > generic
  const stationNameMap = buildStationNameMap(corpTransactions, tfTransactions, shiftsInfo);

  // Этап 1: Построчная сверка Corp ↔ TF
  const { transactions, matched, onlyCorp, onlyTf, mismatch } = performLineByLineReconciliation(
    corpTransactions,
    tfTransactions,
    shiftsInfo,
    stationNameMap
  );

  // Этап 2: Агрегация по сменам и сравнение с данными сменного отчёта
  const byStation = aggregateByStationAndShift(
    transactions,
    shiftsInfo,
    stationNameMap,
    showAllShifts
  );

  // Подсчёт итогов (исключаем нулевые транзакции - авторизации без заправки)
  const filteredCorpTransactions = corpTransactions.filter(t => Math.abs(t.quantity) > 0);
  const filteredTfTransactions = tfTransactions.filter(t => Math.abs(t.volume) > 0);

  const totalCorpLiters = filteredCorpTransactions.reduce((sum, t) => sum + Math.abs(t.quantity), 0);
  const totalTfLiters = filteredTfTransactions.reduce((sum, t) => sum + Math.abs(t.volume), 0);
  const totalShiftLiters = shiftsInfo.reduce((sum, s) =>
    sum + s.fuelSales.reduce((fsum, f) => fsum + Math.abs(f.quantity), 0), 0
  );

  // Есть расхождения если:
  // - есть транзакции только в Corp или только в TF
  // - есть транзакции с несовпадением литров (mismatch)
  // - есть ошибки в агрегации по станциям
  const hasErrors = onlyCorp > 0 || onlyTf > 0 || mismatch > 0 ||
                    byStation.some(s => s.status === 'error');

  const summary: ReconciliationSummary = {
    totalCorpLiters: round(totalCorpLiters),
    totalTfLiters: round(totalTfLiters),
    totalShiftLiters: round(totalShiftLiters),
    matched,
    onlyCorp,
    onlyTf,
    mismatch,
    hasErrors
  };

  return {
    params,
    summary,
    byStation,
    transactions,
    executedAt: new Date().toISOString(),
    duration: Date.now() - startTime
  };
}
