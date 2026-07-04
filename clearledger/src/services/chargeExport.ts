/**
 * Экспорт управленческой аналитики ЭЗС в Excel и PDF — читает DOM пункта.
 *
 * Excel (ExcelJS): лист «KPI» (карточки) + лист(ы) с таблицами (редактируемые
 *   значения как на экране) + лист «Графики» (снимки recharts/heatmap).
 * PDF: снимок содержимого пункта (html-to-image) с пагинацией — кириллица
 *   читаема (у jsPDF-шрифтов по умолчанию её нет).
 */

import { toPng } from 'html-to-image'
import { saveAs } from 'file-saver'
import { getChargePivot, getChargeSessionRows, type ChargePivotDim, type ChargeMetric, type ChargeSessionRow } from './analyticsService'

const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

function fileBase(title: string): string {
  const date = new Date().toISOString().slice(0, 10)
  return `${title.replace(/[\\/:*?"<>|]+/g, ' ').trim()} · ${date}`
}

function safeSheet(name: string, used: Set<string>): string {
  const base = (name.replace(/[\\/*?:[\]]/g, ' ').trim() || 'Лист').slice(0, 28)
  let n = base, i = 2
  while (used.has(n)) n = `${base.slice(0, 26)} ${i++}`
  used.add(n)
  return n
}

/** Снимок элемента. На время съёмки прячем управляющие элементы (кнопки, селекторы,
 * переключатели) — в отчёт идут только данные, графики и таблицы. */
async function snapshot(el: HTMLElement): Promise<string> {
  const bg = getComputedStyle(el).backgroundColor
  const style = document.createElement('style')
  style.textContent = '[data-export-ignore]{display:none !important}'
  document.head.appendChild(style)
  try {
    return await toPng(el, { pixelRatio: 2, backgroundColor: bg && bg !== 'rgba(0, 0, 0, 0)' ? bg : undefined, cacheBust: true })
  } finally {
    document.head.removeChild(style)
  }
}

interface Kpi { label: string; value: string; hint: string }
interface Tbl { name: string; columns: string[]; rows: (string | number)[][] }

/** KPI-карточки помечены data-kpi; читаем label/value/hint из детей. */
function readKpis(root: HTMLElement): Kpi[] {
  return Array.from(root.querySelectorAll<HTMLElement>('[data-kpi]')).map((el) => {
    const ch = el.children
    return {
      label: ch[0]?.textContent?.trim() ?? '',
      value: ch[1]?.textContent?.trim() ?? '',
      hint: ch[2]?.textContent?.trim() ?? '',
    }
  })
}

/** Таблицы пункта. Приоритет — сырые ЧИСЛА из data-export-rows (для формул в Excel);
 * иначе fallback на текст из DOM (как отображено). data-export-name → имя листа. */
function readTables(root: HTMLElement): Tbl[] {
  return Array.from(root.querySelectorAll('table')).map((tbl, i) => {
    const name = tbl.getAttribute('data-export-name')
      ?? tbl.closest('[data-export-name]')?.getAttribute('data-export-name') ?? `Таблица ${i + 1}`
    const raw = tbl.getAttribute('data-export-rows')
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as { columns: string[]; rows: (string | number)[][] }
        if (Array.isArray(parsed.columns) && Array.isArray(parsed.rows)) return { name, columns: parsed.columns, rows: parsed.rows }
      } catch { /* fallback ниже */ }
    }
    const columns = Array.from(tbl.querySelectorAll('thead th')).map((th) => th.textContent?.trim() ?? '')
    const rows = Array.from(tbl.querySelectorAll('tbody tr')).map((tr) =>
      Array.from(tr.querySelectorAll('td')).map((td) => td.textContent?.trim() ?? ''))
    return { name, columns, rows }
  }).filter((t) => t.rows.length > 0)
}

function findCharts(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>('.recharts-wrapper, [data-chart]'))
}

export async function exportChargeExcel(el: HTMLElement, title: string, subtitle?: string): Promise<void> {
  const ExcelJS = (await import('exceljs')).default
  const wb = new ExcelJS.Workbook()
  wb.creator = 'TradeLedger'; wb.created = new Date()
  const used = new Set<string>()

  const kpis = readKpis(el)
  if (kpis.length) {
    const ws = wb.addWorksheet(safeSheet('KPI', used))
    ws.mergeCells('A1:C1')
    ws.getCell('A1').value = title
    ws.getCell('A1').font = { bold: true, size: 14 }
    if (subtitle) { ws.getCell('A2').value = subtitle; ws.getCell('A2').font = { color: { argb: 'FF888888' } } }
    const head = ws.addRow(['Показатель', 'Значение', 'Примечание']); head.font = { bold: true }
    kpis.forEach((k) => ws.addRow([k.label, k.value, k.hint]))
    ws.columns = [{ width: 34 }, { width: 24 }, { width: 30 }]
  }

  readTables(el).forEach((t, i) => {
    const ws = wb.addWorksheet(safeSheet(t.name || `Таблица ${i + 1}`, used))
    const head = ws.addRow(t.columns); head.font = { bold: true }
    head.eachCell((c) => { c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEFEF' } } })
    t.rows.forEach((r) => {
      const row = ws.addRow(r)
      row.eachCell((cell) => {
        if (typeof cell.value === 'number') { cell.numFmt = '#,##0.##'; cell.alignment = { horizontal: 'right' } }
      })
    })
    ws.columns.forEach((c, ci) => {
      const maxLen = Math.max(String(t.columns[ci] ?? '').length, ...t.rows.map((r) => String(r[ci] ?? '').length), 8)
      c.width = Math.min(46, maxLen + 2)
    })
    ws.views = [{ state: 'frozen', ySplit: 1 }]
    if (t.columns.length) ws.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: t.columns.length } }
  })

  const charts = findCharts(el)
  if (charts.length) {
    const ws = wb.addWorksheet(safeSheet('Графики', used))
    let rowCursor = 0
    for (const c of charts) {
      try {
        const imgId = wb.addImage({ base64: await snapshot(c), extension: 'png' })
        const w = Math.min(920, c.offsetWidth || 640)
        const h = (c.offsetHeight || 320) * (w / (c.offsetWidth || 640))
        ws.addImage(imgId, { tl: { col: 0, row: rowCursor }, ext: { width: w, height: h } })
        rowCursor += Math.ceil(h / 18) + 2
      } catch { /* пропуск */ }
    }
  }

  const buf = await wb.xlsx.writeBuffer()
  saveAs(new Blob([buf], { type: XLSX_MIME }), `${fileBase(title)}.xlsx`)
}

export async function exportChargePdf(el: HTMLElement, title: string): Promise<void> {
  const { jsPDF } = await import('jspdf')
  const dataUrl = await snapshot(el)
  const img = new Image()
  await new Promise<void>((res, rej) => { img.onload = () => res(); img.onerror = () => rej(new Error('img')); img.src = dataUrl })

  // Ориентация — по форме контента: широкий → альбомная (иначе таблицы ужимаются).
  const orientation = img.width > img.height * 1.15 ? 'landscape' : 'portrait'
  const doc = new jsPDF({ orientation, unit: 'pt', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()
  const margin = 24
  const imgW = pageW - margin * 2
  const imgH = imgW * (img.height / img.width)

  let heightLeft = imgH
  doc.addImage(dataUrl, 'PNG', margin, margin, imgW, imgH)
  heightLeft -= (pageH - margin * 2)
  while (heightLeft > 0) {
    doc.addPage()
    doc.addImage(dataUrl, 'PNG', margin, margin - (imgH - heightLeft), imgW, imgH)
    heightLeft -= (pageH - margin * 2)
  }
  doc.save(`${fileBase(title)}.pdf`)
}


/* ── Сводные таблицы (pivot) для «Нормализации» ────────────────────────────
 * Мультилистовой Excel: опц. лист «Сессии» (детально) + лист на каждую сводную.
 * Данные тянутся с бэкенда (/charge-sessions/pivot|rows), листы строятся ExcelJS.
 */

export const PIVOT_DIM_LABEL: Record<string, string> = {
  station: 'Станция', region: 'Регион', connector: 'Тип коннектора', user_type: 'Тип клиента',
  client: 'Клиент (ЮЛ)', charge_type: 'Канал запуска', result: 'Исход', cut: 'Разрез расчёта',
  tariff: 'Тариф', month: 'Месяц', week: 'Неделя', day: 'День', decade: 'Декада',
  quarter: 'Квартал', hour: 'Час', weekday: 'День недели',
}
export const PIVOT_METRIC_LABEL: Record<string, string> = {
  sessions: 'Сессии, шт', energy_kwh: 'Энергия, кВт·ч', amount: 'Сумма, ₽',
  avg_check: 'Средний чек, ₽', avg_energy: 'Ср. энергия, кВт·ч',
  avg_duration_min: 'Ср. длительность, мин', success_pct: 'Успешных, %', price_per_kwh: '₽/кВт·ч',
}

export interface PivotSpec { title: string; rows: ChargePivotDim; cols?: ChargePivotDim; metric?: ChargeMetric }

// Pivot-ready колонки листа «Данные» (Excel-таблица): измерения + меры + счётчик.
// Пользователь строит свою сводную поверх — выделить таблицу → Вставка → Сводная.
const WD = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
const PIVOT_READY_COLS: [string, (r: ChargeSessionRow) => string | number][] = [
  ['Регион', (r) => r.region || '—'],
  ['Станция', (r) => r.station_name || r.station_code || '—'],
  ['Коннектор', (r) => r.connector_type || '—'],
  ['Тип клиента', (r) => r.user_type || '—'],
  ['Клиент (ЮЛ)', (r) => r.client_name || 'Без клиента (ФЛ)'],
  ['Канал запуска', (r) => r.charge_type || '—'],
  ['Исход', (r) => r.result || '—'],
  ['Разрез', (r) => r.cut_key || '—'],
  ['Месяц', (r) => (r.started_at || '').slice(0, 7) || '—'],
  ['Час', (r) => (r.started_at || '').slice(11, 13) || '—'],
  ['День недели', (r) => (r.started_at ? WD[new Date(r.started_at).getDay()] : '—')],
  ['Энергия кВт·ч', (r) => Number(r.energy_kwh) || 0],
  ['Сумма ₽', (r) => Number(r.amount) || 0],
  ['Длительность мин', (r) => Number(r.duration_min) || 0],
  ['Сессии', () => 1],
]

export async function exportChargePivots(opts: {
  companyId: string; dateFrom: string; dateTo: string; title: string
  pivots: PivotSpec[]; onProgress?: (msg: string) => void
}): Promise<void> {
  const ExcelJS = (await import('exceljs')).default
  const wb = new ExcelJS.Workbook()
  const used = new Set<string>()

  // Лист «Данные» — настоящая Excel-таблица (pivot-ready). Свою сводную строит сам
  // Excel: выделить ячейку в таблице → Вставка → Сводная таблица (область полей).
  opts.onProgress?.('Загрузка сессий…')
  const res = await getChargeSessionRows({ companyId: opts.companyId, dateFrom: opts.dateFrom, dateTo: opts.dateTo })
  if (res.rows.length) {
    const ws = wb.addWorksheet(safeSheet('Данные', used))
    ws.addTable({
      name: 'СессииЭЗС', displayName: 'СессииЭЗС', ref: 'A1', headerRow: true,
      style: { theme: 'TableStyleMedium2', showRowStripes: true },
      columns: PIVOT_READY_COLS.map((c) => ({ name: c[0], filterButton: true })),
      rows: res.rows.map((r) => PIVOT_READY_COLS.map((c) => c[1](r))),
    })
    ws.views = [{ state: 'frozen', ySplit: 1 }]
    for (let i = 1; i <= PIVOT_READY_COLS.length; i++) ws.getColumn(i).width = i <= 2 ? 20 : i === 5 ? 24 : 13
    if (res.truncated) {
      const w = ws.getCell(`A${res.rows.length + 3}`)
      w.value = `⚠ Показаны первые ${res.rows.length} строк — для полного экспорта сузьте период.`
      w.font = { italic: true, color: { argb: 'FFB8760A' } }
    }
  }

  for (const pv of opts.pivots) {
    opts.onProgress?.(`Сводная: ${pv.title}…`)
    const d = await getChargePivot({
      companyId: opts.companyId, dateFrom: opts.dateFrom, dateTo: opts.dateTo,
      rows: pv.rows, cols: pv.cols, metric: pv.metric,
    })
    const ws = wb.addWorksheet(safeSheet(pv.title, used))
    const corner = PIVOT_DIM_LABEL[pv.rows] + (pv.cols ? ` \ ${PIVOT_DIM_LABEL[pv.cols]}` : '')
    ws.addRow([`${pv.title} — ${PIVOT_METRIC_LABEL[pv.metric ?? 'amount']}`]).font = { bold: true, size: 13 }
    ws.addRow([`Период ${opts.dateFrom} … ${opts.dateTo}`]).font = { italic: true, color: { argb: 'FF888888' } }
    ws.addRow([])
    ws.addRow([corner, ...d.col_labels, 'Итого']).font = { bold: true }
    d.row_labels.forEach((rl, i) => ws.addRow([rl, ...d.matrix[i], d.row_totals[i]]))
    ws.addRow(['Итого', ...d.col_totals, d.grand_total]).font = { bold: true }
    ws.getColumn(1).width = 30
    ws.views = [{ state: 'frozen', xSplit: 1, ySplit: 4 }]
    if (d.truncated.rows || d.truncated.cols) {
      const w = ws.addRow([`⚠ Свёрнуто в «Прочие»: строк ${d.truncated.rows}, столбцов ${d.truncated.cols}.`])
      w.font = { italic: true, color: { argb: 'FFB8760A' } }
    }
  }

  opts.onProgress?.('Формирование файла…')
  const buf = await wb.xlsx.writeBuffer()
  saveAs(new Blob([buf], { type: XLSX_MIME }), `${fileBase(opts.title)}.xlsx`)
}
