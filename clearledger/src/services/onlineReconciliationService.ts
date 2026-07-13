import { del, get, post, put } from '@/services/apiClient'

export type OnlineReconStatus =
  | 'matched'
  | 'resolved'
  | 'wait_done'
  | 'only_msto'
  | 'only_transaction'
  | 'mismatch'
  | 'shift_mismatch'

export interface OnlineReconDecision {
  id: string
  status: 'open' | 'in_progress' | 'resolved'
  resolution: 'accept_msto' | 'accept_transaction' | 'accept_shift' | 'manual' | 'exclude'
  target_system: 'msto' | 'sts_transaction' | 'shift_report' | 'ledger' | 'none'
  canonical_amount: number | null
  canonical_volume: number | null
  instruction: string | null
  note: string | null
  assignee: string | null
  applied_at: string | null
  updated_at: string | null
}

export interface OnlineReconCase {
  case_key: string
  kind: 'transaction' | 'shift_gap'
  status: OnlineReconStatus
  base_status: OnlineReconStatus
  station_id: string | null
  station_code: number | null
  station_name: string
  shift_number: number | null
  shift_key: string | null
  fuel_code: number | null
  fuel_name: string
  event_at: string | null
  aggregator: string | null
  external_order_id: string | null
  online_order_id: string | null
  fuel_transaction_id: string | null
  transaction_ext_id: number | null
  msto_amount: number | null
  msto_volume: number | null
  transaction_amount: number | null
  transaction_volume: number | null
  shift_amount: number | null
  shift_volume: number | null
  operation_result: string | null
  effective_amount: number
  effective_volume: number
  decision: OnlineReconDecision | null
  locked: boolean
}

interface SourceTotal {
  count: number
  amount: number
  volume: number
}

export interface OnlineReconShift {
  key: string
  station_id: string
  station_code: number | null
  station_name: string
  shift_number: number
  opened_at: string | null
  closed_at: string | null
  locked: boolean
  status: OnlineReconStatus | 'needs_review'
  msto: SourceTotal
  transactions: SourceTotal
  shift: SourceTotal
  normalized: Omit<SourceTotal, 'count'>
  case_count: number
  unresolved_count: number
}

export interface OnlineReconWorkspace {
  period: { date_from: string; date_to: string }
  sources: {
    msto: SourceTotal
    transactions: SourceTotal
    shifts: SourceTotal
    normalized: SourceTotal
  }
  status_counts: Record<string, number>
  unresolved_count: number
  shifts: OnlineReconShift[]
  cases: OnlineReconCase[]
  refresh?: { msto?: unknown }
}

export interface OnlineReconParams {
  companyId: string
  dateFrom: string
  dateTo: string
  stationCodes?: number[]
  includeEmptyShifts?: boolean
}

export function getOnlineReconciliation(params: OnlineReconParams) {
  return get<OnlineReconWorkspace>('/api/reconciliation/online/workspace', {
    company_id: params.companyId,
    date_from: params.dateFrom,
    date_to: params.dateTo,
    station_codes: params.stationCodes?.length ? params.stationCodes.join(',') : undefined,
    include_empty_shifts: params.includeEmptyShifts ? 'true' : undefined,
  })
}

export function runOnlineReconciliation(params: OnlineReconParams) {
  return post<OnlineReconWorkspace>('/api/reconciliation/online/run', {
    company_id: params.companyId,
    date_from: params.dateFrom,
    date_to: params.dateTo,
    station_codes: params.stationCodes ?? [],
    include_empty_shifts: params.includeEmptyShifts ?? false,
    refresh_msto: true,
  })
}

export interface SaveDecisionBody {
  case: OnlineReconCase
  companyId: string
  status: 'open' | 'in_progress' | 'resolved'
  resolution: OnlineReconDecision['resolution']
  targetSystem: OnlineReconDecision['target_system']
  canonicalAmount?: number
  canonicalVolume?: number
  instruction?: string
  note?: string
  assignee?: string
}

export function saveOnlineDecision(body: SaveDecisionBody) {
  const c = body.case
  return put<OnlineReconDecision>('/api/reconciliation/online/decision', {
    company_id: body.companyId,
    case_key: c.case_key,
    station_id: c.station_id,
    shift_number: c.shift_number,
    fuel_code: c.fuel_code,
    online_order_id: c.online_order_id,
    fuel_transaction_id: c.fuel_transaction_id,
    status: body.status,
    resolution: body.resolution,
    target_system: body.targetSystem,
    canonical_amount: body.canonicalAmount,
    canonical_volume: body.canonicalVolume,
    instruction: body.instruction,
    note: body.note,
    assignee: body.assignee,
    source_snapshot: {
      msto: { amount: c.msto_amount, volume: c.msto_volume, external_id: c.external_order_id },
      transaction: { amount: c.transaction_amount, volume: c.transaction_volume, external_id: c.transaction_ext_id },
      shift: { amount: c.shift_amount, volume: c.shift_volume, number: c.shift_number },
    },
  })
}

export function deleteOnlineDecision(companyId: string, caseKey: string) {
  return del<{ deleted: number }>(
    `/api/reconciliation/online/decision/${encodeURIComponent(caseKey)}?company_id=${encodeURIComponent(companyId)}`,
  )
}

export function applyOnlineDecisions(params: OnlineReconParams) {
  return post<{ ok: boolean; applied: number; resolved_cases: number }>(
    '/api/reconciliation/online/apply',
    {
      company_id: params.companyId,
      date_from: params.dateFrom,
      date_to: params.dateTo,
      station_codes: params.stationCodes ?? [],
    },
  )
}
