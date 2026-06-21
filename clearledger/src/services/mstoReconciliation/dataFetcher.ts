/**
 * Модуль получения данных для трёхсторонней сверки онлайн-заказов
 *
 * Три источника данных:
 * 1. Сменный отчет (STS /v1/report/shift_report) - итоговые суммы по смене
 * 2. MSTO IntegratorService (через backend-прокси TradeLedger) - детальные транзакции агрегаторов
 * 3. TF транзакции (STS /v2/transactions) - факт отпуска на ТРК
 *
 * Адаптация под TradeLedger:
 * - MSTO берётся из backend-прокси (mstoProxyClient → /api/msto/*)
 * - TF и смены берутся напрямую из STS через stsApiClient
 */

import type { MSTOTransaction, MSTOServicePoint, MSTOTariff, TFOnlineTransaction } from '@/types/mstoReconciliation';
import type { StsShift, StsTransaction } from '@/services/fuel/types';
import { getMstoTransactions, getMstoServicePoints, getMstoTariffs } from '@/services/mstoProxyClient';
import { stsGetTransactions, stsGetShifts, stsGetShiftReport } from '@/services/fuel/stsApiClient';
import { getSettings } from '@/services/settingsService';
import { SUCCESSFUL_OPERATION_RESULTS } from './constants';
import { normalizeStationIds, normalizeMstoFuelName, normalizeAggregatorName } from './utils';

/**
 * Информация о смене с данными для сверки онлайн-заказов
 */
export interface MSTOShiftInfo {
  id: number;
  stationId: number;
  stationName: string;
  openedAt: string;
  closedAt: string | null;
  // Данные из payment_totals
  sbpRevenue: number;           // Выручка онлайн (СБП)
  // Данные из salesBreakdown
  nonCashVolume: number;        // Объем безналичных продаж
  // Разбивка по топливу
  fuelBreakdown: {
    fuelName: string;
    volume: number;             // Литры
    revenue: number;            // Выручка
  }[];
}

/**
 * Маппинг станций: TF station ID -> MSTO servicePointId
 */
export interface StationMapping {
  tfStationId: number;
  tfStationName: string;
  mstoServicePointId: number;
  mstoServicePointName: string;
}

/**
 * Получить транзакции MSTO за период
 * Фильтруем только успешные операции
 * ВАЖНО: MSTO API не поддерживает несколько servicePointId в одном запросе,
 * поэтому делаем отдельные запросы для каждой станции
 */
export async function fetchMstoTransactions(
  dateFrom: string,
  dateTo: string,
  mstoServicePointIds?: number[]
): Promise<MSTOTransaction[]> {
  const allTransactions: MSTOTransaction[] = [];

  // ВАЖНО: MSTO API медленно работает с фильтром servicePointId
  // Поэтому получаем ВСЕ транзакции одним запросом и фильтруем на клиенте

  try {
    const transactions = await getMstoTransactions({
      dateFrom,
      dateTo
      // НЕ передаём servicePointId и operationResults - фильтруем на клиенте
    });
    allTransactions.push(...transactions);
  } catch {
    // Игнорируем ошибки получения транзакций
  }

  // Фильтруем по статусу (success, wait)
  let filteredTransactions = allTransactions.filter(tx =>
    (SUCCESSFUL_OPERATION_RESULTS as readonly string[]).includes(tx.operationResult)
  );

  // Фильтруем нулевые заказы (созданы, но не отпущены)
  // Это отменённые/таймаут заказы с resultValue = 0
  filteredTransactions = filteredTransactions.filter(tx =>
    (tx.resultValue || 0) > 0.01 || (tx.resultSum || 0) > 1
  );

  // Фильтруем по станциям если указаны
  // ВАЖНО: servicePointId может быть числом или строкой, приводим к числу
  if (mstoServicePointIds?.length) {
    const servicePointSet = new Set(mstoServicePointIds);

    filteredTransactions = filteredTransactions.filter(tx => {
      const spId = typeof tx.servicePointId === 'string'
        ? parseInt(tx.servicePointId, 10)
        : (tx.servicePointId || 0);
      return servicePointSet.has(spId);
    });
  }

  // Нормализуем данные
  return filteredTransactions.map(tx => ({
    ...tx,
    fuelName: normalizeMstoFuelName(tx.fuelName),
    tariffName: tx.tariffName ? normalizeAggregatorName(tx.tariffName) : 'Неизвестный',
    resultSum: Math.abs(tx.resultSum || 0),
    resultValue: Math.abs(tx.resultValue || 0),
    orderSum: Math.abs(tx.orderSum || 0),
    orderValue: Math.abs(tx.orderValue || 0),
  }));
}

/**
 * Получить список станций MSTO
 */
export async function fetchMstoServicePoints(): Promise<MSTOServicePoint[]> {
  return getMstoServicePoints();
}

/**
 * Получить список тарифов (агрегаторов) MSTO
 */
export async function fetchMstoTariffs(): Promise<MSTOTariff[]> {
  return getMstoTariffs();
}

/**
 * Получить транзакции TF (факт отпуска) с типом оплаты online_order
 * Источник: STS API /v2/transactions (детальные транзакции) через stsApiClient.
 * ВАЖНО: STS API не фильтрует по датам точно — дофильтровываем на клиенте.
 */
export async function fetchTfOnlineTransactions(
  dateFrom: string,
  dateTo: string,
  stationIds: number[],
  systemId?: number
): Promise<TFOnlineTransaction[]> {
  if (!systemId) {
    throw new Error('systemId обязателен для загрузки TF транзакций');
  }
  const normalizedStationIds = normalizeStationIds(stationIds);

  // Преобразуем даты для фильтрации (STS API не фильтрует по датам!)
  const dateFromTs = new Date(dateFrom + 'T00:00:00').getTime();
  const dateToTs = new Date(dateTo + 'T23:59:59').getTime();

  // Если станции не указаны, получаем все доступные
  const stationsToQuery = normalizedStationIds.length > 0
    ? normalizedStationIds
    : await getAvailableStations(systemId);

  // Параллельная загрузка транзакций по станциям (батчами по 5)
  const BATCH_SIZE = 5;
  const allResults: TFOnlineTransaction[][] = [];

  for (let i = 0; i < stationsToQuery.length; i += BATCH_SIZE) {
    const batch = stationsToQuery.slice(i, i + BATCH_SIZE);
    const batchResults = await Promise.allSettled(
      batch.map(stationId => fetchStationTransactions(stationId, systemId, dateFrom, dateTo, dateFromTs, dateToTs))
    );
    for (const result of batchResults) {
      if (result.status === 'fulfilled') {
        allResults.push(result.value);
      }
    }
  }

  return allResults.flat();
}

/** Загрузка онлайн-транзакций одной станции */
async function fetchStationTransactions(
  stationId: number,
  systemId: number,
  dateFrom: string,
  dateTo: string,
  dateFromTs: number,
  dateToTs: number
): Promise<TFOnlineTransaction[]> {
  const transactions: TFOnlineTransaction[] = [];

  const response: StsTransaction[] = await stsGetTransactions(dateFrom, dateTo, stationId, systemId);

  const num = (v: string | number | undefined): number =>
    typeof v === 'number' ? v : parseFloat(String(v ?? '0')) || 0;

  for (const tx of response) {
    const dt = typeof tx.dt === 'string' ? tx.dt : '';
    const txDate = dt ? new Date(dt).getTime() : 0;
    if (txDate < dateFromTs || txDate > dateToTs) continue;

    const payType = (tx.pay_type?.name || '').toLowerCase();
    const isOnlineOrder = payType.includes('мобил') || payType.includes('mobil') ||
                          payType.includes('онлайн') || payType.includes('online');
    if (!isOnlineOrder) continue;

    const fuelName = tx.fuel_name || 'Топливо';
    const volume = num(tx.quantity);
    const price = num(tx.price);
    const total = num(tx.cost);

    if (volume === 0 && total === 0) continue;

    transactions.push({
      id: tx.id || transactions.length + 1,
      transactionId: String(tx.id || ''),
      date: dt,
      stationId,
      stationName: `АЗС ${stationId}`,
      fuelType: normalizeMstoFuelName(fuelName),
      volume: Math.abs(volume),
      price: Math.abs(price),
      total: Math.abs(total),
      paymentMethod: tx.pay_type?.name || 'online_order',
      columnNumber: tx.pos,
      nozzleNumber: tx.nozzle,
      shiftId: tx.shift
    });
  }

  return transactions;
}

/**
 * Получить информацию о сменах с данными для сверки онлайн-заказов
 */
export async function fetchShiftsWithOnlineData(
  dateFrom: string,
  dateTo: string,
  stationIds: number[],
  showAllShifts?: boolean,
  systemId?: number
): Promise<MSTOShiftInfo[]> {
  if (!systemId) {
    throw new Error('systemId обязателен для загрузки смен');
  }

  const normalizedStationIds = normalizeStationIds(stationIds);

  // Если станции не указаны, получаем все доступные
  const stationsToQuery = normalizedStationIds.length > 0
    ? normalizedStationIds
    : await getAvailableStations(systemId);

  // Шаг 1: Параллельная загрузка списков смен по всем станциям (батчами по 5)
  const BATCH_SIZE = 5;
  const stationShiftsMap = new Map<number, StsShift[]>();

  for (let i = 0; i < stationsToQuery.length; i += BATCH_SIZE) {
    const batch = stationsToQuery.slice(i, i + BATCH_SIZE);
    const results = await Promise.allSettled(
      batch.map(stationId =>
        stsGetShifts(systemId, stationId).then(allShifts => ({
          stationId,
          shifts: (allShifts || []).filter(shift => {
            const shiftDate = shift.dt_open || shift.dt_close;
            if (!shiftDate) return false;
            const shiftDateStr = shiftDate.substring(0, 10);
            return shiftDateStr >= dateFrom && shiftDateStr <= dateTo;
          })
        }))
      )
    );
    for (const result of results) {
      if (result.status === 'fulfilled' && result.value.shifts.length > 0) {
        stationShiftsMap.set(result.value.stationId, result.value.shifts);
      }
    }
  }

  // Шаг 2: Параллельная загрузка shift_report для ВСЕХ смен (батчами по 10)
  const REPORT_BATCH_SIZE = 10;
  const reportTasks: { stationId: number; shift: StsShift }[] = [];
  for (const [stationId, shifts] of stationShiftsMap) {
    for (const shift of shifts) {
      reportTasks.push({ stationId, shift });
    }
  }

  const shiftsInfo: MSTOShiftInfo[] = [];

  for (let i = 0; i < reportTasks.length; i += REPORT_BATCH_SIZE) {
    const batch = reportTasks.slice(i, i + REPORT_BATCH_SIZE);
    const results = await Promise.allSettled(
      batch.map(({ stationId, shift }) =>
        stsGetShiftReport(stationId, shift.shift, systemId).then(shiftReport => ({ stationId, shift, shiftReport }))
      )
    );

    for (const result of results) {
      if (result.status !== 'fulfilled') continue;
      const { stationId, shift, shiftReport } = result.value;

      // Извлекаем данные онлайн-заказов из sales
      // ВАЖНО: Берём ТОЛЬКО "МобилПр." — это мобильные платежи (Яндекс, FuelUp и др.)
      let sbpRevenue = 0;
      let nonCashVolume = 0;
      const fuelBreakdown: MSTOShiftInfo['fuelBreakdown'] = [];

      if (shiftReport?.sales) {
        for (const sale of shiftReport.sales) {
          const payTypeName = (sale.pay_type?.name || '').toLowerCase();
          const isOnlineOrder = payTypeName.includes('мобил') || payTypeName.includes('mobil') ||
                                payTypeName.includes('онлайн') || payTypeName.includes('online');
          if (!isOnlineOrder) continue;

          if (sale.fuel && Array.isArray(sale.fuel)) {
            for (const fuelItem of sale.fuel) {
              const fuelName = fuelItem.service?.service_name || 'Топливо';
              const volume = parseFloat(fuelItem.release?.volume || '0') || 0;
              const revenue = parseFloat(fuelItem.release?.cost || '0') || 0;

              if (volume > 0) {
                nonCashVolume += Math.abs(volume);
                sbpRevenue += Math.abs(revenue);
                fuelBreakdown.push({
                  fuelName: fuelName.toUpperCase(),
                  volume: Math.abs(volume),
                  revenue: Math.abs(revenue)
                });
              }
            }
          }
        }
      }

      const shouldAdd = sbpRevenue > 0 || nonCashVolume > 0 || showAllShifts;
      if (shouldAdd) {
        shiftsInfo.push({
          id: shift.shift,
          stationId,
          stationName: `АЗС ${stationId}`,
          openedAt: shift.dt_open || '',
          closedAt: shift.dt_close || null,
          sbpRevenue: Math.abs(sbpRevenue),
          nonCashVolume: Math.abs(nonCashVolume),
          fuelBreakdown
        });
      }
    }
  }

  return shiftsInfo;
}

/**
 * Получить список доступных станций.
 *
 * У STS API нет endpoint списка станций — используем коды станций из настроек
 * приложения (settingsService) как fallback. Обычно сюда не попадаем —
 * модалка параметров передаёт станции из справочника Location явным списком.
 */
export async function getAvailableStations(_systemId: number): Promise<number[]> {
  try {
    return getSettings().stations.map(s => s.code).filter(Boolean);
  } catch {
    return [];
  }
}

/**
 * Построить маппинг станций TF -> MSTO
 *
 * MSTO ID берётся из externalCodes торговой точки (system='msto')
 *
 * @param tfStationIds - ID станций TF/STS
 * @param stations - Информация о станциях из настроек (с mstoServicePointId из externalCodes)
 */
export async function buildStationMapping(
  tfStationIds: number[],
  stations?: { stsStationId: number; mstoServicePointId?: number; mstoServicePointIds?: number[] }[]
): Promise<Map<number, number>> {
  const mapping = new Map<number, number>();

  // Создаём lookup по stsStationId
  const stationLookup = new Map<number, { mstoServicePointId?: number; mstoServicePointIds?: number[] }>();
  if (stations) {
    for (const station of stations) {
      if (station.stsStationId > 0) {
        stationLookup.set(station.stsStationId, station);
      }
    }
  }

  for (const stationId of tfStationIds) {
    const stationInfo = stationLookup.get(stationId);

    // MSTO ID из настроек торговой точки (externalCodes)
    if (stationInfo?.mstoServicePointId) {
      mapping.set(stationId, stationInfo.mstoServicePointId);
    }
    // Если нет MSTO ID - станция не будет сопоставляться с транзакциями MSTO
  }

  return mapping;
}

/**
 * Получить все MSTO servicePointIds для станций (включая альтернативные)
 * Используется для фильтрации транзакций MSTO
 *
 * MSTO ID берутся из externalCodes торговых точек (system='msto')
 */
export function getAllMstoServicePointIds(
  stations?: { mstoServicePointId?: number; mstoServicePointIds?: number[] }[]
): number[] {
  const ids = new Set<number>();

  if (stations) {
    for (const station of stations) {
      // Основной ID
      if (station.mstoServicePointId) {
        ids.add(station.mstoServicePointId);
      }
      // Альтернативные ID (если станция имеет несколько MSTO кодов)
      if (station.mstoServicePointIds) {
        for (const id of station.mstoServicePointIds) {
          if (id > 0) ids.add(id);
        }
      }
    }
  }

  return Array.from(ids);
}
