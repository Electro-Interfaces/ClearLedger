/**
 * Утилиты для сервиса сверки MSTO онлайн-заказов
 */

import { AGGREGATOR_NAME_MAP, FUEL_NAME_MAP } from './constants';

/**
 * Округление до 2 знаков после запятой
 */
export function round(value: number | null | undefined): number {
  if (value == null || typeof value !== 'number' || !Number.isFinite(value)) return 0;
  return Math.round(value * 100) / 100;
}

/**
 * Нормализация названия агрегатора
 */
export function normalizeAggregatorName(name: string): string {
  if (!name) return 'Неизвестный';

  const lowered = name.toLowerCase().trim();
  return AGGREGATOR_NAME_MAP[lowered] || name;
}

/**
 * Нормализация названия топлива MSTO к стандартному формату
 */
export function normalizeMstoFuelName(mstoName: string): string {
  if (!mstoName) return 'Неизвестно';

  const lowered = mstoName.toLowerCase().trim();

  // Точное совпадение в маппинге
  if (FUEL_NAME_MAP[lowered]) {
    return FUEL_NAME_MAP[lowered];
  }

  // Fuzzy match по ключевым словам
  if (lowered.includes('92')) return 'АИ-92';
  if (lowered.includes('95')) return 'АИ-95';
  if (lowered.includes('98')) return 'АИ-98';
  if (lowered.includes('100')) return 'АИ-100';
  if (lowered.includes('дизел') || lowered === 'дт') return 'ДТ';

  // Возвращаем как есть в верхнем регистре
  return mstoName.toUpperCase();
}

/**
 * Нормализация названия топлива из сменного отчета
 */
export function normalizeShiftFuelName(name: string): string {
  if (!name) return 'НЕИЗВЕСТНО';
  return name.toUpperCase().trim();
}

/**
 * Проверка совпадения названий топлива
 */
export function fuelNamesMatch(name1: string, name2: string): boolean {
  const n1 = normalizeMstoFuelName(name1);
  const n2 = normalizeShiftFuelName(name2);

  // Точное совпадение
  if (n1 === n2) return true;

  // Проверка вхождения (для случаев типа "АИ-95" vs "БЕНЗИН АИ-95")
  if (n1.includes(n2) || n2.includes(n1)) return true;

  return false;
}

/**
 * Генерация уникального ID для транзакции сверки (три источника)
 */
export function generateTransactionId(
  date: string,
  stationId: number,
  mstoId?: number,
  shiftId?: number,
  tfId?: number
): string {
  return `rec-${date}-${stationId}-m${mstoId || 'x'}-s${shiftId || 'x'}-t${tfId || 'x'}-${Date.now()}`;
}

/**
 * Форматирование даты для отображения
 */
export function formatDate(isoDate: string): string {
  if (!isoDate) return '';

  try {
    const date = new Date(isoDate);
    return date.toLocaleDateString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric'
    });
  } catch {
    return isoDate.substring(0, 10);
  }
}

/**
 * Форматирование даты и времени для отображения
 */
export function formatDateTime(isoDate: string): string {
  if (!isoDate) return '';

  try {
    const date = new Date(isoDate);
    return date.toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch {
    return isoDate;
  }
}

/**
 * Проверка, попадает ли дата в смену
 * @param transactionDate - ISO datetime транзакции
 * @param shiftOpenedAt - ISO datetime открытия смены
 * @param shiftClosedAt - ISO datetime закрытия смены (null = не закрыта)
 */
export function isDateInShift(
  transactionDate: string,
  shiftOpenedAt: string,
  shiftClosedAt: string | null
): boolean {
  if (!transactionDate || !shiftOpenedAt) return false;

  const txTime = new Date(transactionDate).getTime();
  const openTime = new Date(shiftOpenedAt).getTime();

  // Если смена не закрыта, проверяем только что после открытия
  if (!shiftClosedAt) {
    return txTime >= openTime;
  }

  const closeTime = new Date(shiftClosedAt).getTime();

  return txTime >= openTime && txTime <= closeTime;
}

/**
 * Нормализация stationIds к числам
 */
export function normalizeStationIds(stationIds: (number | string)[]): number[] {
  return stationIds
    .map(id => typeof id === 'string' ? parseInt(id, 10) : id)
    .filter(id => !isNaN(id));
}

/**
 * Получение имени станции из карты
 */
export function getStationName(stationId: number, stationNameMap: Map<number, string>): string {
  return stationNameMap.get(stationId) || `АЗС ${stationId}`;
}

/**
 * Информация о станции из настроек приложения
 */
interface StationInfoInput {
  code: string;                   // Код в TF (1, 2, 3, 4)
  name: string;                   // Название (АКАЗС №1)
  description?: string;           // Описание (Непокоренных)
  stsStationId: number;           // ID в STS API
  mstoServicePointId?: number;    // ID в MSTO
}

function extractStationNumber(value: string): number | null {
  const match = value.match(/(?:^|\D)([1-4])(?!\d)/);
  if (!match) return null;
  const num = parseInt(match[1], 10);
  return Number.isFinite(num) ? num : null;
}

/**
 * Маппинг ключевых слов в названии станции -> TF station ID
 * Используется для восстановления servicePointId когда MSTO не передаёт StationExtendedId
 */
const STATION_KEYWORDS: Record<number, string[]> = {
  1: ['непокоренных', 'непокорённых'],
  2: ['выборг'],
  3: ['кудрово', 'автополе'],
  4: ['первомайское', 'первомайск'],
};

/**
 * Восстановление servicePointId по названию станции, если MSTO его не передал
 */
export function normalizeMstoServicePointIds<T extends { servicePointId?: number; servicePointName?: string }>(
  mstoTransactions: T[],
  stationMapping: Map<number, number>
): T[] {
  return mstoTransactions.map(tx => {
    // Уже есть servicePointId — не трогаем
    if (tx.servicePointId) return tx;
    if (!tx.servicePointName) return tx;

    const nameLower = tx.servicePointName.toLowerCase();

    // Ищем по ключевым словам (Непокоренных, Выборг, Кудрово, Первомайское)
    for (const [stationIdStr, keywords] of Object.entries(STATION_KEYWORDS)) {
      const stationId = parseInt(stationIdStr, 10);
      if (keywords.some(kw => nameLower.includes(kw))) {
        const mstoId = stationMapping.get(stationId);
        if (mstoId) {
          return { ...tx, servicePointId: mstoId };
        }
      }
    }

    // Fallback: ищем по номеру станции в названии (АКАЗС-1, АКАЗС-2, etc.)
    const hasAkazs = /аказс/i.test(tx.servicePointName);
    if (hasAkazs) {
      const stationNumber = extractStationNumber(tx.servicePointName);
      if (stationNumber) {
        const mappedId = stationMapping.get(stationNumber);
        if (mappedId) {
          return { ...tx, servicePointId: mappedId };
        }
      }
    }

    return tx;
  });
}

/**
 * Построение карты имён станций
 * Приоритет: Настройки приложения > MSTO ServicePoints > MSTO транзакции > fallback "АЗС X"
 */
export function buildStationNameMap(
  mstoTransactions: { servicePointId?: number; servicePointName?: string }[],
  _shiftsInfo: { stationId: number; stationName?: string }[],
  mstoServicePoints?: { id: number; name: string }[],
  stationMapping?: Map<number, number>,
  appStations?: StationInfoInput[]
): Map<number, string> {
  const stationNameMap = new Map<number, string>();

  // Создаём обратный маппинг: MSTO servicePointId -> TF stationId
  const mstoToTfMap = new Map<number, number>();
  if (stationMapping) {
    for (const [tfId, mstoId] of stationMapping.entries()) {
      mstoToTfMap.set(mstoId, tfId);
    }
  }

  // ПРИОРИТЕТ 0 (НАИВЫСШИЙ): Из настроек приложения (params.stations)
  if (appStations?.length) {
    for (const station of appStations) {
      const stsId = station.stsStationId;
      if (stsId > 0) {
        // Формируем полное название: "АКАЗС №1 Непокоренных" или просто "АКАЗС №1"
        const fullName = station.description
          ? `${station.name} ${station.description}`
          : station.name;
        stationNameMap.set(stsId, fullName);

        // Также сохраняем по MSTO ID если есть
        if (station.mstoServicePointId) {
          stationNameMap.set(station.mstoServicePointId, fullName);
        }
      }
    }
  }

  // Приоритет 1: Из MSTO ServicePoints (если не задано в настройках)
  if (mstoServicePoints?.length) {
    for (const sp of mstoServicePoints) {
      if (sp.id && sp.name) {
        // Находим TF stationId по MSTO servicePointId
        const tfStationId = mstoToTfMap.get(sp.id);
        if (tfStationId !== undefined && !stationNameMap.has(tfStationId)) {
          stationNameMap.set(tfStationId, sp.name);
        }
        // Также сохраняем по MSTO ID для прямого доступа
        if (!stationNameMap.has(sp.id)) {
          stationNameMap.set(sp.id, sp.name);
        }
      }
    }
  }

  // Приоритет 2: Из транзакций MSTO (servicePointName)
  for (const tx of mstoTransactions) {
    if (tx.servicePointName) {
      // Пробуем найти TF stationId
      const tfStationId = tx.servicePointId ? mstoToTfMap.get(tx.servicePointId) : undefined;
      if (tfStationId !== undefined && !stationNameMap.has(tfStationId)) {
        stationNameMap.set(tfStationId, tx.servicePointName);
      }
      // Также по MSTO ID
      if (tx.servicePointId && !stationNameMap.has(tx.servicePointId)) {
        stationNameMap.set(tx.servicePointId, tx.servicePointName);
      }
    }
  }

  return stationNameMap;
}

/**
 * Форматирование суммы в рублях
 */
export function formatMoney(value: number | null | undefined): string {
  const safeValue = typeof value === 'number' && Number.isFinite(value) ? value : 0;
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(safeValue);
}

/**
 * Форматирование объема в литрах
 */
export function formatVolume(value: number | null | undefined): string {
  return `${round(value ?? 0)} л`;
}
