/**
 * Правила приёма узла как данные экрана: тип документа, значения по умолчанию,
 * подписи полей по-русски и дни недели.
 *
 * Тип повторяет `Reception` узла (ContactHub node/src/rules.ts) — схема та же, что
 * узел отдаёт в `GET /config/reception/schema`. Значения по умолчанию — те, что узел
 * подставляет сам (`waitRules`, `callbackRules`, `controls`): пустое поле на экране
 * значит «как у узла по умолчанию», а не ноль.
 */

export interface Часы { days?: string; from?: string; to?: string; tz?: string }

export type Цель = { action: 'message'; sounds: string[] } | { action: 'forward'; endpoint: string }

export interface Подписанный { code: string; label: string }

export interface ПультОператора {
  commands?: string[]
  staff?: Подписанный[]
  external?: Подписанный[]
  lines?: Подписанный[]
  conference?: boolean
  park?: { maxSec: number } | false
  recording?: 'none' | 'pause'
  recordingAnnounce?: { pause?: string; resume?: string }
  callback?: boolean
  escalate?: boolean
  blindFailed?: 'same_operator' | 'queue'
  holdRemindSec?: number
  holdRepeatSec?: number
  maxHoldSec?: number
  holdAutoResume?: boolean
}

export interface ПравилаПриёма {
  lineId: string
  lineName?: string
  slaTargetSec?: number
  hours: Часы[]
  vip: string[]
  repeatWithinMin: number
  priority: { normal: number; repeat: number; vip: number }
  afterHoursTarget: string
  operators: string[]
  targets: Record<string, Цель>
  greeting?: string
  mohClass?: string
  agentLostSound?: string
  topics?: { code: string; name: string; category?: string; description?: string }[]
  operatorControls?: ПультОператора
  queueAnnounceSec?: number
  queueAnnounceFirstSec?: number
  queueAnnounceSound?: string[]
  callbackOfferSec?: number
  callbackLeadSec?: number
  callbackOfferSound?: string[]
  callbackConfirmSound?: string[]
  callbackRetryMin?: number
  callbackMaxAttempts?: number
  callbackRingSec?: number
  callbackDial?: string
  callbackCallerId?: string
}

/** Что узел подставляет сам, если поля нет (node/src/rules.ts). */
export const УМОЛЧАНИЯ = {
  slaTargetSec: 20,
  queueAnnounceFirstSec: 5,
  queueAnnounceSec: 60,
  callbackOfferSec: 60,
  callbackLeadSec: 10,
  callbackRetryMin: 5,
  callbackMaxAttempts: 3,
  callbackRingSec: 30,
  callbackDial: 'PJSIP/{number}@carrier',
  mohClass: 'default',
  holdRemindSec: 45,
  holdRepeatSec: 30,
  parkMaxSec: 120,
  /** потолок ожидания паспорта, если в паспорте не задан (`fallback.maxTotalSec`) */
  fallbackMaxTotalSec: 90,
}

/** Команды пульта, которые узел умеет (rules.ts ROUTING), — словами. */
export const КОМАНДЫ: Record<string, string> = {
  'call.hold': 'Удержание',
  'call.unhold': 'Снять с удержания',
  'call.dtmf': 'Тоновый набор',
  'call.transfer': 'Перевод',
  'call.consult': 'Консультация',
  'call.consult.cancel': 'Отменить консультацию',
  'call.consult.complete': 'Перевод после консультации',
  'call.consult.conference': 'Конференция из консультации',
  'call.requeue': 'Вернуть в очередь',
  'call.park': 'Парковка',
  'call.unpark': 'Снять с парковки',
  'call.recording': 'Пауза записи',
  'call.callback': 'Поставить обратный звонок',
  'call.escalate': 'Позвать начальника смены',
}

/** Подписи полей для итога проверки и сравнения версий (путь — JSON Pointer). */
export const ПОДПИСИ_ПРАВИЛ: Record<string, string> = {
  '/lineId': 'Код линии',
  '/lineName': 'Название линии',
  '/slaTargetSec': 'Цель SLA линии',
  '/hours': 'Часы приёма',
  '/vip': 'Номера VIP',
  '/repeatWithinMin': 'Окно повтора',
  '/priority': 'Приоритеты',
  '/priority/normal': 'Приоритет обычного звонка',
  '/priority/repeat': 'Приоритет повторного звонка',
  '/priority/vip': 'Приоритет VIP',
  '/afterHoursTarget': 'Вне часов приёма',
  '/operators': 'Трубки узла',
  '/targets': 'Цели сообщений и переадресаций',
  '/greeting': 'Приветствие',
  '/mohClass': 'Музыка ожидания',
  '/agentLostSound': 'Пульт оператора пропал',
  '/topics': 'Темы обращения',
  '/queueAnnounceSec': 'Повтор объявления позиции',
  '/queueAnnounceFirstSec': 'Первое объявление позиции',
  '/queueAnnounceSound': 'Звук перед объявлением позиции',
  '/callbackOfferSec': 'Предложить обратный звонок',
  '/callbackLeadSec': 'Предложение не позже, чем за',
  '/callbackOfferSound': 'Звук предложения перезвонить',
  '/callbackConfirmSound': 'Звук подтверждения',
  '/callbackRetryMin': 'Повтор дозвона',
  '/callbackMaxAttempts': 'Попыток дозвона',
  '/callbackRingSec': 'Сколько звонит набор',
  '/callbackDial': 'Строка набора',
  '/callbackCallerId': 'Номер, который видит звонящий',
  '/operatorControls': 'Пульт оператора',
  '/operatorControls/commands': 'Разрешённые команды пульта',
  '/operatorControls/staff': 'Сотрудники для перевода',
  '/operatorControls/external': 'Внешние номера для перевода',
  '/operatorControls/lines': 'Линии для перевода',
  '/operatorControls/conference': 'Конференция',
  '/operatorControls/park': 'Парковка',
  '/operatorControls/recording': 'Пауза записи',
  '/operatorControls/recordingAnnounce': 'Объявления паузы записи',
  '/operatorControls/callback': 'Обратный звонок от оператора',
  '/operatorControls/escalate': 'Позвать начальника смены',
  '/operatorControls/blindFailed': 'Перевод вслепую не удался',
  '/operatorControls/holdRemindSec': 'Напомнить об удержании через',
  '/operatorControls/holdRepeatSec': 'Повторять напоминание каждые',
  '/operatorControls/maxHoldSec': 'Предел удержания',
  '/operatorControls/holdAutoResume': 'На пределе снять с удержания',
}

// ——— Дни недели ———

/** Порядок на экране — с понедельника; коды — как у узла (`inHours`). */
export const ДНИ = [
  { code: 'mon', name: 'Пн' }, { code: 'tue', name: 'Вт' }, { code: 'wed', name: 'Ср' },
  { code: 'thu', name: 'Чт' }, { code: 'fri', name: 'Пт' }, { code: 'sat', name: 'Сб' }, { code: 'sun', name: 'Вс' },
] as const

const ПО_УЗЛУ = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']

/** «mon-fri,sat» → номера дней с понедельника (0 — Пн). Диапазон через воскресенье («fri-mon») узел понимает — и мы. */
export function дниИз(spec = 'mon-sun'): Set<number> {
  const out = new Set<number>()
  for (const part of spec.split(',')) {
    const [a, b = a] = part.trim().toLowerCase().split('-')
    const from = ПО_УЗЛУ.indexOf(a), to = ПО_УЗЛУ.indexOf(b)
    if (from < 0 || to < 0) continue
    for (let d = from, n = 0; n < 7; d = (d + 1) % 7, n++) {
      out.add((d + 6) % 7)
      if (d === to) break
    }
  }
  return out
}

/** Номера дней с понедельника → строка узла: подряд три и больше — диапазоном («mon-fri»). */
export function дниВ(дни: Set<number>): string {
  if (дни.size === 7) return 'mon-sun'
  const по = [...дни].sort((x, y) => x - y)
  const куски: string[] = []
  for (let i = 0; i < по.length;) {
    let j = i
    while (j + 1 < по.length && по[j + 1] === по[j] + 1) j++
    if (j - i >= 2) куски.push(`${ДНИ[по[i]].code}-${ДНИ[по[j]].code}`)
    else for (let k = i; k <= j; k++) куски.push(ДНИ[по[k]].code)
    i = j + 1
  }
  return куски.join(',')
}

/** К E.164, как у узла (`normalizePhone`): 8…, 7…, 10 цифр → +7…. */
export function кНомеру(raw: string): string {
  const d = raw.replace(/\D/g, '')
  if (d.length === 10) return `+7${d}`
  if (d.length === 11 && (d[0] === '8' || d[0] === '7')) return `+7${d.slice(1)}`
  return d ? `+${d}` : ''
}

/** Список звуков через запятую ↔ массив; пусто — поля нет (у узла своё по умолчанию). */
export const звукиИз = (v?: string[]) => (v ?? []).join(', ')
export const звукиВ = (t: string) => {
  const list = t.split(',').map(x => x.trim()).filter(Boolean)
  return list.length ? list : undefined
}
