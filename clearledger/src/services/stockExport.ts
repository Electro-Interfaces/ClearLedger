/**
 * Чистовая выгрузка остатков магазина — книга для сверки и пересчёта.
 *
 * Плоская таблица отвечает на «покажи данные», а товароведу нужен рабочий
 * документ: с чего начать, что нести к полке, куда вписать факт. Поэтому книга:
 *
 *   Сводка          — сколько чего и где непорядок; с неё начинают
 *   Требуют решения — минусы, позиции без цены и без себестоимости
 *   Остатки         — весь отбор; лист на станцию, когда их несколько
 *
 * Колонка ФАКТ пустая: книга печатается или заполняется прямо в Excel, а
 * дальше пересчёт проводится на станции (там факт становится остатком).
 * Колонка GUID нужна именно для этого — по ней строка возвращается к карточке.
 *
 * ExcelJS уже в зависимостях (см. chargeExport) — своего генератора не заводим.
 */
import type { StoreStockItem } from './storeService'

export interface StockExportInput {
  items: StoreStockItem[]
  /** Что именно выгружаем — попадёт в шапку сводки. */
  scopeLabel: string
  snapshotAt?: string | null
  summary?: {
    sku_count: number; positive: number; negative: number
    retail_value_positive: number; cost_value: number
    costed_count: number; margin_value: number
    marked_count: number; units_positive: number
  }
}

const money = (v: number | null | undefined) => (v == null ? '' : Math.round(v * 100) / 100)
const num = (v: number | null | undefined) => (v == null || v === 0 ? '' : v)

/** Почему позицию нельзя просто пересчитать и забыть. */
function проблема(i: StoreStockItem): string {
  if (i.negative) return 'минус в учёте — продажи опередили приёмку'
  if (i.qty > 0 && (i.retail_price == null || i.retail_price === 0)) return 'нет цены — не продать'
  if (i.cost_doubt) return `себестоимость под вопросом: ${i.cost_doubt}`
  if (i.qty > 0 && i.cost_amount == null) return 'нет партий — себестоимость неизвестна'
  return ''
}

const ЗАГОЛОВКИ = [
  'Станция', 'Место', 'Наименование', 'Штрихкод', 'Артикул', 'Ед.',
  'Остаток', 'Цена', 'Сумма в рознице', 'Себест. ед.', 'Сумма в закупке',
  'Маркировка', 'Замечание', 'ФАКТ', 'GUID',
]

function строка(i: StoreStockItem) {
  return [
    i.station_id ?? '', i.place_name ?? i.place_code ?? '', i.name,
    i.barcode ?? '', i.article ?? '', i.unit ?? '',
    num(i.qty), money(i.retail_price), money(i.retail_value),
    money(i.cost_unit), money(i.cost_amount),
    i.marked ? 'ЧЗ' : '', проблема(i), '', i.guid,
  ]
}

/** Собирает книгу и отдаёт её браузеру файлом. */
export async function exportStockBook(input: StockExportInput): Promise<void> {
  const ExcelJS = (await import('exceljs')).default
  const wb = new ExcelJS.Workbook()
  wb.created = new Date()

  const { items, scopeLabel, snapshotAt, summary } = input
  const проблемные = items.filter((i) => проблема(i) !== '')
  const наПолке = items.filter((i) => i.qty > 0)
  const минусов = items.filter((i) => i.negative).length
  const безЦены = наПолке.filter((i) => i.retail_price == null || i.retail_price === 0).length

  // ── Сводка ──────────────────────────────────────────────────────────────
  const s = wb.addWorksheet('Сводка')
  s.columns = [{ width: 30 }, { width: 20 }, { width: 60 }]
  s.addRow(['Остатки магазина', '', '']).font = { bold: true, size: 14 }
  s.addRow(['Отбор', scopeLabel, ''])
  s.addRow(['Снято', new Date().toLocaleString('ru-RU'), ''])
  if (snapshotAt) s.addRow(['Снимок станции', new Date(snapshotAt).toLocaleString('ru-RU'), ''])
  s.addRow([])
  const шапкаСводки = s.addRow(['Показатель', 'Значение', 'Пояснение'])
  шапкаСводки.font = { bold: true }
  s.addRow(['Позиций в отборе', items.length, 'строк в этой книге'])
  s.addRow(['На полке', наПолке.length, 'остаток больше нуля'])
  s.addRow(['Единиц на полке', summary?.units_positive ?? наПолке.reduce((a, i) => a + i.qty, 0), ''])
  s.addRow(['Стоимость в рознице', money(summary?.retail_value_positive) || '', 'по цене продажи'])
  s.addRow(['Стоимость в закупке', money(summary?.cost_value) || '',
    `посчитана по ${summary?.costed_count ?? 0} позициям с партиями`])
  s.addRow([])
  s.addRow(['Требуют решения', проблемные.length, 'разобрать до пересчёта']).font = { bold: true }
  s.addRow(['  в минусе', минусов, 'продажи опередили приёмку'])
  s.addRow(['  без цены', безЦены, 'лежит, но не продать'])
  s.addRow(['  маркированных', summary?.marked_count ?? items.filter((i) => i.marked).length,
    'нужен код «Честного знака»'])
  s.addRow([])
  s.addRow(['Как пользоваться', '', '']).font = { bold: true }
  s.addRow(['1', 'Разберите лист «Требуют решения»', 'минус и отсутствие цены пересчётом не лечатся'])
  s.addRow(['2', 'Считайте по листам, колонка ФАКТ', 'лист на станцию, если их несколько'])
  s.addRow(['3', 'Пустой ФАКТ — позиция не тронется', '«не посчитали» и «ноль на полке» — разные вещи'])
  s.addRow(['4', 'Пересчёт проводится на станции', 'там факт становится остатком агента'])

  // ── Листы с позициями ───────────────────────────────────────────────────
  const лист = (name: string, rows: StoreStockItem[]) => {
    if (!rows.length) return
    const ws = wb.addWorksheet(name.slice(0, 31))
    ws.columns = [
      { width: 10 }, { width: 18 }, { width: 46 }, { width: 16 }, { width: 14 },
      { width: 7 }, { width: 11 }, { width: 11 }, { width: 15 }, { width: 12 },
      { width: 15 }, { width: 11 }, { width: 34 }, { width: 11 }, { width: 38 },
    ]
    ws.addRow(ЗАГОЛОВКИ).font = { bold: true }
    ws.views = [{ state: 'frozen', ySplit: 1 }]
    ;[...rows].sort((a, b) => a.name.localeCompare(b.name, 'ru')).forEach((i) => ws.addRow(строка(i)))
    ws.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: ЗАГОЛОВКИ.length } }
  }

  лист('Требуют решения', проблемные)

  // Станций может быть много: по листу на каждую — их обходят разные люди.
  // Одна станция в отборе — один лист «Остатки», без лишнего дробления.
  const станции = [...new Set(items.map((i) => i.station_id).filter((v) => v != null))] as number[]
  if (станции.length > 1) {
    станции.sort((a, b) => a - b)
    станции.forEach((st) => лист(`АЗС ${st}`, items.filter((i) => i.station_id === st)))
    const ничьи = items.filter((i) => i.station_id == null)
    лист('Без станции', ничьи)
  } else {
    лист('Остатки', items)
  }

  const buf = await wb.xlsx.writeBuffer()
  const stamp = new Date().toISOString().slice(0, 10)
  const blob = new Blob([buf], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `ostatki-${stamp}.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}
