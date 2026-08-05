/**
 * Печатная форма первичного документа станции.
 *
 * Документ существует в системе, но при проверке и внутреннем разборе нужна
 * подписанная бумага: акт списания, накладная на перемещение, опись пересчёта.
 * Формы сделаны по смыслу унифицированных (ТОРГ-13, ТОРГ-16, ИНВ-3) — те же
 * реквизиты, стороны и подписи, — но без попытки выдать себя за официальный
 * бланк: подпись ставит человек, и он должен видеть, что подписывает.
 *
 * Печатаем в отдельном окне со своим CSS, а не через стили приложения: у
 * рабочей области печать альбомная и своя, документ же требует портрета и
 * жёсткой вёрстки, которую тема приложения не должна двигать.
 */
import type { StoreStationDocFull } from '@/services/storeService'

/** Заголовок бумаги по виду документа — и подпись, какой форме он отвечает. */
const ФОРМЫ: Record<string, { title: string; form?: string; from: string; to: string }> = {
  writeoff: { title: 'Акт о списании товаров', form: 'по смыслу ТОРГ-16',
              from: 'Материально ответственное лицо', to: 'Утвердил' },
  transfer: { title: 'Накладная на внутреннее перемещение товаров', form: 'по смыслу ТОРГ-13',
              from: 'Отпустил', to: 'Принял' },
  inventory: { title: 'Инвентаризационная опись товаров', form: 'по смыслу ИНВ-3',
               from: 'Материально ответственное лицо', to: 'Председатель комиссии' },
  purchase: { title: 'Акт приёмки товаров', from: 'Сдал (поставщик)', to: 'Принял' },
  return_supplier: { title: 'Накладная на возврат товаров поставщику',
                     from: 'Отпустил', to: 'Принял (поставщик)' },
  return_sale: { title: 'Акт о возврате товара покупателем', from: 'Оформил', to: 'Принял' },
  production_release: { title: 'Акт производства (выпуск продукции)',
                        from: 'Изготовил', to: 'Принял' },
  revaluation: { title: 'Акт переоценки товаров', from: 'Составил', to: 'Утвердил' },
}

const экран = (v: unknown) => String(v ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const число = (n: number | null | undefined, d = 3) =>
  n == null ? '' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

const деньги = (n: number | null | undefined) =>
  n == null ? '' : new Intl.NumberFormat('ru-RU',
    { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)

function дата(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('ru-RU',
    { day: '2-digit', month: 'long', year: 'numeric' })
}

export function printStationDoc(d: StoreStationDocFull) {
  const форма = ФОРМЫ[d.kind] ?? { title: d.label, from: 'Составил', to: 'Принял' }
  const итогКоличество = d.lines.reduce((a, l) => a + (l.qty || 0), 0)
  const итогСумма = d.lines.reduce((a, l) => a + (l.amount || 0), 0)

  const строки = d.lines.map((l, i) => `
    <tr>
      <td class="c">${i + 1}</td>
      <td>${экран(l.name)}</td>
      <td class="c">${экран(l.barcode)}</td>
      <td class="c">${экран(l.unit)}</td>
      <td class="r">${число(l.qty)}</td>
      <td class="r">${l.qty_book != null ? число(l.qty_book) : ''}</td>
      <td class="r">${деньги(l.price)}</td>
      <td class="r">${деньги(l.amount)}</td>
    </tr>`).join('')

  const реквизит = (подпись: string, значение: string | null | undefined) =>
    значение ? `<div><span class="lbl">${подпись}:</span> ${экран(значение)}</div>` : ''

  const html = `<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>${экран(форма.title)} № ${экран(d.number ?? '')}</title>
<style>
  @page { size: A4 portrait; margin: 15mm 12mm; }
  body { font: 11pt/1.35 "Times New Roman", serif; color: #000; margin: 0; }
  h1 { font-size: 14pt; text-align: center; margin: 0 0 2mm; }
  .form { text-align: center; font-size: 9pt; color: #555; margin-bottom: 6mm; }
  .org { font-size: 10pt; margin-bottom: 4mm; }
  .meta { display: flex; flex-wrap: wrap; gap: 2mm 8mm; font-size: 10pt; margin-bottom: 4mm; }
  .lbl { color: #555; }
  table { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
  th, td { border: 1px solid #000; padding: 1.2mm 1.6mm; }
  th { background: #f0f0f0; font-weight: normal; }
  td.c { text-align: center; } td.r { text-align: right; }
  tfoot td { font-weight: bold; }
  .sign { margin-top: 10mm; display: flex; gap: 12mm; font-size: 10pt; }
  .sign div { flex: 1; }
  .line { border-bottom: 1px solid #000; height: 6mm; margin-bottom: 1mm; }
  .hint { font-size: 8pt; color: #555; text-align: center; }
  .note { margin-top: 4mm; font-size: 9.5pt; }
  .foot { margin-top: 8mm; font-size: 8pt; color: #555; }
</style></head>
<body>
  <div class="org">${экран(d.org?.name)}${d.org?.inn ? `, ИНН ${экран(d.org.inn)}` : ''}</div>
  <h1>${экран(форма.title)} № ${экран(d.number ?? 'б/н')}</h1>
  ${форма.form ? `<div class="form">${форма.form}</div>` : ''}

  <div class="meta">
    <div><span class="lbl">Дата:</span> ${дата(d.doc_date ?? d.received_at)}</div>
    <div><span class="lbl">АЗС:</span> ${экран(d.station_id)}</div>
    ${реквизит('Место', d.place_from)}
    ${d.place_to ? реквизит('Куда', d.place_to) : ''}
    ${реквизит('Контрагент', d.counterparty)}
    ${реквизит('Договор', d.contract)}
    ${реквизит('Входящий документ', d.incoming_number)}
    ${реквизит('Основание', d.basis)}
    ${реквизит('Причина', d.reason)}
    ${реквизит('Смена', d.shift_number)}
  </div>

  <table>
    <thead><tr>
      <th style="width:8mm">№</th>
      <th>Наименование товара</th>
      <th style="width:26mm">Штрихкод</th>
      <th style="width:14mm">Ед.</th>
      <th style="width:20mm">Кол-во</th>
      <th style="width:20mm">По учёту</th>
      <th style="width:22mm">Цена, ₽</th>
      <th style="width:24mm">Сумма, ₽</th>
    </tr></thead>
    <tbody>${строки || '<tr><td colspan="8" class="c">Строк нет</td></tr>'}</tbody>
    <tfoot><tr>
      <td colspan="4" class="r">Итого</td>
      <td class="r">${число(итогКоличество)}</td>
      <td></td><td></td>
      <td class="r">${деньги(итогСумма || d.amount)}</td>
    </tr></tfoot>
  </table>

  ${d.meta_note ? `<div class="note"><span class="lbl">Примечание:</span> ${экран(d.meta_note)}</div>` : ''}

  <div class="sign">
    <div>
      <div class="line"></div>
      <div class="hint">${форма.from}${d.responsible_from ? ` — ${экран(d.responsible_from)}` : ''}</div>
    </div>
    <div>
      <div class="line"></div>
      <div class="hint">${форма.to}${d.responsible_to ? ` — ${экран(d.responsible_to)}` : ''}</div>
    </div>
  </div>

  <div class="foot">
    Документ сформирован из учётной записи АЗС ${экран(d.station_id)}
    (пакет ${экран(d.packet_uuid).slice(0, 8)}). Оформил на станции:
    ${экран(d.author) || 'не указан'}.
  </div>
</body></html>`

  const окно = window.open('', '_blank', 'width=900,height=1000')
  if (!окно) return false
  окно.document.write(html)
  окно.document.close()
  // Печать после отрисовки: иначе окно уходит в диалог с пустым листом.
  окно.onload = () => окно.print()
  setTimeout(() => { try { окно.print() } catch { /* окно закрыли раньше */ } }, 400)
  return true
}
