/**
 * Печатная форма документа движения оборудования: накладная или акт с таблицей
 * единиц и подписями «сдал / принял». Открывается в отдельном окне и уходит на
 * печать или в PDF средствами браузера — тот же приём, что у печати документов
 * «Магазина»: печатается документ, а не экран приложения.
 */
import type { EquipmentDocument } from '@/services/equipmentService'

const esc = (v: unknown) => String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!))
/** «Фора 60», а не «Фора Фора 60»: модель часто уже начинается с производителя. */
export const eqName = (vendor?: string | null, model?: string | null) =>
  vendor && model && model.toLowerCase().startsWith(vendor.toLowerCase()) ? model : [vendor, model].filter(Boolean).join(' ')
const ru = (iso?: string | null) => (iso ? iso.slice(0, 10).split('-').reverse().join('.') : '')

export function equipmentDocHtml(d: EquipmentDocument, orgName: string): string {
  const lines = d.lines ?? []
  const rows = lines.map((l, i) => `<tr><td>${i + 1}</td><td>${esc(eqName(l.vendor, l.model))}</td>
    <td>${esc(l.serialNumber)}</td><td>${esc(l.inventoryNumber)}</td><td>${esc(l.from)}</td><td>${esc(l.to)}</td>
    <td>${esc(l.toState)}</td></tr>`).join('')
  const field = (k: string, v?: string | null) => (v ? `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>` : '')
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>${esc(d.title)} № ${esc(d.number)}</title>
<style>
  body{font:12px/1.4 Arial,sans-serif;color:#111;margin:24px}
  h1{font-size:16px;margin:0 0 4px;text-align:center} .sub{text-align:center;margin-bottom:14px}
  table{border-collapse:collapse;width:100%} .head th{text-align:left;width:190px;font-weight:600;padding:2px 6px;vertical-align:top}
  .head td{padding:2px 6px} .lines{margin-top:12px} .lines th,.lines td{border:1px solid #444;padding:4px 6px;text-align:left}
  .lines th{background:#eee} .sign{display:flex;gap:40px;margin-top:36px} .sign div{flex:1}
  .line{border-bottom:1px solid #111;height:22px;margin-bottom:2px} small{color:#555}
  @media print{body{margin:10mm}}
</style></head><body>
<div style="text-align:right"><small>${esc(orgName)}</small></div>
<h1>${esc(d.title)}</h1>
<div class="sub">№ ${esc(d.number)} от ${esc(ru(d.docDate))}</div>
<table class="head">
${field('Операция', d.opLabel)}${field('Откуда', d.fromLocation)}${field('Куда', d.toLocation)}
${field('Контрагент', d.counterpartyName)}${field('Договор', d.contractLabel)}${field('Основание', d.basis)}${field('Комментарий', d.comment)}
${field('Заявка Поддержки', d.details?.ticketRef ? '№ ' + d.details.ticketRef : '')}${field('Вид ремонта', d.details?.repairKind ? { warranty: 'гарантийный', paid: 'платный' }[d.details.repairKind] : '')}${field('Плановый возврат', ru(d.details?.plannedReturn))}${field('Оценка стоимости', d.details?.costEstimate != null ? d.details.costEstimate.toLocaleString('ru-RU') + ' ₽' : '')}${field('Стоимость ремонта', d.details?.costActual != null ? d.details.costActual.toLocaleString('ru-RU') + ' ₽' : '')}${field('Результат', d.details?.result ? { repaired: 'отремонтировано', unrepairable: 'ремонту не подлежит' }[d.details.result] : '')}
</table>
<table class="lines"><thead><tr><th>№</th><th>Оборудование</th><th>Серийный №</th><th>Инв. №</th><th>Откуда</th><th>Куда</th><th>Состояние после</th></tr></thead>
<tbody>${rows}</tbody></table>
<p>Всего единиц: ${lines.length}</p>
<div class="sign">
  <div><b>Сдал</b><div class="line"></div><small>${esc(d.responsibleFrom) || 'должность, ФИО, подпись'}</small></div>
  <div><b>Принял</b><div class="line"></div><small>${esc(d.responsibleTo) || 'должность, ФИО, подпись'}</small></div>
</div>
<p style="margin-top:24px"><small>Документ оформлен в пространстве ${esc(orgName)} · ${esc(d.createdBy)} · ${esc(ru(d.createdAt))}</small></p>
</body></html>`
}

export function printEquipmentDocument(d: EquipmentDocument, orgName: string) {
  const w = window.open('', '_blank')
  if (!w) throw new Error('Браузер заблокировал окно печати — разрешите всплывающие окна для пространства')
  w.document.open()
  w.document.write(equipmentDocHtml(d, orgName))
  w.document.close()
  w.focus()
  setTimeout(() => w.print(), 300)
}
