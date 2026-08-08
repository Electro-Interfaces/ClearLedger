import { get, put } from './apiClient'

export type BusinessRole = 'station_administrator' | 'network_merchandiser'
export type BusinessScope = 'station' | 'network'

export interface BusinessGrant {
  role: BusinessRole
  scope_type: BusinessScope
  scope_id: string
}

export interface StoreAccessPolicy {
  schema_version: number
  commercial_owner: 'station'
  central_mode: 'projection'
  fuel_mode: 'analytics_only'
  revision: string
  business_grants: BusinessGrant[]
  capabilities: {
    station_administrator: string[]
    network_merchandiser: boolean
    central_commercial_write: boolean
  }
}

export async function getStoreAccessPolicy(): Promise<StoreAccessPolicy> {
  return get<StoreAccessPolicy>('/api/store/access-policy')
}

export async function saveStoreAccessPolicy(): Promise<StoreAccessPolicy> {
  return put<StoreAccessPolicy>('/api/store/access-policy', { commercial_owner: 'station' })
}
