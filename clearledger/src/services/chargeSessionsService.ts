/**
 * Сервис зарядных сессий ЭЗС — операции обработки данных канала сессий.
 * Аналитика (чтение) — в analyticsService; здесь мутации (обогащение и т.п.).
 */
import { upload, post, getToken } from './apiClient'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

export interface EnrichResult {
  status: string
  orgs: number          // строк «телефон+название» в справочнике
  orgs_matched: number  // организаций, у которых нашлись сессии
  updated: number       // обновлено строк-сессий (client_name проставлен)
  priced?: number       // сессий с рассчитанной корп-выручкой (client_amount)
  revenue?: number      // суммарная корп-выручка компании, ₽
  message: string
}

/**
 * Обогащение сессий справочником «Организации» (xlsx): проставить наименование
 * корпоративного клиента (client_name) ЮЛ-сессиям по телефону (user_id = телефон
 * организации). Идемпотентно — UPDATE по ключу, сессии не задваивает.
 */
export async function enrichChargeSessions(companyId: string, file: File): Promise<EnrichResult> {
  const fd = new FormData()
  fd.append('file', file)
  return upload<EnrichResult>(`/api/charge-sessions/enrich?company_id=${companyId}`, fd)
}

/**
 * Переприменить обогащение из СОХРАНЁННОГО реестра (без файла) — восстанавливает
 * распределение по ЮЛ (client_name/тариф/выручка) после перезагрузки таблицы сессий.
 */
export async function reenrichChargeSessions(companyId: string): Promise<EnrichResult> {
  return post<EnrichResult>(`/api/charge-sessions/reenrich?company_id=${companyId}`)
}

/**
 * Построчная выгрузка сессий в xlsx с ОБЕИМИ ценами (тариф станции/розница +
 * договорной тариф ЮЛ + обе выручки + разница). Фильтры: период (обяз.),
 * опц. тип клиента (ФЛ/ЮЛ) и конкретный клиент. Скачивает файл в браузере.
 */
export async function exportChargeSessionsXlsx(p: {
  companyId: string; dateFrom: string; dateTo: string; userType?: string; client?: string
}): Promise<void> {
  const qs = new URLSearchParams({ company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo })
  if (p.userType) qs.set('user_type', p.userType)
  if (p.client) qs.set('client', p.client)
  const token = getToken()
  const res = await fetch(`${API_BASE}/api/charge-sessions/export?${qs.toString()}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new Error(`Выгрузка не удалась (${res.status})`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `sessions_${p.dateFrom}_${p.dateTo}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
