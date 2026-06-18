/**
 * ReconcileMapping CRUD — соответствия внешний ключ ↔ запись Catalog БП.
 * См. docs/sverka-spec.md §4.
 */

import { get, post, patch, del } from './apiClient'

export type MappingKind = 'station' | 'fuel' | 'paytype' | 'nomenclature' | 'counterparty'
export type MappingMethod = 'manual' | 'auto' | 'ai' | 'imported_from_bp'

export interface ReconcileMapping {
  id: string
  company_id: string
  /** Маппинг уровня канала (override). null = дефолт компании (общий для всех каналов). */
  channel_id?: string | null
  kind: MappingKind
  source_key: string
  target_ref: string
  target_name?: string | null
  confidence: number
  method: MappingMethod
  note?: string | null
  created_at: string
  updated_at: string
}

export interface MappingStats {
  total: number
  byKind: Record<string, number>
  byMethod: Record<string, number>
}

export async function listMappings(
  companyId: string,
  kind?: MappingKind,
  channelId?: string,
): Promise<ReconcileMapping[]> {
  return get<ReconcileMapping[]>('/api/reconcile/mappings', {
    company_id: companyId,
    kind: kind ?? undefined,
    channel_id: channelId ?? undefined,
  })
}

export async function createMapping(input: {
  companyId: string
  channelId?: string
  kind: MappingKind
  sourceKey: string
  targetRef: string
  targetName?: string
  confidence?: number
  method?: MappingMethod
  note?: string
}): Promise<ReconcileMapping> {
  return post<ReconcileMapping>('/api/reconcile/mappings', {
    company_id: input.companyId,
    channel_id: input.channelId,
    kind: input.kind,
    source_key: input.sourceKey,
    target_ref: input.targetRef,
    target_name: input.targetName,
    confidence: input.confidence ?? 100,
    method: input.method ?? 'manual',
    note: input.note,
  })
}

export async function updateMapping(id: string, input: Partial<{
  sourceKey: string
  targetRef: string
  targetName: string
  confidence: number
  method: MappingMethod
  note: string
}>): Promise<ReconcileMapping> {
  const body: Record<string, unknown> = {}
  if (input.sourceKey !== undefined) body.source_key = input.sourceKey
  if (input.targetRef !== undefined) body.target_ref = input.targetRef
  if (input.targetName !== undefined) body.target_name = input.targetName
  if (input.confidence !== undefined) body.confidence = input.confidence
  if (input.method !== undefined) body.method = input.method
  if (input.note !== undefined) body.note = input.note
  return patch<ReconcileMapping>(`/api/reconcile/mappings/${id}`, body)
}

export async function deleteMapping(id: string): Promise<void> {
  await del(`/api/reconcile/mappings/${id}`)
}

export async function mappingStats(companyId: string): Promise<MappingStats> {
  return get<MappingStats>('/api/reconcile/mappings/stats', { company_id: companyId })
}
