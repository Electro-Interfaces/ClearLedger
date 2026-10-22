/** URL реестра и заготовки постановки имеют разный смысл даже при одном исполнителе. */
export function taskDraft(params: URLSearchParams) {
  if (!params.has('draft')) return undefined
  const title = params.get('draft') || undefined
  // Старые ссылки с заголовком ещё читаются; новые используют отдельный параметр.
  const assigneeId = params.get('draft_assignee') || params.get('assignee') || undefined
  return title || assigneeId ? { title, assigneeId } : undefined
}

export function consumeTaskDraft(params: URLSearchParams) {
  const next = new URLSearchParams(params)
  if (!params.has('draft')) return next
  next.delete('draft')
  if (!params.has('draft_assignee')) next.delete('assignee')
  next.delete('draft_assignee')
  return next
}

export function taskDraftParams(title: string, assigneeId: string) {
  const params = new URLSearchParams()
  if (title.trim() || assigneeId) {
    params.set('draft', title.trim())
    if (assigneeId) params.set('draft_assignee', assigneeId)
  }
  return params
}

const REPORT_SCOPES = ['open', 'overdue', 'closed', 'mine', 'all', 'triage'] as const
export type TaskReportScope = typeof REPORT_SCOPES[number]

/** Из отчёта разрешено сужать реестр; личные пункты сохраняют свой вопрос. */
export function taskReportScope(params: URLSearchParams): TaskReportScope | undefined {
  const scope = params.get('scope')
  return REPORT_SCOPES.find((candidate) => candidate === scope)
}

export function taskReportParams(
  filters: { scope?: string; assignee?: string; type?: string; object?: string },
  period: { from: string; to: string },
) {
  const params = new URLSearchParams({ view: 'registry', scope: filters.scope ?? 'all' })
  for (const key of ['assignee', 'type', 'object'] as const) {
    if (filters[key]) params.set(key, filters[key])
  }
  // Открытый остаток — на сейчас. Период закрытия относится только к закрытому.
  if (filters.scope === 'closed') {
    params.set('closed_from', period.from)
    params.set('closed_to', period.to)
  }
  return params
}

/** Обе боковые полосы оставляют списку хотя бы 360 px, даже после resize ручками. */
export function taskQueueIsCompact(width: number, rail: number, day: number) {
  return width < rail + day + 360 + 16
}
