import type { MegafonVoiceData } from '@/services/megafonVoiceService'
import type { Лист } from './exportTable'

export const currentMonth = (now = new Date()) => `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
export function monthlyBounds(month: string, now = new Date()) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month) || Number(month.slice(0, 4)) < 1970 || month > currentMonth(now)) return null
  const [year, m] = month.split('-').map(Number)
  return { from: new Date(year, m - 1, 1).toISOString(), to: new Date(year, m, 1).toISOString() }
}
export function shiftMonth(month: string, offset: number) {
  const [year, m] = month.split('-').map(Number)
  return currentMonth(new Date(year, m - 1 + offset, 1))
}
export const monthlyTitle = (month: string) => new Date(`${month}-01T12:00:00`).toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })
export const monthlyDate = (value: string | null) => value ? new Date(value).toLocaleString('ru-RU') : 'Не указана'
export function monthlyMetrics(data: MegafonVoiceData): [string, number | null, string][] {
  const s = data.summary
  return [
    ['Всего звонков', s.total, 'По загруженной истории'], ['Входящие', s.inbound, 'Направление: входящий'],
    ['Отвеченные входящие', s.answered, 'Входящий без признака пропуска'], ['Пропущенные входящие', s.missed, 'Входящий с признаком пропуска'],
    ['Доля пропущенных, %', s.inbound ? Math.round(s.missed / s.inbound * 1000) / 10 : null, 'Пропущенные входящие / все входящие × 100'],
    ['Исходящие', s.outbound, 'Направление: исходящий'], ['Направление не указано', s.total - s.inbound - s.outbound, 'Всего минус входящие и исходящие'],
    ['Среднее ожидание ответа, с', s.avg_wait_sec, 'Только отвеченные входящие с известным ожиданием'],
    ['Средний разговор, с', s.avg_talk_sec, 'Звонки с положительной длительностью разговора'],
    ['С записью', s.recordings, 'Наличие записи по истории; без оценки её доступности'], ['Операторов', s.operator_count, 'По именам в истории'],
  ]
}
export const monthlyLimits = [
  'Только загруженная история МегаФона. Отсутствие строк не доказывает отсутствие звонков у оператора связи.',
  'Группа указана лишь у части звонков; эти данные не описывают полную нагрузку смен.',
  'SLA и решение с первого звонка (FCR) не рассчитываются: необходимых данных в истории нет.',
  'Исходный номер 8 800 не подтверждён для каждого звонка. Настройка линии приводится отдельно.',
  'Отчёт пересчитывается по истории; зафиксированная опубликованная версия не создаётся.',
]
export function monthlySheets(data: MegafonVoiceData, month: string, line: string, generatedAt: string): Лист[] {
  const known = data.groups.filter(g => g.name).reduce((sum, g) => sum + g.total, 0)
  const meta: (string | number | null)[][] = [['Источник', 'МегаФон ВАТС'], ['Месяц', month], ['Часовой пояс', Intl.DateTimeFormat().resolvedOptions().timeZone],
    ['Начало включительно', data.period.from], ['Конец не включая', data.period.to], ['Линия по истории', line || 'Все линии'],
    ['Сформирован', generatedAt], ['Последняя синхронизация', data.connection.last_sync_at],
    ['Публичный номер в настройке', data.line.public_number], ['Переадресация в настройке', data.line.forwarding_number]]
  return [
    { имя: 'Сводка', строки: [...meta, [], ['Показатель', 'Значение', 'Расчёт'], ...monthlyMetrics(data)] },
    { имя: 'Операторы', строки: [['Оператор', 'Добавочный', 'Всего', 'Отвеченные входящие', 'Исходящие', 'Пропущенные входящие', 'Средний разговор, с', 'Среднее ожидание ответа, с'], ...data.operators.map(o => [o.name || 'Без оператора', o.extension, o.total, o.inbound_answered, o.outbound, o.missed, o.avg_talk_sec, o.avg_wait_sec])] },
    { имя: 'Группы', строки: [['Группа указана', known, 'из', data.summary.total], ['Группа', 'Всего', 'Отвеченные входящие', 'Пропущенные входящие'], ...data.groups.map(g => [g.name || 'Группа не указана', g.total, g.answered, g.missed])] },
    { имя: 'Ограничения', строки: monthlyLimits.map(text => [text]) },
  ]
}
const html = (value: unknown) => String(value ?? '—').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;')
export function monthlyPrint(sheets: Лист[], month: string) {
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>МегаФон — отчёт ${html(month)}</title><style>@page{size:A4;margin:14mm}body{font:13px Arial,sans-serif;color:#162033}h1{font-size:22px}h2{font-size:17px;margin-top:24px}table{border-collapse:collapse;width:100%;margin:12px 0;table-layout:fixed}td{border:1px solid #bbb;padding:6px;overflow-wrap:anywhere}tr{break-inside:avoid}p{color:#555}@media print{.print-help{display:none}thead{display:table-header-group}}</style></head><body><h1>МегаФон ВАТС · отчёт за ${html(monthlyTitle(month))}</h1><p class="print-help">Печать или сохранение в PDF: Ctrl+P.</p>${sheets.map(s => { const columns = Math.max(1, ...s.строки.map(row => row.length)); return `<h2>${html(s.имя)}</h2><table><tbody>${s.строки.map(row => `<tr>${Array.from({ length: columns }, (_, i) => `<td>${html(row[i])}</td>`).join('')}</tr>`).join('')}</tbody></table>` }).join('')}</body></html>`
}
