/**
 * Excel Parser — извлечение данных из .xlsx/.xls/.csv через SheetJS (xlsx).
 * Извлекает текст из всех листов + metadata (кол-во листов, строк, колонок).
 */

import type { ExtractResult } from '../extract'

export async function parseExcel(file: File): Promise<ExtractResult> {
  try {
    const XLSX = await import('xlsx')
    const arrayBuffer = await file.arrayBuffer()
    const workbook = XLSX.read(arrayBuffer, { type: 'array', cellDates: true })

    const metadata: Record<string, string> = {}
    const textParts: string[] = []

    metadata['_excel.sheets'] = String(workbook.SheetNames.length)
    metadata['_excel.sheetNames'] = workbook.SheetNames.join(', ')

    let totalRows = 0

    for (const sheetName of workbook.SheetNames) {
      const sheet = workbook.Sheets[sheetName]
      if (!sheet) continue

      // Извлекаем данные как массив массивов
      const rows: unknown[][] = XLSX.utils.sheet_to_json(sheet, {
        header: 1,
        defval: '',
        blankrows: false,
      })

      if (rows.length === 0) continue

      totalRows += rows.length

      if (workbook.SheetNames.length > 1) {
        textParts.push(`--- Лист: ${sheetName} (${rows.length} строк) ---`)
      }

      // Заголовок (первая строка)
      const header = rows[0]?.map((c) => String(c ?? '').trim()) ?? []

      // Анализируем заголовки для определения типа данных
      analyzeHeaders(header, metadata)

      // Собираем текст из первых 100 строк (для classify)
      const maxRows = Math.min(rows.length, 100)
      for (let i = 0; i < maxRows; i++) {
        const row = rows[i]
        if (!row) continue
        const cells = row
          .map((c) => formatCell(c))
          .filter((c) => c.length > 0)
        if (cells.length > 0) {
          textParts.push(cells.join(' | '))
        }
      }

      if (rows.length > 100) {
        textParts.push(`... ещё ${rows.length - 100} строк`)
      }

      // Извлекаем ключевые поля из данных
      extractFieldsFromRows(rows, header, metadata)
    }

    metadata['_excel.totalRows'] = String(totalRows)

    return { text: textParts.join('\n'), metadata }
  } catch (err) {
    console.error('Excel parse error:', err)
    return {
      text: '',
      metadata: { _extractError: `Excel парсер: ${String(err)}` },
    }
  }
}

/** Парсинг CSV — тоже через SheetJS для единообразия */
export async function parseCsv(file: File): Promise<ExtractResult> {
  try {
    const XLSX = await import('xlsx')
    const text = await file.text()
    const workbook = XLSX.read(text, { type: 'string' })

    // Дальше как Excel, но всегда один лист
    const sheetName = workbook.SheetNames[0]
    if (!sheetName) return { text, metadata: {} }

    const sheet = workbook.Sheets[sheetName]
    if (!sheet) return { text, metadata: {} }

    const rows: unknown[][] = XLSX.utils.sheet_to_json(sheet, {
      header: 1,
      defval: '',
      blankrows: false,
    })

    const metadata: Record<string, string> = {
      '_excel.totalRows': String(rows.length),
      '_excel.sheets': '1',
    }
    const textParts: string[] = []

    const header = rows[0]?.map((c) => String(c ?? '').trim()) ?? []
    analyzeHeaders(header, metadata)

    const maxRows = Math.min(rows.length, 100)
    for (let i = 0; i < maxRows; i++) {
      const row = rows[i]
      if (!row) continue
      const cells = row
        .map((c) => formatCell(c))
        .filter((c) => c.length > 0)
      if (cells.length > 0) {
        textParts.push(cells.join(' | '))
      }
    }

    if (rows.length > 100) {
      textParts.push(`... ещё ${rows.length - 100} строк`)
    }

    extractFieldsFromRows(rows, header, metadata)

    return { text: textParts.join('\n'), metadata }
  } catch (err) {
    console.error('CSV parse error:', err)
    // Fallback: plain text
    try {
      const raw = await file.text()
      return { text: raw, metadata: { _extractError: `CSV парсер: ${String(err)}` } }
    } catch {
      return { text: '', metadata: { _extractError: `CSV парсер: ${String(err)}` } }
    }
  }
}

// ---- Helpers ----

function formatCell(val: unknown): string {
  if (val === null || val === undefined || val === '') return ''
  if (val instanceof Date) {
    return val.toLocaleDateString('ru-RU')
  }
  return String(val).trim()
}

/** Анализ заголовков для определения типа данных */
function analyzeHeaders(header: string[], metadata: Record<string, string>) {
  const lower = header.map((h) => h.toLowerCase())

  // Определяем тип таблицы по заголовкам
  const patterns: Record<string, RegExp[]> = {
    'реестр транзакций': [/транзакц/, /терминал/, /карт/],
    'остатки': [/остат/, /резервуар/, /ёмкость|емкость/],
    'поставки': [/поставк|поставщик/, /объём|объем|литр|тонн/],
    'z-отчёт': [/смен/, /ккт|касс/, /итого/],
    'реестр документов': [/номер.*док|№.*док/, /дата.*док/, /сумм/],
    'выписка': [/дебет/, /кредит/, /сальдо/],
    'акт сверки': [/сверк/, /контрагент|организац/, /период/],
  }

  for (const [type, regexes] of Object.entries(patterns)) {
    const matches = regexes.filter((rx) => lower.some((h) => rx.test(h)))
    if (matches.length >= 2) {
      metadata['_excel.detectedType'] = type
      break
    }
  }

  metadata['_excel.columns'] = String(header.length)
  if (header.length > 0) {
    metadata['_excel.headerSample'] = header.slice(0, 5).join(', ')
  }
}

/** Извлечь ключевые поля из данных таблицы */
function extractFieldsFromRows(
  rows: unknown[][],
  header: string[],
  metadata: Record<string, string>,
) {
  if (rows.length < 2) return

  const lower = header.map((h) => h.toLowerCase())

  // Ищем колонки по шаблону
  const colIdx = {
    docNumber: findCol(lower, /номер|№|num/),
    docDate: findCol(lower, /дата|date/),
    amount: findCol(lower, /сумм|итого|amount|всего/),
    inn: findCol(lower, /инн|inn/),
    counterparty: findCol(lower, /контрагент|организац|поставщик|покупатель|наименование/),
  }

  // Берём значения из первой строки данных (row[1])
  const dataRow = rows[1] as unknown[] | undefined
  if (!dataRow) return

  for (const [key, idx] of Object.entries(colIdx)) {
    if (idx === -1 || !dataRow[idx]) continue
    const val = formatCell(dataRow[idx])
    if (val && !metadata[key]) {
      metadata[key] = val
    }
  }

  // Итого: ищем последнюю строку со словом "итого"
  for (let i = rows.length - 1; i >= Math.max(1, rows.length - 10); i--) {
    const row = rows[i] as unknown[] | undefined
    if (!row) continue
    const firstCell = String(row[0] ?? '').toLowerCase()
    if (/итого|всего|total/i.test(firstCell)) {
      // Берём сумму из колонки amount или последней числовой
      if (colIdx.amount !== -1 && row[colIdx.amount]) {
        metadata['amount'] = formatCell(row[colIdx.amount])
      }
      break
    }
  }
}

function findCol(headers: string[], pattern: RegExp): number {
  return headers.findIndex((h) => pattern.test(h))
}
