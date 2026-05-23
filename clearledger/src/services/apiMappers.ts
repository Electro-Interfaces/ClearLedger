/**
 * Централизованные маппинги API (snake_case) ↔ Frontend (camelCase).
 * Все API-типы и функции преобразования — в одном месте.
 */

import type { DataEntry, Connector, DocumentLink, LinkType, AuditEvent } from '@/types'
import type { EntryStatus } from '@/config/statuses'
import type { Company } from '@/config/companies'

// ============================================================
// DataEntry
// ============================================================

export interface ApiEntry {
  id: string
  company_id: string
  source_id: string | null
  title: string
  category_id: string
  subcategory_id: string
  doc_type_id: string | null
  status: string
  doc_purpose?: string
  sync_status?: string
  source_type?: string
  source: string
  source_label: string
  metadata: Record<string, string>
  created_at: string
  updated_at: string
  verified_at?: string | null
  verified_by?: string | null
  transferred_at?: string | null
  file_url?: string | null
  file_type?: string | null
  file_size?: number | null
  ocr_data?: Record<string, unknown> | null
}

export function apiToEntry(a: ApiEntry): DataEntry {
  return {
    id: a.id,
    title: a.title,
    categoryId: a.category_id,
    subcategoryId: a.subcategory_id,
    docTypeId: a.doc_type_id ?? undefined,
    companyId: a.company_id,
    status: a.status as EntryStatus,
    docPurpose: (a.doc_purpose as DataEntry['docPurpose']) ?? 'accounting',
    syncStatus: (a.sync_status as DataEntry['syncStatus']) ?? 'not_applicable',
    source: (a.source_type ?? a.source) as DataEntry['source'],
    sourceLabel: a.source_label,
    metadata: a.metadata,
    sourceId: a.source_id ?? undefined,
    fileUrl: a.file_url ?? undefined,
    fileType: a.file_type ?? undefined,
    fileSize: a.file_size ?? undefined,
    createdAt: a.created_at,
    updatedAt: a.updated_at,
  }
}

// ============================================================
// Company
// ============================================================

export interface ApiCompany {
  id: string
  name: string
  slug: string
  short_name?: string
  profile_id: string
  color?: string
  inn?: string
  created_at: string
}

export function apiToCompany(a: ApiCompany): Company {
  return {
    id: a.slug ?? a.id,
    name: a.name,
    shortName: a.short_name ?? a.name,
    profileId: a.profile_id as Company['profileId'],
    color: a.color ?? '#3b82f6',
    inn: a.inn,
  }
}

export function companyToApi(c: Company): Record<string, unknown> {
  return {
    name: c.name,
    slug: c.id,
    short_name: c.shortName,
    profile_id: c.profileId,
    color: c.color,
    inn: c.inn,
  }
}

// ============================================================
// Connector
// ============================================================

export interface ApiConnector {
  id: string
  name: string
  type: string
  url: string
  company_id: string
  status: string
  last_sync: string | null
  last_sync_at: string | null
  sync_status: string
  records_count: number
  errors_count: number
  category_id: string
  interval: number
  config: Record<string, unknown>
  created_at: string
}

export function apiToConnector(a: ApiConnector): Connector {
  return {
    id: a.id,
    name: a.name,
    type: a.type,
    url: a.url,
    companyId: a.company_id,
    status: a.status as Connector['status'],
    lastSync: a.last_sync ?? undefined,
    lastSyncAt: a.last_sync_at ?? undefined,
    syncStatus: (a.sync_status as Connector['syncStatus']) ?? undefined,
    recordsCount: a.records_count,
    errorsCount: a.errors_count,
    categoryId: a.category_id,
    interval: a.interval,
  }
}

export function connectorToApi(
  c: Partial<Omit<Connector, 'id' | 'companyId'>> & { companyId?: string },
): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  if (c.name !== undefined) body.name = c.name
  if (c.type !== undefined) body.type = c.type
  if (c.url !== undefined) body.url = c.url
  if (c.companyId !== undefined) body.company_id = c.companyId
  if (c.status !== undefined) body.status = c.status
  if (c.categoryId !== undefined) body.category_id = c.categoryId
  if (c.interval !== undefined) body.interval = c.interval
  return body
}

// ============================================================
// DocumentLink
// ============================================================

export interface ApiDocumentLink {
  id: string
  source_entry_id: string
  target_entry_id: string
  link_type: string
  label: string | null
  created_at: string
}

export function apiToLink(a: ApiDocumentLink): DocumentLink {
  return {
    id: a.id,
    sourceEntryId: a.source_entry_id,
    targetEntryId: a.target_entry_id,
    type: a.link_type as LinkType,
    label: a.label ?? undefined,
    createdAt: a.created_at,
  }
}

export function linkToApi(
  sourceEntryId: string,
  targetEntryId: string,
  type: LinkType,
  label?: string,
): Record<string, unknown> {
  return {
    source_entry_id: sourceEntryId,
    target_entry_id: targetEntryId,
    link_type: type,
    label: label ?? null,
  }
}

// ============================================================
// AuditEvent
// ============================================================

export interface ApiAuditEvent {
  id: string
  entry_id: string | null
  company_id: string
  user_id: string
  user_name: string
  action: string
  details: string | null
  timestamp: string
}

export function apiToAuditEvent(a: ApiAuditEvent): AuditEvent {
  return {
    id: a.id,
    entryId: a.entry_id ?? undefined,
    companyId: a.company_id,
    userId: a.user_id,
    userName: a.user_name,
    action: a.action as AuditEvent['action'],
    details: a.details ?? undefined,
    timestamp: a.timestamp,
  }
}
