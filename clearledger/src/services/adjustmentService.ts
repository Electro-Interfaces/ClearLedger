/**
 * Корректировки документов перед выгрузкой в 1С — работа бухгалтера.
 *
 * Факт станции не правится: правка ложится поверх отдельной записью и помнит
 * автора, причину и версию факта, на которой сделана. «Магазин» показывает те же
 * цифры, что и агент, — правки живут только здесь.
 */
import { get, post, del } from './apiClient'

/** Строка документа в том виде, в каком её отдаёт эмиттер пакета. */
export interface ДокСтрока {
  НомерСтроки: number
  Наименование?: string
  Номенклатура?: string
  Количество?: number
  Цена?: number
  Сумма?: number
  СуммаНДС?: number
  СтавкаНДС?: string
  [k: string]: unknown
}

export interface ДокументПакета {
  Тип?: string
  Номер?: string
  Дата?: string
  Склад?: string
  Комментарий?: string
  Товары?: ДокСтрока[]
  Корректировка?: { Была: boolean; Правки: { Автор: string; Причина: string; Когда: string }[] }
  [k: string]: unknown
}

/** Документ в двух состояниях: как пришёл со станции и каким уйдёт в 1С. */
export interface ПараДокумента {
  doc_kind: string
  document_id: string
  Номер?: string
  Дата?: string
  /** Отпечаток версии факта: правка обязана на него ссылаться. */
  content_hash: string
  'От станции': ДокументПакета
  'К выгрузке': ДокументПакета
  Правился: boolean
}

export interface ПредпросмотрПравок {
  shift_key: string
  Документы: ПараДокумента[]
  Правок: number
  /** Правки, сделанные на другой версии факта: смену пересчитали после них. */
  Устарели: { id: string; reason: string; author: string }[]
}

export interface ЗаписьИстории {
  id: string
  doc_kind: string
  document_id: string
  patch: { Строки?: Record<string, unknown>[]; Шапка?: Record<string, unknown> }
  reason: string
  author: string
  status: 'applied' | 'cancelled'
  created_at: string | null
  cancelled_at: string | null
  cancelled_by: string
  base_content_hash: string
}

export interface СписокПравок {
  действующие: ЗаписьИстории[]
  история: ЗаписьИстории[]
}

export const getПредпросмотрПравок = (shiftKey: string) =>
  get<ПредпросмотрПравок>('/api/accounting/adjustments/preview', { shift_key: shiftKey })

export const getПравки = (shiftKey: string) =>
  get<СписокПравок>('/api/accounting/adjustments', { shift_key: shiftKey })

export const завестиПравку = (тело: {
  shift_key: string
  doc_kind: string
  document_id: string
  base_content_hash: string
  patch: { Строки?: Record<string, unknown>[]; Шапка?: Record<string, unknown> }
  reason: string
}) => post<{ id: string; ok: boolean }>('/api/accounting/adjustments', тело)

export const отменитьПравку = (id: string) =>
  del<{ ok: boolean }>(`/api/accounting/adjustments/${id}`)

/** Что именно изменила правка — для истории и подсветки. */
export function измененияСтроки(
  было: ДокСтрока | undefined, стало: ДокСтрока | undefined,
): { поле: string; было: unknown; стало: unknown }[] {
  if (!было || !стало) return []
  return Object.keys(стало)
    .filter((поле) => поле !== 'НомерСтроки' && было[поле] !== стало[поле])
    .map((поле) => ({ поле, было: было[поле], стало: стало[поле] }))
}

/** Строка журнала за период: правка вместе с тем, что было до неё. */
export interface ЗаписьЖурнала extends ЗаписьИстории {
  shift_key: string
  station_id: number | null
  business_date: string | null
  amount_delta: number
  prev_values: {
    Строки?: Record<string, Record<string, unknown>>
    Шапка?: Record<string, unknown>
  }
}

export interface ЖурналПравок {
  Записи: ЗаписьЖурнала[]
  Всего: number
  Действующих: number
  /** На сколько действующие правки изменили суммы документов. */
  ВлияниеНаСумму: number
  Авторы: string[]
}

export const getЖурналПравок = (
  dateFrom: string, dateTo: string, stationId?: number,
) => get<ЖурналПравок>('/api/accounting/adjustments/journal', {
  date_from: dateFrom, date_to: dateTo,
  station_id: stationId ? String(stationId) : undefined,
})
