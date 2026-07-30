/**
 * Выгрузка сводной в Excel - два листа.
 *
 * **«Сводная»** повторяет экран: иерархия с подытогами и долями.
 * **«Данные»** отдаёт плоские листья (колонки-измерения плюс метрики). Из второго
 * листа человек строит свои сводные средствами Excel, и это половина ценности файла:
 * наш разрез всегда чей-то частный случай.
 *
 * Грабли, каждая из которых уже стоила отладки в «Мониторе»:
 *  1. Шапка пишется ПЕРВОЙ (`aoa_to_sheet`), таблица дописывается ниже. Обратный
 *     порядок (`sheet_add_aoa` поверх готового листа) затирает первую колонку у
 *     первых строк, и в файле выходит мешанина.
 *  2. Отступы уровней - неразрывными пробелами (U+00A0): обычные Excel схлопывает,
 *     и иерархия разваливается в плоский список.
 *  3. Служебные значения («все АЗС» из фильтра) в шапку не протекают.
 *  4. Ошибка не глотается: пробрасываем наверх, там уведомление и console.error.
 *  5. Имя файла латиницей.
 */
import * as XLSX from 'xlsx'
import type { PivotLeaf, PivotLabeler, PivotMetric, PivotNode, PivotTotals } from './pivotTree'
import { flattenAll } from './pivotTree'

const NBSP = ' '
const METRIC_LABEL: Record<PivotMetric, string> = {
  amount: 'выручке', liters: 'литрам', ops: 'операциям',
}

export interface PivotExportOptions {
  nodes: PivotNode[]
  totals: PivotTotals
  /** Порядок уровней на экране. */
  dims: string[]
  dimLabels: string[]
  metric: PivotMetric
  /** Листья от сервера - для второго листа. */
  leaves: PivotLeaf[]
  serverDims: string[]
  labeler: PivotLabeler
  dateFrom: string
  dateTo: string
  /** Подпись отбора станций. Служебные значения сюда не доходят. */
  stationName?: string
}

const round = (v: number, d = 2) => Math.round(v * 10 ** d) / 10 ** d

export async function exportPivotToExcel(o: PivotExportOptions): Promise<void> {
  const wb = XLSX.utils.book_new()

  // ── Лист «Сводная»: сначала шапка, потом таблица ниже ───────────────────
  const head: (string | number)[][] = [
    ['Сводная по операциям'],
    [`Период: ${o.dateFrom} — ${o.dateTo}`],
    [`АЗС: ${cleanLabel(o.stationName)}`],
    [`Разрез: ${o.dimLabels.join(' → ')}`],
    [`Сортировка и доли по ${METRIC_LABEL[o.metric]}`],
    [],
  ]
  const pivotRows = flattenAll(o.nodes).map((n) => ({
    'Разрез': NBSP.repeat(n.level * 4) + n.label,
    'Уровень': n.level + 1,
    'Измерение': o.dimLabels[n.level] ?? n.dim,
    'Операций': n.ops,
    'Литры': round(n.liters, 3),
    'Выручка, ₽': round(n.amount),
    'Ср. цена, ₽/л': n.liters > 0 ? round(n.amount / n.liters, 3) : null,
    'Доля от родителя, %': round(n.share * 100, 1),
  }))
  pivotRows.push({
    'Разрез': 'ИТОГО',
    'Уровень': 0,
    'Измерение': '',
    'Операций': o.totals.ops,
    'Литры': round(o.totals.liters, 3),
    'Выручка, ₽': round(o.totals.amount),
    'Ср. цена, ₽/л': o.totals.liters > 0 ? round(o.totals.amount / o.totals.liters, 3) : null,
    'Доля от родителя, %': 100,
  })
  const wsPivot = XLSX.utils.aoa_to_sheet(head)
  XLSX.utils.sheet_add_json(wsPivot, pivotRows, { origin: `A${head.length + 1}` })
  wsPivot['!cols'] = [{ wch: 42 }, { wch: 9 }, { wch: 18 }, { wch: 11 }, { wch: 13 }, { wch: 15 }, { wch: 14 }, { wch: 20 }]
  XLSX.utils.book_append_sheet(wb, wsPivot, 'Сводная')

  // ── Лист «Данные»: плоские листья под собственные сводные Excel ─────────
  const dataHead: (string | number)[][] = [
    ['Листья разреза (для собственных сводных)'],
    [`Период: ${o.dateFrom} — ${o.dateTo}`],
    [],
  ]
  const dataRows = o.leaves.map((leaf) => {
    const row: Record<string, string | number | null> = {}
    o.serverDims.forEach((dim, i) => {
      const label = o.dimLabels[o.dims.indexOf(dim)] ?? dim
      row[label] = o.labeler(dim, leaf.keys[i] ?? null)
    })
    row['Операций'] = leaf.ops
    row['Литры'] = round(leaf.liters, 3)
    row['Выручка, ₽'] = round(leaf.amount)
    row['Ср. цена, ₽/л'] = leaf.liters > 0 ? round(leaf.amount / leaf.liters, 3) : null
    return row
  })
  const wsData = XLSX.utils.aoa_to_sheet(dataHead)
  XLSX.utils.sheet_add_json(wsData, dataRows, { origin: `A${dataHead.length + 1}` })
  wsData['!cols'] = [...o.serverDims.map(() => ({ wch: 22 })), { wch: 11 }, { wch: 13 }, { wch: 15 }, { wch: 14 }]
  XLSX.utils.book_append_sheet(wb, wsData, 'Данные')

  XLSX.writeFile(wb, `svodnaya_operacii_${o.dateFrom}_${o.dateTo}.xlsx`)
}

/**
 * Подпись отбора для шапки. Служебные значения фильтра («all», в localStorage ещё и
 * закавыченное `"all"`) в отчёт протекать не должны: читатель файла таких слов не знает.
 */
function cleanLabel(v?: string): string {
  const s = (v ?? '').trim().replace(/^"+|"+$/g, '')
  if (!s || s.toLowerCase() === 'all') return 'все'
  return s
}
