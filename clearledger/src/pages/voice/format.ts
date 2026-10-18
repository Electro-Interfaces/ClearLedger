/**
 * Как «Телефония» называет время, исходы, состояния и этапы звонка.
 *
 * Узел говорит кодами (`fallback_forward`, `callback_offered`), а администратор
 * заказчика — не телефонист: код ему ничего не скажет. Здесь коды становятся
 * словами; неизвестный код показывается как есть, моноширинным, — лучше честный
 * код, чем пустое место.
 */
import type { Alert, LiveState, Outcome } from '@/services/voiceService'

/** «16 окт., 14:30:05». Год — только когда не текущий. */
export function когда(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', {
    day: 'numeric', month: 'short',
    year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

/** «14:30:05» — внутри одного звонка дата одна, её не повторяем. */
export function время(iso?: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function дата(iso?: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

/** Секунды словами: «45 с», «3 мин 05 с», «1 ч 12 мин». */
export function сек(s?: number | null) {
  if (s == null) return '—'
  const в = Math.round(s)
  if (в < 60) return `${в} с`
  const м = Math.floor(в / 60)
  if (м < 60) return `${м} мин ${String(в % 60).padStart(2, '0')} с`
  return `${Math.floor(м / 60)} ч ${м % 60} мин`
}

/** Секунды с момента ISO до `сейчас` — для ожидания, которое идёт на экране. */
export function прошло(iso: string, сейчас: number) {
  return Math.max(0, (сейчас - Date.parse(iso)) / 1000)
}

export function процент(v?: number | null) {
  return v == null ? '—' : `${v.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} %`
}

export function число(v?: number | null) {
  return v == null ? '—' : v.toLocaleString('ru-RU')
}

export const ИСХОД: Record<Outcome, string> = {
  connected: 'отвечен',
  abandoned: 'брошен',
  fallback_message: 'запасной сценарий: сообщение',
  fallback_forward: 'запасной сценарий: переадресация',
  callback: 'выбрал «перезвонить»',
  transferred: 'переведён сотруднику',
  interrupted: 'прерван перезапуском узла',
  callback_reached: 'перезвонили, дозвонились',
  callback_not_reached: 'перезвонили, не дозвонились',
  callback_canceled: 'обратный звонок снят',
}

/** Исход, требующий внимания: им окрашивается строка журнала (вместе со словом). */
export function плохойИсход(o?: Outcome | null) {
  return o === 'abandoned' || o === 'interrupted' || o === 'callback_not_reached'
}

export const СОСТОЯНИЕ: Record<LiveState, string> = {
  ivr: 'приветствие',
  waiting: 'ждёт',
  offered: 'предложен оператору',
  dialing: 'набор обратного звонка',
  connected: 'разговор',
  held: 'на удержании',
  parked: 'на парковке',
  consulting: 'консультация',
  fallback: 'запасной сценарий',
  wrapup: 'постобработка',
}

export const ФЛАГ: Record<string, string> = {
  vip: 'VIP',
  repeat: 'повтор',
  after_hours: 'вне часов',
  callback: 'обратный звонок',
  transferred: 'перевод',
  recorded: 'запись',
}

export const ОБСЛУЖИЛ: Record<string, string> = {
  cc: 'контакт-центр',
  local: 'сотрудник заказчика',
  fallback: 'запасной сценарий',
  none: 'никто',
}

/** Этапы звонка (`call_stages` узла): что услышал и прошёл звонящий. */
export const ЭТАП: Record<string, string> = {
  arrived: 'звонок поступил',
  answered: 'узел ответил',
  card_ready: 'карточка звонящего готова',
  rules: 'правила приёма',
  waiting: 'встал в очередь',
  queue_announced: 'объявлена позиция',
  callback_offered: 'предложено перезвонить',
  callback_scheduled: 'выбрал «перезвонить»',
  callback_task: 'поставлена задача перезвонить',
  callback_dial: 'набор обратного звонка',
  callback_failed: 'обратный звонок не прошёл',
  offer: 'предложен оператору',
  offer_failed: 'оператор не принял',
  connected: 'соединён с оператором',
  agent_announced: 'оператору объявлена линия',
  enrich_started: 'началась живая расшифровка',
  enrich_unavailable: 'живая расшифровка недоступна',
  recording_started: 'запись началась',
  recording_paused: 'запись на паузе',
  recording_resumed: 'запись продолжена',
  recording_finished: 'запись закончилась',
  recording_failed: 'запись не удалась',
  opch: 'действие в пульте оператора',
  cc_command: 'команда контакт-центра',
  hold: 'на удержании',
  unhold: 'снят с удержания',
  hold_timeout: 'удержание дольше предела',
  park: 'на парковке',
  unpark: 'снят с парковки',
  park_timeout: 'парковка дольше предела',
  consult: 'консультация',
  consult_connected: 'консультант на линии',
  consult_complete: 'консультация завершена',
  consult_end: 'консультация закончилась',
  conference: 'конференция',
  transfer: 'перевод',
  transfer_requested: 'запрошен перевод',
  transfer_request_end: 'запрос перевода закрыт',
  transfer_staff: 'перевод сотруднику',
  transfer_line: 'перевод на линию',
  forward: 'переадресация',
  requeue: 'вернулся в очередь',
  agent_lost: 'пульт оператора пропал',
  escalation_requested: 'запрошен старший',
  operator_hangup: 'оператор положил трубку',
  disposition: 'оператор записал итог',
  fallback: 'запасной сценарий',
  cc_event_rejected: 'узел отклонил событие КЦ',
  node_restart: 'узел перезапустился, разговор сохранён',
  interrupted: 'прерван перезапуском узла',
  ended: 'звонок закончен',
}

export const ТРЕВОГА: Record<Alert['code'], string> = {
  trunk_down: 'SIP-транк не отвечает: звонки линии не доходят до узла',
  cc_offline: 'Контакт-центр не на связи: звонки уходят в запасной сценарий',
  sl_low: 'Уровень обслуживания за час ниже порога',
  disk_low: 'На диске записей мало места',
  delivery_stuck: 'События не доходят до получателя больше суток',
  backup_stale: 'Резервная копия узла давно не делалась',
  asr_down: 'Распознавание речи недоступно: подсказок оператору нет, расшифровки не пишутся',
  cert_expiring: 'Скоро истекает сертификат узла',
  cert_expired: 'Истёк сертификат узла: связь с пространством или контакт-центром может не устанавливаться',
}

/** Подробность тревоги словами — из `detail` без ПДн. */
export function подробностьТревоги(a: Alert) {
  const d = a.detail as Record<string, number | string | undefined>
  switch (a.code) {
    case 'sl_low': return d.slPct != null ? `SL ${d.slPct} % при пороге ${d.thresholdPct} %, поступило ${d.offered}` : null
    case 'disk_low': return d.freePct != null ? `свободно ${d.freePct} %` : null
    case 'backup_stale': return d.ageH != null ? `последняя удачная — ${d.ageH} ч назад` : null
    case 'delivery_stuck': return d.oldestSec != null ? `старейшее событие ждёт ${сек(Number(d.oldestSec))}` : null
    case 'cert_expiring':
    case 'cert_expired': {
      const certs = (a.detail.certs ?? []) as { name?: string; daysLeft?: number | null }[]
      return certs.length ? certs.map(c => (c.daysLeft != null && c.daysLeft >= 0 ? `${c.name}: ${c.daysLeft} дн.` : `${c.name}: истёк`)).join('; ') : null
    }
    default: return null
  }
}

/** Оператор строкой: сотрудник — трубкой, оператор КЦ — его непрозрачным id. */
export function оператор(op?: { kind: 'staff' | 'cc'; id: string; name?: string | null } | null) {
  if (!op) return '—'
  if (op.kind === 'staff') return op.name || `сотрудник ${op.id}`
  return `оператор КЦ ${op.id.length > 10 ? `${op.id.slice(0, 8)}…` : op.id}`
}

/** Начало сегодняшних суток в ISO — для фильтров «за сегодня». */
export function началоДня(сдвигДней = 0) {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + сдвигДней)
  return d.toISOString()
}

/** Присутствие оператора словами (канал оператора и реестр допуска КЦ). */
/**
 * Местная дата «ГГГГ-ММ-ДД» для имени файла. `toISOString().slice(0, 10)` дал бы дату в UTC:
 * местная полночь в Москве — это ещё вчерашний день по UTC.
 */
export function деньФайла(когда: string | number) {
  const d = new Date(когда)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export const ПРИСУТСТВИЕ: Record<string, string> = {
  available: 'готов', ready: 'готов', online: 'трубка на связи', away: 'отошёл', break: 'перерыв',
  offline: 'не на связи', unknown: 'неизвестно', wrapup: 'постобработка',
}

/** Действие журнала доступа словами (node-admin-api.yaml, `AuditEntry.action`). */
export const ДЕЙСТВИЕ_АУДИТА: Record<string, string> = {
  'call.view': 'открыл карточку звонка',
  'call.number': 'открыл номер целиком',
  'call.search_number': 'искал по номеру',
  'journal.export': 'выгрузил журнал звонков',
  'recording.ticket': 'открыл запись',
  'recording.play': 'прослушал запись',
  'recording.download': 'скачал запись',
  'recording.delete': 'удалил запись досрочно',
  'transcript.read': 'открыл расшифровку',
  'retention.hold': 'запретил удаление по сроку',
  'retention.release': 'снял запрет удаления',
  'callback.cancel': 'снял обратный звонок',
  'config.import': 'импорт настроек из файла',
  'config.draft': 'завёл черновик настроек',
  'config.draft_delete': 'удалил черновик настроек',
  'config.apply': 'применил настройки',
  'config.rollback': 'откатил настройки',
  'config.targets': 'изменил цели перевода',
  'sound.upload': 'загрузил звук',
  'sound.delete': 'удалил звук',
  'cc.invite': 'пригласил контакт-центр',
  'cc.activate': 'включил контакт-центр',
  'cc.state': 'сменил состояние контакт-центра',
  'cc.operator': 'изменил допуск оператора КЦ',
  'webhook.add': 'добавил получателя событий',
  'webhook.delete': 'удалил получателя событий',
  'reconciliation.upload': 'загрузил детализацию оператора связи',
  'purge.run': 'удалил по сроку хранения',
}

/** Кто сделал: человек — по имени, иначе вид входа. */
export function ктоСделал(a?: { sub?: string; name?: string | null; kind?: string } | null) {
  if (!a) return '—'
  if (a.name) return a.name
  if (a.kind === 'node') return 'узел'
  if (a.kind === 'service') return `система ${a.sub ?? ''}`.trim()
  if (a.kind === 'cc') return 'контакт-центр'
  return a.sub ?? '—'
}

/** Части узла словами, в порядке экрана: сначала то, без чего линия не принимается. */
export const ЧАСТЬ: Record<string, string> = {
  trunk: 'SIP-транк',
  ari: 'Asterisk',
  cc: 'Связь с контакт-центром',
  db: 'База узла',
  asr: 'Распознавание речи',
  llm: 'Языковая модель',
  disk: 'Диск записей',
  cert: 'Сертификаты',
  backup: 'Резервная копия',
  node: 'Процесс узла',
}

export const СОСТОЯНИЕ_ЧАСТИ: Record<string, string> = {
  up: 'работает',
  warn: 'работает, нужно внимание',
  down: 'не работает',
  unknown: 'не удалось проверить',
  off: 'выключено',
  started: 'запущен',
  stopped: 'остановлен',
}

/** Байты словами: 1,4 ГБ. */
export function объём(b?: number | null) {
  if (b == null) return '—'
  const ед = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']
  let v = b
  let i = 0
  while (v >= 1024 && i < ед.length - 1) { v /= 1024; i++ }
  return `${v.toLocaleString('ru-RU', { maximumFractionDigits: v < 10 && i > 0 ? 1 : 0 })} ${ед[i]}`
}

// ——— Волна 7: показатель → звонки ———

/**
 * Журнал ровно тех обращений, из которых сложилось число плитки (`/calls?metric=`):
 * тот же период и линия; `back` — откуда пришли, чтобы вернуться к той же плитке.
 * Ссылка — адрес: её можно переслать, она откроет тот же список.
 */
export function журналПо(metric: string, о: { from: string; to: string; line?: string; servedBy?: string; back?: string }) {
  const q = new URLSearchParams({ metric, from: о.from, to: о.to })
  if (о.line) q.set('line', о.line)
  if (о.servedBy) q.set('servedBy', о.servedBy)
  if (о.back) q.set('back', о.back)
  return `/voice/calls?${q}`
}

/** Причины пропуска (node stats.ts MISSED_REASONS) — для `missed:<причина>` и правила missedCallback. */
export const ПРИЧИНА_ПРОПУСКА: Record<string, string> = {
  after_hours: 'вне часов приёма',
  callback: 'выбрал обратный звонок',
  fallback: 'запасной сценарий без оператора',
  forward: 'переадресация без ответа',
  before_queue: 'положил трубку до очереди',
  abandoned_short: 'коротко брошен в очереди',
  abandoned: 'брошен в очереди',
  interrupted: 'прерван перезапуском узла',
  other: 'прочее',
}

/** Причины запасного сценария (`fallback:<причина>`). */
export const ПРИЧИНА_ЗАПАСНОГО: Record<string, string> = {
  max_wait: 'потолок ожидания',
  kc_offline: 'КЦ не на связи',
  no_command: 'КЦ не назначил оператора',
  rule: 'правило',
}

/** Единица счёта показателя: обращение, отрезок на линии, задача перезвона. */
export const ЕДИНИЦА: Record<string, string> = {
  call: 'обращений',
  segment: 'отрезков на линии',
  task: 'задач перезвона',
}

// ——— Волна 7: участки звонка ———

/** Участок словами: вид и роль. */
export function участок(l: { kind: string; role?: string }) {
  if (l.kind === 'talk') {
    return ({
      transfer: 'Разговор после перевода', staff_transfer: 'Переведён сотруднику', consult_transfer: 'Передан после консультации',
      forward: 'Переадресация', callback: 'Обратный звонок',
    } as Record<string, string>)[l.role ?? ''] ?? 'Разговор'
  }
  if (l.kind === 'attempt') return l.role === 'transfer' || l.role === 'staff_transfer' ? 'Перевод не состоялся' : 'Не ответил'
  return ({
    ivr: 'Приветствие', queue: 'Ждал', consult: 'Консультация', park: 'Парковка', fallback: 'Запасной сценарий',
    dial: 'Набор обратного звонка',
  } as Record<string, string>)[l.kind] ?? l.kind
}

/** Кто на участке: оператор КЦ — псевдонимом, сотрудник — подписью из правил или трубкой. */
export function ктоНаУчастке(w?: { kind: string; id: string; label?: string | null; endpoint?: string } | null) {
  if (!w) return null
  if (w.kind === 'cc') return оператор({ kind: 'cc', id: w.id })
  if (w.kind === 'line') return `линия ${w.id}`
  const имя = w.label || w.id
  return w.kind === 'external' ? `внешний номер ${имя}` : w.endpoint && w.endpoint !== имя ? `${имя} (${w.endpoint})` : имя
}

/** Чем кончился участок (node history.ts). */
export const ИТОГ_УЧАСТКА: Record<string, string> = {
  queued: 'встал в очередь',
  answered: 'ответили',
  abandoned: 'звонящий положил трубку',
  fallback: 'ушёл в запасной сценарий',
  callback: 'выбрал обратный звонок',
  transferred: 'передан дальше',
  requeued: 'вернули в очередь',
  agent_lost: 'пульт оператора пропал',
  transfer_line: 'переведён на другую линию',
  completed: 'передал звонок',
  returned: 'вернулся к звонящему',
  caller_hangup: 'звонящий завершил',
  operator_hangup: 'оператор завершил',
  parked: 'припаркован',
  park_timeout: 'парковка истекла',
  unparked: 'снят с парковки',
  ended: 'завершён',
  node_restart: 'прерван перезапуском узла',
  declined: 'отклонил',
  busy: 'занят',
  expired: 'не ответил вовремя',
  unreachable: 'недоступен',
  target_no_answer: 'не ответил',
  canceled: 'отменено',
  reached: 'дозвонились',
  not_reached: 'не дозвонились',
  failed: 'не удалось',
}

/** Участок, который человек ищет глазами: кто говорил, кто не ответил, куда ушло. Остальное — технические этапы. */
export const ГЛАВНЫЙ_УЧАСТОК = new Set(['queue', 'attempt', 'talk', 'consult', 'fallback', 'dial'])

// ——— Волна 7: долг перезвона ———

export const ИСПОЛНИТЕЛЬ = (a?: { kind: 'cc' } | { kind: 'staff'; id?: string | null; name?: string | null } | null) =>
  !a ? 'не назначен' : a.kind === 'cc' ? 'контакт-центр' : a.name || a.id || 'сотрудник'

export const ИТОГ_ДОЛГА: Record<string, string> = {
  reached: 'дозвонились',
  not_reached: 'не дозвонились',
  refused: 'отказ',
  resolved: 'решено иначе',
  canceled: 'снят',
}

export const КТО_ЗАВЁЛ: Record<string, string> = {
  caller: 'звонящий',
  operator: 'оператор',
  space: 'администратор',
  auto: 'правило',
}
