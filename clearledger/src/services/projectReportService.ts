/**
 * Отчёт проекта: Excel (собирает сервер) и PDF-презентация (собирает браузер).
 *
 * Данные у обоих форматов из одного серверного сборщика (`GET /sites/{id}/report`),
 * поэтому цифры в файле и на слайде совпадают. PDF — pdfMake: у шрифтов jsPDF нет
 * кириллицы (см. `utils/pdfMake.ts`).
 */
import { downloadFile, get } from './apiClient'
import { loadPdfMake } from '@/utils/pdfMake'

type Row = Record<string, string | number | null>
export interface ProjectReport {
  generatedAt: string
  summary: {
    projectNo: string | null; title: string | null; kind: string; stage: string; stageLabel: string; phaseLabel: string
    owner: string; region: string; address: string; nextAction: string; nextActionDue: string; stageSince: string
    createdAt: string; plannedPowerKwt: number | null; plannedEzs: number | null; freePowerKwt: number | null
    controlForm: string; contractStart: string; commissionedOn: string; exitKind: string
  }
  gate: { stageLabel: string; blocking: string[]; closed: number; total: number }
  verdict: { label: string; hint: string; confidence: number | null; unknown: string[] } | null
  phases: { label: string; state: 'done' | 'current' | 'next' }[]
  checklist: Row[]; work: Row[]; equipment: Row[]; costs: Row[]; documents: Row[]; history: Row[]
  techConnection: Row | null
  budget: { plan: number; fact: number; delta: number }
  integration?: {
    partner: Record<string, string>; settlement: Record<string, string>; work: Record<string, string>
    scenarios: Row[]; tests: Row[]; reconciliations: Row[]; listVersions: Row[]; stations: Row[]
  }
}

export const getProjectReport = (companyId: string, siteId: string) =>
  get<ProjectReport>(`/api/sites/${siteId}/report`, { company_id: companyId })

const fileBase = (r: { projectNo?: string | null }, siteId: string) => `project_${(r.projectNo || siteId).replace(/\s+/g, '_')}`

export const downloadProjectXlsx = (companyId: string, siteId: string, projectNo?: string | null) =>
  downloadFile(`/api/sites/${siteId}/report.xlsx?company_id=${companyId}`, `${fileBase({ projectNo }, siteId)}.xlsx`)

/* ── PDF-презентация ─────────────────────────────────────────────────────── */

const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const money = (v: number | string | null | undefined) => (v == null || v === '' ? '—' : `${nf.format(Number(v))} ₽`)
const s = (v: unknown) => (v == null || v === '' ? '—' : String(v))
const TH = (text: string) => ({ text, style: 'th' })
const MATCH: Record<string, string> = { account: 'договорной аккаунт', client: 'юрлицо клиента', card: 'номера карт' }
const TD = (text: unknown, opts: Record<string, unknown> = {}) => ({ text: s(text), style: 'td', ...opts })

function table(widths: (number | string)[], header: string[], body: unknown[][], empty: string) {
  if (!body.length) return { text: empty, style: 'note', margin: [0, 4, 0, 10] }
  return {
    table: { headerRows: 1, widths, body: [header.map(TH), ...body], dontBreakRows: true },
    layout: {
      fillColor: (i: number) => (i === 0 ? '#1f2937' : i % 2 === 0 ? '#f3f4f6' : '#ffffff'),
      hLineColor: () => '#d1d5db', vLineColor: () => '#d1d5db',
      paddingLeft: () => 5, paddingRight: () => 5, paddingTop: () => 3, paddingBottom: () => 3,
    },
    margin: [0, 0, 0, 10],
  }
}

// Лист-«слайд» начинается с новой страницы: титул и «Где мы». Остальные разделы
// идут подряд — у нового проекта половина из них пуста, и отдельный лист на
// «Затраты не внесены» превращал отчёт в стопку пустых страниц.
const slide = (title: string, body: unknown[], first = false) => [
  { text: title, style: 'slideTitle', ...(first ? {} : { pageBreak: 'before' }) },
  { canvas: [{ type: 'line', x1: 0, y1: 0, x2: 770, y2: 0, lineWidth: 1, lineColor: '#2563eb' }], margin: [0, 0, 0, 10] },
  ...body,
]
const section = (title: string, body: unknown[]) => [
  { text: title, style: 'sectionTitle', headlineLevel: 1 },
  { canvas: [{ type: 'line', x1: 0, y1: 0, x2: 770, y2: 0, lineWidth: 0.5, lineColor: '#93c5fd' }], margin: [0, 0, 0, 8] },
  ...body,
]

function tile(label: string, value: string, hint = '', tone = '#111827') {
  return { stack: [{ text: label, style: 'tileLabel' }, { text: value, style: 'tileValue', color: tone }, { text: hint, style: 'tileHint' }],
    margin: [0, 0, 0, 0] }
}

function kv(pairs: [string, unknown][]) {
  const rows = pairs.filter(([, v]) => v != null && v !== '')
  return table([180, '*'], ['Параметр', 'Значение'], rows.map(([k, v]) => [TD(k, { bold: true }), TD(v)]), 'Данные не заполнены')
}

/** Дата «дд.мм.гггг чч:мм» из отчёта → Date для отбора свежих изменений. */
function parseRu(at: string): Date | null {
  const m = /^(\d{2})\.(\d{2})\.(\d{4})/.exec(at || '')
  return m ? new Date(+m[3], +m[2] - 1, +m[1]) : null
}

export function buildProjectPdf(r: ProjectReport, spaceName: string) {
  const sm = r.summary
  const name = `${sm.projectNo ?? ''} · ${sm.title ?? 'Проект'}`.trim()
  const integ = r.integration
  const openWork = r.work.filter((w) => w.state !== 'Готово')
  const overdue = r.work.filter((w) => w.overdue)
  const since = new Date(); since.setDate(since.getDate() - 30)
  const recent = r.history.filter((h) => { const d = parseRu(String(h.at)); return d && d >= since })
  const holds = r.checklist.filter((c) => c.stage === r.gate.stageLabel)

  const phaseRow = r.phases.map((p) => ({
    text: p.label, alignment: 'center', bold: p.state === 'current',
    color: p.state === 'next' ? '#6b7280' : '#ffffff', fillColor: p.state === 'current' ? '#2563eb' : p.state === 'done' ? '#16a34a' : '#e5e7eb',
    margin: [0, 6, 0, 6], fontSize: 10,
  }))

  const content: unknown[] = [
    ...slide(name, [
      { text: `${spaceName} · ${integ ? 'Интеграция с партнёром' : 'Проект развития сети'} · отчёт на ${r.generatedAt}`, style: 'subtitle' },
      ...(phaseRow.length ? [{ table: { widths: phaseRow.map(() => '*'), body: [phaseRow] }, layout: 'noBorders', margin: [0, 6, 0, 14] }] : []),
      ...(r.verdict ? [{ text: [{ text: 'Решение: ', bold: true }, `${r.verdict.label} — ${r.verdict.hint}`,
        r.verdict.confidence != null ? `; уверенность оценки ${r.verdict.confidence}%` : '',
        r.verdict.unknown.length ? `. Не хватает: ${r.verdict.unknown.join('; ')}` : ''], style: 'verdict', margin: [0, 0, 0, 12] }] : []),
      { columns: [
        tile('Стадия', sm.stageLabel, sm.stageSince ? `с ${sm.stageSince}` : ''),
        tile('Чек-лист стадии', `${r.gate.closed} из ${r.gate.total}`, r.gate.blocking.length ? `держит: ${r.gate.blocking.length}` : 'переход открыт',
          r.gate.blocking.length ? '#b45309' : '#15803d'),
        tile('Открытая работа', String(openWork.length), overdue.length ? `просрочено: ${overdue.length}` : 'просрочек нет', overdue.length ? '#b91c1c' : '#111827'),
        r.budget.plan || r.budget.fact ? tile('Бюджет', money(r.budget.plan), `факт ${money(r.budget.fact)}`) : tile('Бюджет', 'не внесён', '', '#6b7280'),
      ], columnGap: 12, margin: [0, 0, 0, 14] },
      kv([
        ['Ответственный', sm.owner || 'не назначен'], ['Следующий шаг', sm.nextAction ? `${sm.nextAction}${sm.nextActionDue ? ` · до ${sm.nextActionDue}` : ''}` : 'не задан'],
        ...(integ ? [['Партнёр', integ.partner.name], ['Цель', integ.partner.purpose]] as [string, unknown][]
          : [['Регион', sm.region], ['Адрес', sm.address], ['Мощность план, кВт', sm.plannedPowerKwt], ['ЭЗС план', sm.plannedEzs],
            ['Свободная мощность, кВт', sm.freePowerKwt], ['Форма оформления', sm.controlForm], ['Договор с', sm.contractStart],
            ['Введён', sm.commissionedOn]] as [string, unknown][]),
      ]),
    ], true),
    ...slide(`Где мы: стадия «${r.gate.stageLabel || sm.stageLabel}»`, [
      r.gate.blocking.length ? { text: `Держит переход: ${r.gate.blocking.join('; ')}`, style: 'alert', margin: [0, 0, 0, 8] }
        : { text: 'Обязательные пункты стадии закрыты — переход открыт', style: 'ok', margin: [0, 0, 0, 8] },
      table([34, '*', 70, 130, 110], ['Пункт', 'Требование', 'Кто', 'Состояние', 'Подтвердил'],
        holds.map((c) => [TD(c.key), TD(c.label, { bold: !!c.holds }), TD(c.role), TD(c.status, { color: c.holds ? '#b45309' : c.status === 'Выполнено' ? '#15803d' : '#111827' }), TD(c.by)]),
        'Пунктов чек-листа у этой стадии нет'),
    ]),
  ]

  if (integ) {
    content.push(...section('Сценарии, станции и расчёты', [
      table(['*', 110, 80, 60, 60, 60], ['Сценарий', 'Расчёты', 'Ставка', 'Выбрано', 'Согласовано', 'Подключено'],
        integ.scenarios.map((x) => [TD(x.name), TD(x.payer), TD(x.rate), TD(x.selected, { alignment: 'right' }), TD(x.agreed, { alignment: 'right' }), TD(x.connected, { alignment: 'right' })]),
        'Сценарии подключения не заданы'),
      kv([['Периодичность расчётов', integ.settlement.period], ['Срок оплаты', integ.settlement.paymentTerm], ['Документы', integ.settlement.documents],
        ['Сессии партнёра в учёте', integ.settlement.matchKind ? `${MATCH[integ.settlement.matchKind] ?? integ.settlement.matchKind}: ${integ.settlement.matchValues}` : '']]),
    ]))
    content.push(...section('Испытания и сверки', [
      table(['*', 60, 80, 90, 160], ['Испытание', 'Обяз.', 'Статус', 'Сессия', 'Комментарий'],
        integ.tests.map((t) => [TD(t.title), TD(t.required), TD(t.status, { color: t.status === 'замечание' ? '#b91c1c' : t.status === 'пройдено' ? '#15803d' : '#111827' }), TD(t.session), TD(t.comment)]),
        'Испытания не заведены'),
      table([90, 90, 60, 60, 80, 80, 90], ['Вид', 'Период', 'Сессии: мы', 'партнёр', '₽: мы', '₽: партнёр', 'Итог'],
        integ.reconciliations.map((x) => [TD(x.kind), TD(x.period), TD(x.ourSessions, { alignment: 'right' }), TD(x.partnerSessions, { alignment: 'right' }),
          TD(money(x.ourAmount), { alignment: 'right' }), TD(money(x.partnerAmount), { alignment: 'right' }),
          TD(x.state, { color: x.state === 'расхождение' ? '#b91c1c' : '#15803d' })]),
        'Сверок пока нет'),
    ]))
  } else {
    const tc = r.techConnection
    content.push(...section('Присоединение и оборудование', [
      tc ? { unbreakable: true, stack: [kv([['Статус', tc.status], ['Сетевая', tc.gridOperator],
        ['Заявка', [tc.applicationNo, tc.applicationDate].filter(Boolean).join(' от ')], ['ТУ', [tc.specsNo, tc.specsDate].filter(Boolean).join(' от ')],
        ['Договор ТП', [tc.contractNo, tc.contractDate].filter(Boolean).join(' от ')], ['Мощность, кВт', tc.powerKwt], ['Стоимость', money(tc.totalCost ?? tc.cost)],
        ['Срок мероприятий', tc.due], ['Исполнено', tc.done]])] } : { text: 'Технологическое присоединение не заведено', style: 'note' },
      ...(r.equipment.length ? [{ text: 'Оборудование', style: 'h2' }, table(['*', 90, 40, 90, 70, 70], ['Позиция', 'Производитель', 'Кол.', 'Статус', 'Срок', 'Поставлено'],
        r.equipment.map((e) => [TD(e.title), TD(e.manufacturer), TD(e.qty, { alignment: 'right' }), TD(e.status), TD(e.due), TD(e.supplied)]), '')]
        : [{ text: 'Оборудование не заведено', style: 'note' }]),
    ]))
    content.push(...section('Бюджет: план и факт', [
      ...(r.costs.length ? [{ columns: [tile('План', money(r.budget.plan)), tile('Факт', money(r.budget.fact)),
        tile('Отклонение', money(r.budget.delta), '', r.budget.delta > 0 ? '#b91c1c' : '#111827')], columnGap: 12, margin: [0, 0, 0, 12] }] : []),
      table([130, 90, '*', 90, 90], ['Статья', 'Судьба', 'Описание', 'План', 'Факт'],
        r.costs.map((c) => [TD(c.kind), TD(c.capital), TD(c.title), TD(money(c.plan), { alignment: 'right' }), TD(money(c.fact), { alignment: 'right' })]),
        'Затраты по проекту не внесены'),
    ]))
  }

  content.push(...section('Работа по проекту', [
    table([60, '*', 90, 120, 80, 60], ['Номер', 'Работа', 'Состояние', 'Исполнитель', 'Срок', ''],
      r.work.map((w) => [TD(w.key), TD(w.work), TD(w.state), TD(w.responsible), TD(w.due), TD(w.overdue, { color: '#b91c1c' })]),
      'К проекту не привязано ни одного поручения или документа «Трека»'),
  ]))
  content.push(...section('Изменения за 30 дней', [
    table([80, 110, 90, 140, '*', '*'], ['Когда', 'Кто', 'Событие', 'Что', 'Было', 'Стало'],
      recent.slice(0, 45).map((h) => [TD(h.at), TD(h.author), TD(h.kind), TD(h.field || h.text), TD(h.old), TD(h.new)]),
      'За 30 дней изменений не было'),
    ...(recent.length > 45 ? [{ text: `Показаны 45 из ${recent.length}. Полная история — в Excel проекта, лист «История».`, style: 'note' }] : []),
  ]))
  return {
    info: { title: name, subject: `${spaceName} · отчёт проекта` },
    pageSize: 'A4', pageOrientation: 'landscape', pageMargins: [36, 30, 36, 34],
    // Заголовок раздела не остаётся последней строкой страницы — уходит к своей таблице.
    pageBreakBefore: (node: { headlineLevel?: number }, following: unknown[]) => node.headlineLevel === 1 && following.length < 3,
    footer: (page: number, total: number) => ({ text: `${spaceName} · ${name} · ${r.generatedAt} · стр. ${page} из ${total}`, style: 'footer', alignment: 'center', margin: [0, 10, 0, 0] }),
    content,
    styles: {
      slideTitle: { fontSize: 20, bold: true, color: '#111827', margin: [0, 0, 0, 4] },
      sectionTitle: { fontSize: 14, bold: true, color: '#111827', margin: [0, 8, 0, 3] },
      verdict: { fontSize: 10, color: '#1e3a8a' },
      subtitle: { fontSize: 10, color: '#4b5563' },
      h2: { fontSize: 12, bold: true, color: '#111827', margin: [0, 2, 0, 6] },
      tileLabel: { fontSize: 9, color: '#6b7280' }, tileValue: { fontSize: 18, bold: true }, tileHint: { fontSize: 8, color: '#6b7280' },
      th: { fontSize: 8.5, bold: true, color: '#f9fafb' }, td: { fontSize: 8.5, color: '#111827', lineHeight: 1.15 },
      alert: { fontSize: 10, bold: true, color: '#b45309' }, ok: { fontSize: 10, bold: true, color: '#15803d' },
      note: { fontSize: 9, italics: true, color: '#6b7280' }, footer: { fontSize: 7, color: '#6b7280' },
    },
    defaultStyle: { font: 'Roboto' },
  }
}

export async function downloadProjectPdf(companyId: string, siteId: string, spaceName: string) {
  const [pdfMake, report] = await Promise.all([loadPdfMake(), getProjectReport(companyId, siteId)])
  pdfMake.createPdf(buildProjectPdf(report, spaceName)).download(`${fileBase(report.summary, siteId)}.pdf`)
}
