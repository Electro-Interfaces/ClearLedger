/**
 * Утилиты для сервиса сверки корпоративного процессинга
 */

import { STATION_NAME_PATTERNS } from './constants';

/**
 * Нормализация названия топлива для сопоставления
 * Приводит к верхнему регистру и убирает пробелы
 */
export function normalizeFuelName(name: string): string {
  if (!name) return 'НЕИЗВЕСТНО';
  return name.toUpperCase().trim();
}

/**
 * Округление до 2 знаков после запятой
 * Защита от NaN/undefined/null
 */
export function round(value: number): number {
  if (value == null || !Number.isFinite(value)) return 0;
  return Math.round(value * 100) / 100;
}

/**
 * Маппинг станций TradeCorp -> STS
 * TradeCorp использует свою нумерацию, STS - свою
 * Извлекаем номер станции из названия (АКАЗС-3 Автополе -> 3)
 */
export function mapTradecorpStationToSts(stationName: string, stationNumber: number): number {
  for (const pattern of STATION_NAME_PATTERNS) {
    const match = stationName?.match(pattern);
    if (match && match[1]) {
      return parseInt(match[1], 10);
    }
  }

  // Fallback: используем оригинальный номер
  return stationNumber;
}

/**
 * Нормализация stationIds к числам (могут приходить как строки)
 */
export function normalizeStationIds(stationIds: (number | string)[]): number[] {
  return stationIds.map(id => typeof id === 'string' ? parseInt(id, 10) : id);
}

/**
 * Создание унифицированного имени станции
 */
export function getStationName(stationId: number, stationNameMap: Map<number, string>): string {
  return stationNameMap.get(stationId) || `АЗС ${stationId}`;
}

/**
 * Нормализация номера карты для сопоставления
 * Извлекает последние 4 цифры из номера карты
 * Примеры:
 * - "1000745" -> "0745"
 * - "МПС ****6880" -> "6880"
 * - "****1234" -> "1234"
 * - "1234****5678" -> "5678"
 */
export function normalizeCardNumber(cardNumber: string | number | undefined | null): string {
  if (cardNumber == null) return '';

  // Приводим к строке (может прийти число)
  const cardStr = String(cardNumber);

  // Убираем все символы кроме цифр
  const digitsOnly = cardStr.replace(/\D/g, '');

  // Берём последние 4 цифры
  if (digitsOnly.length >= 4) {
    return digitsOnly.slice(-4);
  }

  // Если цифр меньше 4, возвращаем все что есть
  return digitsOnly;
}

/**
 * Проверка совпадения номеров карт
 * Сравнивает последние 4 цифры
 */
export function cardNumbersMatch(card1: string | number | undefined | null, card2: string | number | undefined | null): boolean {
  const normalized1 = normalizeCardNumber(card1);
  const normalized2 = normalizeCardNumber(card2);

  // Если оба номера пусты - не считаем совпадением
  if (!normalized1 || !normalized2) return false;

  return normalized1 === normalized2;
}

/**
 * Построение карты имён станций из данных
 * Приоритет: TradeCorp > TF > Shifts > generic
 */
export function buildStationNameMap(
  corpTransactions: { stationNumber: number; stationName: string }[],
  tfTransactions: { stationId: number; stationName?: string }[],
  shiftsInfo: { stationId: number; stationName?: string }[]
): Map<number, string> {
  const stationNameMap = new Map<number, string>();

  // Сначала добавляем из Corp (лучшие имена)
  for (const t of corpTransactions) {
    if (t.stationNumber && t.stationName) {
      stationNameMap.set(t.stationNumber, t.stationName);
    }
  }

  // Потом из TF (если нет в Corp)
  for (const t of tfTransactions) {
    if (t.stationId && !stationNameMap.has(t.stationId)) {
      stationNameMap.set(t.stationId, t.stationName || `АЗС ${t.stationId}`);
    }
  }

  // И из смен (fallback)
  for (const s of shiftsInfo) {
    if (s.stationId && !stationNameMap.has(s.stationId)) {
      stationNameMap.set(s.stationId, s.stationName || `АЗС ${s.stationId}`);
    }
  }

  return stationNameMap;
}
