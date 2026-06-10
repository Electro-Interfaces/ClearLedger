import { format } from 'date-fns';
import { ru } from 'date-fns/locale';
import type { ReconciliationResult } from '@/types/reconciliation';
import { loadXlsx } from '@/utils/xlsxLoader';

/**
 * Экспорт результатов сверки в Excel с несколькими листами
 */
export async function exportReconciliationToExcel(result: ReconciliationResult): Promise<void> {
  const { summary, byStation, transactions, params } = result;
  const XLSX = await loadXlsx();

  const wb = XLSX.utils.book_new();

  // Форматирование даты
  const formatDate = (dateStr: string) => {
    try {
      if (dateStr === 'Без смены') return dateStr;
      const date = new Date(dateStr);
      return format(date, 'dd.MM.yyyy', { locale: ru });
    } catch {
      return dateStr;
    }
  };

  const formatDateTime = (dateStr: string) => {
    try {
      const date = new Date(dateStr);
      return format(date, 'dd.MM.yyyy HH:mm', { locale: ru });
    } catch {
      return dateStr;
    }
  };

  // ========== Лист 1: Сводка ==========
  const totalCorp = summary.totalCorpLiters || 0;
  const totalTf = summary.totalTfLiters || 0;
  const totalShift = summary.totalShiftLiters || 0;

  const summaryData = [
    ['ОТЧЁТ ПО СВЕРКЕ КОРПОРАТИВНОГО ПРОЦЕССИНГА'],
    [],
    ['Период:', `${formatDate(params.dateFrom)} — ${formatDate(params.dateTo)}`],
    ['Дата формирования:', formatDateTime(result.executedAt)],
    [],
    ['ИТОГИ ПО ИСТОЧНИКАМ', 'Литры'],
    ['Corp (TradeCorp)', Number(totalCorp.toFixed(2))],
    ['TF (TradePoint)', Number(totalTf.toFixed(2))],
    ['Смена (Сменный отчёт)', Number(totalShift.toFixed(2))],
    [],
    ['РАСХОЖДЕНИЯ', 'Литры'],
    ['Corp - TF', Number((totalCorp - totalTf).toFixed(2))],
    ['TF - Смена', Number((totalTf - totalShift).toFixed(2))],
    [],
    ['СТАТИСТИКА ТРАНЗАКЦИЙ', 'Количество'],
    ['Совпавших (OK)', summary.matched ?? 0],
    ['Только в Corp', summary.onlyCorp ?? 0],
    ['Только в TF', summary.onlyTf ?? 0],
    ['С расхождением литров', summary.mismatch ?? 0],
    [],
    ['ОБЩИЙ СТАТУС', summary.hasErrors ? 'ЕСТЬ РАСХОЖДЕНИЯ' : 'ВСЁ СХОДИТСЯ'],
  ];

  const wsSummary = XLSX.utils.aoa_to_sheet(summaryData);
  wsSummary['!cols'] = [{ wch: 30 }, { wch: 20 }];
  XLSX.utils.book_append_sheet(wb, wsSummary, 'Сводка');

  // ========== Лист 2: По станциям и топливу ==========
  const stationsData: (string | number)[][] = [
    ['Станция', 'Топливо', 'Смена', 'Дата смены', 'Corp (л)', 'TF (л)', 'Смена (л)', 'Corp-TF', 'TF-Смена', 'Статус'],
  ];

  byStation.forEach(station => {
    station.byFuel.forEach(fuel => {
      fuel.byShift.forEach(shift => {
        const corpTfDiff = shift.corpLiters - shift.tfLiters;
        const tfShiftDiff = shift.tfLiters - shift.shiftLiters;
        stationsData.push([
          station.stationName,
          fuel.fuelName,
          shift.shiftId === 0 ? 'Без смены' : `#${shift.shiftId}`,
          formatDate(shift.shiftDate),
          shift.corpLiters,
          shift.tfLiters,
          shift.shiftLiters,
          corpTfDiff,
          tfShiftDiff,
          shift.status === 'ok' ? 'OK' : 'Расхождение',
        ]);
      });

      // Итог по топливу
      stationsData.push([
        station.stationName,
        `ИТОГО ${fuel.fuelName}`,
        '',
        '',
        fuel.corpLitersTotal,
        fuel.tfLitersTotal,
        fuel.shiftLitersTotal,
        fuel.corpLitersTotal - fuel.tfLitersTotal,
        fuel.tfLitersTotal - fuel.shiftLitersTotal,
        fuel.status === 'ok' ? 'OK' : 'Расхождение',
      ]);
    });

    // Итог по станции
    stationsData.push([
      `ИТОГО ${station.stationName}`,
      '',
      '',
      '',
      station.corpLitersTotal,
      station.tfLitersTotal,
      station.shiftLitersTotal,
      station.corpLitersTotal - station.tfLitersTotal,
      station.tfLitersTotal - station.shiftLitersTotal,
      station.status === 'ok' ? 'OK' : 'Расхождение',
    ]);
    stationsData.push([]); // Пустая строка между станциями
  });

  const wsStations = XLSX.utils.aoa_to_sheet(stationsData);
  wsStations['!cols'] = [
    { wch: 15 }, { wch: 15 }, { wch: 12 }, { wch: 12 },
    { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 15 },
  ];
  XLSX.utils.book_append_sheet(wb, wsStations, 'По станциям');

  // ========== Лист 3: Только расхождения ==========
  const discrepanciesData: (string | number)[][] = [
    ['Станция', 'Топливо', 'Смена', 'Дата смены', 'Corp (л)', 'TF (л)', 'Смена (л)', 'Corp-TF', 'TF-Смена'],
  ];

  byStation.forEach(station => {
    station.byFuel.forEach(fuel => {
      fuel.byShift.forEach(shift => {
        if (shift.status === 'error') {
          const corpTfDiff = shift.corpLiters - shift.tfLiters;
          const tfShiftDiff = shift.tfLiters - shift.shiftLiters;
          discrepanciesData.push([
            station.stationName,
            fuel.fuelName,
            shift.shiftId === 0 ? 'Без смены' : `#${shift.shiftId}`,
            formatDate(shift.shiftDate),
            shift.corpLiters,
            shift.tfLiters,
            shift.shiftLiters,
            corpTfDiff,
            tfShiftDiff,
          ]);
        }
      });
    });
  });

  // Добавим итоговую строку расхождений
  if (discrepanciesData.length > 1) {
    discrepanciesData.push([]);
    discrepanciesData.push([
      'ИТОГО расхождения:',
      '',
      '',
      '',
      totalCorp,
      totalTf,
      totalShift,
      Number((totalCorp - totalTf).toFixed(2)),
      Number((totalTf - totalShift).toFixed(2)),
    ]);
  }

  const wsDiscrepancies = XLSX.utils.aoa_to_sheet(discrepanciesData);
  wsDiscrepancies['!cols'] = [
    { wch: 15 }, { wch: 15 }, { wch: 12 }, { wch: 12 },
    { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 12 },
  ];
  XLSX.utils.book_append_sheet(wb, wsDiscrepancies, 'Расхождения');

  // ========== Лист 4: Детальные транзакции ==========
  const transactionsData: (string | number)[][] = [
    ['Дата/Время', 'Станция', 'Топливо', 'Карта', 'Смена', 'Corp (л)', 'TF (л)', 'Статус'],
  ];

  transactions.forEach(tx => {
    transactionsData.push([
      formatDateTime(tx.date),
      tx.stationName,
      tx.fuelType || '',
      tx.cardNumber,
      tx.shiftId ? `#${tx.shiftId}` : 'Без смены',
      tx.corpLiters ?? '',
      tx.tfLiters ?? '',
      getStatusText(tx.status),
    ]);
  });

  const wsTransactions = XLSX.utils.aoa_to_sheet(transactionsData);
  wsTransactions['!cols'] = [
    { wch: 18 }, { wch: 15 }, { wch: 12 }, { wch: 20 },
    { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 15 },
  ];
  XLSX.utils.book_append_sheet(wb, wsTransactions, 'Транзакции');

  // ========== Лист 5: Только транзакции с расхождениями ==========
  const txDiscrepanciesData: (string | number)[][] = [
    ['Дата/Время', 'Станция', 'Топливо', 'Карта', 'Смена', 'Corp (л)', 'TF (л)', 'Разница', 'Статус'],
  ];

  transactions
    .filter(tx => tx.status !== 'matched')
    .forEach(tx => {
      const diff = (tx.corpLiters ?? 0) - (tx.tfLiters ?? 0);
      txDiscrepanciesData.push([
        formatDateTime(tx.date),
        tx.stationName,
        tx.fuelType || '',
        tx.cardNumber,
        tx.shiftId ? `#${tx.shiftId}` : 'Без смены',
        tx.corpLiters ?? '',
        tx.tfLiters ?? '',
        diff || '',
        getStatusText(tx.status),
      ]);
    });

  const wsTxDiscrepancies = XLSX.utils.aoa_to_sheet(txDiscrepanciesData);
  wsTxDiscrepancies['!cols'] = [
    { wch: 18 }, { wch: 15 }, { wch: 12 }, { wch: 20 },
    { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 15 },
  ];
  XLSX.utils.book_append_sheet(wb, wsTxDiscrepancies, 'Транзакции-расхождения');

  // Формируем имя файла
  const fileName = `Сверка_${formatDate(params.dateFrom)}_${formatDate(params.dateTo)}.xlsx`;

  // Сохраняем файл
  XLSX.writeFile(wb, fileName);
}

function getStatusText(status: string): string {
  switch (status) {
    case 'matched': return 'OK';
    case 'only_corp': return 'Только Corp';
    case 'only_tf': return 'Только TF';
    case 'mismatch': return 'Расхождение литров';
    default: return status;
  }
}
