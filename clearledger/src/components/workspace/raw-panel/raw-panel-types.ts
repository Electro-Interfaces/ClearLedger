import type { StsShift } from '@/services/fuel/types'
import type { ShiftRecord } from '@/services/fuel/types'
import type { DeliveryRecord } from '@/services/receiptExtractService'
import type { LoadedDocument } from '@/services/channelSyncService'

export interface FsNode {
  name: string
  type: 'folder' | 'file'
  path: string
  /** Загруженный документ каталога компании (для файлов). */
  doc?: LoadedDocument
  /** STS shift data (for shift files) */
  shift?: StsShift
  stationId?: number
  /** Child count for folders */
  childCount?: number
  /** Formatted date string */
  date?: string
  /** Status text */
  status?: string
  /** Size or volume string */
  size?: string
  /** Document type for icon selection */
  docType?: 'shift' | 'delivery'
  /** Delivery record ref (for TTN files) */
  deliveryRecord?: DeliveryRecord
  /** Shift record ref (for loaded shift files) */
  shiftRecord?: ShiftRecord
}

export type ViewMode = 'tree' | 'list'

export type SortColumn = 'name' | 'date' | 'status'
export type SortDirection = 'asc' | 'desc'

export interface SortConfig {
  column: SortColumn
  direction: SortDirection
}

export interface RawPanelFilters {
  searchQuery: string
  status: 'all' | 'open' | 'closed'
  docType: 'all' | 'shifts' | 'receipts'
}

export interface TreeState {
  expandedPaths: string[]
  scrollTop: number
}

// ─── Advanced Filters (universal, not fuel-specific) ──────────

export interface AdvancedFilters {
  /** Text search across title, number, counterparty */
  query: string
  /** Date range */
  dateFrom: string
  dateTo: string
  /** Document classification */
  category: string        // 'all' | dynamic from data
  docType: string         // 'all' | dynamic from data
  /** Binding */
  objectId: string        // 'all' | specific object (station, warehouse, etc.)
  counterparty: string    // 'all' | specific
  source: string          // 'all' | 'sts-api' | '1c' | 'manual' | ...
  /** Status multi-select */
  statuses: string[]      // ['open', 'closed', 'draft', 'posted']
  /** Special filters */
  onlyWithIssues: boolean
}

export const DEFAULT_ADVANCED_FILTERS: AdvancedFilters = {
  query: '',
  dateFrom: '',
  dateTo: '',
  category: 'all',
  docType: 'all',
  objectId: 'all',
  counterparty: 'all',
  source: 'all',
  statuses: [],
  onlyWithIssues: false,
}

export type GroupMode =
  | 'default'     // Object → Year → Month → Type
  | 'object'      // Object → Documents
  | 'category'    // Category → Type → Documents
  | 'date'        // Year → Month → Documents
  | 'status'      // Status → Documents
  | 'source'      // Source → Documents
  | 'flat'        // No grouping

export interface FilterPreset {
  id: string
  label: string
  apply: Partial<AdvancedFilters>
}

export interface StatsBreakdown {
  label: string
  count: number
  percent: number
}

export interface DocumentStats {
  total: number
  filtered: number
  byStatus: StatsBreakdown[]
  byCategory: StatsBreakdown[]
  byObject: StatsBreakdown[]
  byMonth: StatsBreakdown[]
  bySource: StatsBreakdown[]
}
