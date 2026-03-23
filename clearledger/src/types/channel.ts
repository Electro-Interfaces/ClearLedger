/**
 * Типы: Источники, Каналы, Потоки.
 *
 * Источник = подключение (URL, credentials, типы документов).
 * Канал = работа с данными из источника (расписание, периоды, каталоги).
 */

// ─── Источники (Sources) ─────────────────────────────────

export type SourceType = 'rest' | '1c' | 'email' | 'ftp' | 'webhook' | 'watch-dir' | 'edi' | 'cloud'

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
}

/** Дефолтные типы документов для STS REST API */
export function defaultStsDocTypes(): SourceDocType[] {
  return [
    { id: 'shift_report', name: 'Сменные отчёты', endpoint: '/v1/report/shift_report', description: 'Продажи, резервуары, ТРК, оплаты' },
    { id: 'receipt', name: 'Поступления (ТТН)', endpoint: '/v1/report/receipts', description: 'Приём топлива, плотность, масса' },
    { id: 'price', name: 'Цены', endpoint: '/v1/prices', description: 'Текущие цены на топливо' },
  ]
}

// ─── Каналы (Channels) ──────────────────────────────────

export type ChannelStatus = 'active' | 'paused' | 'error' | 'draft'

export type DuplicatePolicy = 'skip' | 'warn' | 'overwrite'

/** Поток данных внутри канала — что забираем и куда кладём */
export interface ChannelStream {
  id: string
  /** ID типа документа из источника */
  docTypeId: string
  /** Название (копируется из SourceDocType.name) */
  name: string
  /** Шаблон каталога хранения */
  catalogTemplate: string
  /** Фильтры (станции, типы и т.д.) */
  filters: Record<string, string>
  /** Активен ли поток */
  enabled: boolean
}

/** Запись лога синхронизации */
export interface SyncLogEntry {
  timestamp: string
  level: 'info' | 'warn' | 'error' | 'success'
  event: 'AUTH' | 'SYNC' | 'LOAD' | 'DONE' | 'ERROR' | 'SKIP' | 'DUPLICATE'
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

/** Канал — работа с данными из источника */
export interface Channel {
  id: string
  name: string
  /** ID источника */
  sourceId: string
  status: ChannelStatus
  description?: string
  /** Политика дубликатов */
  duplicatePolicy: DuplicatePolicy
  /** Расписание (manual / cron / realtime) */
  schedule: string
  /** Период загрузки (дней назад) */
  periodDays: number
  /** Потоки данных (что забираем, куда кладём) */
  streams: ChannelStream[]
  /** Последняя синхронизация */
  lastSync?: string
  /** Кол-во загруженных документов */
  docsLoaded: number
  /** Лог последних операций */
  syncLog: SyncLogEntry[]
  createdAt: string
  updatedAt: string
}

export const DUPLICATE_POLICY_META: Record<DuplicatePolicy, { label: string; description: string }> = {
  skip: { label: 'Пропустить', description: 'Не загружать повторно' },
  warn: { label: 'Предупредить', description: 'Показать список дубликатов' },
  overwrite: { label: 'Перезаписать', description: 'Обновить существующие данные' },
}
