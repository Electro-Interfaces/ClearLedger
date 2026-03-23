/**
 * Настройки приложения GIG Fuel Ledger.
 */

import { getItem, setItem } from './storage'

const SETTINGS_KEY = 'gig-fuel-settings'

export interface StsStation {
  code: number
  name: string
}

export interface AppSettings {
  theme: 'light' | 'dark' | 'system'
  /** URL API STS (без /v1/) */
  stsApiUrl: string
  stsLogin: string
  stsPassword: string
  /** Код системы (сети) в STS */
  stsSystemCode: number
  /** Станции для загрузки */
  stations: StsStation[]
}

const defaults: AppSettings = {
  theme: 'system',
  stsApiUrl: 'https://pos.autooplata.ru/tms',
  stsLogin: '',
  stsPassword: '',
  stsSystemCode: 15,
  stations: [
    { code: 4, name: 'АКАЗС №5' },
  ],
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

export function getStationCodes(): number[] {
  return getSettings().stations.map((s) => s.code)
}

export function getStationName(code: number): string {
  const s = getSettings().stations.find((st) => st.code === code)
  return s?.name ?? `Станция ${code}`
}
