/**
 * Печатная форма документа ЗИП: приходный ордер, требование-накладная, накладная
 * на перемещение, акт на списание, инвентаризационная опись. Тот же приём, что у
 * документов оборудования (`equipmentDocPrint.ts`): отдельное окно, печать или PDF
 * средствами браузера.
 */
import type { SpareDocument } from '@/services/equipmentService'

const esc = (v: unknown) => String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!))
const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
export const ruDate = (iso?: string | null) => (iso ? iso.slice(0, 10).split('-').reverse().join('.') : '')
/** «+3» / «−2»: отклонение читается со знаком. */
export const signed = (n: number) => (n > 0 ? '+' : n < 0 ? '−' : '') + nf.format(Math.abs(n))

/** Получатель расхода: станция с серийным номером либо объект без привязки к станции. */
export function spareTarget(d: Pick<SpareDocument, 'targetUnit' | 'targetLocation' | 'targetNote'>): string {
  const u = d.targetUnit
  if (u) return `${u.name || 'Станция'}${u.serialNumber ? ` · с/н ${u.serialNumber}` : ''}`
  const place = d.targetNote || d.targetLocation
  return place ? `Объект без привязки к станции: ${place}` : ''
}

/** Подписи под документом: у описи расписываются не «сдал / принял». */
export const spareSigners = (op: SpareDocument['op']): [string, string] =>
  op === 'inventory' ? ['Материально ответственное лицо', 'Пересчёт провёл'] : ['Сдал', 'Принял']

export function spareDocHtml(d: SpareDocument, orgName: string): string {
  const lines = d.lines ?? []
  const inv = d.op === 'inventory'
  const rows = lines.map((l, i) => `<tr><td>${i + 1}</td><td>${esc(l.name)}</td><td>${esc(l.article)}</td><td>${esc(l.unitLabel)}</td>${inv
    ? `<td class="n">${nf.format(l.book ?? 0)}</td><td class="n">${nf.format(l.fact ?? 0)}</td><td class="n">${l.delta ? signed(l.delta) : '—'}</td>`
    : `<td class="n">${nf.format(l.qty ?? 0)}</td>`}</tr>`).join('')
  const field = (k: string, v?: string | null) => (v ? `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>` : '')
  const [from, to] = spareSigners(d.op)
  const diff = lines.filter((l) => l.delta).length
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>${esc(d.title)} № ${esc(d.number)}</title>
<style>
  body{font:12px/1.4 Arial,sans-serif;color:#111;margin:24px}
  h1{font-size:16px;margin:0 0 4px;text-align:center} .sub{text-align:center;margin-bottom:14px}
  table{border-collapse:collapse;width:100%} .head th{text-align:left;width:190px;font-weight:600;padding:2px 6px;vertical-align:top}
  .head td{padding:2px 6px} .lines{margin-top:12px} .lines th,.lines td{border:1px solid #444;padding:4px 6px;text-align:left}
  .lines th{background:#eee} .lines .n{text-align:right;white-space:nowrap} .sign{display:flex;gap:40px;margin-top:36px} .sign div{flex:1}
  .line{border-bottom:1px solid #111;height:22px;margin-bottom:2px} small{color:#555}
  .void{border:2px solid #b00;color:#b00;padding:6px 10px;margin-bottom:12px;font-weight:600}
  @media print{body{margin:10mm}}
</style></head><body>
<div style="text-align:right"><small>${esc(orgName)}</small></div>
${d.status === 'cancelled' ? `<div class="void">Документ отменён ${esc(ruDate(d.cancelledAt))}${d.cancelledBy ? ` · ${esc(d.cancelledBy)}` : ''}. Причина: ${esc(d.cancelReason)}</div>` : ''}
<h1>${esc(d.title)}</h1>
<div class="sub">№ ${esc(d.number)} от ${esc(ruDate(d.docDate))}</div>
<table class="head">
${field(inv ? 'Склад' : 'Склад-получатель', d.toLocation)}${field('Склад-отправитель', d.fromLocation)}${field('Получатель', spareTarget(d))}
${field('Акт ремонта', d.repairDocument?.number ? '№ ' + d.repairDocument.number : '')}${field(d.op === 'issue' ? 'Счёт затрат' : 'Счёт списания', d.costAccount ? d.costAccount + (d.costItem ? ' · ' + d.costItem : '') : '')}${field('Контрагент', d.counterpartyName)}${field('Договор', d.contractLabel)}${field('Основание', d.basis)}${field('Комментарий', d.comment)}
${field('Первичный документ контрагента', d.primaryNumber || d.primaryDate ? `№ ${d.primaryNumber ?? '—'} от ${ruDate(d.primaryDate) || '—'}` : '')}
</table>
<table class="lines"><thead><tr><th>№</th><th>Наименование</th><th>Артикул</th><th>Ед.</th>${inv ? '<th>По учёту</th><th>Фактически</th><th>Отклонение</th>' : '<th>Количество</th>'}</tr></thead>
<tbody>${rows}</tbody></table>
<p>Всего строк: ${lines.length}${inv ? ` · с расхождением: ${diff}` : ''}</p>
<div class="sign">
  <div><b>${from}</b><div class="line"></div><small>${esc(d.responsibleFrom) || 'должность, ФИО, подпись'}</small></div>
  <div><b>${to}</b><div class="line"></div><small>${esc(d.responsibleTo) || 'должность, ФИО, подпись'}</small></div>
</div>
<p style="margin-top:24px"><small>Документ оформлен в пространстве ${esc(orgName)} · ${esc(d.createdBy)} · ${esc(ruDate(d.createdAt))}</small></p>
</body></html>`
}

export function printSpareDocument(d: SpareDocument, orgName: string) {
  const w = window.open('', '_blank')
  if (!w) throw new Error('Браузер заблокировал окно печати — разрешите всплывающие окна для пространства')
  w.document.open()
  w.document.write(spareDocHtml(d, orgName))
  w.document.close()
  w.focus()
  setTimeout(() => w.print(), 300)
}
