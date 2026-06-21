/**
 * Настройки подключения TradeLedger к 1С (БП ГИГ).
 *
 * Поддерживает два режима:
 * - OData: HTTP-публикация 1С через Apache/IIS (production)
 * - COM: V83.COMConnector на локальную файловую БД (development)
 *
 * Хранится в localStorage. Реальное подключение реализуется
 * параллельным агентом — backend в clearledger/server/app/services/onec/.
 */

import { getItem, setItem } from './storage'

export type OneCConnectionMode = 'odata' | 'com' | 'http_service'

export type OneCConnectionStatus =
  | 'not_configured'
  | 'configured'
  | 'testing'
  | 'connected'
  | 'error'

export interface OneCConnection {
  mode: OneCConnectionMode

  /** OData mode */
  odataUrl?: string

  /** COM mode */
  comPath?: string

  /** HTTP service mode */
  httpServiceUrl?: string

  /** Логин в 1С (для всех режимов) */
  login: string
  /** Пароль (хранится в localStorage — для production вынести на бэк) */
  password: string

  /** Имя организации/ИНН для фильтрации запросов */
  organizationInn: string

  /** Статус подключения */
  status: OneCConnectionStatus
  /** Сообщение об ошибке последнего теста */
  lastError?: string
  /** Когда последний раз тестировали */
  lastTestedAt?: string
  /** Когда последний раз синхронизировали */
  lastSyncAt?: string
  /** Версия конфигурации БП (после успешного теста) */
  configVersion?: string
  /** Платформа 1С (после успешного теста) */
  platformVersion?: string
}

const STORAGE_KEY = 'gig-1c-connection'

const defaults: OneCConnection = {
  mode: 'odata',
  odataUrl: 'http://192.168.40.31/acc/odata/standard.odata/',
  comPath: 'D:\\Users\\magsp\\GIG Base2',
  login: '',
  password: '',
  organizationInn: '7839440090',
  status: 'not_configured',
}

export function getOneCConnection(): OneCConnection {
  return { ...defaults, ...getItem<Partial<OneCConnection>>(STORAGE_KEY, {}) }
}

export function saveOneCConnection(updates: Partial<OneCConnection>): OneCConnection {
  const current = getOneCConnection()
  const merged: OneCConnection = {
    ...current,
    ...updates,
  }
  // Если меняем параметры подключения — сбрасываем статус
  const connectionFieldsChanged = [
    'mode', 'odataUrl', 'comPath', 'httpServiceUrl',
    'login', 'password', 'organizationInn',
  ].some((k) => k in updates)
  if (connectionFieldsChanged && !('status' in updates)) {
    merged.status = current.status === 'connected' ? 'configured' : current.status
  }
  setItem(STORAGE_KEY, merged)
  return merged
}

export function setOneCStatus(
  status: OneCConnectionStatus,
  details?: { error?: string; configVersion?: string; platformVersion?: string },
): OneCConnection {
  return saveOneCConnection({
    status,
    lastTestedAt: new Date().toISOString(),
    lastError: details?.error,
    configVersion: details?.configVersion,
    platformVersion: details?.platformVersion,
  })
}

/** Тест-заглушка пока бэкенд не реализован — параллельный агент заменит. */
export async function testOneCConnection(): Promise<{ ok: boolean; message: string }> {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        ok: false,
        message:
          'Бэкенд OData/COM-клиента ещё не реализован. ' +
          'Промпт для параллельного агента — в PROMPT_подключение_к_БП_ГИГ.md',
      })
    }, 800)
  })
}
