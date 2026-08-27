/**
 * Логика «панели управления парком» точек обслуживания.
 * Единый отбор (фильтры) + агрегаты (дашборд/KPI) + предикаты «требуют внимания».
 * Чистые функции над ServiceLocation[] (данные синхронны, без React Query).
 */
import {
  LOCATION_STATUS_META, locationField, type LocationStatus, type ServiceLocation,
} from '@/types/location'
import type { LocationTypeDef } from '@/types/locationType'
import { OP_META, OP_OPTIONS } from '@/components/locations/cockpit/shared'

/** Поле точки строкой: нормализованный паспорт, иначе сырой снимок metadata. */
export const m = locationField

/** Нормализованный операционный статус (старые точки без поля → 'unknown'). */
export function opStatusOf(l: ServiceLocation): string {
  return l.operationalStatus ?? 'unknown'
}

// ─── Признак «служебная / не служебная» (наш слой) ───────────────────────────
const SERVICE_TRUE = new Set(['true', '1', 'yes', 'да', 'служебная', 'service'])
const PLACEHOLDER = new Set(['001', '000', '0', '1', 'test', 'тест', 'demo', 'демо'])

/** Тестовая/служебная станция. Источник правды — БД-флаг `is_test` (приходит на
 *  фронт как `passport.isTest`): его ведёт сверка со справочником, и он ловит
 *  мусор, который эвристика по имени пропускает («123123123», «Предпоказ»).
 *  Эвристика по имени/коду — лишь фолбэк, пока флаг в БД не выставлен (NULL). */
export function isTestStation(l: ServiceLocation): boolean {
  const flag = (l.passport as Record<string, unknown> | undefined)?.isTest
  if (typeof flag === 'boolean') return flag
  const name = (l.name ?? '').trim().toLowerCase()
  const code = (l.code ?? '').trim().toLowerCase()
  if (PLACEHOLDER.has(name) || PLACEHOLDER.has(code)) return true
  return /\b(тест|test|демонстрац|служебн|проверочн|sandbox|пробн)\b/i.test(`${l.name ?? ''} ${l.code ?? ''}`)
}

/** Служебная: помечена вручную (metadata.service) ИЛИ тестовая по эвристике. */
export function isService(l: ServiceLocation): boolean {
  return SERVICE_TRUE.has(m(l, 'service').trim().toLowerCase()) || isTestStation(l)
}

// ─── Фильтры ────────────────────────────────────────────────────────────────

export interface LocationFilters {
  q: string
  types: string[]
  lifeStatuses: LocationStatus[]
  opStatuses: string[]
  regions: string[]
  owners: string[]
  linkStatuses: string[]
  /** Наличие привязки к источнику данных. */
  sourceBinding: 'any' | 'bound' | 'unbound'
  /** Назначение станции: служебная / рабочая. */
  serviceKind: 'any' | 'service' | 'regular'
}

export const EMPTY_LOCATION_FILTERS: LocationFilters = {
  q: '', types: [], lifeStatuses: [], opStatuses: [],
  regions: [], owners: [], linkStatuses: [], sourceBinding: 'any', serviceKind: 'any',
}

/** Активен ли хоть один фильтр (для бейджа «Очистить» и счётчика). */
export function activeFilterCount(f: LocationFilters): number {
  return (f.q.trim() ? 1 : 0) +
    f.types.length + f.lifeStatuses.length + f.opStatuses.length +
    f.regions.length + f.owners.length + f.linkStatuses.length +
    (f.sourceBinding !== 'any' ? 1 : 0) + (f.serviceKind !== 'any' ? 1 : 0)
}

/** Применить фильтры. Пустой массив = «все». Сортировка — НЕ здесь (в таблице). */
export function applyLocationFilters(locations: ServiceLocation[], f: LocationFilters): ServiceLocation[] {
  const qq = f.q.trim().toLowerCase()
  return locations.filter((l) => {
    if (f.types.length && !f.types.includes(l.type)) return false
    if (f.lifeStatuses.length && !f.lifeStatuses.includes(l.status)) return false
    if (f.opStatuses.length && !f.opStatuses.includes(opStatusOf(l))) return false
    if (f.regions.length && !f.regions.includes(m(l, 'federalSubject'))) return false
    if (f.owners.length && !f.owners.includes(m(l, 'ownerTitle'))) return false
    if (f.linkStatuses.length && !f.linkStatuses.includes(m(l, 'linkStatus'))) return false
    if (f.sourceBinding === 'bound' && l.sourceBindings.length === 0) return false
    if (f.sourceBinding === 'unbound' && l.sourceBindings.length > 0) return false
    if (f.serviceKind === 'service' && !isService(l)) return false
    if (f.serviceKind === 'regular' && isService(l)) return false
    if (qq) {
      const hay = [
        m(l, 'number'), l.code, l.name, l.address ?? '', m(l, 'cityName'),
        m(l, 'serialNumber'), m(l, 'ownerTitle'),
      ].join(' ').toLowerCase()
      if (!hay.includes(qq)) return false
    }
    return true
  })
}

// ─── «Требуют внимания» ───────────────────────────────────────────────────────

// «Нет связи» и «Отключена» — состояния из выгрузки CPO. Раньше первое схлопывалось
// в unknown и в категории внимания не попадало вовсе, второе приходило как
// not_working и мешалось с реальными авариями. Теперь это отдельные категории.
export const ATTENTION = {
  noLink: (l: ServiceLocation) => opStatusOf(l) === 'no_link',
  disabled: (l: ServiceLocation) => opStatusOf(l) === 'disabled',
  notWorking: (l: ServiceLocation) => opStatusOf(l) === 'not_working',
  onRepair: (l: ServiceLocation) => opStatusOf(l) === 'on_repair',
  linkConflict: (l: ServiceLocation) => m(l, 'linkStatus') === 'conflict',
  noBinding: (l: ServiceLocation) => l.sourceBindings.length === 0,
} as const
export type AttentionKey = keyof typeof ATTENTION

/** Фильтр-патч, который выделяет точки данной категории «внимания». */
export const ATTENTION_PATCH: Record<AttentionKey, Partial<LocationFilters>> = {
  noLink: { opStatuses: ['no_link'] },
  disabled: { opStatuses: ['disabled'] },
  notWorking: { opStatuses: ['not_working'] },
  onRepair: { opStatuses: ['on_repair'] },
  linkConflict: { linkStatuses: ['conflict'] },
  noBinding: { sourceBinding: 'unbound' },
}

/**
 * Какая пилюля «требуют внимания» сейчас включена, если включена вообще.
 *
 * Пилюля ставит срез РЕЖИМОМ ЗАМЕНЫ, поэтому включённой считается ровно та,
 * чей патч совпал с текущим отбором целиком. Нужна двум вещам: подсветить
 * включённую (иначе по виду не понять, нажата она или нет) и снять срез
 * повторным нажатием — просил Якушевич 27.08.2026.
 */
export function activeAttentionKey(f: LocationFilters): AttentionKey | null {
  // Отпечаток по фиксированному списку полей: перечисление короче и проверяемее
  // поэлементного сравнения шести массивов, а состав `LocationFilters` тут виден
  // целиком — новое поле в нём сразу заметно и здесь.
  const sig = (x: LocationFilters) => JSON.stringify([
    x.q, x.sourceBinding, x.serviceKind,
    x.types, x.lifeStatuses, x.opStatuses, x.regions, x.owners, x.linkStatuses,
  ])
  const mine = sig(f)
  const keys = Object.keys(ATTENTION_PATCH) as AttentionKey[]
  return keys.find((k) => sig({ ...EMPTY_LOCATION_FILTERS, ...ATTENTION_PATCH[k] }) === mine) ?? null
}

export const ATTENTION_META: Record<AttentionKey, { label: string }> = {
  noLink: { label: 'Нет связи' },
  disabled: { label: 'Отключены' },
  notWorking: { label: 'Не работают' },
  onRepair: { label: 'На ремонте' },
  linkConflict: { label: 'Конфликт связки HubEx' },
  noBinding: { label: 'Без привязки к источнику' },
}

// ─── Агрегаты для дашборда / KPI ──────────────────────────────────────────────

export interface CountItem { key: string; label: string; count: number }

export interface FleetStats {
  total: number
  active: number
  notWorkingOrRepair: number
  noBindingCount: number
  regionCount: number
  ownerCount: number
  byType: CountItem[]
  byLifeStatus: CountItem[]
  byOpStatus: CountItem[]
  byLinkStatus: CountItem[]
  topRegions: CountItem[]
  topOwners: CountItem[]
  attention: Record<AttentionKey, number>
}

/** Подсчёт частот по ключу (пустые ключи отбрасываются). */
function countBy(locations: ServiceLocation[], keyOf: (l: ServiceLocation) => string): Map<string, number> {
  const map = new Map<string, number>()
  for (const l of locations) {
    const k = keyOf(l)
    if (!k) continue
    map.set(k, (map.get(k) ?? 0) + 1)
  }
  return map
}

const LINK_LABEL: Record<string, string> = {
  ok: 'Связка ok', review: 'На проверке', conflict: 'Конфликт',
  test: 'Тест', no_match: 'Нет связки',
}

export function computeFleetStats(
  locations: ServiceLocation[],
  typeByCode: Map<string, LocationTypeDef>,
  topN = 8,
): FleetStats {
  const total = locations.length

  // Типы — в порядке убывания количества.
  const byType: CountItem[] = Array.from(countBy(locations, (l) => l.type).entries())
    .map(([key, count]) => ({ key, label: typeByCode.get(key)?.name ?? key, count }))
    .sort((a, b) => b.count - a.count)

  // Жизненные статусы — фиксированный порядок словаря.
  const lifeCounts = countBy(locations, (l) => l.status)
  const byLifeStatus: CountItem[] = (Object.keys(LOCATION_STATUS_META) as LocationStatus[])
    .filter((k) => lifeCounts.get(k))
    .map((k) => ({ key: k, label: LOCATION_STATUS_META[k].label, count: lifeCounts.get(k)! }))

  // Операционные статусы — фиксированный порядок OP_OPTIONS.
  const opCounts = countBy(locations, opStatusOf)
  const byOpStatus: CountItem[] = OP_OPTIONS
    .filter((k) => opCounts.get(k))
    .map((k) => ({ key: k, label: OP_META[k]?.label ?? k, count: opCounts.get(k)! }))

  const byLinkStatus: CountItem[] = Array.from(countBy(locations, (l) => m(l, 'linkStatus')).entries())
    .map(([key, count]) => ({ key, label: LINK_LABEL[key] ?? key, count }))
    .sort((a, b) => b.count - a.count)

  const regionMap = countBy(locations, (l) => m(l, 'federalSubject'))
  const topRegions: CountItem[] = Array.from(regionMap.entries())
    .map(([key, count]) => ({ key, label: key, count }))
    .sort((a, b) => b.count - a.count).slice(0, topN)

  const ownerMap = countBy(locations, (l) => m(l, 'ownerTitle'))
  const topOwners: CountItem[] = Array.from(ownerMap.entries())
    .map(([key, count]) => ({ key, label: key, count }))
    .sort((a, b) => b.count - a.count).slice(0, topN)

  const attention = {
    noLink: locations.filter(ATTENTION.noLink).length,
    disabled: locations.filter(ATTENTION.disabled).length,
    notWorking: locations.filter(ATTENTION.notWorking).length,
    onRepair: locations.filter(ATTENTION.onRepair).length,
    linkConflict: locations.filter(ATTENTION.linkConflict).length,
    noBinding: locations.filter(ATTENTION.noBinding).length,
  }

  return {
    total,
    active: locations.filter((l) => l.status === 'active').length,
    notWorkingOrRepair: attention.notWorking + attention.onRepair,
    noBindingCount: attention.noBinding,
    regionCount: regionMap.size,
    ownerCount: ownerMap.size,
    byType, byLifeStatus, byOpStatus, byLinkStatus, topRegions, topOwners,
    attention,
  }
}

// ─── Опции мультиселектов (от полного парка) ─────────────────────────────────

export interface FilterOptions {
  types: { value: string; label: string }[]
  lifeStatuses: { value: string; label: string }[]
  opStatuses: { value: string; label: string }[]
  regions: { value: string; label: string }[]
  owners: { value: string; label: string }[]
  linkStatuses: { value: string; label: string }[]
}

export function collectFilterOptions(
  locations: ServiceLocation[],
  typeByCode: Map<string, LocationTypeDef>,
): FilterOptions {
  const uniq = (vals: string[]) => Array.from(new Set(vals.filter(Boolean))).sort((a, b) => a.localeCompare(b, 'ru'))
  const typeCodes = uniq(locations.map((l) => l.type))
  const opPresent = new Set(locations.map(opStatusOf))
  const lifePresent = new Set(locations.map((l) => l.status))
  return {
    types: typeCodes.map((c) => ({ value: c, label: typeByCode.get(c)?.name ?? c })),
    lifeStatuses: (Object.keys(LOCATION_STATUS_META) as LocationStatus[])
      .filter((k) => lifePresent.has(k))
      .map((k) => ({ value: k, label: LOCATION_STATUS_META[k].label })),
    opStatuses: OP_OPTIONS.filter((k) => opPresent.has(k)).map((k) => ({ value: k, label: OP_META[k]?.label ?? k })),
    regions: uniq(locations.map((l) => m(l, 'federalSubject'))).map((r) => ({ value: r, label: r })),
    owners: uniq(locations.map((l) => m(l, 'ownerTitle'))).map((o) => ({ value: o, label: o })),
    linkStatuses: uniq(locations.map((l) => m(l, 'linkStatus'))).map((s) => ({ value: s, label: LINK_LABEL[s] ?? s })),
  }
}
