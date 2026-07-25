/**
 * Клиент карты пространства (Центр управления → «Карта»).
 *
 * Классические разделы отвечают «что настроено», карта — «что здесь происходит»: кто эти
 * люди, куда допущен каждый, кто давно не заходил, где активность. Только чтение.
 */
import { get } from './apiClient'

export interface SpaceMapPerson {
  id: string
  name: string
  email: string
  partyType: 'internal' | 'partner' | 'vendor'
  orgName?: string | null
  role: string
  position?: string | null
  isSuperadmin: boolean
  apps: string[]
  fullAccess: boolean
  lastSeenAt?: string | null
  online: boolean
  events: number
}

export interface SpaceMapCompany {
  id: string
  name: string
  slug: string
  apps: { code: string; name: string; enabled: boolean }[]
  people: SpaceMapPerson[]
  counts: {
    people: number
    online: number
    internal: number
    partners: number
    neverSeen: number
    noAccess: number
    objects: number
    organizations: number
    equipment: number
    events: number
  }
  topActions: { action: string; count: number }[]
}

export interface SpaceMapEvent {
  at?: string | null
  company: string
  userName: string
  action: string
  summary?: string | null
}

export interface SpaceMap {
  windowDays: number
  companies: SpaceMapCompany[]
  recentEvents: SpaceMapEvent[]
}

/** Карта пространства. Без companyId суперадмин получает весь контейнер. */
export async function getSpaceMap(companyId?: string): Promise<SpaceMap> {
  return get<SpaceMap>('/api/registry/space-map', companyId ? { company_id: companyId } : undefined)
}
