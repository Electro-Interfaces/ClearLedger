/**
 * Выгрузки раздела «Товародвижение» — Excel и PDF, одинаково на всех пунктах.
 *
 * Раньше выгрузка жила внутри вкладок: книга остатков умела Excel, «Причины» и
 * приёмка — свой, а «Замечания» и «Расхождения» не умели ничего, PDF не умел
 * никто. Менеджер не мог унести с экрана то, что видит, а бухгалтеру нужен
 * именно печатный лист с шапкой периода.
 *
 * Данные берём теми же сервисами, что и экраны: запрос уже в кеше react-query,
 * так что выгрузка мгновенная, а цифры в файле гарантированно те же, что на
 * экране (собирать их отдельным путём — верный способ разойтись).
 *
 * PDF через pdfMake: у jsPDF-шрифтов нет кириллицы (см. `utils/pdfMake.ts`).
 */
import { loadPdfMake } from '@/utils/pdfMake'
import {
  getFuelBalance, getReceiptAnalysis, getTankLedger, getVarianceDiagnostics,
  type FuelBalanceResponse, type ReceiptAnalysisResponse,
  type TankLedgerResponse, type VarianceDiagnosticsResponse,
} from '@/services/analyticsService'

export type GoodsView = 'balance' | 'variances' | 'intake' | 'inventory'

export interface GoodsExportParams {
  companyId: string
  dateFrom: string
  dateTo: string
  stationCodes: number[]
  fuelCodes: number[]
  /** Подпись контура в шапке файла — что именно выгружено. */
  scopeLabel: string
}

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

const L = (v: number | null | undefined) => (v == null ? '—' : `${nf0.format(v)} л`)
const r1 = (v: number | null | undefined) => (v == null ? '' : Math.round(v * 10) / 10)
const gapWord = (v: number | null | undefined) =>
  v == null ? '—' : Math.abs(v) < 0.5 ? 'сходится'
    : `${nf0.format(Math.abs(v))} л ${v > 0 ? 'недостача' : 'излишек'}`
const dt = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleDateString('ru-RU') : ''

const BREAK_LABEL: Record<string, string> = {
  delivery: 'слив между сменами', renumber: 'перенумерация', gap: 'пауза между сменами',
  reversal: 'возврат', fuel_change: 'смена топлива', book_reset: 'сброс книги',
  pulled_to_fact: 'списано на станции', manual: 'ручная правка',
  unexplained: 'требует разбора', fact_suspect: 'прибор неисправен',
}

const VIEW_TITLE: Record<GoodsView, string> = {
  balance: 'Контроль топливного баланса',
  variances: 'Расхождения книги и факта',
  intake: 'Приёмка и сливы',
  inventory: 'Инвентаризация резервуаров',
}

const FILE_BASE: Record<GoodsView, string> = {
  balance: 'kontrol_balansa', variances: 'rashozhdeniya',
  intake: 'priyomka_slivy', inventory: 'inventarizaciya',
}

/** Данные под выгрузку: грузим ровно то, что нужно виду. */
async function collect(view: GoodsView, p: GoodsExportParams) {
  const base = {
    companyId: p.companyId, dateFrom: p.dateFrom, dateTo: p.dateTo,
    stationCodes: p.stationCodes, fuelCodes: p.fuelCodes,
  }
  if (view === 'intake') return { receipts: await getReceiptAnalysis(base) }
  if (view === 'variances') {
    const [ledger, diag] = await Promise.all([getTankLedger(base), getVarianceDiagnostics(base)])
    return { ledger, diag }
  }
  // Инвентаризация и баланс опираются на книгу резервуаров; для баланса нужен ещё
  // периодный свод (АЗС × топливо) — он считается другой формулой.
  const [ledger, balance] = await Promise.all([
    getTankLedger(base),
    getFuelBalance({ ...base, groupBy: 'station_fuel' }),
  ])
  return { ledger, balance }
}

// ─────────────────────────── Excel ───────────────────────────

export async function exportGoodsXlsx(view: GoodsView, p: GoodsExportParams) {
  const XLSX = await import('xlsx')
  const data = await collect(view, p)
  const wb = XLSX.utils.book_new()

  const head = [
    [VIEW_TITLE[view]],
    [`Период: ${dt(p.dateFrom)} — ${dt(p.dateTo)}`, `Контур: ${p.scopeLabel}`],
    [`Сформировано: ${new Date().toLocaleString('ru-RU')}`],
    [],
  ]
  const sheet = (rows: Record<string, unknown>[], name: string, widths?: number[]) => {
    if (rows.length === 0) return
    const ws = XLSX.utils.aoa_to_sheet(head)
    XLSX.utils.sheet_add_json(ws, rows, { origin: `A${head.length + 1}` })
    ws['!cols'] = (widths ?? Object.keys(rows[0]).map(() => 14)).map((wch) => ({ wch }))
    XLSX.utils.book_append_sheet(wb, ws, name)
  }

  if ('receipts' in data && data.receipts) {
    const d = data.receipts as ReceiptAnalysisResponse
    sheet(d.rows.map((r) => ({
      'ТТН': r.ttn, 'Дата': dt(r.date), 'АЗС': r.station_name, 'Резервуар': r.tank ?? '',
      'Топливо': r.fuel_name, 'Поставщик': r.supplier,
      'Документ, кг': r1(r.doc_mass_kg), 'Факт, кг': r1(r.fact_mass_kg),
      'Отклонение, кг': r1(r.diff_mass_kg), 'Отклонение, %': r.diff_pct ?? '',
      'Документ, л': r1(r.doc_volume_l), 'Факт, л': r1(r.fact_volume_l),
      'Плотность док.': r.density_doc ?? '', 'Плотность факт': r.density_fact ?? '',
      'Темп. док.': r.temp_doc ?? '', 'Темп. факт': r.temp_fact ?? '',
      'Причина': r.klass_title,
    })), 'Ошибки слива', [12, 11, 14, 10, 12, 20, ...Array(11).fill(13)])
    sheet(d.by_station.map((s) => ({
      'АЗС': s.station_name, 'ТТН': s.ttn, 'Документ, кг': r1(s.doc_kg),
      'Отклонение, кг': r1(s.diff_kg),
      'Недоливов': s.shortfall, 'Переливов': s.surplus,
      'Без замера': s.not_measured, 'Сорванный замер': s.broken_measure,
    })), 'По АЗС')
  }

  if ('ledger' in data && data.ledger) {
    const d = data.ledger as TankLedgerResponse
    sheet(d.tanks.map((t) => ({
      'АЗС': t.station_name, 'Резервуар': t.tank_number, 'Топливо': t.fuel_name,
      'Смен': t.shifts,
      'Книга нач., л': r1(t.book_start), 'Приход, л': r1(t.receipts), 'Отпуск, л': r1(t.sales),
      'Книга кон., л': r1(t.book_end), 'Замер, л': r1(t.fact_end),
      'Книга − факт, л': r1(t.fact_gap), 'Состояние': gapWord(t.fact_gap),
      '% от отпуска': t.fact_gap_pct ?? '',
      'Было на входе, л': r1(t.fact_gap_opening),
      'Оформлено ведомостями, л': r1(t.inventory_adjustment),
      'К разбору, л': r1(t.fact_gap_open),
      'Ведомость от': t.inventory_date ?? '',
      'Арифметика': t.arithmetic_breaks, 'Стык': t.continuity_breaks,
      'Расхождение замера': t.fact_breaks,
      'Учёт начинался заново': t.chain_resets ?? 0,
      'Недостоверных замеров': t.suspect_facts ?? 0,
      'Вместимость по книге, л': t.capacity_hint ?? '',
    })), 'По резервуарам', [14, 10, 10, 7, ...Array(18).fill(15)])

    sheet(d.issues.map((i) => ({
      'Тип': i.type === 'fact_suspect' ? 'замер' : i.type === 'arithmetic' ? 'арифметика'
        : i.type === 'fuel_change' ? 'смена топлива' : 'стык смен',
      'Причина': i.kind ? (BREAK_LABEL[i.kind] ?? i.kind) : '',
      'АЗС': i.station_name, 'Резервуар': i.tank_number, 'Топливо': i.fuel_name,
      'Смена': i.shift_number, 'Дата': dt(i.date),
      'Расхождение, л': i.gap_liters == null ? 'не измерено' : r1(i.gap_liters),
      'Что не сходится': i.detail, 'Пояснение': i.reason ?? '',
    })), 'Замечания', [14, 20, 14, 10, 10, 8, 11, 14, 46, 60])

    // Журнал по сменам — полная лента, по ней и разбирают.
    sheet(d.rows.map((r) => ({
      'АЗС': r.station_name, 'Резервуар': r.tank_number, 'Топливо': r.fuel_name,
      'Смена': r.shift_number, 'Дата': dt(r.opened_at),
      'Книга нач., л': r1(r.book_start), 'Приход, л': r1(r.receipts),
      'Отпуск, л': r1(r.sales), 'Книга кон., л': r1(r.book_end),
      'Счёт (арифметика), л': r1(r.arithmetic_gap),
      'Стык, л': r1(r.continuity_gap),
      'Причина разрыва': r.continuity_kind ? (BREAK_LABEL[r.continuity_kind] ?? r.continuity_kind) : '',
      'Пояснение разрыва': r.continuity_reason ?? '',
      'Учёт начат заново': r.chain_break ? 'да' : '',
      'Замер нач., л': r1(r.fact_start), 'Замер кон., л': r1(r.fact_end),
      'Показание прибора, л': r.fact_suspect ? r1(r.fact_raw) : '',
      'Прибор недостоверен': r.fact_suspect ? 'да' : '',
      'Расхождение нач., л': r1(r.fact_gap_start), 'Расхождение кон., л': r1(r.fact_gap),
      'Изменение за смену, л': r1(r.fact_gap_delta),
      'Плотность': r.density_end ?? '', 'Темп., °C': r1(r.temp_end),
      'Уровень, мм': r1(r.level_end), 'Вода, л': r1(r.water_volume),
    })), 'Журнал по сменам', [14, 10, 10, 8, 11, ...Array(20).fill(14)])
  }

  if ('diag' in data && data.diag) {
    const d = data.diag as VarianceDiagnosticsResponse
    sheet(d.tanks.map((t) => ({
      'АЗС': t.station_name, 'Резервуар': t.tank_number, 'Топливо': t.fuel_name,
      'Природа расхождения': t.nature_title,
      'Тренд, л/смену': t.trend_per_shift, 'Накоплено за период, л': r1(t.accumulated),
      'Скачок, л': r1(t.jump_liters), 'В какой смене': t.jump_shift ?? '',
      'Скачок при сливе': t.jump_on_receipt ? 'да' : '',
      'Доля температурных смен': t.temperature_share,
      'Разброс (σ), л': r1(t.std_gap), 'Расхождение сейчас, л': r1(t.last_gap),
      'Смен': t.shifts,
    })), 'Причины расхождений', [14, 10, 10, 26, ...Array(9).fill(15)])
  }

  if ('balance' in data && data.balance) {
    const d = data.balance as FuelBalanceResponse
    sheet(d.lines.map((l) => ({
      'Разрез': l.label,
      'Начальный остаток, л': r1(l.balance_start_liters),
      'Поступления, л': r1(l.receipts_liters), 'Реализация, л': r1(l.sales_liters),
      'Конечный остаток, л': r1(l.balance_end_liters),
      'Невязка книги, л': r1(l.variance_liters), 'Невязка, % от реализации': l.variance_pct,
      'Резервуаров': l.tanks_count, 'Разрывов стыка': l.continuity_breaks,
    })), 'АЗС × топливо', [24, ...Array(8).fill(16)])
  }

  XLSX.writeFile(wb, `${FILE_BASE[view]}_${p.dateFrom}_${p.dateTo}.xlsx`)
}

// ─────────────────────────── PDF ───────────────────────────

const TH = (text: string, alignment?: string) => ({ text, style: 'th', alignment })
const TD = (text: string | number, alignment?: string) => ({ text: String(text), style: 'td', alignment })

/** Таблица pdfMake с шапкой и зеброй. */
function table(widths: (number | string)[], header: unknown[], body: unknown[][]) {
  return {
    table: { headerRows: 1, widths, body: [header, ...body] },
    layout: {
      fillColor: (i: number) => (i === 0 ? '#1f2937' : i % 2 === 0 ? '#f3f4f6' : '#ffffff'),
      hLineColor: () => '#d1d5db', vLineColor: () => '#d1d5db',
      paddingLeft: () => 5, paddingRight: () => 5, paddingTop: () => 4, paddingBottom: () => 4,
    },
    margin: [0, 0, 0, 12],
  }
}

export async function exportGoodsPdf(view: GoodsView, p: GoodsExportParams) {
  const pdfMake = await loadPdfMake()
  const data = await collect(view, p)
  const content: Record<string, unknown>[] = [
    { text: VIEW_TITLE[view], style: 'title' },
    {
      columns: [
        { text: [{ text: 'Период: ', bold: true }, `${dt(p.dateFrom)} — ${dt(p.dateTo)}`], style: 'info' },
        { text: [{ text: 'Контур: ', bold: true }, p.scopeLabel], style: 'info', alignment: 'center' },
        { text: [{ text: 'Сформировано: ', bold: true }, new Date().toLocaleString('ru-RU')], style: 'info', alignment: 'right' },
      ],
      columnGap: 10, margin: [0, 0, 0, 12],
    },
  ]

  if ('balance' in data && data.balance) {
    const t = (data.balance as FuelBalanceResponse).totals
    content.push({
      columns: [
        { text: [{ text: 'Начальный остаток\n', bold: true }, L(t.balance_start_liters)], style: 'kpi' },
        { text: [{ text: 'Поступления\n', bold: true }, L(t.receipts_liters)], style: 'kpi' },
        { text: [{ text: 'Реализация\n', bold: true }, L(t.sales_liters)], style: 'kpi' },
        { text: [{ text: 'Конечный остаток\n', bold: true }, L(t.balance_end_liters)], style: 'kpi' },
        { text: [{ text: 'Невязка книги\n', bold: true }, L(t.variance_liters)], style: 'kpi' },
      ],
      columnGap: 8, margin: [0, 0, 0, 12],
    })
  }

  if ('ledger' in data && data.ledger) {
    const d = data.ledger as TankLedgerResponse
    content.push({
      columns: [
        { text: [{ text: 'Книга на конец\n', bold: true }, L(d.totals.book_end)], style: 'kpi' },
        { text: [{ text: 'Замер\n', bold: true }, L(d.totals.fact_end)], style: 'kpi' },
        { text: [{ text: 'Книга − факт\n', bold: true }, gapWord(d.totals.fact_gap)], style: 'kpi' },
        { text: [{ text: 'К разбору\n', bold: true }, gapWord(d.totals.fact_gap_open)], style: 'kpi' },
        { text: [{ text: 'Замечаний\n', bold: true },
                 `арифметика ${d.totals.arithmetic_breaks} · стык ${d.totals.continuity_breaks} · замер ${d.totals.fact_breaks}`], style: 'kpi' },
      ],
      columnGap: 8, margin: [0, 0, 0, 12],
    })

    content.push({ text: 'По резервуарам', style: 'h2' })
    content.push(table(
      [58, 26, 40, 22, 48, 44, 48, 48, 62, 62],
      [TH('АЗС'), TH('Рез.'), TH('Топливо'), TH('Смен'), TH('Книга кон.', 'right'),
       TH('Замер', 'right'), TH('Приход', 'right'), TH('Отпуск', 'right'),
       TH('Книга − факт', 'right'), TH('К разбору', 'right')],
      d.tanks.map((t) => [
        TD(t.station_name), TD(`№${t.tank_number}`), TD(t.fuel_name), TD(t.shifts, 'right'),
        TD(nf0.format(t.book_end), 'right'), TD(t.fact_end == null ? '—' : nf0.format(t.fact_end), 'right'),
        TD(nf0.format(t.receipts), 'right'), TD(nf0.format(t.sales), 'right'),
        TD(gapWord(t.fact_gap), 'right'), TD(gapWord(t.fact_gap_open), 'right'),
      ]),
    ))

    if (view === 'variances' && d.issues.length > 0) {
      content.push({ text: 'Замечания', style: 'h2', pageBreak: 'before' })
      content.push(table(
        [46, 66, 56, 26, 34, 46, 52, '*'],
        [TH('Тип'), TH('Причина'), TH('АЗС'), TH('Рез.'), TH('Смена'), TH('Дата'),
         TH('Расхождение', 'right'), TH('Что не сходится')],
        d.issues.slice(0, 300).map((i) => [
          TD(i.type === 'fact_suspect' ? 'замер' : i.type === 'arithmetic' ? 'арифметика'
            : i.type === 'fuel_change' ? 'топливо' : 'стык'),
          TD(i.kind ? (BREAK_LABEL[i.kind] ?? i.kind) : '—'),
          TD(i.station_name), TD(`№${i.tank_number}`), TD(`№${i.shift_number}`), TD(dt(i.date)),
          TD(i.gap_liters == null ? 'не измерено' : `${nf1.format(i.gap_liters)} л`, 'right'),
          TD(i.detail),
        ]),
      ))
      if (d.issues.length > 300) {
        content.push({ text: `Показано 300 замечаний из ${d.issues_total}. Полный список — в выгрузке Excel.`, style: 'note' })
      }
    }
  }

  if ('diag' in data && data.diag) {
    const d = data.diag as VarianceDiagnosticsResponse
    content.push({ text: 'Природа расхождения по резервуарам', style: 'h2', pageBreak: 'before' })
    content.push(table(
      [58, 26, 40, 96, 52, 60, 52, 40, 56],
      [TH('АЗС'), TH('Рез.'), TH('Топливо'), TH('Природа'), TH('Тренд, л/см', 'right'),
       TH('Накоплено', 'right'), TH('Скачок', 'right'), TH('Смена'), TH('Сейчас', 'right')],
      d.tanks.map((t) => [
        TD(t.station_name), TD(`№${t.tank_number}`), TD(t.fuel_name), TD(t.nature_title),
        TD(nf1.format(t.trend_per_shift), 'right'), TD(gapWord(t.accumulated), 'right'),
        TD(gapWord(t.jump_liters), 'right'), TD(t.jump_shift ? `№${t.jump_shift}` : '—'),
        TD(gapWord(t.last_gap), 'right'),
      ]),
    ))
  }

  if ('receipts' in data && data.receipts) {
    const d = data.receipts as ReceiptAnalysisResponse
    content.push({
      columns: [
        { text: [{ text: 'Принято ТТН\n', bold: true }, `${d.totals.ttn} · ${nf1.format(d.totals.doc_tonn)} т`], style: 'kpi' },
        { text: [{ text: 'Недолив\n', bold: true }, `${d.totals.shortfall_ttn} ТТН · ${nf0.format(Math.abs(d.totals.shortfall_kg))} кг`], style: 'kpi' },
        { text: [{ text: 'Без замера\n', bold: true }, `${d.totals.not_measured_ttn} ТТН`], style: 'kpi' },
        { text: [{ text: 'Перелив\n', bold: true }, `${d.totals.surplus_ttn} ТТН`], style: 'kpi' },
        { text: [{ text: 'Плотность расходится\n', bold: true }, `${d.totals.density_mismatch} ТТН`], style: 'kpi' },
      ],
      columnGap: 8, margin: [0, 0, 0, 12],
    })
    content.push({ text: 'Накладные периода', style: 'h2' })
    content.push(table(
      [46, 44, 56, 26, 40, 74, 52, 52, 56, 46, '*'],
      [TH('ТТН'), TH('Дата'), TH('АЗС'), TH('Рез.'), TH('Топливо'), TH('Поставщик'),
       TH('Док., кг', 'right'), TH('Факт, кг', 'right'), TH('Откл., кг', 'right'),
       TH('Откл., %', 'right'), TH('Причина')],
      d.rows.map((r) => [
        TD(r.ttn), TD(dt(r.date)), TD(r.station_name), TD(r.tank ?? '—'), TD(r.fuel_name),
        TD(r.supplier || '—'), TD(nf1.format(r.doc_mass_kg), 'right'),
        TD(nf1.format(r.fact_mass_kg), 'right'), TD(nf1.format(r.diff_mass_kg), 'right'),
        TD(r.diff_pct == null ? '—' : nf1.format(r.diff_pct), 'right'), TD(r.klass_title),
      ]),
    ))
  }

  pdfMake.createPdf({
    info: { title: VIEW_TITLE[view], subject: 'Товародвижение · выгрузка' },
    pageOrientation: 'landscape',
    pageMargins: [20, 20, 20, 28],
    footer: (page: number, total: number) => ({
      text: `${VIEW_TITLE[view]} · ${dt(p.dateFrom)} — ${dt(p.dateTo)} · стр. ${page} из ${total}`,
      style: 'footer', alignment: 'center', margin: [0, 8, 0, 0],
    }),
    content,
    styles: {
      title: { fontSize: 16, bold: true, color: '#111827', margin: [0, 0, 0, 8] },
      h2: { fontSize: 12, bold: true, color: '#111827', margin: [0, 6, 0, 6] },
      info: { fontSize: 9, color: '#374151' },
      kpi: { fontSize: 9, color: '#111827' },
      th: { fontSize: 8, bold: true, color: '#f9fafb' },
      td: { fontSize: 8, color: '#111827', lineHeight: 1.15 },
      note: { fontSize: 8, italics: true, color: '#6b7280' },
      footer: { fontSize: 7, color: '#6b7280' },
    },
    defaultStyle: { font: 'Roboto' },
  }).download(`${FILE_BASE[view]}_${p.dateFrom}_${p.dateTo}.pdf`)
}
