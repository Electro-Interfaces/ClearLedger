/**
 * Фасеты подбора станций ЭЗС: какие признаки паспорта сужают сеть и как
 * считаются счётчики рядом со значениями.
 *
 * Вынесено из компонента, потому что здесь ломается молча: счётчик, посчитанный
 * с учётом собственной группы, обнуляет все её невыбранные значения — фасетом
 * становится нельзя расширить выборку, и понять это по экрану трудно.
 */

/** Станция, как её отдаёт справочник фильтра (`/analytics/charge-sessions/dimensions`). */
export interface FacetStation {
  code: string
  name: string
  sessions: number
  region: string | null
  city: string | null
  address: string | null
  speed: string | null
  placement: string | null
  brand: string | null
  power: number | null
  ports: number | null
  connectors: string[]
  opStatus: string | null
  lifecycle: string | null
  corp: boolean
}

/** Значения, которого в паспорте нет: отдельная строка фасета, а не «спрятать станцию». */
export const UNSET = '—'

export const SPEED_LABELS: Record<string, string> = { fast: 'Быстрая', slow: 'Медленная' }
export const PLACEMENT_LABELS: Record<string, string> = { city: 'Город', highway: 'Трасса' }
export const OP_LABELS: Record<string, string> = {
  working: 'Работает',
  no_link: 'Нет связи',
  decommissioned: 'Выведена',
  disabled: 'Отключена',
  not_working: 'Не работает',
  unknown: 'Состояние не известно',
}
const LIFECYCLE_LABELS: Record<string, string> = { active: 'Действующая', closed: 'Закрыта' }
const CORP_LABELS: Record<string, string> = { corp: 'Корпоративная', retail: 'Розничная' }
const ACTIVITY_LABELS: Record<string, string> = { with: 'Есть зарядки', without: 'Без зарядок' }

export const POWER_BUCKETS: { key: string; label: string; hit: (power: number) => boolean }[] = [
  { key: 'le22', label: 'до 22 кВт', hit: (p) => p <= 22 },
  { key: 'le50', label: '22–50 кВт', hit: (p) => p > 22 && p <= 50 },
  { key: 'le150', label: '50–150 кВт', hit: (p) => p > 50 && p <= 150 },
  { key: 'gt150', label: 'свыше 150 кВт', hit: (p) => p > 150 },
]

export function powerBucket(power: number | null): string {
  if (power == null) return UNSET
  return POWER_BUCKETS.find((b) => b.hit(power))?.key ?? UNSET
}

export type GroupKey =
  | 'region' | 'city' | 'speed' | 'placement' | 'brand'
  | 'power' | 'connector' | 'opStatus' | 'lifecycle' | 'corp' | 'activity'

export interface FacetGroupDef {
  key: GroupKey
  label: string
  /** Значения станции в этой группе. Их может быть несколько (разъёмы). */
  valuesOf: (station: FacetStation) => string[]
  labelOf: (value: string) => string
  /** Сколько значений показывать до «ещё N». */
  head?: number
  /** Порядок значений; по умолчанию — по числу станций. */
  order?: string[]
}

export const FACET_GROUPS: FacetGroupDef[] = [
  {
    key: 'region', label: 'Регион', head: 8,
    // Записи без букв («12» и подобные) — мусор справочника, а не регион: тот же
    // отбор стоит в общем селекторе области, и «12» висел первой строкой списка.
    valuesOf: (s) => {
      const region = s.region?.trim() ?? ''
      return [/[а-яёa-z]/i.test(region) ? region : UNSET]
    },
    labelOf: (v) => (v === UNSET ? 'Регион не указан' : v),
  },
  {
    key: 'city', label: 'Город', head: 6,
    valuesOf: (s) => [s.city?.trim() || UNSET],
    labelOf: (v) => (v === UNSET ? 'Город не указан' : v),
  },
  {
    key: 'speed', label: 'Класс скорости', order: ['fast', 'slow', UNSET],
    valuesOf: (s) => [s.speed || UNSET],
    labelOf: (v) => SPEED_LABELS[v] ?? 'Класс не размечен',
  },
  {
    key: 'placement', label: 'Размещение', order: ['city', 'highway', UNSET],
    valuesOf: (s) => [s.placement || UNSET],
    labelOf: (v) => PLACEMENT_LABELS[v] ?? 'Размещение не размечено',
  },
  {
    key: 'brand', label: 'Производитель', head: 6,
    valuesOf: (s) => [s.brand?.trim() || UNSET],
    labelOf: (v) => (v === UNSET ? 'Производитель не указан' : v),
  },
  {
    key: 'power', label: 'Мощность', order: [...POWER_BUCKETS.map((b) => b.key), UNSET],
    valuesOf: (s) => [powerBucket(s.power)],
    labelOf: (v) => POWER_BUCKETS.find((b) => b.key === v)?.label ?? 'Мощность не указана',
  },
  {
    key: 'connector', label: 'Разъём', head: 6,
    valuesOf: (s) => (s.connectors.length ? s.connectors : [UNSET]),
    labelOf: (v) => (v === UNSET ? 'Разъёмы не указаны' : v),
  },
  {
    key: 'opStatus', label: 'Рабочее состояние', head: 6,
    valuesOf: (s) => [s.opStatus || 'unknown'],
    labelOf: (v) => OP_LABELS[v] ?? v,
  },
  {
    key: 'lifecycle', label: 'Жизненный цикл', order: ['active', 'closed', UNSET],
    valuesOf: (s) => [s.lifecycle || UNSET],
    labelOf: (v) => LIFECYCLE_LABELS[v] ?? 'Цикл не указан',
  },
  {
    key: 'corp', label: 'Контур', order: ['retail', 'corp'],
    valuesOf: (s) => [s.corp ? 'corp' : 'retail'],
    labelOf: (v) => CORP_LABELS[v] ?? v,
  },
  {
    key: 'activity', label: 'Зарядки за всё время', order: ['with', 'without'],
    valuesOf: (s) => [s.sessions > 0 ? 'with' : 'without'],
    labelOf: (v) => ACTIVITY_LABELS[v] ?? v,
  },
]

export type Facets = Partial<Record<GroupKey, string[]>>

/** Проходит ли станция все условия. `except` — группа, которую при счёте пропускаем. */
export function matchesFacets(station: FacetStation, facets: Facets, except?: GroupKey): boolean {
  return FACET_GROUPS.every((group) => {
    if (group.key === except) return true
    const picked = facets[group.key]
    if (!picked || picked.length === 0) return true
    return group.valuesOf(station).some((value) => picked.includes(value))
  })
}

export interface FacetValue { value: string; count: number }

/**
 * Значения групп со счётчиками.
 *
 * Счётчик группы считается по отбору БЕЗ неё самой — иначе выбранное значение
 * всегда показывало бы «столько же, сколько отобрано», а остальные нули, и
 * фасетом нельзя было бы расширить выборку, не сбросив её.
 */
export function facetValues(stations: FacetStation[], facets: Facets): Map<GroupKey, FacetValue[]> {
  const result = new Map<GroupKey, FacetValue[]>()
  for (const group of FACET_GROUPS) {
    const counts = new Map<string, number>()
    for (const station of stations) {
      if (!matchesFacets(station, facets, group.key)) continue
      for (const value of group.valuesOf(station)) {
        counts.set(value, (counts.get(value) ?? 0) + 1)
      }
    }
    // Отмеченные значения остаются в списке даже с нулём: иначе фасет исчезает
    // вместе с возможностью его снять.
    for (const value of facets[group.key] ?? []) {
      if (!counts.has(value)) counts.set(value, 0)
    }
    const rows = [...counts.entries()].map(([value, count]) => ({ value, count }))
    rows.sort((a, b) => {
      if (group.order) {
        const ia = group.order.indexOf(a.value)
        const ib = group.order.indexOf(b.value)
        if (ia !== ib) return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
      }
      if (b.count !== a.count) return b.count - a.count
      return a.value.localeCompare(b.value, 'ru')
    })
    result.set(group.key, rows)
  }
  return result
}

export type StationSort = 'sessions' | 'name' | 'code' | 'power'

export function sortStations(stations: FacetStation[], sort: StationSort): FacetStation[] {
  const rows = [...stations]
  rows.sort((a, b) => {
    if (sort === 'name') return a.name.localeCompare(b.name, 'ru')
    if (sort === 'code') return a.code.localeCompare(b.code, 'ru', { numeric: true })
    if (sort === 'power') return (b.power ?? -1) - (a.power ?? -1)
    if (b.sessions !== a.sessions) return b.sessions - a.sessions
    return a.name.localeCompare(b.name, 'ru')
  })
  return rows
}

/** Строка поиска станции: место и производителя ищут чаще, чем код. */
export function stationSearchText(station: FacetStation): string {
  return [station.name, station.code, station.city, station.address, station.brand]
    .filter(Boolean).join(' ').toLowerCase()
}

/** Мета-строка станции: место, паспорт и состояние — то, по чему её узнают. */
export function stationMeta(station: FacetStation): string {
  const parts: string[] = []
  const place = [station.city, station.address].filter(Boolean).join(', ')
  if (place) parts.push(place)
  else if (station.region) parts.push(station.region)
  if (station.power != null) parts.push(`${station.power} кВт`)
  if (station.speed) parts.push(SPEED_LABELS[station.speed] ?? station.speed)
  if (station.placement) parts.push(PLACEMENT_LABELS[station.placement] ?? station.placement)
  if (station.opStatus && station.opStatus !== 'working') {
    parts.push(OP_LABELS[station.opStatus] ?? station.opStatus)
  }
  if (station.corp) parts.push('корп')
  return parts.join(' · ')
}
