/**
 * Каталог типов точек — API-first (через React Query hook useLocationTypes).
 * В офлайне (без VITE_API_URL) — встроенный набор как фолбэк.
 */
import { get, post, patch, del, isApiEnabled } from './apiClient'
import type { LocationTypeDef, MetadataField, NomenclatureKind } from '@/types/locationType'
import { BUILTIN_LOCATION_TYPES } from '@/config/locationTypes'

interface ApiLocationType {
  id: string
  company_id: string | null
  code: string
  name: string
  icon: string
  unit: string
  nomenclature_kind: string
  fields: MetadataField[]
  is_builtin: boolean
  sort_order: number
  status: string
}

function fromApi(r: ApiLocationType): LocationTypeDef {
  return {
    id: r.id,
    companyId: r.company_id,
    code: r.code,
    name: r.name,
    icon: r.icon,
    unit: r.unit,
    nomenclatureKind: (r.nomenclature_kind as NomenclatureKind) ?? 'none',
    fields: r.fields ?? [],
    isBuiltin: r.is_builtin,
    sortOrder: r.sort_order,
    status: r.status,
  }
}

export interface LocationTypeInput {
  code: string
  name: string
  icon?: string
  unit?: string
  nomenclatureKind?: NomenclatureKind
  fields?: MetadataField[]
  sortOrder?: number
  status?: string
}

function toBody(input: LocationTypeInput): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  if (input.code !== undefined) body.code = input.code
  if (input.name !== undefined) body.name = input.name
  if (input.icon !== undefined) body.icon = input.icon
  if (input.unit !== undefined) body.unit = input.unit
  if (input.nomenclatureKind !== undefined) body.nomenclature_kind = input.nomenclatureKind
  if (input.fields !== undefined) body.fields = input.fields
  if (input.sortOrder !== undefined) body.sort_order = input.sortOrder
  if (input.status !== undefined) body.status = input.status
  return body
}

/** Все типы активной компании: встроенные + кастомные. */
export async function loadLocationTypes(companyId: string): Promise<LocationTypeDef[]> {
  if (!isApiEnabled()) return BUILTIN_LOCATION_TYPES
  try {
    const rows = await get<ApiLocationType[]>('/api/location-types', { company_id: companyId })
    return rows.map(fromApi)
  } catch (e) {
    console.warn('locationTypeService: loadLocationTypes упал, фолбэк на встроенные', e)
    return BUILTIN_LOCATION_TYPES
  }
}

export async function createLocationType(
  companyId: string, input: LocationTypeInput,
): Promise<LocationTypeDef> {
  const r = await post<ApiLocationType>('/api/location-types', {
    company_id: companyId, ...toBody(input),
  })
  return fromApi(r)
}

export async function updateLocationType(
  id: string, input: LocationTypeInput,
): Promise<LocationTypeDef> {
  const r = await patch<ApiLocationType>(`/api/location-types/${id}`, toBody(input))
  return fromApi(r)
}

export async function deleteLocationType(id: string): Promise<void> {
  await del(`/api/location-types/${id}`)
}
