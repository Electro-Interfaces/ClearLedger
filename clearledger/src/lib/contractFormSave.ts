/** Локальные UUID имеют приоритет; внешний ключ разрешается только однозначно. */
export function localReferenceId(ref: string, rows: readonly { id: string; externalRef?: string }[]): string {
  if (rows.some((row) => row.id === ref)) return ref
  const matches = rows.filter((row) => row.externalRef === ref)
  return matches.length === 1 ? matches[0].id : ''
}

export function searchContractCounterparties<T extends { name: string; inn?: string }>(rows: readonly T[], query: string): T[] {
  const q = query.trim().toLocaleLowerCase('ru')
  return rows.filter((row) => !q || `${row.name} ${row.inn ?? ''}`.toLocaleLowerCase('ru').includes(q))
    .sort((a, b) => a.name.localeCompare(b.name, 'ru')).slice(0, 200)
}

const nullableCpFields = new Set([
  'shortName', 'fullName', 'kpp', 'ogrn', 'okpo', 'okved', 'legalAddress', 'actualAddress',
  'phone', 'email', 'directorName', 'directorPosition', 'bankAccount', 'bankBik', 'bankName',
])

/** undefined не попадает в JSON; в PATCH пустое редактируемое поле означает очистку. */
export function counterpartyPatch(updates: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(updates).map(([key, value]) =>
    [key, nullableCpFields.has(key) && (value === undefined || value === '') ? null : value]))
}

export interface CreationProgress {
  id?: string
  completed: string[]
  running?: boolean
}

/** Один create на черновик; подтверждённые этапы переживают отказ следующего запроса. */
export async function resumeCreation(
  progress: CreationProgress,
  create: () => Promise<{ id: string }>,
  steps: readonly { name: string; run: (id: string) => Promise<unknown> }[],
): Promise<string> {
  if (progress.running) throw new Error('Сохранение уже выполняется')
  progress.running = true
  try {
    if (!progress.id) progress.id = (await create()).id
    if (!progress.id) throw new Error('Сервер не вернул идентификатор созданной карточки')
    for (const step of steps) {
      if (progress.completed.includes(step.name)) continue
      await step.run(progress.id)
      progress.completed.push(step.name)
    }
    return progress.id
  } finally { progress.running = false }
}

/** Сначала перечитываем связи: часть прошлого сохранения уже могла пройти. */
export async function reconcileContractLinks<T extends { id?: string; app: string; projectRef?: string | null }>(
  after: readonly T[],
  read: () => Promise<T[]>,
  remove: (id: string) => Promise<unknown>,
  add: (link: T) => Promise<unknown>,
): Promise<void> {
  const before = await read()
  const key = (link: T) => JSON.stringify([link.app, link.projectRef ?? ''])
  const keep = new Set(after.map(key))
  for (const link of before) if (link.id && !keep.has(key(link))) await remove(link.id)
  const had = new Set(before.map(key))
  for (const link of after) {
    if (had.has(key(link))) continue
    await add(link)
    had.add(key(link))
  }
}
