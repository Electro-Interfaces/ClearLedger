/**
 * Выгрузка реестра «Операций» — Excel и PDF (перенос из «Монитора»,
 * `src/services/operationsExportService.ts`).
 *
 * Обе выгрузки берут ВЕСЬ текущий отбор, а не видимую страницу: реестром
 * отчитываются перед клиентом и поставщиком, а там нужен период целиком.
 * В PDF сверху — шапка периода, итоги и разрезы по топливу и оплатам, затем
 * построчная таблица; ландшафтная ориентация, иначе 14 колонок не помещаются.
 */
import type { FuelTxRow } from './fuelMappingService'
import { loadPdfMake } from '@/utils/pdfMake'

export interface OperationsExportOptions {
  rows: FuelTxRow[]
  dateFrom: string
  dateTo: string
  stationName?: string
}

const STATUS_LABEL: Record<string, string> = {
  completed: 'Завершено', in_progress: 'Выполняется',
  failed: 'Ошибка', pending: 'Ожидание', cancelled: 'Отменено',
}

const num = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const dt = (s: string | null) => (s
  ? new Date(s).toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  : '—')

const payment = (r: FuelTxRow) => r.payment_method ?? r.pay_type_name ?? '—'

/** Итоги по ключу (вид топлива / способ оплаты), по убыванию выручки. */
function groupTotals(rows: FuelTxRow[], key: (r: FuelTxRow) => string) {
  const acc = new Map<string, { liters: number; amount: number }>()
  for (const r of rows) {
    const k = key(r) || '—'
    const e = acc.get(k) ?? { liters: 0, amount: 0 }
    e.liters += r.liters
    e.amount += r.amount
    acc.set(k, e)
  }
  return [...acc.entries()].sort((a, b) => b[1].amount - a[1].amount)
}

export async function exportOperationsToExcel({ rows, dateFrom, dateTo }: OperationsExportOptions) {
  const XLSX = await import('xlsx')
  const sheet = rows.map((r) => ({
    'Чек': r.receipt ?? '',
    'ID операции': r.ext_id,
    'Дата/время': dt(r.dt),
    'АЗС': r.station_name,
    'Смена': r.shift_number ?? '',
    'ТРК': r.pos ?? '',
    'Пистолет': r.nozzle ?? '',
    'Резервуар': r.tank ?? '',
    'Топливо': r.fuel_name ?? '',
    'Оплата': payment(r),
    'Карта': r.card ?? '',
    'Литры': r.liters,
    'Цена, ₽/л': r.price ?? '',
    'Сумма, ₽': r.amount,
    'Масса, кг': r.mass ?? '',
    'Заказ, л': r.order_qty ?? '',
    'Заказ, ₽': r.order_cost ?? '',
    'Статус': STATUS_LABEL[r.status] ?? r.status,
  }))
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(sheet), 'Операции')
  XLSX.writeFile(wb, `operacii_${dateFrom}_${dateTo}.xlsx`)
}

export async function exportOperationsToPdf({ rows, dateFrom, dateTo, stationName }: OperationsExportOptions) {
  const pdfMake = await loadPdfMake()

  const totals = rows.reduce((acc, r) => ({
    liters: acc.liters + r.liters,
    amount: acc.amount + r.amount,
    orderLiters: acc.orderLiters + (r.order_qty ?? 0),
    orderAmount: acc.orderAmount + (r.order_cost ?? 0),
  }), { liters: 0, amount: 0, orderLiters: 0, orderAmount: 0 })

  const byFuel = groupTotals(rows, (r) => r.fuel_name ?? '—')
  const byPayment = groupTotals(rows, payment)

  const head = (text: string, alignment?: string) => ({ text, style: 'tableHeader', alignment })
  const body = [
    [head('Чек'), head('ID'), head('Дата и время'), head('АЗС'), head('Пист.', 'center'), head('Топливо'),
     head('Кол-во, л', 'right'), head('Цена, ₽/л', 'right'), head('Сумма, ₽', 'right'),
     head('Оплата'), head('Карта'), head('POS', 'center'), head('Смена', 'center'),
     head('Заказ, л', 'right'), head('Статус')],
    ...rows.map((r) => [
      { text: r.receipt != null ? String(r.receipt) : '-', style: 'cellMono' },
      { text: String(r.ext_id), style: 'cellMono' },
      { text: dt(r.dt), style: 'cell' },
      { text: r.station_name, style: 'cell' },
      { text: r.nozzle != null ? String(r.nozzle) : '-', style: 'cell', alignment: 'center' },
      { text: r.fuel_name ?? '-', style: 'cell' },
      { text: num(r.liters), style: 'cell', alignment: 'right' },
      { text: r.price != null ? num(r.price) : '-', style: 'cell', alignment: 'right' },
      { text: num(r.amount), style: 'cell', alignment: 'right' },
      { text: payment(r), style: 'cell' },
      { text: r.card ?? '-', style: 'cellMono' },
      { text: r.pos != null ? String(r.pos) : '-', style: 'cell', alignment: 'center' },
      { text: r.shift_number != null ? String(r.shift_number) : '-', style: 'cell', alignment: 'center' },
      { text: r.order_qty ? num(r.order_qty) : '-', style: 'cell', alignment: 'right' },
      { text: STATUS_LABEL[r.status] ?? r.status, style: 'cell' },
    ]),
  ]

  const breakdown = (label: string, data: [string, { liters: number; amount: number }][]) => ({
    width: '*',
    stack: [
      { text: label, style: 'sectionLabel' },
      ...data.map(([name, d]) => ({
        text: `${name}: ${num(d.liters)} л / ${num(d.amount)} ₽`, style: 'summaryDetail',
      })),
    ],
  })

  pdfMake.createPdf({
    info: { title: 'Отчёт по операциям', subject: 'Экспорт операций' },
    pageOrientation: 'landscape',
    pageMargins: [24, 24, 24, 32],
    content: [
      { text: 'Отчёт по операциям', style: 'title' },
      {
        columns: [
          { text: [{ text: 'АЗС: ', bold: true }, stationName || 'Все АЗС'], style: 'infoBlock' },
          {
            text: [{ text: 'Период: ', bold: true }, `${dateFrom} – ${dateTo}`, '\n',
                   { text: 'Сформировано: ', bold: true }, new Date().toLocaleString('ru-RU')],
            style: 'infoBlock', alignment: 'right',
          },
        ],
        columnGap: 12, margin: [0, 0, 0, 12],
      },
      {
        columns: [
          { text: [{ text: 'Операций: ', bold: true }, String(rows.length)], style: 'summaryBlock' },
          { text: [{ text: 'Отпуск, л: ', bold: true }, num(totals.liters)], style: 'summaryBlock', alignment: 'center' },
          { text: [{ text: 'Сумма, ₽: ', bold: true }, num(totals.amount)], style: 'summaryBlock', alignment: 'center' },
          {
            text: [{ text: 'Заказ, л: ', bold: true }, num(totals.orderLiters), '\n',
                   { text: 'Заказ, ₽: ', bold: true }, num(totals.orderAmount)],
            style: 'summaryBlock', alignment: 'right',
          },
        ],
        columnGap: 12, margin: [0, 0, 0, 16],
      },
      {
        columns: [breakdown('Итоги по топливу', byFuel), breakdown('Итоги по оплатам', byPayment)],
        columnGap: 18, margin: [0, 0, 0, 16],
      },
      {
        table: { headerRows: 1, widths: [34, 42, 72, 70, 24, 48, 40, 40, 48, 52, 48, 22, 24, 38, 44], body },
        layout: {
          fillColor: (rowIndex: number) => (rowIndex === 0 ? '#1f2937' : rowIndex % 2 === 0 ? '#f3f4f6' : '#ffffff'),
          hLineColor: () => '#d1d5db',
          vLineColor: () => '#d1d5db',
          paddingLeft: () => 6, paddingRight: () => 6, paddingTop: () => 5, paddingBottom: () => 5,
        },
      },
    ],
    styles: {
      title: { fontSize: 18, bold: true, margin: [0, 0, 0, 12], color: '#111827' },
      infoBlock: { fontSize: 10, color: '#111827' },
      summaryBlock: { fontSize: 11, color: '#111827' },
      sectionLabel: { fontSize: 11, bold: true, color: '#111827', margin: [0, 0, 0, 4] },
      summaryDetail: { fontSize: 10, color: '#374151', margin: [0, 0, 0, 2] },
      tableHeader: { bold: true, fontSize: 10, color: '#f9fafb' },
      cell: { fontSize: 9, color: '#111827', lineHeight: 1.2 },
      cellMono: { fontSize: 8, color: '#111827', lineHeight: 1.2 },
    },
    defaultStyle: { font: 'Roboto' },
  }).download(`operacii_${dateFrom}_${dateTo}.pdf`)
}
