/**
 * Подразделения — штатная структура компании: дерево с руководителями.
 * По ней строится цепочка эскалации и подача людей по отделам.
 */
import { get, post, patch, del } from './apiClient'

export interface Department {
  id: string
  name: string
  parent_id: string | null
  head_user_id: string | null
  head_name: string | null
  people: number
}

export async function listDepartments(companyId: string): Promise<Department[]> {
  const r = await get<{ departments: Department[] }>('/api/departments', { company_id: companyId })
  return r.departments
}

export async function createDepartment(companyId: string, data: {
  name: string; parentId?: string; headUserId?: string
}): Promise<{ id: string }> {
  return post('/api/departments', {
    company_id: companyId, name: data.name,
    parent_id: data.parentId || undefined, head_user_id: data.headUserId || undefined,
  })
}

/** parentId/headUserId: '' — снять значение; undefined — не трогать. */
export async function updateDepartment(id: string, companyId: string, data: {
  name?: string; parentId?: string; headUserId?: string
}): Promise<void> {
  await patch(`/api/departments/${id}`, {
    company_id: companyId, name: data.name,
    parent_id: data.parentId, head_user_id: data.headUserId,
  })
}

export async function deleteDepartment(id: string, companyId: string): Promise<void> {
  await del(`/api/departments/${id}?company_id=${encodeURIComponent(companyId)}`)
}
