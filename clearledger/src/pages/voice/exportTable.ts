/**
 * Выгрузка таблиц экрана в CSV и Excel — той же выборки, что на экране, со строкой
 * фильтров первой строкой. Номеров здесь нет: статистика узла обезличена.
 *
 * CSV — с точкой с запятой и BOM: так его без мастера импорта открывает русский
 * Excel. Excel собираем через exceljs, загружаемый только по нажатию кнопки.
 */

export type Ячейка = string | number | null | undefined

export interface Лист {
  имя: string
  строки: Ячейка[][]
}

function скачать(blob: Blob, имя: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = имя
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const вCSV = (v: Ячейка) => {
  if (v == null) return ''
  const s = typeof v === 'number' ? String(v).replace('.', ',') : v
  return /[";\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
}

export function скачатьCSV(файл: string, листы: Лист[]) {
  const текст = листы
    .map(л => [[л.имя], ...л.строки].map(r => r.map(вCSV).join(';')).join('\r\n'))
    .join('\r\n\r\n')
  скачать(new Blob(['﻿', текст], { type: 'text/csv;charset=utf-8' }), `${файл}.csv`)
}

export async function скачатьExcel(файл: string, листы: Лист[]) {
  const { Workbook } = await import('exceljs')
  const wb = new Workbook()
  for (const л of листы) {
    // Имя листа Excel — до 31 знака и без []:*?/\
    const ws = wb.addWorksheet(л.имя.replace(/[[\]:*?/\\]/g, ' ').slice(0, 31))
    ws.addRows(л.строки.map(r => r.map(v => (v == null ? null : v))))
    ws.getRow(1).font = { bold: true }
    ws.columns.forEach(c => { c.width = 18 })
  }
  const buf = await wb.xlsx.writeBuffer()
  скачать(new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }), `${файл}.xlsx`)
}
