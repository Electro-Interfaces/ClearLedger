/**
 * Точки обслуживания клиента.
 *
 * Справочник мест, где клиент ведёт бизнес: АЗС, торговые точки,
 * офисы, склады. Каждая точка может быть привязана к одному или
 * нескольким источникам через `sourceBindings` (например, АЗС
 * связана с STS API через `system_id` + `station`).
 */

export type LocationType = 'fuel_station' | 'retail' | 'office' | 'warehouse' | 'other'

export type LocationStatus = 'active' | 'closed' | 'planned'

/** Привязка точки к источнику данных */
export interface LocationSourceBinding {
  /** ID источника из gig-sources */
  sourceId: string
  /** Параметры для этого источника (зависят от типа) */
  config: Record<string, string | number>
  /** Описание привязки для UI («STS sys=65, station=5») */
  label?: string
}

export interface ServiceLocation {
  id: string
  /** Короткий код для отображения и ссылок ("208", "MAIN-OFFICE") */
  code: string
  /** Полное имя ("АКЗС Витебский (208)") */
  name: string
  /** Тип точки */
  type: LocationType
  /** Статус */
  status: LocationStatus
  /** Адрес */
  address?: string
  /** Свободное описание */
  description?: string
  /** Привязки к источникам данных */
  sourceBindings: LocationSourceBinding[]
  /** Произвольные метаданные (lat/lng, контакты, ответственный, ...) */
  metadata?: Record<string, unknown>
  createdAt: string
  updatedAt: string
}

export const LOCATION_TYPE_META: Record<LocationType, { label: string; description: string; icon: string }> = {
  fuel_station: { label: 'АЗС', description: 'Автозаправочная станция', icon: 'Fuel' },
  retail: { label: 'Торговая точка', description: 'Магазин, киоск, павильон', icon: 'Store' },
  office: { label: 'Офис', description: 'Административный офис, представительство', icon: 'Building2' },
  warehouse: { label: 'Склад', description: 'Складское помещение', icon: 'Warehouse' },
  other: { label: 'Другое', description: 'Другой тип объекта', icon: 'MapPin' },
}

export const LOCATION_STATUS_META: Record<LocationStatus, { label: string; color: string }> = {
  active: { label: 'Активна', color: 'green' },
  closed: { label: 'Закрыта', color: 'gray' },
  planned: { label: 'В планах', color: 'blue' },
}
