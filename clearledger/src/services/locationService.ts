/**
 * CRUD для точек обслуживания — ДВУХРЕЖИМНЫЙ.
 *
 * Чтения (getLocations/...) — СИНХРОННЫЕ из localStorage (зеркало бэкенда),
 * чтобы не переписывать многочисленных потребителей.
 * Записи (create/update/delete) — синхронные в localStorage + зеркалирование
 * в бэкенд (`/api/locations`). `loadLocations(companyId)` тянет бэкенд в
 * localStorage (общие для всех браузеров); если бэкенд пуст, а локальные есть —
 * мигрирует локальные вверх (одноразовый перенос из старой localStorage-схемы).
 *
 * id — клиентский nanoid, общий для фронта и бэка.
 */

import { getItem, setItem } from './storage'
import { get, post, patch, del, isApiEnabled } from './apiClient'
import type {
  LocationSourceBinding,
  LocationStatus,
  LocationType,
  ServiceLocation,
} from '@/types/location'
import { nanoid } from 'nanoid'

const STORAGE_KEY = 'gig-locations'
let _companyId: string | null = null

function lsGet(): ServiceLocation[] {
  return getItem<ServiceLocation[]>(STORAGE_KEY, [])
}
function lsSet(v: ServiceLocation[]) {
  setItem(STORAGE_KEY, v)
}

// ─── Чтения (sync) ───────────────────────────────────────────────────────
export function getLocations(): ServiceLocation[] {
  return lsGet()
}
export function getLocation(id: string): ServiceLocation | undefined {
  return getLocations().find((l) => l.id === id)
}
export function getLocationByCode(code: string): ServiceLocation | undefined {
  return getLocations().find((l) => l.code === code)
}
export function getLocationsByType(type: LocationType): ServiceLocation[] {
  return getLocations().filter((l) => l.type === type)
}
export function getLocationsBySource(sourceId: string): ServiceLocation[] {
  return getLocations().filter((l) =>
    l.sourceBindings.some((b) => b.sourceId === sourceId),
  )
}

/**
 * STS-станции из точек обслуживания (тип fuel_station + STS-привязка).
 * Единый источник станций для разрезов сверки (settings.stations — легаси-стор,
 * для ГИГ пуст; станции живут в точках обслуживания / конфиге каналов).
 */
export interface StsStationRef {
  code: number
  name: string
  systemId: number
}
export function getStsStationsFromLocations(): StsStationRef[] {
  const seen = new Set<string>()
  const out: StsStationRef[] = []
  for (const loc of getLocations()) {
    if (loc.type !== 'fuel_station') continue
    for (const b of loc.sourceBindings) {
      const systemId = Number(b.config.system_id ?? b.config.systemId)
      const code = Number(b.config.station ?? b.config.code ?? loc.code)
      if (!systemId || !code) continue
      const key = `${systemId}|${code}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ code, name: loc.name, systemId })
    }
  }
  out.sort((a, b) => a.systemId - b.systemId || a.code - b.code)
  return out
}

// ─── Бэкенд (зеркало) ─────────────────────────────────────────────────────
interface ApiLocation {
  id: string
  code: string
  name: string
  type: string
  status: string
  address: string | null
  description: string | null
  sourceBindings: LocationSourceBinding[]
  metadata: Record<string, unknown> | null
  createdAt: string
  updatedAt: string
}

function fromApi(r: ApiLocation): ServiceLocation {
  return {
    id: r.id,
    code: r.code,
    name: r.name,
    type: r.type as LocationType,
    status: r.status as LocationStatus,
    address: r.address ?? undefined,
    description: r.description ?? undefined,
    sourceBindings: r.sourceBindings ?? [],
    metadata: r.metadata ?? undefined,
    createdAt: r.createdAt,
    updatedAt: r.updatedAt,
  }
}

function toApiBody(l: ServiceLocation) {
  return {
    id: l.id, company_id: _companyId, code: l.code, name: l.name,
    type: l.type, status: l.status, address: l.address ?? null,
    description: l.description ?? null, sourceBindings: l.sourceBindings,
    metadata: l.metadata ?? null,
  }
}

function mirrorPush(loc: ServiceLocation) {
  if (!isApiEnabled() || !_companyId) return
  void post('/api/locations', toApiBody(loc)).catch((e) =>
    console.warn('locationService: push в бэкенд не удался', e),
  )
}
function mirrorPatch(id: string, updates: Partial<ServiceLocation>) {
  if (!isApiEnabled() || !_companyId) return
  const body: Record<string, unknown> = {}
  for (const k of ['code', 'name', 'type', 'status', 'address', 'description', 'sourceBindings', 'metadata'] as const) {
    if (updates[k] !== undefined) body[k] = updates[k]
  }
  void patch(`/api/locations/${id}`, body).catch((e) =>
    console.warn('locationService: patch в бэкенд не удался', e),
  )
}
function mirrorDelete(id: string) {
  if (!isApiEnabled() || !_companyId) return
  void del(`/api/locations/${id}`).catch((e) =>
    console.warn('locationService: delete в бэкенде не удался', e),
  )
}

/** Гидрация из бэкенда в localStorage (общие точки для всех браузеров). */
export async function loadLocations(companyId: string): Promise<ServiceLocation[]> {
  _companyId = companyId
  if (!isApiEnabled()) return lsGet()
  try {
    const rows = await get<ApiLocation[]>('/api/locations', { company_id: companyId })
    const backend = rows.map(fromApi)
    const local = lsGet()
    if (backend.length === 0 && local.length > 0) {
      // Бэкенд пуст, есть локальные — одноразовая миграция вверх.
      for (const l of local) mirrorPush(l)
      return local
    }
    lsSet(backend)
    return backend
  } catch (e) {
    console.warn('locationService: loadLocations упал, остаюсь на localStorage', e)
    return lsGet()
  }
}

// ─── Записи (sync localStorage + зеркало бэкенда) ─────────────────────────
export function createLocation(data: {
  code: string
  name: string
  type: LocationType
  status?: LocationStatus
  address?: string
  description?: string
  sourceBindings?: LocationSourceBinding[]
  metadata?: Record<string, unknown>
}): ServiceLocation {
  const location: ServiceLocation = {
    id: nanoid(10),
    code: data.code,
    name: data.name,
    type: data.type,
    status: data.status ?? 'active',
    address: data.address,
    description: data.description,
    sourceBindings: data.sourceBindings ?? [],
    metadata: data.metadata,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }
  const all = lsGet()
  all.push(location)
  lsSet(all)
  mirrorPush(location)
  return location
}

export function updateLocation(
  id: string,
  updates: Partial<ServiceLocation>,
): ServiceLocation | undefined {
  const all = lsGet()
  const idx = all.findIndex((l) => l.id === id)
  if (idx === -1) return undefined
  all[idx] = { ...all[idx], ...updates, updatedAt: new Date().toISOString() }
  lsSet(all)
  mirrorPatch(id, updates)
  return all[idx]
}

export function deleteLocation(id: string): boolean {
  const all = lsGet()
  const filtered = all.filter((l) => l.id !== id)
  if (filtered.length === all.length) return false
  lsSet(filtered)
  mirrorDelete(id)
  return true
}
