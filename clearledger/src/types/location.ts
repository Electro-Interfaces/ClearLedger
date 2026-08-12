/**
 * Точки обслуживания клиента.
 *
 * Справочник мест, где клиент ведёт бизнес: АЗС, торговые точки,
 * офисы, склады. Каждая точка может быть привязана к одному или
 * нескольким источникам через `sourceBindings` (например, АЗС
 * связана с STS API через `system_id` + `station`).
 */

/**
 * Код типа точки. Раньше — фиксированный union; теперь типы заданы в
 * редактируемом каталоге (см. useLocationTypes / LocationTypeDef), поэтому это
 * просто строка-код. Нижестоящий код опирается на стабильные коды встроенных
 * типов (например 'fuel_station'). LOCATION_TYPE_META — фолбэк меты.
 */
export type LocationType = string

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
  /** Жизненный статус */
  status: LocationStatus
  /** Операционный статус: working|not_working|on_repair|maintenance|unknown */
  operationalStatus?: string
  /** Адрес */
  address?: string
  /** Свободное описание */
  description?: string
  /** Привязки к источникам данных */
  sourceBindings: LocationSourceBinding[]
  /** Произвольные метаданные (lat/lng, контакты, ответственный, ...) */
  metadata?: Record<string, unknown>
  /** Нормализованный паспорт L2 (типизированные колонки: мощность, коннекторы,
   *  бренд, владелец, координаты…) — для объектов ЭЗС. Из нормализации станций. */
  passport?: Record<string, unknown>
  createdAt: string
  updatedAt: string
}

/**
 * Ключ сырого снимка (metadata) → поле нормализованного паспорта L2.
 *
 * Экраны сети исторически читали только metadata — снимок импорта из HubEx.
 * Станции, приехавшие из витрины АСУиМ, кладут в metadata СВОИ ключи
 * (`brandName`, `groupName`…), а бренд/город/мощность/владельца/серийник
 * нормализация пишет в колонки паспорта. Из-за этого у 124–131 станции пилота
 * графы «Город/Бренд/кВт/Коннекторы/Владелец» пустели в таблице, карточке и
 * выгрузке, хотя данные в базе есть. Паспорт сверен с витриной — он старше
 * сырья по приоритету (в сыром снимке у станции 268 номер вообще «123321»).
 */
const PASSPORT_ALIAS: Record<string, string> = {
  number: 'stationNumber', serialNumber: 'serialNumber', ownerTitle: 'owner',
  cityName: 'city', manufacturer: 'brand', model: 'model',
  maxPowerKw: 'powerKwt', connectorCount: 'connectorsCount',
  connectorTypes: 'connectorTypes', protocolOcpp: 'ocppProtocol',
  latitude: 'latitude', longitude: 'longitude',
  linkStatus: 'hubexLinkStatus', hubexAssetId: 'hubexAssetId',
  inventoryNumber: 'inventoryNumber', stage: 'stage', firmware: 'firmware',
  street: 'street', houseNumber: 'house',
}

/** Поле объекта строкой: сначала нормализованный паспорт, потом сырой снимок. */
export function locationField(l: ServiceLocation, key: string): string {
  const pk = PASSPORT_ALIAS[key]
  const p = pk ? (l.passport as Record<string, unknown> | undefined)?.[pk] : undefined
  const v = p == null || p === ''
    ? (l.metadata as Record<string, unknown> | undefined)?.[key]
    : p
  return v == null ? '' : String(v)
}

/** Значения полей объекта: сырой снимок, перекрытый паспортом (для карточек). */
export function locationValues(l: ServiceLocation): Record<string, unknown> {
  const out = { ...((l.metadata ?? {}) as Record<string, unknown>) }
  const p = (l.passport ?? {}) as Record<string, unknown>
  for (const [mk, pk] of Object.entries(PASSPORT_ALIAS)) {
    const v = p[pk]
    if (v != null && v !== '') out[mk] = v
  }
  return out
}

/** Фолбэк-мета встроенных типов (когда каталог ещё не загружен). */
export const LOCATION_TYPE_META: Record<string, { label: string; description: string; icon: string }> = {
  fuel_station: { label: 'АЗС', description: 'Автозаправочная станция', icon: 'Fuel' },
  ev_charging: { label: 'Электрозарядная станция', description: 'Зарядка электромобилей (кВт·ч)', icon: 'Zap' },
  retail: { label: 'Магазин / сопутка', description: 'Магазин, киоск, павильон', icon: 'Store' },
  food: { label: 'Общепит', description: 'Кафе, столовая, кухня', icon: 'Utensils' },
  office: { label: 'Офис', description: 'Административный офис, представительство', icon: 'Building2' },
  warehouse: { label: 'Склад', description: 'Складское помещение', icon: 'Warehouse' },
  other: { label: 'Другое', description: 'Другой тип объекта', icon: 'MapPin' },
}

export const LOCATION_STATUS_META: Record<LocationStatus, { label: string; color: string }> = {
  active: { label: 'Активна', color: 'green' },
  closed: { label: 'Закрыта', color: 'gray' },
  planned: { label: 'В планах', color: 'blue' },
}
