/**
 * Клиент показателей рабочего стола: что живёт за каждой плиткой продукта.
 *
 * Стол отвечал только «куда войти» — теперь ещё и «что там сейчас»: люди, объекты,
 * сессии, заявки, свежесть данных. Считает бэкенд (`services/space_desk.py`) одним
 * запросом, чтобы первый экран не собирал десяток ручек.
 */
import { get } from './apiClient'

export type MetricTone = 'ok' | 'warn' | 'bad' | null

export interface DeskMetric {
  label: string
  value: string
  tone?: MetricTone
}

export interface DeskSummary {
  windowDays: number
  profileId: string | null
  /** Ключ — код продукта в реестре; продукты без данных сюда не попадают. */
  products: Record<string, { metrics: DeskMetric[] }>
}

export const getDeskSummary = (companyId: string) =>
  get<DeskSummary>('/api/registry/desk', { company_id: companyId })
