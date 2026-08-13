/**
 * Выгрузки раздела «Контрагенты» в Excel.
 *
 * Три вопроса, ради которых из системы уходят в Excel: «дай список с цифрами»,
 * «пришлите сверку» и «покажи все его документы». Пока их нет, человек копирует
 * таблицу с экрана руками — и цифра в письме перестаёт быть цифрой системы.
 *
 * ExcelJS грузится динамически (как в `chargeExport`): библиотека тяжёлая, а
 * выгрузка — редкое действие, класть её в основной чанк незачем.
 */
import { saveAs } from 'file-saver'

import { getAct, getDocs, getCounterpartyStats } from './booksService'

const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const MONEY = '#,##0.00'

function fileName(title: string): string {
  const date = new Date().toISOString().slice(0, 10)
  return `${title.replace(/[\\/:*?"<>|]+/g, ' ').trim()} · ${date}.xlsx`
}

async function workbook() {
  const ExcelJS = (await import('exceljs')).default
  const wb = new ExcelJS.Workbook()
  wb.creator = 'ElsyPlus'
  return wb
}

/** Шапка листа: жирная строка с автофильтром и закреплением — как ждут в Excel. */
function head(ws: any, columns: { header: string; key: string; width: number }[]) {
  ws.columns = columns
  ws.getRow(1).font = { bold: true }
  ws.views = [{ state: 'frozen', ySplit: 1 }]
  ws.autoFilter = {
    from: { row: 1, column: 1 },
    to: { row: 1, column: columns.length },
  }
}

async function save(wb: any, name: string) {
  const buf = await wb.xlsx.writeBuffer()
  saveAs(new Blob([buf], { type: XLSX_MIME }), fileName(name))
}

/**
 * Список контрагентов с оборотами и долгом. Порядок и состав строк задаёт ВЫЗЫВАЮЩИЙ
 * экран: выгружается то, что человек видит после своих фильтров, а не «всё из базы» —
 * иначе выгрузка не совпадает с экраном и ей перестают верить.
 */
export async function exportCounterparties(
  rows: {
    name: string; inn?: string | null; kpp?: string | null; contracts: number
    sales: number; purchases: number; receivable: number; payable: number
    docs: number; lastDoc?: string | null
  }[],
  title = 'Контрагенты',
) {
  const wb = await workbook()
  const ws = wb.addWorksheet('Контрагенты')
  head(ws, [
    { header: 'Контрагент', key: 'name', width: 42 },
    { header: 'ИНН', key: 'inn', width: 14 },
    { header: 'КПП', key: 'kpp', width: 12 },
    { header: 'Договоров', key: 'contracts', width: 11 },
    { header: 'Продажи', key: 'sales', width: 16 },
    { header: 'Закупки', key: 'purchases', width: 16 },
    { header: 'Нам должен', key: 'receivable', width: 16 },
    { header: 'Мы должны', key: 'payable', width: 16 },
    { header: 'Документов', key: 'docs', width: 12 },
    { header: 'Последний документ', key: 'lastDoc', width: 18 },
  ])
  rows.forEach((r) => ws.addRow(r))
  ;['sales', 'purchases', 'receivable', 'payable'].forEach((k) => {
    ws.getColumn(k).numFmt = MONEY
  })
  await save(wb, title)
}

/** Тот же список, но данные берём с сервера (когда экран их не держит). */
export async function exportCounterpartiesFromApi(companyId: string) {
  const { rows } = await getCounterpartyStats(companyId)
  await exportCounterparties(rows)
}

/**
 * Акт сверки. Итоги — по оборотам с субконто (тот же источник, что «Взаиморасчёты»
 * и сальдо), документы идут расшифровкой: они могут не покрыть оборот целиком —
 * зачёты и корректировки приходят проводками без документа.
 */
export async function exportAct(
  companyId: string, counterpartyId: string, period?: { from?: string; to?: string },
) {
  const act = await getAct(companyId, counterpartyId, period)
  const wb = await workbook()
  const ws = wb.addWorksheet('Акт сверки')

  ws.addRow([`Акт сверки взаиморасчётов с ${act.counterparty.name}`]).font = { bold: true, size: 13 }
  ws.addRow([`ИНН ${act.counterparty.inn ?? '—'}`
    + (act.counterparty.kpp ? ` / КПП ${act.counterparty.kpp}` : '')])
  ws.addRow([`Период: ${act.periodFrom ?? 'с начала'} — ${act.periodTo ?? 'по сегодня'}`])
  ws.addRow([act.note]).font = { italic: true, size: 9 }

  if (act.sections.length === 0) ws.addRow(['Движения по расчётам нет'])

  for (const sec of act.sections) {
    ws.addRow([])
    ws.addRow([sec.title]).font = { bold: true }
    ws.addRow([`Сальдо на начало: ${sec.opening.toFixed(2)} ₽`])
    ws.addRow(['Месяц', 'Оборот Дт', 'Оборот Кт', 'Сальдо']).font = { bold: true }
    sec.months.forEach((m) => ws.addRow([m.month, m.debit || null, m.credit || null, m.saldo]))
    const t = ws.addRow(['Итого', sec.debitTotal, sec.creditTotal, sec.closing])
    t.font = { bold: true }
    ws.addRow([`Сальдо на конец: ${sec.closing.toFixed(2)} ₽`
      + (sec.kind === 'receivable' ? ' — задолженность покупателя' : ' — наша задолженность')])

    if (sec.docs.length) {
      ws.addRow([])
      ws.addRow([`Расшифровка документами (${sec.docs.length})`]).font = { bold: true }
      ws.addRow(['Дата', 'Документ', 'Номер', 'Сумма']).font = { bold: true }
      sec.docs.forEach((d) => ws.addRow([d.date, d.label, d.number, d.amount]))
      const sum = sec.docs.reduce((s, d) => s + d.amount, 0)
      ws.addRow(['Итого документов', '', '', sum]).font = { bold: true }
    }
  }

  ws.getColumn(1).width = 14
  ws.getColumn(2).width = 34
  ws.getColumn(3).width = 20
  ws.getColumn(4).width = 18
  ;[2, 3, 4].forEach((i) => { ws.getColumn(i).numFmt = MONEY })
  ws.getColumn(2).numFmt = MONEY

  await save(wb, `Акт сверки · ${act.counterparty.name}`)
}

/** Реестр документов контрагента — то, чем подтверждают строки акта. */
export async function exportCounterpartyDocs(
  counterpartyName: string,
  docs: { date: string; label: string; number: string; amount: number; vat: number
          contract?: string | null; periodStatus?: string }[],
) {
  const wb = await workbook()
  const ws = wb.addWorksheet('Документы')
  head(ws, [
    { header: 'Дата', key: 'date', width: 12 },
    { header: 'Вид документа', key: 'label', width: 32 },
    { header: 'Номер', key: 'number', width: 18 },
    { header: 'Договор', key: 'contract', width: 30 },
    { header: 'Сумма', key: 'amount', width: 16 },
    { header: 'НДС', key: 'vat', width: 14 },
    { header: 'Период', key: 'periodStatus', width: 12 },
  ])
  docs.forEach((d) => ws.addRow({
    ...d,
    contract: d.contract ?? '',
    periodStatus: d.periodStatus === 'closed' ? 'закрыт' : 'открыт',
  }))
  ;['amount', 'vat'].forEach((k) => { ws.getColumn(k).numFmt = MONEY })
  await save(wb, `Документы · ${counterpartyName}`)
}

/** Реестр документов пространства за период — общий, с фильтрами вызывающего экрана. */
export async function exportDocsRegistry(
  companyId: string, period?: { from?: string; to?: string }, docType?: string,
) {
  const { rows } = await getDocs(companyId, docType, period)
  const wb = await workbook()
  const ws = wb.addWorksheet('Реестр')
  head(ws, [
    { header: 'Дата', key: 'date', width: 12 },
    { header: 'Вид документа', key: 'label', width: 32 },
    { header: 'Номер', key: 'number', width: 18 },
    { header: 'Контрагент', key: 'counterparty', width: 40 },
    { header: 'ИНН', key: 'inn', width: 14 },
    { header: 'Сумма', key: 'amount', width: 16 },
    { header: 'НДС', key: 'vat', width: 14 },
    { header: 'Строк', key: 'lines', width: 8 },
  ])
  rows.forEach((r) => ws.addRow(r))
  ;['amount', 'vat'].forEach((k) => { ws.getColumn(k).numFmt = MONEY })
  await save(wb, 'Реестр документов')
}
