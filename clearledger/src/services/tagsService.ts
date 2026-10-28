/** Личные теги: видит только хозяин (server/app/routers/personal_tags_router.py). */
import { get, post } from './apiClient'
import type { TagTone } from '@/lib/tagTones'

export interface PersonalTag { id: string; name: string; color: TagTone; position: number }

export async function listTags(companyId: string) {
  return get<{ tags: PersonalTag[]; links: Record<string, string[]> }>('/api/work/tags', { company_id: companyId })
}

export async function createTag(companyId: string, name: string, color: TagTone) {
  return post<PersonalTag>('/api/work/tags', { company_id: companyId, name, color })
}

export async function updateTag(companyId: string, id: string, data: { name?: string; color?: TagTone; delete?: boolean }) {
  return post<PersonalTag | { deleted: true }>(`/api/work/tags/${id}`, { company_id: companyId, ...data })
}

/** Теги предмета целиком: пришедший набор заменяет прежний. */
export async function assignTags(companyId: string, targetRef: string, tagIds: string[]) {
  return post<{ target_ref: string; tag_ids: string[] }>('/api/work/tags-assign',
    { company_id: companyId, target_ref: targetRef, tag_ids: tagIds })
}
