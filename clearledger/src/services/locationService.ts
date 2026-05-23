/**
 * CRUD для точек обслуживания (localStorage).
 * Точка обслуживания = место, где клиент ведёт бизнес: АЗС, магазин,
 * офис, склад. Привязывается к источникам данных через sourceBindings.
 */

import { getItem, setItem } from './storage'
import type {
  LocationSourceBinding,
  LocationStatus,
  LocationType,
  ServiceLocation,
} from '@/types/location'
import { nanoid } from 'nanoid'

const STORAGE_KEY = 'gig-locations'

export function getLocations(): ServiceLocation[] {
  return getItem<ServiceLocation[]>(STORAGE_KEY, [])
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
  const all = getLocations()
  all.push(location)
  setItem(STORAGE_KEY, all)
  return location
}

export function updateLocation(
  id: string,
  updates: Partial<ServiceLocation>,
): ServiceLocation | undefined {
  const all = getLocations()
  const idx = all.findIndex((l) => l.id === id)
  if (idx === -1) return undefined
  all[idx] = { ...all[idx], ...updates, updatedAt: new Date().toISOString() }
  setItem(STORAGE_KEY, all)
  return all[idx]
}

export function deleteLocation(id: string): boolean {
  const all = getLocations()
  const filtered = all.filter((l) => l.id !== id)
  if (filtered.length === all.length) return false
  setItem(STORAGE_KEY, filtered)
  return true
}

/** Найти точки, привязанные к источнику */
export function getLocationsBySource(sourceId: string): ServiceLocation[] {
  return getLocations().filter((l) =>
    l.sourceBindings.some((b) => b.sourceId === sourceId),
  )
}
