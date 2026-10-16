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
}

/** Подробность тревоги словами — из `detail` без ПДн. */
export function подробностьТревоги(a: Alert) {
  const d = a.detail as Record<string, number | string | undefined>
  switch (a.code) {
    case 'sl_low': return d.slPct != null ? `SL ${d.slPct} % при пороге ${d.thresholdPct} %, поступило ${d.offered}` : null
    case 'disk_low': return d.freePct != null ? `свободно ${d.freePct} %` : null
    case 'backup_stale': return d.ageH != null ? `последняя удачная — ${d.ageH} ч назад` : null
    case 'delivery_stuck': return d.oldestSec != null ? `старейшее событие ждёт ${сек(Number(d.oldestSec))}` : null
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
