/**
 * Клиент приёма первички (`/api/intake-docs`).
 *
 * Загрузка и приём — РАЗНЫЕ действия: `upload` только разбирает и проверяет,
 * `accept` пишет документы в учёт. Между ними стоит человек, и это не формальность:
 * в разборе видно, чего система не поняла и что её смущает.
 */
import { get, post } from './apiClient'

export interface IntakeCheck {
  level: 'error' | 'warning' | 'info'
  code: string
  text: string
}

export interface IntakeItemRow {
  id: string
  rowNo: number
  docType: string
  number: string | null
  date: string | null
  counterpartyName: string | null
  counterpartyInn: string | null
  /** null — контрагент не сведён со справочником: новый или назван иначе. */
  counterpartyId: string | null
  contractName: string | null
  contractId: string | null
  amount: number
  vat: number
  lines: { name: string; qty: number; price: number; amount: number; vat: number }[]
  raw: Record<string, unknown> | null
  status: 'ready' | 'warning' | 'blocked' | 'duplicate' | 'accepted' | 'rejected'
  checks: IntakeCheck[]
  docId: string | null
}

export interface IntakeBatchRow {
  id: string
  source: string
  fileName: string | null
  declaredType: string | null
  uploadedBy: string | null
  status: string
  stats: { rows?: number; items?: number; ready?: number; warning?: number; blocked?: number; duplicate?: number }
  accepted: number
  createdAt: string | null
}

/** Разобрать файл. В учёт НИЧЕГО не пишет — только показывает, что понято. */
export async function uploadIntake(
  companyId: string, file: File, declaredType: string,
): Promise<{ batchId: string; items?: IntakeItemRow[]; error?: string; columns: string[] }> {
  const fd = new FormData()
  fd.append('company_id', companyId)
  fd.append('declared_type', declaredType)
  fd.append('source', 'file')
  fd.append('file', file)
  const res = await fetch('/api/intake-docs/upload', {
    method: 'POST',
    body: fd,
    credentials: 'include',
    headers: authHeader(),
  })
  if (!res.ok) throw new Error(`upload failed: ${res.status}`)
  return res.json()
}

/** Токен берём тем же ключом, что apiClient: FormData через `post` не отправить. */
function authHeader(): Record<string, string> {
  try {
    const t = localStorage.getItem('clearledger-token')
    return t ? { Authorization: `Bearer ${t}` } : {}
  } catch {
    return {}
  }
}

export const getIntakeBatches = (companyId: string) =>
  get<{ rows: IntakeBatchRow[] }>(`/api/intake-docs/batches?company_id=${companyId}`)

export const getIntakeItems = (companyId: string, batchId: string) =>
  get<{ rows: IntakeItemRow[] }>(
    `/api/intake-docs/items?company_id=${companyId}&batch_id=${batchId}`)

export const acceptIntake = (companyId: string, itemIds: string[]) =>
  post<{ created: number; skipped: number }>(
    `/api/intake-docs/accept?company_id=${companyId}`, itemIds)

export const rejectIntake = (companyId: string, itemIds: string[]) =>
  post<{ rejected: number }>(`/api/intake-docs/reject?company_id=${companyId}`, itemIds)
