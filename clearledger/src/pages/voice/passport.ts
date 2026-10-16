/**
 * Паспорт для КЦ как данные экрана: тип, подписи полей и словари значений.
 *
 * Тип повторяет схему `Passport` протокола (ContactHub protocol/openapi.yaml):
 * паспорт уходит в контакт-центр новой версией, поэтому на экране каждое
 * изменение подписано «уйдёт в контакт-центр». Номера телефонов в паспорте нет —
 * он только о том, что КЦ видит и может.
 */
import type { Часы } from './reception'

export interface Паспорт {
  version: number
  effectiveAt?: string
  minAcceptedVersion?: number
  presentation: { greeting?: string; brandName?: string; operatorNameMode?: 'full' | 'first_name' | 'pseudonym' }
  disposition?: { codes?: string[]; requiredFields?: Record<string, string[]>; wrapupSec?: number }
  privacy: { phoneMask: 'none' | 'last4' | 'hidden'; cardFields: string[]; postContactAccessHours?: number; recordingDownload?: false }
  access: { admission?: 'manual' | 'auto'; hours?: Часы[]; cidr?: string[]; requireMfa?: boolean }
  actions: {
    transferTargets?: { code: string; kind: 'client_staff' | 'external'; label: string }[]
    ccOperatorTransfer?: boolean
    takeover?: boolean
    createTicket?: boolean
  }
  fallback: { afterSec?: number; retryAfterSec?: number; maxTotalSec?: number; target?: string }
  offer?: { maxTtlSec?: number; allowPick?: boolean }
  kcRetention?: { dispositionFields?: string[]; ticketNumber?: boolean; preferredOperator?: boolean; days?: number }
  liveEnrichment?: { enabled?: boolean; showTranscript?: boolean; llmEnabled?: boolean; threshold?: number; cloudFallback?: false }
}

/** Значения по умолчанию схемы протокола. */
export const УМОЛЧАНИЯ_ПАСПОРТА = {
  wrapupSec: 120,
  postContactAccessHours: 2,
  afterSec: 20,
  retryAfterSec: 20,
  maxTotalSec: 90,
  maxTtlSec: 25,
  threshold: 0.8,
}

export const ИМЯ_ОПЕРАТОРА: Record<string, string> = {
  full: 'имя и фамилия',
  first_name: 'только имя',
  pseudonym: 'псевдоним',
}

export const МАСКА: Record<string, string> = {
  none: 'номер целиком',
  last4: 'последние 4 цифры',
  hidden: 'номер скрыт',
}

/** Поля карточки звонящего, которые знает окно заказчика (testdata, протокол). */
export const ПОЛЯ_КАРТОЧКИ: Record<string, string> = {
  'identity.kind': 'кто звонит: клиент, сотрудник, неизвестный',
  'identity.displayName': 'имя звонящего',
  'identity.repeat': 'звонит повторно',
  station: 'станция',
  session: 'сессия зарядки',
  openTickets: 'открытые заявки',
  balance: 'баланс',
}

export const ПОДПИСИ_ПАСПОРТА: Record<string, string> = {
  '/version': 'Номер версии',
  '/effectiveAt': 'Действует с',
  '/minAcceptedVersion': 'Старшая версия, которую ещё принимаем',
  '/presentation': 'Представление',
  '/presentation/greeting': 'Приветствие оператора',
  '/presentation/brandName': 'Название для оператора',
  '/presentation/operatorNameMode': 'Как называть оператора',
  '/disposition': 'Итоги',
  '/disposition/codes': 'Коды итога',
  '/disposition/requiredFields': 'Обязательные поля итога',
  '/disposition/wrapupSec': 'Время на итог после разговора',
  '/privacy': 'Приватность',
  '/privacy/phoneMask': 'Номер звонящего у оператора',
  '/privacy/cardFields': 'Поля карточки звонящего',
  '/privacy/postContactAccessHours': 'Доступ к звонку после разговора',
  '/privacy/recordingDownload': 'Скачивание записи в КЦ',
  '/access': 'Допуск операторов',
  '/access/admission': 'Как допускать операторов',
  '/access/hours': 'Часы работы операторов',
  '/access/cidr': 'Сети, из которых можно работать',
  '/access/requireMfa': 'Вторая проверка входа',
  '/actions': 'Действия оператора',
  '/actions/transferTargets': 'Цели перевода',
  '/actions/ccOperatorTransfer': 'Перевод между операторами КЦ',
  '/actions/takeover': 'Перехват разговора старшим',
  '/actions/createTicket': 'Создание заявки',
  '/fallback': 'Запасной сценарий',
  '/fallback/afterSec': 'Нет готовых операторов — ждём',
  '/fallback/retryAfterSec': 'Повторно предлагаем через',
  '/fallback/maxTotalSec': 'Потолок ожидания',
  '/fallback/target': 'Цель запасного сценария',
  '/offer': 'Предложение оператору',
  '/offer/maxTtlSec': 'Сколько ждём ответа оператора',
  '/offer/allowPick': 'Оператор сам выбирает звонок из очереди',
  '/kcRetention': 'Что КЦ хранит',
  '/kcRetention/dispositionFields': 'Поля итога, которые КЦ хранит',
  '/kcRetention/ticketNumber': 'Номер заявки',
  '/kcRetention/preferredOperator': 'Предпочтительный оператор',
  '/kcRetention/days': 'Сколько дней КЦ хранит',
  '/liveEnrichment': 'Распознавание и подсказки',
  '/liveEnrichment/enabled': 'Подсказки оператору',
  '/liveEnrichment/showTranscript': 'Показывать оператору расшифровку',
  '/liveEnrichment/llmEnabled': 'Языковая модель для подсказок',
  '/liveEnrichment/threshold': 'Порог уверенности',
  '/liveEnrichment/cloudFallback': 'Облачный запасной вариант',
}

/** Подписи политики хранения узла (Policy). */
export const ПОДПИСИ_ХРАНЕНИЯ: Record<string, string> = {
  '/recordingsDays': 'Записи разговоров, дней',
  '/transcriptsDays': 'Расшифровки, дней',
  '/numberMonths': 'Номер в журнале, месяцев',
  '/recordingDownload': 'Скачивание записей',
  '/fcrWindowMin': 'Окно FCR, минут',
  '/shortAbandonSec': 'Коротко брошенный, секунд',
  '/callbackDueSec': 'Обратный звонок просрочен через, секунд',
  '/alertSlPct': 'Тревога: SL ниже, %',
  '/alertSlMinOffered': 'Тревога SL: не меньше звонков за час',
}
