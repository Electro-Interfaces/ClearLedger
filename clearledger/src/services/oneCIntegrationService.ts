/**
 * API-сервис интеграции ClearLedger ↔ 1С:Бухгалтерия 3.0
 */

import { get, post, patch, del } from '@/services/apiClient'
import type {
  OneCConnection, OneCSyncLog, OneCTestResult, OneCSyncResult,
} from '@/types'

// ── Маппинг snake_case ↔ camelCase ──────────────────────

interface ApiOneCConnection {
  id: string
  company_id: string
  name: string
  odata_url: string
  username: string
  exchange_path: string | null
  status: string
  last_sync_at: string | null
  sync_interval_sec: number
  created_at: string
  updated_at: string
}

function apiToConnection(a: ApiOneCConnection): OneCConnection {
  return {
    id: a.id,
    companyId: a.company_id,
    name: a.name,
    odataUrl: a.odata_url,
    username: a.username,
    exchangePath: a.exchange_path ?? undefined,
    status: a.status as OneCConnection['status'],
    lastSyncAt: a.last_sync_at ?? undefined,
    syncIntervalSec: a.sync_interval_sec,
    createdAt: a.created_at,
    updatedAt: a.updated_at,
  }
}

interface ApiOneCSyncLog {
  id: string
  connection_id: string
  direction: string
  sync_type: string
  status: string
  items_processed: number
  items_created: number
  items_updated: number
  items_errors: number
  details: Record<string, unknown>
  started_at: string
  finished_at: string | null
}

function apiToSyncLog(a: ApiOneCSyncLog): OneCSyncLog {
  return {
    id: a.id,
    connectionId: a.connection_id,
    direction: a.direction as OneCSyncLog['direction'],
    syncType: a.sync_type as OneCSyncLog['syncType'],
    status: a.status as OneCSyncLog['status'],
    itemsProcessed: a.items_processed,
    itemsCreated: a.items_created,
    itemsUpdated: a.items_updated,
    itemsErrors: a.items_errors,
    details: a.details,
    startedAt: a.started_at,
    finishedAt: a.finished_at ?? undefined,
  }
}

interface ApiSyncResult {
  status: string
  stats: { processed: number; created: number; updated: number; errors: number }
  details: Record<string, unknown>
  log_id: string
}

function apiToSyncResult(a: ApiSyncResult): OneCSyncResult {
  return {
    status: a.status,
    stats: a.stats,
    details: a.details,
    logId: a.log_id,
  }
}

// ── Подключения ─────────────────────────────────────────

export interface CreateConnectionInput {
  companyId: string
  name?: string
  odataUrl: string
  username: string
  password: string
  exchangePath?: string
  syncIntervalSec?: number
}

export interface UpdateConnectionInput {
  name?: string
  odataUrl?: string
  username?: string
  password?: string
  exchangePath?: string
  syncIntervalSec?: number
  status?: string
}

export async function getConnections(companyId?: string): Promise<OneCConnection[]> {
  const params = companyId ? { company_id: companyId } : undefined
  const res = await get<ApiOneCConnection[]>('/api/onec/connections', params)
  return res.map(apiToConnection)
}

export async function getConnection(id: string): Promise<OneCConnection> {
  const res = await get<ApiOneCConnection>(`/api/onec/connections/${id}`)
  return apiToConnection(res)
}

export async function createConnection(input: CreateConnectionInput): Promise<OneCConnection> {
  const res = await post<ApiOneCConnection>('/api/onec/connections', {
    company_id: input.companyId,
    name: input.name ?? '1С:Бухгалтерия',
    odata_url: input.odataUrl,
    username: input.username,
    password: input.password,
    exchange_path: input.exchangePath,
    sync_interval_sec: input.syncIntervalSec ?? 300,
  })
  return apiToConnection(res)
}

export async function updateConnection(id: string, input: UpdateConnectionInput): Promise<OneCConnection> {
  const body: Record<string, unknown> = {}
  if (input.name !== undefined) body.name = input.name
  if (input.odataUrl !== undefined) body.odata_url = input.odataUrl
  if (input.username !== undefined) body.username = input.username
  if (input.password !== undefined) body.password = input.password
  if (input.exchangePath !== undefined) body.exchange_path = input.exchangePath
  if (input.syncIntervalSec !== undefined) body.sync_interval_sec = input.syncIntervalSec
  if (input.status !== undefined) body.status = input.status

  const res = await patch<ApiOneCConnection>(`/api/onec/connections/${id}`, body)
  return apiToConnection(res)
}

export async function deleteConnection(id: string): Promise<void> {
  await del(`/api/onec/connections/${id}`)
}

// ── Тест подключения ────────────────────────────────────

export async function testConnection(id: string): Promise<OneCTestResult> {
  return post<OneCTestResult>(`/api/onec/connections/${id}/test`)
}

// ── Синхронизация ───────────────────────────────────────

export async function syncCatalogs(id: string): Promise<OneCSyncResult> {
  const res = await post<ApiSyncResult>(`/api/onec/connections/${id}/sync/catalogs`)
  return apiToSyncResult(res)
}

export async function syncDocuments(id: string): Promise<OneCSyncResult> {
  const res = await post<ApiSyncResult>(`/api/onec/connections/${id}/sync/documents`)
  return apiToSyncResult(res)
}

export async function syncFull(id: string): Promise<OneCSyncResult> {
  const res = await post<ApiSyncResult>(`/api/onec/connections/${id}/sync/full`)
  return apiToSyncResult(res)
}

// ── Статус и история ────────────────────────────────────

export interface SyncStatusResponse {
  isSyncing: boolean
  currentLog: OneCSyncLog | null
  connectionStatus: string
  lastSyncAt: string | null
}

export async function getSyncStatus(id: string): Promise<SyncStatusResponse> {
  const res = await get<{
    is_syncing: boolean
    current_log: ApiOneCSyncLog | null
    connection_status: string
    last_sync_at: string | null
  }>(`/api/onec/connections/${id}/sync/status`)

  return {
    isSyncing: res.is_syncing,
    currentLog: res.current_log ? apiToSyncLog(res.current_log) : null,
    connectionStatus: res.connection_status,
    lastSyncAt: res.last_sync_at,
  }
}

export async function getSyncHistory(id: string, limit = 20): Promise<OneCSyncLog[]> {
  const res = await get<ApiOneCSyncLog[]>(`/api/onec/connections/${id}/history`, { limit })
  return res.map(apiToSyncLog)
}

// ── Экспорт ─────────────────────────────────────────────

export interface ExportResult {
  status: string
  filePath?: string
  entriesCount: number
  error?: string
}

export interface ExportFeedback {
  status: string
  files: Array<{
    filename: string
    status: string
    processedCount?: number
    errorCount?: number
    errors?: Array<{ code: string; message: string }>
  }>
  error?: string
}

export async function exportTo1C(id: string): Promise<ExportResult> {
  const res = await post<{ status: string; file_path: string | null; entries_count: number; error?: string }>(
    `/api/onec/connections/${id}/export`
  )
  return {
    status: res.status,
    filePath: res.file_path ?? undefined,
    entriesCount: res.entries_count,
    error: res.error,
  }
}

export async function getExportStatus(id: string): Promise<ExportFeedback> {
  return get<ExportFeedback>(`/api/onec/connections/${id}/export/status`)
}
