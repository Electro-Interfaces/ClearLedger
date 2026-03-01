import type { AccountingDocType, MatchStatus, DocPurpose, SyncStatus } from '@/types'

export type EntryStatus = 'new' | 'recognized' | 'verified' | 'transferred' | 'error' | 'archived'

export interface StatusConfig {
  id: EntryStatus
  label: string
  variant: 'default' | 'secondary' | 'outline' | 'destructive'
  className: string
}

export const statuses: Record<EntryStatus, StatusConfig> = {
  new: {
    id: 'new',
    label: 'Новый',
    variant: 'outline',
    className: 'border-blue-400/50 text-blue-300/80',
  },
  recognized: {
    id: 'recognized',
    label: 'Распознан',
    variant: 'outline',
    className: 'border-amber-400/50 text-amber-300/80',
  },
  verified: {
    id: 'verified',
    label: 'Проверен',
    variant: 'outline',
    className: 'border-emerald-400/50 text-emerald-300/80',
  },
  transferred: {
    id: 'transferred',
    label: 'Передан',
    variant: 'default',
    className: 'bg-emerald-600/80 text-white border-emerald-600/80',
  },
  error: {
    id: 'error',
    label: 'Ошибка',
    variant: 'destructive',
    className: '',
  },
  archived: {
    id: 'archived',
    label: 'В архиве',
    variant: 'secondary',
    className: 'border-zinc-600 text-zinc-500',
  },
}

// ============================================================
// Назначение документа (DocPurpose)
// ============================================================

export const DOC_PURPOSE_CONFIG: Record<DocPurpose, { label: string; icon: string }> = {
  accounting: { label: 'Бухгалтерский', icon: 'FileText' },
  reference: { label: 'Справочный', icon: 'BookOpen' },
  context: { label: 'Контекстный', icon: 'Image' },
  archive: { label: 'Архивный', icon: 'Archive' },
}

// ============================================================
// Статус синхронизации (SyncStatus)
// ============================================================

export const SYNC_STATUS_CONFIG: Record<SyncStatus, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  not_applicable: { label: 'Не требуется', variant: 'secondary' },
  pending: { label: 'Ожидает', variant: 'outline' },
  exported: { label: 'Выгружен', variant: 'outline' },
  confirmed: { label: 'Подтверждён', variant: 'default' },
  rejected_1c: { label: 'Отклонён 1С', variant: 'destructive' },
}

// ============================================================
// Учётные документы 1С
// ============================================================

export const DOC_TYPE_LABELS: Record<AccountingDocType | string, string> = {
  receipt: 'Поступление',
  'invoice-received': 'СФ полученный',
  'payment-out': 'Платёж исходящий',
  'payment-in': 'Платёж входящий',
  sales: 'Реализация',
  'invoice-issued': 'СФ выданный',
  reconciliation: 'Акт сверки',
}

export const MATCH_STATUS_CONFIG: Record<MatchStatus | string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  matched: { label: 'Сопоставлен', variant: 'default' },
  unmatched: { label: 'Без пары', variant: 'destructive' },
  discrepancy: { label: 'Расхождение', variant: 'secondary' },
  pending: { label: 'Ожидает', variant: 'outline' },
}
