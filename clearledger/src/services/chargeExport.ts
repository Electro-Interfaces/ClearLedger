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
import { exportDateStamp } from '@/lib/exportDate'
import { showCell } from '@/components/report-kit/format'
import {
  getChargePivot, getChargeSessionRows, getChargeNewClientsList,
  type ChargePivotDim, type ChargeMetric, type ChargeSessionRow, type ChargeNewClientRow,
} from './analyticsService'

const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
let pdfFonts: Promise<Record<string, string>> | undefined

function loadPdfFonts(): Promise<Record<string, string>> {
  pdfFonts ??= fetch(`${import.meta.env.BASE_URL}pdfmake/vfs_fonts.js`).then(async (response) => {
    if (!response.ok) throw new Error('Не удалось загрузить шрифт PDF')
    // Локальный файл поставки содержит JSON-словарь TTF. Код файла не исполняется.
    const source = await response.text()
    const start = source.indexOf('{'), end = source.indexOf('};', start)
    const fonts = JSON.parse(source.slice(start, end + 1)) as Record<string, string>
    if (!fonts['Roboto-Regular.ttf'] || !fonts['Roboto-Medium.ttf']) throw new Error('Не найден шрифт PDF')
    return fonts
  }).catch((error) => { pdfFonts = undefined; throw error })
  return pdfFonts
}

function fileBase(title: string): string {
  const date = exportDateStamp()
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
  let bg = 'rgb(255, 255, 255)'
  for (let parent: HTMLElement | null = el; parent; parent = parent.parentElement) {
    const color = getComputedStyle(parent).backgroundColor
    if (color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent') { bg = color; break }
  }
  // Копия раскрывает прокрутку, не меняя положение рабочего экрана.
  const host = document.createElement('div')
  host.style.cssText = 'position:fixed;left:-100000px;top:0;pointer-events:none'
  const clone = el.cloneNode(true) as HTMLElement
  host.appendChild(clone)
  document.body.appendChild(host)
  host.style.width = `${Math.max(el.offsetWidth, el.scrollWidth, ...Array.from(el.querySelectorAll<HTMLElement>('[data-export-expand]')).map((node) => node.scrollWidth))}px`
  clone.style.width = '100%'
  for (const node of clone.querySelectorAll<HTMLElement>('[data-export-ignore],.recharts-tooltip-wrapper')) node.remove()
  for (const node of [clone, ...clone.querySelectorAll<HTMLElement>('[data-export-expand]')]) {
    node.style.maxHeight = 'none'
    node.style.overflow = 'visible'
  }
  try {
    return await toPng(clone, { pixelRatio: 2, backgroundColor: bg, cacheBust: true })
  } finally {
    host.remove()
  }
}

interface Kpi { label: string; value: string; hint: string }
interface Tbl { name: string; columns: string[]; rows: (string | number | null)[][] }

function exportMetadata(root: HTMLElement, title: string, subtitle?: string): string[][] {
  const rows = [['Отчёт', title], ...(subtitle ? [['Общий контур', subtitle]] : []),
    ['Сформировано', new Date().toLocaleString('ru-RU')]]
  for (const node of [root, ...root.querySelectorAll<HTMLElement>('[data-export-meta]')]) {
    const raw = node.getAttribute('data-export-meta')
    if (raw) rows.push(...JSON.parse(raw) as string[][])
  }
  return rows
}

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
        const parsed = JSON.parse(raw) as { columns: string[]; rows: (string | number | null)[][] }
        if (Array.isArray(parsed.columns) && Array.isArray(parsed.rows)) return { name, columns: parsed.columns, rows: parsed.rows }
      } catch { /* fallback ниже */ }
    }
    const columns = Array.from(tbl.querySelectorAll('thead th')).map((th) => th.textContent?.trim() ?? '')
    const rows = Array.from(tbl.querySelectorAll<HTMLTableRowElement>('tbody tr')).map((tr) =>
      Array.from(tr.cells).map((cell) => cell.textContent?.trim() ?? ''))
    return { name, columns, rows }
  }).filter((t) => t.rows.length > 0)
}

function findCharts(root: HTMLElement): HTMLElement[] {
  const charts = Array.from(root.querySelectorAll<HTMLElement>('[data-export-chart], .recharts-wrapper, [data-chart]'))
  return charts.filter(chart => !charts.some(parent => parent !== chart && parent.contains(chart)))
}

export async function exportChargeExcel(el: HTMLElement, title: string, subtitle?: string): Promise<void> {
  if (el.matches('[data-export-state="unavailable"]') || el.querySelector('[data-export-state="unavailable"]')) throw new Error('Дождитесь загрузки данных отчёта')
  const ExcelJS = (await import('exceljs')).default
  const wb = new ExcelJS.Workbook()
  wb.creator = 'TradeLedger'; wb.created = new Date()
  const used = new Set<string>()

  const params = wb.addWorksheet(safeSheet('Параметры', used))
  for (const row of exportMetadata(el, title, subtitle)) params.addRow(row)
  params.getRow(1).font = { bold: true }
  params.columns = [{ width: 28 }, { width: 110 }]
  params.getColumn(2).alignment = { wrapText: true, vertical: 'top' }

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

  // Ленивые листы: списки КОНКРЕТНЫХ новых клиентов по периодам. Данных нет в DOM
  // (они на сервере) — компонент оставляет маркеры [data-export-newclients] с
  // параметрами запроса, экспортёр дотягивает список и строит лист на период.
  const lazySpecs = Array.from(el.querySelectorAll<HTMLElement>('[data-export-newclients]'))
  for (const le of lazySpecs) {
    try {
      const spec = JSON.parse(le.getAttribute('data-export-newclients') ?? '') as {
        companyId: string; from: string; to: string; label: string
        stations?: string[]; regions?: string[]; dim?: string; dimVal?: string
      }
      const res = await getChargeNewClientsList({
        companyId: spec.companyId, dateFrom: spec.from, dateTo: spec.to, limit: 1000,
        stations: spec.stations, regions: spec.regions, dim: spec.dim, dimVal: spec.dimVal,
      })
      if (!res.clients.length) continue
      const ws = wb.addWorksheet(safeSheet(`Новые ${spec.label}`, used))
      ws.addRow([`Новые клиенты · ${spec.label} (${spec.from} — ${spec.to})`]).font = { bold: true, size: 13 }
      ws.addRow([`Всего ${res.count}${res.count > res.clients.length ? ` · в листе первые ${res.clients.length} по выручке` : ''}`])
        .font = { italic: true, color: { argb: 'FF888888' } }
      ws.addRow([])
      const head = ws.addRow(['Клиент', 'Тип', 'Первая сессия', 'Сессий', 'кВт·ч', 'Выручка, ₽', 'ЭЗС'])
      head.font = { bold: true }
      head.eachCell((c) => { c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEFEF' } } })
      res.clients.forEach((c: ChargeNewClientRow) => {
        const row = ws.addRow([c.clientName || c.userId || c.key, c.userType ?? '', c.firstAt ?? '', c.sessions, c.kwh, c.revenue, c.stations])
        row.eachCell((cell) => {
          if (typeof cell.value === 'number') { cell.numFmt = '#,##0.##'; cell.alignment = { horizontal: 'right' } }
        })
      })
      ws.columns = [{ width: 30 }, { width: 6 }, { width: 18 }, { width: 9 }, { width: 10 }, { width: 12 }, { width: 6 }]
      ws.views = [{ state: 'frozen', ySplit: 4 }]
      ws.autoFilter = { from: { row: 4, column: 1 }, to: { row: 4, column: 7 } }
    } catch { /* пропуск листа */ }
  }

  const charts = findCharts(el)
  if (charts.length) {
    const ws = wb.addWorksheet(safeSheet('Графики', used))
    let rowCursor = 0
    for (const c of charts) {
        const png = await snapshot(c)
        const image = new Image()
        await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error('Не удалось подготовить график')); image.src = png })
        const imgId = wb.addImage({ base64: png, extension: 'png' })
        const w = Math.min(920, c.offsetWidth || 640)
        const h = image.height * w / image.width
        ws.addImage(imgId, { tl: { col: 0, row: rowCursor }, ext: { width: w, height: h } })
        rowCursor += Math.ceil(h / 18) + 2
    }
  }

  const buf = await wb.xlsx.writeBuffer()
  saveAs(new Blob([buf], { type: XLSX_MIME }), `${fileBase(title)}.xlsx`)
}

/** Точечная выгрузка списка новых клиентов (кнопка в модалке): один лист. */
export async function exportNewClientsXlsx(
  label: string, count: number, clients: ChargeNewClientRow[],
): Promise<void> {
  const ExcelJS = (await import('exceljs')).default
  const wb = new ExcelJS.Workbook()
  const ws = wb.addWorksheet('Новые клиенты')
  ws.addRow([`Новые клиенты · ${label}`]).font = { bold: true, size: 13 }
  ws.addRow([`Всего ${count}${count > clients.length ? ` · в листе первые ${clients.length} по выручке` : ''}`])
    .font = { italic: true, color: { argb: 'FF888888' } }
  ws.addRow([])
  const head = ws.addRow(['Клиент', 'Тип', 'Первая сессия', 'Сессий', 'кВт·ч', 'Выручка, ₽', 'ЭЗС'])
  head.font = { bold: true }
  clients.forEach((c) => {
    const row = ws.addRow([c.clientName || c.userId || c.key, c.userType ?? '', c.firstAt ?? '', c.sessions, c.kwh, c.revenue, c.stations])
    row.eachCell((cell) => {
      if (typeof cell.value === 'number') { cell.numFmt = '#,##0.##'; cell.alignment = { horizontal: 'right' } }
    })
  })
  ws.columns = [{ width: 30 }, { width: 6 }, { width: 18 }, { width: 9 }, { width: 10 }, { width: 12 }, { width: 6 }]
  ws.views = [{ state: 'frozen', ySplit: 4 }]
  ws.autoFilter = { from: { row: 4, column: 1 }, to: { row: 4, column: 7 } }
  const buf = await wb.xlsx.writeBuffer()
  saveAs(new Blob([buf], { type: XLSX_MIME }), `${fileBase(`Новые клиенты · ${label}`)}.xlsx`)
}

export async function exportChargePdf(el: HTMLElement, title: string, subtitle?: string): Promise<void> {
  if (el.matches('[data-export-state="unavailable"]') || el.querySelector('[data-export-state="unavailable"]')) throw new Error('Дождитесь загрузки данных отчёта')
  const [{ jsPDF }, { default: autoTable }, fonts] = await Promise.all([
    import('jspdf'), import('jspdf-autotable'), loadPdfFonts(),
  ])
  const tables = readTables(el)
  const charts = findCharts(el)
  const wide = tables.some((table) => table.columns.length > 7)
  const doc = new jsPDF({ orientation: wide ? 'landscape' : 'portrait', unit: 'pt', format: 'a4' })
  for (const [file, style] of [['Roboto-Regular.ttf', 'normal'], ['Roboto-Medium.ttf', 'bold']]) {
    doc.addFileToVFS(file, fonts[file]); doc.addFont(file, 'Report', style)
  }
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()
  const margin = 24
  doc.setFont('Report', 'bold'); doc.setFontSize(13)
  const heading = doc.splitTextToSize(title, pageW - margin * 2)
  doc.text(heading, margin, 35)
  autoTable(doc, {
    startY: 40 + heading.length * 15,
    body: exportMetadata(el, title, subtitle).slice(1),
    margin: { top: margin, bottom: 30, left: margin, right: margin },
    theme: 'plain', styles: { font: 'Report', fontSize: 9, cellPadding: 3, overflow: 'linebreak' },
  })
  let y = (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 20
  const kpis = readKpis(el)
  const sections: Tbl[] = [...(kpis.length ? [{ name: 'Показатели', columns: ['Показатель', 'Значение', 'Примечание'], rows: kpis.map((k) => [k.label, k.value, k.hint]) }] : []), ...tables]
  for (const table of sections) {
    if (y > pageH - 80) { doc.addPage(); y = 30 }
    doc.setFont('Report', 'bold'); doc.setFontSize(10)
    doc.text(`${table.name} · строк: ${table.rows.length}`, margin, y)
    autoTable(doc, {
      startY: y + 8, head: [table.columns],
      body: table.rows.map((row) => row.map((value, col) => value == null || value === '' ? '—' : showCell(value, table.columns[col]))),
      margin: { top: margin, bottom: 30, left: margin, right: margin },
      theme: 'grid', styles: { font: 'Report', fontSize: 8, cellPadding: 3, overflow: 'linebreak' },
      headStyles: { font: 'Report', fontStyle: 'bold', fillColor: [238, 240, 246], textColor: [25, 32, 45] },
      columnStyles: Object.fromEntries(table.columns.flatMap((_, col) => table.rows.some((row) => typeof row[col] === 'number') ? [[col, { halign: 'right' as const }]] : [])),
    })
    y = (doc as typeof doc & { lastAutoTable: { finalY: number } }).lastAutoTable.finalY + 20
  }
  // Отдельная страница на график: масштаб по всей ширине/высоте, без обрезки
  // вложенных прокруток. Табличные данные уже содержат все строки выше.
  for (const chart of charts) {
    const png = await snapshot(chart)
    const img = new Image()
    await new Promise<void>((resolve, reject) => { img.onload = () => resolve(); img.onerror = () => reject(new Error('Не удалось подготовить график')); img.src = png })
    doc.addPage()
    doc.setFont('Report', 'bold'); doc.setFontSize(10)
    doc.text(doc.splitTextToSize(chart.getAttribute('data-export-name') || title, pageW - margin * 2), margin, 35)
    const scale = Math.min((pageW - margin * 2) / img.width, (pageH - 90) / img.height)
    doc.addImage(png, 'PNG', margin, 55, img.width * scale, img.height * scale)
  }
  const pages = doc.getNumberOfPages()
  for (let page = 1; page <= pages; page++) {
    doc.setPage(page); doc.setFont('Report', 'normal'); doc.setFontSize(8)
    doc.text(`${page} / ${pages}`, pageW - margin, pageH - 14, { align: 'right' })
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
  ['Выручка ₽', (r) => Number(r.revenue) || 0],
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
    const corner = PIVOT_DIM_LABEL[pv.rows] + (pv.cols ? `  ${PIVOT_DIM_LABEL[pv.cols]}` : '')
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
