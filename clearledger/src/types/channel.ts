/**
 * Типы: Источники, Каналы, Pipeline.
 *
 * Источник = техническое подключение (URL, credentials, типы документов).
 * Канал = pipeline обработки данных: несколько источников → обработка → сверка → результат.
 */

// ─── Источники (Sources) ─────────────────────────────────

export type SourceType = 'rest' | '1c' | 'email' | 'ftp' | 'webhook' | 'watch-dir' | 'edi' | 'cloud' | 'msto' | 'tradecorp'

export type SourceStatus = 'connected' | 'disconnected' | 'error' | 'draft'

/** Тип документа, доступный в источнике */
export interface SourceDocType {
  id: string
  name: string
  /** Endpoint/метод для получения этого типа */
  endpoint?: string
  description?: string
}

/** Источник данных — подключение + доступные типы документов */
export interface Source {
  id: string
  name: string
  type: SourceType
  status: SourceStatus
  description?: string
  /** Настройки подключения (URL, логин, пароль, и т.д.) */
  connection: Record<string, string>
  /** Типы документов, доступные в этом источнике */
  docTypes: SourceDocType[]
  /** Сообщение об ошибке */
  errorMessage?: string
  /** Реальный source_type бэкенда (sts|onec_operational|…) — round-trip в API-режиме */
  backendType?: string
  createdAt: string
  updatedAt: string
}

export const SOURCE_TYPE_META: Record<SourceType, { label: string; description: string; icon: string }> = {
  rest: { label: 'REST API', description: 'HTTP/REST подключение к внешнему API', icon: 'Globe' },
  '1c': { label: '1С Обмен', description: 'OData или файловый обмен с 1С', icon: 'Database' },
  email: { label: 'Email', description: 'Входящая почта с документами', icon: 'Mail' },
  ftp: { label: 'FTP/SFTP', description: 'Файловый сервер', icon: 'HardDrive' },
  webhook: { label: 'Webhook', description: 'Входящий HTTP webhook', icon: 'Webhook' },
  'watch-dir': { label: 'Папка', description: 'Мониторинг локальной/сетевой папки', icon: 'FolderOpen' },
  edi: { label: 'ЭДО', description: 'Электронный документооборот (Контур, СБИС)', icon: 'FileCheck' },
  cloud: { label: 'Облако', description: 'Google Drive, OneDrive, Dropbox', icon: 'Cloud' },
  msto: { label: 'MSTO', description: 'Онлайн-заказы (Яндекс, FuelUp, Benzuber)', icon: 'Fuel' },
  tradecorp: { label: 'TradeCorp', description: 'Корпоративные карты (процессинг)', icon: 'CreditCard' },
}

/**
 * Дефолтные типы документов для STS REST API (pos.autooplata.ru/tms).
 *
 * Один STS-источник покрывает всю сеть АЗС ГИГ (system_id 65 и 15 —
 * технические коды, не разные компании). Все типы документов берутся
 * с одного хоста и одного login/password.
 */
export function defaultStsDocTypes(): SourceDocType[] {
  return [
    { id: 'shift_report', name: 'Сменные отчёты', endpoint: '/v1/report/shift_report', description: 'Продажи, резервуары, ТРК, оплаты' },
    { id: 'receipt', name: 'Поступления (ТТН)', endpoint: '/v1/report/receipts', description: 'Приём топлива, плотность, масса' },
    { id: 'price', name: 'Цены', endpoint: '/v1/prices', description: 'Текущие цены на топливо' },
    { id: 'sts_transactions', name: 'Операции отпуска', endpoint: '/v2/transactions', description: 'Индивидуальные транзакции отпуска на ТРК' },
    { id: 'sts_coupons', name: 'Купоны и талоны', endpoint: '/v2/coupons', description: 'Операции по талонам и купонам на топливо' },
    { id: 'sts_tanks', name: 'Остатки резервуаров', endpoint: '/v1/tanks', description: 'Уровни, объёмы и плотности в резервуарах' },
  ]
}

/** Дефолтные типы документов для MSTO (онлайн-заказы) */
export function defaultMstoDocTypes(): SourceDocType[] {
  return [
    { id: 'msto_transactions', name: 'Транзакции онлайн-заказов', endpoint: '/private/transactions', description: 'Заказы агрегаторов: Яндекс, FuelUp, Benzuber' },
    { id: 'msto_service_points', name: 'Станции обслуживания', endpoint: '/private/servicePoints', description: 'Список подключённых АЗС/АКАЗС' },
    { id: 'msto_tariffs', name: 'Тарифы агрегаторов', endpoint: '/private/tariffs', description: 'Справочник агрегаторов и тарифов' },
  ]
}

/** Дефолтные типы документов для TradeCorp (корпоративные карты) */
export function defaultTradecorpDocTypes(): SourceDocType[] {
  return [
    { id: 'corp_transactions', name: 'Транзакции по картам', endpoint: '/v1/transactions_get', description: 'Заправки, возвраты, операции по корп. картам' },
    { id: 'corp_summary', name: 'Сводка по станциям', endpoint: '/v1/transactions_summary', description: 'Агрегированные итоги по станциям и картам' },
  ]
}

// ─── Каналы (Channels) — pipeline обработки данных ──────

/**
 * Конкретная АЗС, обрабатываемая каналом, вместе с тех. сетью STS.
 *
 * Раньше канал хранил только `stationCodes: number[]` и неявно использовал
 * один `systemCode` из source.connection. Когда у клиента несколько сетей
 * (у ГИГ — 65 и 15), это перестаёт работать: одна станция может
 * существовать только в одной из сетей. Поэтому привязка теперь явная.
 */
export interface ChannelStation {
  /** Код станции в STS (5, 208, 209, ...) */
  code: number
  /** Технический ID сети STS (65 или 15 для ГИГ) */
  systemId: number
  /** Человекочитаемое имя — для UI и логов (необязательно) */
  name?: string
  /** ID ServiceLocation, если станция выбрана из справочника */
  locationId?: string
}

export type ChannelStatus = 'active' | 'paused' | 'error' | 'draft'

export type DuplicatePolicy = 'skip' | 'warn' | 'overwrite'

/** Поток данных внутри канала — что забираем и куда кладём */
export interface ChannelStream {
  id: string
  /** ID типа документа из источника */
  docTypeId: string
  /** ID источника, из которого забираем */
  sourceId: string
  /** Название (копируется из SourceDocType.name) */
  name: string
  /** Шаблон каталога хранения */
  catalogTemplate: string
  /** Фильтры (станции, типы и т.д.) */
  filters: Record<string, string>
  /** Активен ли поток */
  enabled: boolean
}

/** Этап pipeline обработки данных */
export type StageType = 'fetch' | 'normalize' | 'reconcile' | 'validate' | 'transform'

export interface ChannelStage {
  id: string
  type: StageType
  name: string
  /** Для fetch — из какого источника */
  sourceId?: string
  /** Для reconcile — какие потоки сверяем */
  reconcileStreamIds?: string[]
  /** Настройки этапа */
  config: Record<string, any>
  enabled: boolean
  order: number
}

export const STAGE_TYPE_META: Record<StageType, { label: string; description: string; icon: string }> = {
  fetch: { label: 'Загрузка', description: 'Получение данных из источника', icon: 'Download' },
  normalize: { label: 'Нормализация', description: 'Приведение к единому формату', icon: 'Shuffle' },
  reconcile: { label: 'Сверка', description: 'Сравнение данных между потоками', icon: 'GitCompare' },
  validate: { label: 'Валидация', description: 'Проверка правил и ограничений', icon: 'ShieldCheck' },
  transform: { label: 'Трансформация', description: 'Преобразование для выгрузки', icon: 'ArrowRightLeft' },
}

/** Правило сверки между потоками */
export interface ReconcileRule {
  id: string
  name: string
  /** Потоки для сверки (минимум 2) */
  streamIds: string[]
  /** Поле для сопоставления записей */
  matchField: string
  /** Поля для сравнения значений */
  compareFields: string[]
  /** Допустимое расхождение (%) */
  tolerance: number
  enabled: boolean
}

/** Запись лога синхронизации */
export interface SyncLogEntry {
  timestamp: string
  level: 'info' | 'warn' | 'error' | 'success'
  event: 'AUTH' | 'SYNC' | 'LOAD' | 'DONE' | 'ERROR' | 'SKIP' | 'DUPLICATE' | 'RECONCILE'
  message: string
}

/** Результат синхронизации */
export interface SyncResult {
  channelId: string
  startedAt: string
  finishedAt: string
  loaded: number
  skipped: number
  duplicates: number
  errors: number
  log: SyncLogEntry[]
}

// ─── Расписание ─────────────────────────────────────────

export type ScheduleMode = 'manual' | 'interval' | 'cron'

export interface ScheduleConfig {
  mode: ScheduleMode
  /** Интервал в минутах (для mode='interval') */
  intervalMinutes?: number
  /** Cron-выражение (для mode='cron') */
  cronExpression?: string
  /** Активные часы — не загружать вне диапазона */
  activeHoursFrom?: string
  activeHoursTo?: string
  /** Пауза при ошибках */
  pauseOnError: boolean
  /** Макс. кол-во повторов при ошибке */
  maxRetries: number
}

export const DEFAULT_SCHEDULE: ScheduleConfig = {
  mode: 'manual',
  intervalMinutes: 60,
  pauseOnError: true,
  maxRetries: 3,
}

export const INTERVAL_OPTIONS = [
  { value: 5, label: 'Каждые 5 минут' },
  { value: 15, label: 'Каждые 15 минут' },
  { value: 30, label: 'Каждые 30 минут' },
  { value: 60, label: 'Каждый час' },
  { value: 360, label: 'Каждые 6 часов' },
  { value: 720, label: 'Каждые 12 часов' },
  { value: 1440, label: 'Раз в сутки' },
]

// ─── Шаблоны каналов ────────────────────────────────────

export interface SetupField {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'select' | 'tags'
  required: boolean
  defaultValue?: string
  placeholder?: string
  options?: { value: string; label: string }[]
}

export interface TemplateStream {
  docTypeId: string
  docTypeLabel: string
  catalogTemplate: string
  enabled: boolean
}

export interface ChannelTemplate {
  id: string
  name: string
  description: string
  icon: string
  category: string
  sourceType: SourceType
  defaultConnection: Record<string, string>
  streams: TemplateStream[]
  defaultSchedule: ScheduleConfig
  setupFields: SetupField[]
}

// ─── Канал ──────────────────────────────────────────────

/** Канал — pipeline обработки данных из нескольких источников */
export interface Channel {
  id: string
  name: string
  /** ID источников (множественные) */
  sourceIds: string[]
  /** @deprecated — для обратной совместимости, использовать sourceIds */
  sourceId?: string
  status: ChannelStatus
  description?: string
  /** Конфигурация канала (станции, параметры обработки и т.д.) */
  config: Record<string, any>
  /** Политика дубликатов */
  duplicatePolicy: DuplicatePolicy
  /** Расписание загрузки */
  schedule: ScheduleConfig | string
  /** Период загрузки (дней назад) */
  periodDays: number
  /** ID шаблона, из которого создан */
  templateId?: string
  /** Потоки данных (что забираем, куда кладём) */
  streams: ChannelStream[]
  /** Этапы pipeline */
  stages: ChannelStage[]
  /** Правила сверки */
  reconcileRules: ReconcileRule[]
  /** Корневой каталог хранения */
  rootCatalog: string
  /** Последняя синхронизация */
  lastSync?: string
  /** Кол-во загруженных документов */
  docsLoaded: number
  /** Лог последних операций */
  syncLog: SyncLogEntry[]
  createdAt: string
  updatedAt: string
}

/** Получить все sourceIds канала (с учётом legacy sourceId) */
export function getChannelSourceIds(ch: Channel): string[] {
  if (ch.sourceIds?.length) return ch.sourceIds
  if (ch.sourceId) return [ch.sourceId]
  return []
}

/**
 * Получить станции канала с явным system_id.
 *
 * Совместимость:
 * - если в config есть `stations: ChannelStation[]` — берём как есть;
 * - иначе строим из legacy `stationCodes: number[]`, подставляя systemId
 *   из config.systemCode или 65 как fallback.
 */
export function getChannelStations(ch: Channel): ChannelStation[] {
  const cfg = ch.config ?? {}
  if (Array.isArray(cfg.stations) && cfg.stations.length > 0) {
    return cfg.stations as ChannelStation[]
  }
  const codes: number[] = cfg.stationCodes ?? []
  const fallbackSystem = Number(cfg.systemCode ?? cfg.system_id ?? 65)
  return codes.map((code) => ({ code, systemId: fallbackSystem }))
}

export const DUPLICATE_POLICY_META: Record<DuplicatePolicy, { label: string; description: string }> = {
  skip: { label: 'Пропустить', description: 'Не загружать повторно' },
  warn: { label: 'Предупредить', description: 'Показать список дубликатов' },
  overwrite: { label: 'Перезаписать', description: 'Обновить существующие данные' },
}
