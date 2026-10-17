/**
 * Разделы «Телефонии» — один источник для левой рельсы, выпадающего списка на
 * телефоне и маршрутов (docs/voice-app.html ContactHub, §4 «Карта разделов»).
 *
 * Группы — по частоте: работа каждый день, настройка по событию, подключения
 * редко, контроль по необходимости. Раздел, экран которого ещё не собран, в меню
 * всё равно стоит: открывается заглушка с назначением и волной — человек видит,
 * что здесь будет, а не гадает, куда делся пункт.
 */

export type VoiceGroup = 'work' | 'setup' | 'links' | 'control' | 'pbx'

export interface VoiceView {
  key: string
  /** путь под `/voice`; пусто — первый экран */
  path: string
  label: string
  hint: string
  group: VoiceGroup
  /** волна экранов (план ContactHub, §9); `null` — ступень 2, не оценена */
  wave: string | null
  /** экран собран; иначе — заглушка */
  ready: boolean
}

export const VOICE_GROUPS: { key: VoiceGroup; label: string }[] = [
  { key: 'work', label: 'Работа' },
  { key: 'setup', label: 'Настройка' },
  { key: 'links', label: 'Подключения' },
  { key: 'control', label: 'Контроль' },
  { key: 'pbx', label: 'АТС компании · ступень 2' },
]

export const VOICE_VIEWS: VoiceView[] = [
  { key: 'now', path: '', label: 'Сейчас', group: 'work', wave: '2.1', ready: true,
    hint: 'принимается ли линия и кто ждёт' },
  { key: 'calls', path: 'calls', label: 'Журнал звонков', group: 'work', wave: '2.1', ready: true,
    hint: 'все звонки линии: найти звонок по последним цифрам номера' },
  { key: 'callbacks', path: 'callbacks', label: 'Обратные звонки', group: 'work', wave: '2.3', ready: true,
    hint: 'задачи «перезвонить»: от звонящего и от оператора' },
  { key: 'stats', path: 'stats', label: 'Статистика', group: 'work', wave: '2.3', ready: true,
    hint: 'все звонки линии, а не только дошедшие до контакт-центра' },
  { key: 'report', path: 'report', label: 'Отчёт за месяц', group: 'work', wave: '2.6', ready: true,
    hint: 'отчёт по линии для заказчика: пропущенные, время ответа, решённые с первого звонка; выпуск и выгрузка' },
  { key: 'reconcile', path: 'reconcile', label: 'Сверка с оператором', group: 'work', wave: '2.6', ready: true,
    hint: 'детализация оператора связи против журнала узла: потерянные звонки и расхождения длительности' },

  { key: 'reception', path: 'reception', label: 'Правила приёма', group: 'setup', wave: '2.2', ready: true,
    hint: 'часы, VIP, очередь и ожидание, обратный звонок, запасной сценарий' },
  { key: 'passport', path: 'passport', label: 'Паспорт для КЦ', group: 'setup', wave: '2.4', ready: true,
    hint: 'что контакт-центр знает о линии: приветствие, итоги, приватность, допуск' },
  { key: 'targets', path: 'targets', label: 'Сотрудники и переводы', group: 'setup', wave: '2.2', ready: true,
    hint: 'цели перевода одним местом: паспорт, правила и пульт оператора' },
  { key: 'sounds', path: 'sounds', label: 'Звуки', group: 'setup', wave: '2.5', ready: true,
    hint: 'приветствие, музыка ожидания, предложение перезвонить, свои записи' },
  { key: 'enrichment', path: 'enrichment', label: 'Распознавание и подсказки', group: 'setup', wave: '2.5', ready: true,
    hint: 'живое обогащение: порог уверенности, что видит оператор' },

  { key: 'cc', path: 'cc', label: 'Контакт-центры', group: 'links', wave: '2.4', ready: true,
    hint: 'подключение КЦ, сверка ключа, допуск операторов' },
  { key: 'webhooks', path: 'webhooks', label: 'Системы и вебхуки', group: 'links', wave: '2.5', ready: true,
    hint: 'ключи для систем заказчика и подписки на события узла' },

  { key: 'versions', path: 'versions', label: 'Версии и изменения', group: 'control', wave: '2.2', ready: true,
    hint: 'версии настроек, сравнение «было — стало», откат и журнал изменений' },
  { key: 'audit', path: 'audit', label: 'Аудит доступа', group: 'control', wave: '2.5', ready: true,
    hint: 'кто открывал номер, запись и расшифровку: когда и по какой причине' },
  { key: 'retention', path: 'retention', label: 'Записи и хранение', group: 'control', wave: '2.5', ready: true,
    hint: 'сроки хранения записей и расшифровок, место на диске, что удалено по сроку' },
  { key: 'health', path: 'health', label: 'Состояние узла', group: 'control', wave: '2.5', ready: true,
    hint: 'транк, Asterisk, связь с КЦ, распознавание, диск и сертификаты — с историей' },

  { key: 'extensions', path: 'extensions', label: 'Внутренние номера', group: 'pbx', wave: null, ready: false,
    hint: 'внутренние номера сотрудников и трубки' },
  { key: 'outbound', path: 'outbound', label: 'Исходящие', group: 'pbx', wave: null, ready: false,
    hint: 'исходящие звонки и номер, который видит собеседник' },
]

export const voicePath = (v: VoiceView) => (v.path ? `/voice/${v.path}` : '/voice')

/** Пункт меню по адресу: самый длинный совпавший путь, иначе «Сейчас». */
export function voiceViewFor(pathname: string): VoiceView {
  return [...VOICE_VIEWS].filter(v => v.path)
    .find(v => pathname === voicePath(v) || pathname.startsWith(`${voicePath(v)}/`)) ?? VOICE_VIEWS[0]
}
