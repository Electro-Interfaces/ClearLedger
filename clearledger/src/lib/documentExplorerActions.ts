/** Links to the owning screens; opening a catalogue row never creates a copy. */
export interface DocumentRouteMetadata {
  docId?: string | null
  contractId?: string | null
  contractIds?: string[]
  fileId?: string | null
  siteId?: string | null
  projectId?: string | null
  siteDocId?: string | null
}

export interface ExplorerAction {
  id: 'card' | 'file' | 'contract' | 'project' | 'channel' | `contract:${string}`
  label: string
  href: string
  attachment?: boolean
}

export function documentExplorerActions(metadata: DocumentRouteMetadata, canOpen: (href: string) => boolean, prefix = ''): ExplorerAction[] {
  const actions: ExplorerAction[] = []
  if (metadata.docId) actions.push({ id: 'card', label: 'Карточка', href: `/docs?view=all&doc=${encodeURIComponent(metadata.docId)}` })
  if (metadata.fileId) actions.push({ id: 'file', label: 'Файл', href: `/api/files/${encodeURIComponent(metadata.fileId)}`, attachment: true })
  const contracts = [...new Set([metadata.contractId, ...(metadata.contractIds ?? [])].filter((id): id is string => !!id))]
  contracts.forEach((id, index) => actions.push({ id: index === 0 ? 'contract' : `contract:${id}`, label: index === 0 ? 'Договор' : `Договор ${index + 1}`, href: `${prefix}/contractors?sub=contracts&contract=${encodeURIComponent(id)}` }))
  // The project workspace loads getSite(project); a site ID is its canonical key.
  const site = metadata.siteId
  if (site) actions.push({ id: 'project', label: 'Проект', href: `/projects?mode=projects&sub=pr_project&project=${encodeURIComponent(site)}&ptab=docs` })
  if (!site && metadata.projectId) actions.push({ id: 'project', label: 'Все проекты', href: '/projects?mode=projects&sub=pr_project' })
  return actions.filter((action) => action.attachment || canOpen(action.href))
}

export function primaryExplorerAction(actions: ExplorerAction[]): ExplorerAction | undefined {
  return actions.find((action) => action.id === 'card')
    ?? actions.find((action) => !action.attachment)
    ?? actions[0]
}

export interface ExplorerLocation { folder: string[]; query: string }
export interface ExplorerHistory { entries: ExplorerLocation[]; index: number }

export function readExplorerLocation(search: string): ExplorerLocation {
  const params = new URLSearchParams(search)
  return { folder: (params.get('folder') ?? '').split('/').filter(Boolean), query: params.get('q') ?? '' }
}

export function pushExplorerHistory(history: ExplorerHistory, next: ExplorerLocation): ExplorerHistory {
  const current = history.entries[history.index]
  if (current.query === next.query && current.folder.join('/') === next.folder.join('/')) return history
  const entries = [...history.entries.slice(0, history.index + 1), next].slice(-100)
  return { entries, index: entries.length - 1 }
}

export function restoreExplorerHistory(saved: ExplorerHistory | null, current: ExplorerLocation): ExplorerHistory {
  if (!saved?.entries?.length || !saved.entries[saved.index]) return { entries: [current], index: 0 }
  const active = saved.entries[saved.index]
  if (active.query === current.query && active.folder.join('/') === current.folder.join('/')) return saved
  const index = saved.entries.findIndex((entry) => entry.query === current.query && entry.folder.join('/') === current.folder.join('/'))
  return index >= 0 ? { ...saved, index } : pushExplorerHistory(saved, current)
}
