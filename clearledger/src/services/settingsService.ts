/**
 * Persist пользовательских настроек в localStorage.
 */

import { getItem, setItem } from './storage'

const SETTINGS_KEY = 'clearledger-settings'

export interface AppSettings {
  language: 'ru' | 'en'
  dateFormat: 'dd.mm.yyyy' | 'yyyy-mm-dd'
  theme: 'light' | 'dark' | 'system'
  defaultCompanyId: string
  userName: string
  userEmail: string
}

const defaults: AppSettings = {
  language: 'ru',
  dateFormat: 'dd.mm.yyyy',
  theme: 'system',
  defaultCompanyId: 'npk',
  userName: 'Михеев Андрей',
  userEmail: 'admin@clearledger.ru',
}

export function getSettings(): AppSettings {
  return { ...defaults, ...getItem<Partial<AppSettings>>(SETTINGS_KEY, {}) }
}

export function saveSettings(updates: Partial<AppSettings>): AppSettings {
  const current = getSettings()
  const merged = { ...current, ...updates }
  setItem(SETTINGS_KEY, merged)
  return merged
}
