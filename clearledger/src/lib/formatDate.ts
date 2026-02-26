import { getSettings } from '@/services/settingsService'

/** Формат даты из настроек */
export function formatDate(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const { dateFormat } = getSettings()

  if (dateFormat === 'yyyy-mm-dd') {
    return d.toLocaleDateString('sv-SE') // ISO format: 2026-02-26
  }
  return d.toLocaleDateString('ru-RU') // DD.MM.YYYY
}

/** Формат даты + времени */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const { dateFormat } = getSettings()

  const locale = dateFormat === 'yyyy-mm-dd' ? 'sv-SE' : 'ru-RU'
  return d.toLocaleString(locale, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Только время */
export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}
