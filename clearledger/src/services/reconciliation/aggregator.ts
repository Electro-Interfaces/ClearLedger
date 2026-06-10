/**
 * Модуль агрегации данных сверки
 *
 * Иерархия: АЗС → Топливо → Смены
 * Сравнение трёх источников: Corp, TF, Shift
 */

import type {
  ReconciliationTransaction,
  ReconciliationByStation,
  ReconciliationByFuelWithShifts,
  ReconciliationShiftData,
  ReconciliationByFuel,
  ShiftInfo
} from '@/types/reconciliation';

import { LITERS_TOLERANCE } from './constants';
import { normalizeFuelName, round, getStationName } from './utils';

/**
 * Этап 2: Агрегация по станциям (АЗС → Топливо → Смены)
 */
export function aggregateByStationAndShift(
  transactions: ReconciliationTransaction[],
  shiftsInfo: ShiftInfo[],
  stationNameMap: Map<number, string>,
  showAllShifts?: boolean
): ReconciliationByStation[] {
  // Группируем транзакции по станциям
  const byStationMap = new Map<number, ReconciliationTransaction[]>();

  for (const tx of transactions) {
    const existing = byStationMap.get(tx.stationId) || [];
    existing.push(tx);
    byStationMap.set(tx.stationId, existing);
  }

  // Добавляем станции из shiftsInfo
  for (const shift of shiftsInfo) {
    if (!byStationMap.has(shift.stationId)) {
      byStationMap.set(shift.stationId, []);
    }
  }

  const result: ReconciliationByStation[] = [];

  for (const [stationId, stationTransactions] of byStationMap) {
    const stationName = getStationName(stationId, stationNameMap);
    const stationShifts = shiftsInfo.filter(s => s.stationId === stationId);

    // Собираем все уникальные виды топлива
    const fuelNames = new Set<string>();
    for (const tx of stationTransactions) {
      fuelNames.add(normalizeFuelName(tx.fuelType));
    }
    for (const shift of stationShifts) {
      for (const fuel of shift.fuelSales) {
        fuelNames.add(normalizeFuelName(fuel.fuelName));
      }
    }

    // Группируем по топливу, затем по сменам
    const byFuel: ReconciliationByFuelWithShifts[] = [];

    for (const fuelKey of fuelNames) {
      const fuelTransactions = stationTransactions.filter(
        tx => normalizeFuelName(tx.fuelType) === fuelKey
      );

      // Определяем отображаемое имя топлива
      const displayName = fuelTransactions[0]?.fuelType ||
        stationShifts.flatMap(s => s.fuelSales).find(f => normalizeFuelName(f.fuelName) === fuelKey)?.fuelName ||
        fuelKey;

      // Разбивка по сменам для этого топлива
      const byShift: ReconciliationShiftData[] = [];

      for (const shift of stationShifts) {
        const shiftFuelTransactions = fuelTransactions.filter(tx => tx.shiftId === shift.id);
        const shiftFuelSale = shift.fuelSales.find(f => normalizeFuelName(f.fuelName) === fuelKey);

        const corpLiters = shiftFuelTransactions
          .filter(tx => tx.corpLiters !== null)
          .reduce((sum, tx) => sum + (tx.corpLiters || 0), 0);

        const tfLiters = shiftFuelTransactions
          .filter(tx => tx.tfLiters !== null)
          .reduce((sum, tx) => sum + (tx.tfLiters || 0), 0);

        const shiftLiters = shiftFuelSale?.quantity || 0;

        // Добавляем смену если есть данные или showAllShifts
        if (corpLiters > 0 || tfLiters > 0 || shiftLiters > 0 || showAllShifts) {
          const hasErrors = Math.abs(corpLiters - tfLiters) > LITERS_TOLERANCE ||
                            (shiftLiters > 0 && Math.abs(tfLiters - shiftLiters) > LITERS_TOLERANCE);

          byShift.push({
            shiftId: shift.id,
            shiftDate: shift.openedAt.substring(0, 10),
            shiftOpenedAt: shift.openedAt,
            shiftClosedAt: shift.closedAt,
            corpLiters: round(corpLiters),
            tfLiters: round(tfLiters),
            shiftLiters: round(shiftLiters),
            status: hasErrors ? 'error' : 'ok'
          });
        }
      }

      // Транзакции без смены для этого топлива
      const noShiftFuelTransactions = fuelTransactions.filter(tx => tx.shiftId === null);
      if (noShiftFuelTransactions.length > 0) {
        const corpLiters = noShiftFuelTransactions
          .filter(tx => tx.corpLiters !== null)
          .reduce((sum, tx) => sum + (tx.corpLiters || 0), 0);

        const tfLiters = noShiftFuelTransactions
          .filter(tx => tx.tfLiters !== null)
          .reduce((sum, tx) => sum + (tx.tfLiters || 0), 0);

        byShift.push({
          shiftId: 0,
          shiftDate: 'Без смены',
          shiftOpenedAt: '',
          shiftClosedAt: null,
          corpLiters: round(corpLiters),
          tfLiters: round(tfLiters),
          shiftLiters: 0,
          status: 'error' // Всегда ошибка - нет привязки к смене
        });
      }

      // Сортируем смены: новые сверху, "Без смены" в конце
      byShift.sort((a, b) => {
        if (a.shiftId === 0) return 1;
        if (b.shiftId === 0) return -1;
        return b.shiftId - a.shiftId;
      });

      // Итоги по топливу
      const corpLitersTotal = byShift.reduce((sum, s) => sum + s.corpLiters, 0);
      const tfLitersTotal = byShift.reduce((sum, s) => sum + s.tfLiters, 0);
      const shiftLitersTotal = byShift.reduce((sum, s) => sum + s.shiftLiters, 0);

      const fuelHasErrors = byShift.some(s => s.status === 'error');

      byFuel.push({
        fuelName: displayName,
        byShift,
        corpLitersTotal: round(corpLitersTotal),
        tfLitersTotal: round(tfLitersTotal),
        shiftLitersTotal: round(shiftLitersTotal),
        status: fuelHasErrors ? 'error' : 'ok'
      });
    }

    // Сортируем топлива по имени
    byFuel.sort((a, b) => a.fuelName.localeCompare(b.fuelName));

    // Итоги по станции
    const corpLitersTotal = byFuel.reduce((sum, f) => sum + f.corpLitersTotal, 0);
    const tfLitersTotal = byFuel.reduce((sum, f) => sum + f.tfLitersTotal, 0);
    const shiftLitersTotal = byFuel.reduce((sum, f) => sum + f.shiftLitersTotal, 0);

    const stationHasErrors = byFuel.some(f => f.status === 'error');

    result.push({
      stationId,
      stationName,
      byFuel,
      corpLitersTotal: round(corpLitersTotal),
      tfLitersTotal: round(tfLitersTotal),
      shiftLitersTotal: round(shiftLitersTotal),
      status: stationHasErrors ? 'error' : 'ok'
    });
  }

  return result.sort((a, b) => a.stationId - b.stationId);
}

/**
 * Агрегация по топливу (вспомогательная функция)
 */
export function aggregateByFuel(
  transactions: ReconciliationTransaction[],
  shiftFuelSales: ShiftInfo['fuelSales']
): ReconciliationByFuel[] {
  // Группируем транзакции по топливу
  const byFuelMap = new Map<string, {
    corpLiters: number;
    tfLiters: number;
  }>();

  for (const tx of transactions) {
    const fuelKey = normalizeFuelName(tx.fuelType);
    const existing = byFuelMap.get(fuelKey) || { corpLiters: 0, tfLiters: 0 };

    if (tx.corpLiters !== null) {
      existing.corpLiters += tx.corpLiters;
    }
    if (tx.tfLiters !== null) {
      existing.tfLiters += tx.tfLiters;
    }

    byFuelMap.set(fuelKey, existing);
  }

  // Добавляем топливо из сменного отчёта
  for (const fuel of shiftFuelSales) {
    const fuelKey = normalizeFuelName(fuel.fuelName);
    if (!byFuelMap.has(fuelKey)) {
      byFuelMap.set(fuelKey, { corpLiters: 0, tfLiters: 0 });
    }
  }

  const result: ReconciliationByFuel[] = [];

  for (const [fuelKey, data] of byFuelMap) {
    // Ищем данные смены для этого топлива
    const shiftFuel = shiftFuelSales.find(f => normalizeFuelName(f.fuelName) === fuelKey);
    const shiftLiters = shiftFuel?.quantity || 0;

    const corpVsTfDiff = data.corpLiters - data.tfLiters;
    const tfVsShiftDiff = data.tfLiters - shiftLiters;

    // Любое расхождение = ошибка
    const hasErrors = Math.abs(corpVsTfDiff) > LITERS_TOLERANCE ||
                      (shiftLiters > 0 && Math.abs(tfVsShiftDiff) > LITERS_TOLERANCE);

    // Определяем отображаемое имя
    const displayName = transactions.find(tx => normalizeFuelName(tx.fuelType) === fuelKey)?.fuelType ||
                        shiftFuel?.fuelName ||
                        fuelKey;

    result.push({
      fuelName: displayName,
      corpLiters: round(data.corpLiters),
      tfLiters: round(data.tfLiters),
      shiftLiters: round(shiftLiters),
      corpVsTfDiff: round(corpVsTfDiff),
      tfVsShiftDiff: round(tfVsShiftDiff),
      status: hasErrors ? 'error' : 'ok'
    });
  }

  return result.sort((a, b) => a.fuelName.localeCompare(b.fuelName));
}
