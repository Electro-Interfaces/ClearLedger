import { get, put, del } from '@/services/apiClient'
import type { CounterpartyContact } from '@/services/referenceService'

export interface LocationContact extends CounterpartyContact {
  counterpartyName: string
  responsibility: string | null
}
export interface LocationContacts {
  assigned: LocationContact[]
  organizationContacts: LocationContact[]
  canEditContacts: boolean
}
export interface LocationContactOptions {
  counterparties: { id: string; name: string }[]
  contacts: LocationContact[]
  canEditContacts: boolean
}
const path = (id: string) => `/api/references/locations/${encodeURIComponent(id)}`
export const getLocationContacts = (id: string) => get<LocationContacts>(`${path(id)}/contacts`)
export const getLocationContactOptions = (id: string) => get<LocationContactOptions>(`${path(id)}/contact-options`)
export const assignLocationContact = (id: string, contactId: string, responsibility: string) =>
  put<LocationContact>(`${path(id)}/contacts/${contactId}`, { responsibility })
export const removeLocationContact = (id: string, contactId: string) => del(`${path(id)}/contacts/${contactId}`)
