/**
 * Клиент для работы с MSTO IntegratorService API через Backend Proxy TradeLedger
 *
 * Все запросы идут через backend TradeLedger на /api/msto/*
 * Backend автоматически управляет JWT авторизацией.
 * HTTP-слой — общий apiClient TradeLedger (BASE_URL + Bearer JWT).
 */

import type {
  MSTOTransaction,
  MSTOServicePoint,
  MSTOTariff
} from '@/types/mstoReconciliation';
import { get } from '@/services/apiClient';

// ============================================
// API методы
// ============================================

/**
 * Параметры запроса транзакций MSTO
 */
export interface GetMstoTransactionsParams {
  dateFrom: string;             // YYYY-MM-DD
  dateTo: string;               // YYYY-MM-DD
  servicePointIds?: number[];   // Фильтр по станциям MSTO
  tariffIds?: number[];         // Фильтр по агрегаторам
  operationResults?: string[];  // Фильтр по статусам (success, wait, error, cancel)
}

/**
 * Преобразование даты из формата MSTO (dd.MM.yyyy HH:mm:ss) в ISO
 */
function parseMstoDate(dateStr: string): string {
  if (!dateStr) return '';
  // Формат: "23.01.2026 17:05:22" -> "2026-01-23T17:05:22"
  const match = dateStr.match(/^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})$/);
  if (match) {
    const [, day, month, year, hour, min, sec] = match;
    return `${year}-${month}-${day}T${hour}:${min}:${sec}`;
  }
  return dateStr;
}

// MSTO может отдавать StationExtendedId (1500x) вместо servicePointId (212/238/245/251)
// Приводим к каноническим MSTO servicePointId для корректной фильтрации/сопоставления
const MSTO_SERVICE_POINT_ID_ALIASES: Record<number, number> = {
  15001: 212,
  15002: 238,
  15003: 245,
  15004: 251,
};

function normalizeServicePointId(servicePointId: number): number {
  return MSTO_SERVICE_POINT_ID_ALIASES[servicePointId] ?? servicePointId;
}

/**
 * Маппинг номера станции АКАЗС → MSTO servicePointId
 * Используется для поиска по названию типа "АКАЗС-1", "АКАЗС №2", etc.
 */
const AKAZS_NUMBER_TO_MSTO_ID: Record<number, number> = {
  1: 212,  // АКАЗС №1 Непокоренных
  2: 238,  // АКАЗС №2 Выборг
  3: 245,  // АКАЗС №3 Кудрово
  4: 251,  // АКАЗС №4 Первомайское
};

/**
 * Уникальные ключевые слова станций (НЕ названия городов!)
 * Используются только если не нашли по "АКАЗС" + номер
 */
const UNIQUE_STATION_KEYWORDS: Record<string, number> = {
  'непокоренных': 212,
  'непокорённых': 212,
  'первомайское': 251,
  'первомайск': 251,
  // НЕ добавляем 'выборг', 'кудрово' — это названия городов, там много АЗС!
};

/**
 * Извлечение servicePointId из servicePointName
 * Используется когда MSTO не передаёт StationExtendedId в JSON
 *
 * ВАЖНО: Ищем ТОЛЬКО наши АКАЗС, не чужие АЗС!
 * Примеры наших: "АКАЗС-2 Выборг", "АКАЗС №1 Непокоренных"
 * Примеры чужих: "АЗС 208 - Выборг", "Северное - Выборгское" — НЕ сопоставляем!
 */
function extractServicePointIdFromName(name: string): number {
  if (!name) return 0;

  const nameLower = name.toLowerCase();

  // 1. Ищем по "АКАЗС" + номер (наши станции)
  if (/аказс/i.test(name)) {
    const match = name.match(/аказс[^\d]*(\d)/i);
    if (match) {
      const stationNumber = parseInt(match[1], 10);
      return AKAZS_NUMBER_TO_MSTO_ID[stationNumber] || 0;
    }
  }

  // 2. Ищем по уникальным ключевым словам (только если содержит "АКАЗС" или наши уникальные слова)
  for (const [keyword, mstoId] of Object.entries(UNIQUE_STATION_KEYWORDS)) {
    if (nameLower.includes(keyword)) {
      return mstoId;
    }
  }

  // 3. НЕ сопоставляем чужие АЗС — возвращаем 0
  return 0;
}

/**
 * Трансформация сырой транзакции MSTO в наш формат
 * Сохраняем также сырые данные для детального просмотра
 */
function transformMstoTransaction(raw: any): MSTOTransaction & { json?: string; companyName?: string; tariff?: string; refundSum?: number } {
  // Извлекаем servicePointId из поля json (StationExtendedId или stationExtendedId)
  // ВАЖНО: Всегда приводим к числу!
  let servicePointId = 0;

  // Пробуем сначала из прямого поля
  if (raw.servicePointId) {
    servicePointId = typeof raw.servicePointId === 'string'
      ? parseInt(raw.servicePointId, 10) || 0
      : raw.servicePointId;
  }

  // Если нет - извлекаем из JSON
  if (!servicePointId && raw.json) {
    try {
      const jsonData = typeof raw.json === 'string' ? JSON.parse(raw.json) : raw.json;
      // MSTO использует StationExtendedId (с большой буквы) или stationExtendedId (с маленькой)
      const extId = jsonData.StationExtendedId || jsonData.stationExtendedId;
      if (extId) {
        servicePointId = typeof extId === 'string' ? parseInt(extId, 10) || 0 : extId;
      }
    } catch {
      // Игнорируем ошибки парсинга JSON
    }
  }

  servicePointId = normalizeServicePointId(servicePointId);

  // Если servicePointId всё ещё 0 — извлекаем из servicePointName
  // Это нужно для тарифов, которые не передают StationExtendedId (например "ЯЗ.Сигма")
  if (!servicePointId && raw.servicePointName) {
    servicePointId = extractServicePointIdFromName(raw.servicePointName);
  }

  return {
    id: raw.id || 0,
    externalId: raw.sessionId || '',
    servicePointId,
    servicePointName: raw.servicePointName || '',
    tariffId: raw.tariffId || 0,
    tariffName: raw.tariff || '',
    fuelName: raw.service || '',
    orderDate: parseMstoDate(raw.dateTime),
    completedAt: parseMstoDate(raw.dateTime),
    orderSum: raw.sum || 0,
    orderValue: raw.value || 0,
    resultSum: raw.resultSum || 0,
    resultValue: raw.resultValue || 0,
    operationResult: raw.operationResult || 'unknown',
    price: raw.price || raw.discountPrice || 0,
    columnNumber: raw.postNumber,
    nozzleNumber: undefined,
    // Сырые данные для детального просмотра
    json: raw.json,
    companyName: raw.companyName,
    tariff: raw.tariff,
    refundSum: raw.refundSum,
  };
}

/**
 * Получить транзакции MSTO за период
 */
export async function getMstoTransactions(
  params: GetMstoTransactionsParams
): Promise<MSTOTransaction[]> {
  const queryParams: Record<string, string | number | undefined> = {
    dateFrom: params.dateFrom,
    dateTo: params.dateTo,
    size: 2000, // Оптимизировано для баланса скорости и полноты данных
  };

  // MSTO API принимает фильтры в единственном числе
  // servicePointId - фильтр по одной станции (или comma-separated список)
  if (params.servicePointIds?.length) {
    queryParams.servicePointId = params.servicePointIds.join(',');
  }

  // operationResult - фильтр по статусу (comma-separated: "success,wait")
  if (params.operationResults?.length) {
    // MSTO API принимает comma-separated список значений
    queryParams.operationResult = params.operationResults.join(',');
  }

  const response = await get<any>('/api/msto/transactions', queryParams);

  // MSTO возвращает { operationStatus, totalCount, models: [...] }
  let rawTransactions: any[] = [];

  if (response && typeof response === 'object') {
    if (Array.isArray(response.models)) {
      rawTransactions = response.models;
    } else if (Array.isArray(response.transactions)) {
      rawTransactions = response.transactions;
    } else if (Array.isArray(response)) {
      rawTransactions = response;
    }
  }

  // Трансформируем в наш формат
  return rawTransactions.map(transformMstoTransaction);
}

/**
 * Получить список станций MSTO
 */
export async function getMstoServicePoints(): Promise<MSTOServicePoint[]> {
  const response = await get<MSTOServicePoint[] | { servicePoints: MSTOServicePoint[] }>('/api/msto/servicePoints');

  if (Array.isArray(response)) {
    return response;
  }

  if (response && typeof response === 'object' && 'servicePoints' in response) {
    return response.servicePoints;
  }

  return [];
}

/**
 * Получить список тарифов (агрегаторов) MSTO
 */
export async function getMstoTariffs(): Promise<MSTOTariff[]> {
  const response = await get<MSTOTariff[] | { tariffs: MSTOTariff[] }>('/api/msto/tariffs');

  if (Array.isArray(response)) {
    return response;
  }

  if (response && typeof response === 'object' && 'tariffs' in response) {
    return response.tariffs;
  }

  return [];
}

/**
 * Проверка доступности MSTO API
 */
export async function checkMstoHealth(): Promise<{
  status: 'ok' | 'error';
  message?: string;
  tokenValid?: boolean;
}> {
  try {
    const response = await get<any>('/api/msto/health');
    return {
      status: response.status || 'ok',
      tokenValid: response.tokenValid
    };
  } catch (error) {
    return {
      status: 'error',
      message: error instanceof Error ? error.message : 'Unknown error'
    };
  }
}

/**
 * Клиент для работы с MSTO API
 */
export const mstoProxyClient = {
  // Высокоуровневые методы - транзакции
  getTransactions: getMstoTransactions,
  getServicePoints: getMstoServicePoints,
  getTariffs: getMstoTariffs,
  checkHealth: checkMstoHealth,
};

export default mstoProxyClient;
