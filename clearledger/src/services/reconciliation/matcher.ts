/**
 * Модуль построчной сверки Corp ↔ TF
 *
 * Алгоритм сопоставления (улучшенный):
 * 1. По станции (exact match)
 * 2. По времени (±90 секунд)
 * 3. По топливу (нормализованные имена)
 * 4. По номеру карты (последние 4 цифры) - дополнительный критерий
 * 5. По сумме (±1 рубль) - дополнительный критерий
 * 6. Проверка литров для определения статуса (matched/mismatch)
 */

import type {
  ReconciliationTransaction,
  ReconciliationTransactionStatus,
  CorpTransaction,
  TfTransaction,
  ShiftInfo
} from '@/types/reconciliation';

import { TIME_TOLERANCE_MS, LITERS_TOLERANCE, COST_TOLERANCE, TRANSACTION_STATUS_ORDER } from './constants';
import { normalizeFuelName, getStationName, cardNumbersMatch } from './utils';

/**
 * Результат построчной сверки
 */
export interface MatchingResult {
  transactions: ReconciliationTransaction[];
  matched: number;
  onlyCorp: number;
  onlyTf: number;
  mismatch: number;
}

/**
 * Вычисление очков соответствия между транзакциями
 * Чем выше очки - тем лучше соответствие
 */
function calculateMatchScore(
  corp: CorpTransaction,
  tf: TfTransaction,
  corpDate: Date,
  tfDate: Date,
  corpFuel: string,
  tfFuel: string
): number {
  let score = 0;

  // Базовые критерии (обязательные)
  if (tf.stationId !== corp.stationNumber) return -1;
  if (tfFuel !== corpFuel) return -1;

  const timeDiff = Math.abs(corpDate.getTime() - tfDate.getTime());
  if (timeDiff > TIME_TOLERANCE_MS) return -1;

  // Базовые очки за прохождение обязательных критериев
  score += 100;

  // Бонус за близость по времени (макс 50 очков)
  const timeScore = Math.max(0, 50 - (timeDiff / 1000));
  score += timeScore;

  // Бонус за совпадение номера карты (50 очков)
  if (cardNumbersMatch(corp.cardNumber, tf.cardNumber)) {
    score += 50;
  }

  // Бонус за совпадение суммы (30 очков)
  const costDiff = Math.abs(corp.cost - tf.total);
  if (costDiff <= COST_TOLERANCE) {
    score += 30;
  } else if (costDiff <= COST_TOLERANCE * 5) {
    score += 15;
  }

  // Бонус за совпадение литров (20 очков)
  const litersDiff = Math.abs(corp.quantity - tf.volume);
  if (litersDiff <= LITERS_TOLERANCE) {
    score += 20;
  } else if (litersDiff <= LITERS_TOLERANCE * 10) {
    score += 10;
  }

  return score;
}

/**
 * Этап 1: Построчная сверка Corp ↔ TF
 */
export function performLineByLineReconciliation(
  corpTransactions: CorpTransaction[],
  tfTransactions: TfTransaction[],
  shiftsInfo: ShiftInfo[],
  stationNameMap: Map<number, string>
): MatchingResult {
  const transactions: ReconciliationTransaction[] = [];
  const matchedTfIds = new Set<number>();
  const matchedCorpIds = new Set<number>();

  let matched = 0;
  let onlyCorp = 0;
  let onlyTf = 0;
  let mismatch = 0;

  // Фильтруем нулевые транзакции Corp (авторизации без заправки, отмены)
  const filteredCorpTransactions = corpTransactions.filter(tx => Math.abs(tx.quantity) > 0);

  // Для каждой Corp транзакции ищем соответствие в TF
  for (const corp of filteredCorpTransactions) {
    const corpDate = new Date(corp.date);
    const corpFuel = normalizeFuelName(corp.productName);

    // Ищем TF с наилучшим соответствием
    let bestMatch: TfTransaction | null = null;
    let bestScore = -1;

    for (const tf of tfTransactions) {
      if (matchedTfIds.has(tf.id)) continue;

      const tfDate = new Date(tf.date);
      const tfFuel = normalizeFuelName(tf.fuelType);

      const score = calculateMatchScore(corp, tf, corpDate, tfDate, corpFuel, tfFuel);

      if (score > bestScore) {
        bestMatch = tf;
        bestScore = score;
      }
    }

    const shiftId = findShiftForTransaction(corp.stationNumber, corpDate, shiftsInfo);

    if (bestMatch && bestScore > 0) {
      matchedTfIds.add(bestMatch.id);
      matchedCorpIds.add(corp.id);

      // Проверяем совпадение литров
      const corpLiters = Math.abs(corp.quantity);
      const tfLiters = Math.abs(bestMatch.volume);
      const litersMatch = Math.abs(corpLiters - tfLiters) < LITERS_TOLERANCE;

      let status: ReconciliationTransactionStatus;
      if (litersMatch) {
        status = 'matched';
        matched++;
      } else {
        status = 'mismatch';
        mismatch++;
      }

      transactions.push({
        id: `match_${corp.id}_${bestMatch.id}`,
        date: corp.date,
        stationId: corp.stationNumber,
        stationName: getStationName(corp.stationNumber, stationNameMap),
        fuelType: corp.productName,
        cardNumber: corp.cardNumber,
        shiftId,
        corpLiters,
        tfLiters,
        corpTransactionId: corp.id,
        tfTransactionId: bestMatch.id,
        status
      });
    } else {
      // Только в Corp
      onlyCorp++;
      transactions.push({
        id: `corp_${corp.id}`,
        date: corp.date,
        stationId: corp.stationNumber,
        stationName: getStationName(corp.stationNumber, stationNameMap),
        fuelType: corp.productName,
        cardNumber: corp.cardNumber,
        shiftId,
        corpLiters: Math.abs(corp.quantity),
        tfLiters: null,
        corpTransactionId: corp.id,
        status: 'only_corp'
      });
    }
  }

  // TF транзакции без соответствия в Corp (также пропускаем нулевые)
  for (const tf of tfTransactions) {
    if (matchedTfIds.has(tf.id)) continue;
    if (Math.abs(tf.volume) <= 0) continue; // Пропускаем нулевые транзакции

    onlyTf++;
    const tfDate = new Date(tf.date);
    const shiftId = findShiftForTransaction(tf.stationId, tfDate, shiftsInfo);

    transactions.push({
      id: `tf_${tf.id}`,
      date: tf.date,
      stationId: tf.stationId,
      stationName: getStationName(tf.stationId, stationNameMap),
      fuelType: tf.fuelType,
      cardNumber: tf.cardNumber || '',
      shiftId,
      corpLiters: null,
      tfLiters: Math.abs(tf.volume),
      tfTransactionId: tf.id,
      status: 'only_tf'
    });
  }

  // Сортируем: сначала расхождения, потом совпадения
  transactions.sort((a, b) => {
    const orderDiff = TRANSACTION_STATUS_ORDER[a.status] - TRANSACTION_STATUS_ORDER[b.status];
    if (orderDiff !== 0) return orderDiff;
    return a.date.localeCompare(b.date);
  });

  return { transactions, matched, onlyCorp, onlyTf, mismatch };
}

/**
 * Определить смену для транзакции по времени
 */
export function findShiftForTransaction(
  stationId: number,
  date: Date,
  shiftsInfo: ShiftInfo[]
): number | null {
  for (const shift of shiftsInfo) {
    if (shift.stationId !== stationId) continue;

    const openedAt = shift.openedAt ? new Date(shift.openedAt) : null;
    const closedAt = shift.closedAt ? new Date(shift.closedAt) : null;

    if (openedAt && closedAt) {
      if (date >= openedAt && date < closedAt) {
        return shift.id;
      }
    } else if (openedAt && !closedAt) {
      // Смена не закрыта
      if (date >= openedAt) {
        return shift.id;
      }
    }
  }

  return null;
}
