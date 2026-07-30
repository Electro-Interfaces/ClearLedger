/**
 * Выгрузка сводной в Excel - два листа.
 *
 * **«Сводная»** повторяет экран: иерархия с подытогами и долями.
 * **«Данные»** отдаёт плоские листья (колонки-измерения плюс метрики). Из второго
 * листа человек строит свои сводные средствами Excel, и это половина ценности файла:
 * наш разрез всегда чей-то частный случай.
 *
 * Метрики берутся из справочника источника, а не зашиты: у реализаций это литры и
 * рубли, у приёмки ТТН - массы по документу и факту с отклонением.
 *
 * Грабли, каждая из которых уже стоила отладки в «Мониторе»:
 *  1. Шапка пишется ПЕРВОЙ (`aoa_to_sheet`), таблица дописывается ниже. Обратный
 *     порядок (`sheet_add_aoa` поверх готового листа) затирает первую колонку у
 *     первых строк, и в файле выходит мешанина.
 *  2. Отступы уровней - неразрывными пробелами (U+00A0): обычные Excel схлопывает,
 *     и иерархия разваливается в плоский список.
 *  3. Служебные значения («all» из фильтра) в шапку не протекают.
 *  4. Ошибка не глотается: пробрасываем наверх, там уведомление и console.error.
 *  5. Имя файла латиницей.
 */
import * as XLSX from 'xlsx'
import type { PivotLabeler, PivotLeaf, PivotNode, PivotTotals } from './pivotTree'
import { flattenAll } from './pivotTree'

const NBSP = ' '

export interface PivotExportOptions {
  nodes: PivotNode[]
  totals: PivotTotals
  /** Порядок уровней на экране. */
  dims: string[]
  dimLabels: string[]
  /** Метрики источника: ключ, подпись колонки, знаков после запятой. */
  metrics: { key: string; label: string; digits: number }[]
  /** Ключ метрики, по которой считались доли и сортировка. */
  sortBy: string
  /** Листья от сервера - для второго листа. */
  leaves: PivotLeaf[]
  serverDims: string[]
  labeler: PivotLabeler
  dateFrom: string
  dateTo: string
  /** Подпись отбора. Служебные значения сюда не доходят. */
  scopeLabel?: string
}

const round = (v: number, d: number) => {
  const p = 10 ** d
  return Math.round(v * p) / p
}

export async function exportPivotToExcel(o: PivotExportOptions): Promise<void> {
  const wb = XLSX.utils.book_new()
  const sortLabel = o.metrics.find((m) => m.key === o.sortBy)?.label ?? o.sortBy

  // ── Лист «Сводная»: сначала шапка, потом таблица ниже ───────────────────
  const head: (string | number)[][] = [
    ['Сводная'],
    [`Период: ${o.dateFrom} — ${o.dateTo}`],
    [`Отбор: ${cleanLabel(o.scopeLabel)}`],
    [`Разрез: ${o.dimLabels.join(' → ')}`],
    [`Сортировка и доли по: ${sortLabel}`],
    [],
  ]
  const pivotRows = flattenAll(o.nodes).map((n) => {
    const row: Record<string, string | number | null> = {
      'Разрез': NBSP.repeat(n.level * 4) + n.label,
      'Уровень': n.level + 1,
      'Измерение': o.dimLabels[n.level] ?? n.dim,
    }
    for (const m of o.metrics) row[m.label] = round(n.m[m.key] ?? 0, m.digits)
    row['Доля от родителя, %'] = round(n.share * 100, 1)
    return row
  })
  const totalRow: Record<string, string | number | null> = {
    'Разрез': 'ИТОГО', 'Уровень': 0, 'Измерение': '',
  }
  for (const m of o.metrics) totalRow[m.label] = round(o.totals[m.key] ?? 0, m.digits)
  totalRow['Доля от родителя, %'] = 100
  pivotRows.push(totalRow)

  const wsPivot = XLSX.utils.aoa_to_sheet(head)
  XLSX.utils.sheet_add_json(wsPivot, pivotRows, { origin: `A${head.length + 1}` })
  wsPivot['!cols'] = [{ wch: 42 }, { wch: 9 }, { wch: 20 },
    ...o.metrics.map(() => ({ wch: 16 })), { wch: 20 }]
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
    for (const m of o.metrics) row[m.label] = round(leaf.m[m.key] ?? 0, m.digits)
    return row
  })
  const wsData = XLSX.utils.aoa_to_sheet(dataHead)
  XLSX.utils.sheet_add_json(wsData, dataRows, { origin: `A${dataHead.length + 1}` })
  wsData['!cols'] = [...o.serverDims.map(() => ({ wch: 22 })), ...o.metrics.map(() => ({ wch: 16 }))]
  XLSX.utils.book_append_sheet(wb, wsData, 'Данные')

  XLSX.writeFile(wb, `svodnaya_${o.dateFrom}_${o.dateTo}.xlsx`)
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
