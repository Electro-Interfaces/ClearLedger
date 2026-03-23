/**
 * Типы для каналов данных, потоков и синхронизации.
 */

export type ChannelType = 'rest' | '1c' | 'email' | 'ftp' | 'webhook' | 'watch-dir' | 'edi' | 'cloud'

export type ChannelStatus = 'active' | 'paused' | 'error' | 'draft'

export type DuplicatePolicy = 'skip' | 'warn' | 'overwrite'

/** Поток данных внутри канала */
export interface ChannelStream {
  id: string
  name: string
  /** Тип документа: shift_report, receipt, price */
  docType: string
  /** Endpoint/метод для этого потока */
  endpoint?: string
  /** Шаблон каталога назначения */
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

export interface Channel {
  id: string
  name: string
  type: ChannelType
  status: ChannelStatus
  description?: string
  /** URL / путь / адрес подключения */
  endpoint?: string
  /** Расписание */
  schedule?: string
  /** Политика дубликатов */
  duplicatePolicy: DuplicatePolicy
  /** Потоки данных */
  streams: ChannelStream[]
  /** Последняя синхронизация */
  lastSync?: string
  /** Кол-во загруженных документов */
  docsLoaded: number
  /** Сообщение об ошибке */
  errorMessage?: string
  /** Настройки подключения */
  config: Record<string, string>
  /** Лог последних операций */
  syncLog: SyncLogEntry[]
  createdAt: string
  updatedAt: string
}

export interface Source {
  id: string
  name: string
  type: 'api' | 'ofd' | 'bank' | 'counterparty' | 'edo' | 'internal'
  description?: string
  status: 'connected' | 'disconnected' | 'pending'
  channelIds: string[]
  createdAt: string
}

export const CHANNEL_TYPE_META: Record<ChannelType, { label: string; description: string; icon: string }> = {
  rest: { label: 'REST API', description: 'HTTP/REST подключение к внешнему API', icon: 'Globe' },
  '1c': { label: '1С Обмен', description: 'OData или файловый обмен с 1С', icon: 'Database' },
  email: { label: 'Email', description: 'Входящая почта с документами', icon: 'Mail' },
  ftp: { label: 'FTP/SFTP', description: 'Файловый сервер', icon: 'HardDrive' },
  webhook: { label: 'Webhook', description: 'Входящий HTTP webhook', icon: 'Webhook' },
  'watch-dir': { label: 'Папка', description: 'Мониторинг локальной/сетевой папки', icon: 'FolderOpen' },
  edi: { label: 'ЭДО', description: 'Электронный документооборот (Контур, СБИС)', icon: 'FileCheck' },
  cloud: { label: 'Облако', description: 'Google Drive, OneDrive, Dropbox', icon: 'Cloud' },
}

export const DUPLICATE_POLICY_META: Record<DuplicatePolicy, { label: string; description: string }> = {
  skip: { label: 'Пропустить', description: 'Не загружать повторно' },
  warn: { label: 'Предупредить', description: 'Показать список дубликатов' },
  overwrite: { label: 'Перезаписать', description: 'Обновить существующие данные' },
}
