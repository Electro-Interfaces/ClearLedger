/**
 * Типы для каналов данных и источников.
 */

export type ChannelType = 'rest' | '1c' | 'email' | 'ftp' | 'webhook' | 'watch-dir' | 'edi' | 'cloud'

export type ChannelStatus = 'active' | 'paused' | 'error' | 'draft'

export interface Channel {
  id: string
  name: string
  type: ChannelType
  status: ChannelStatus
  description?: string
  /** URL / путь / адрес подключения */
  endpoint?: string
  /** Расписание (cron expression или 'realtime') */
  schedule?: string
  /** Последняя синхронизация */
  lastSync?: string
  /** Кол-во загруженных документов */
  docsLoaded: number
  /** Сообщение об ошибке */
  errorMessage?: string
  /** Настройки подключения */
  config: Record<string, string>
  createdAt: string
  updatedAt: string
}

export interface Source {
  id: string
  name: string
  type: 'api' | 'ofd' | 'bank' | 'counterparty' | 'edo' | 'internal'
  description?: string
  status: 'connected' | 'disconnected' | 'pending'
  /** Привязанные каналы */
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
