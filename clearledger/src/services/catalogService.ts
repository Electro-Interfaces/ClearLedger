/**
 * Сервис справочников входного контура TradeLedger.
 * Три каталога: типы источников, шаблоны каналов, разрезы сверки.
 */
import { get } from './apiClient'

export interface DocTypeRef {
  id: string
  name: string
  description?: string | null
  category?: string | null
}

export interface SetupFieldSchema {
  key: string
  label: string
  type: string // text | password | number | select | tags | url
  required?: boolean
  default_value?: string | null
  placeholder?: string | null
  options?: { value: string; label: string }[] | null
  help_text?: string | null
  secret?: boolean
  group?: string | null
}

export interface SourceTypeItem {
  source_type: string
  label: string
  category: string
  description: string
  icon: string
  status: string // available | planned | partial
  version?: string
  setup_guide?: string // подробная инструкция подключения (только в панели, не в каталоге)
  setup_schema: SetupFieldSchema[]
  available_doc_types: DocTypeRef[]
}

export interface ChannelTemplateItem {
  id: string
  label: string
  category: string
  description: string
  icon: string
  direction: string
  status: string
  streams: { source_type: string; doc_type: string; role: string; label: string }[]
  stages: { stage_type: string; name: string }[]
  reconcile_rules: string[]
  schedule: Record<string, unknown>
}

export interface ReconcileRuleItem {
  id: string
  label: string
  module: string
  description: string
  status: string // imperative | planned
  impl: string
  streams: { role: string; source_type: string; doc_type: string; label: string }[]
  key: string[]
  match: { time_tolerance: string; pick?: string; bonus_fields?: unknown[] }
  compare: { field: string; tolerance_abs: number; unit: string }[]
  severity: { thresholds: Record<string, number> }
}

export const getSourceTypes = () =>
  get<{ items: SourceTypeItem[] }>('/api/source-types').then((r) => r.items)

export const getChannelTemplates = () =>
  get<{ items: ChannelTemplateItem[] }>('/api/channel-templates').then((r) => r.items)

export const getReconcileRules = () =>
  get<{ items: ReconcileRuleItem[] }>('/api/reconcile-rules').then((r) => r.items)
