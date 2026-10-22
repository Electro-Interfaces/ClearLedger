/** История только текущего пространства, без страниц входа и внешних сайтов. */
export interface NavigationEntry {
  key: string
  id: string
  aliases: string[]
  position: number
}

export interface NavigationHistory {
  entries: NavigationEntry[]
  index: number
}

export function startNavigationHistory(key: string, position = 0): NavigationHistory {
  return { entries: [{ key, id: key, aliases: [key], position }], index: 0 }
}

export function advanceNavigationHistory(
  history: NavigationHistory, key: string, action: 'POP' | 'PUSH' | 'REPLACE',
  position?: number,
): NavigationHistory {
  if (history.entries[history.index].key === key) return history
  // При быстром переходе нормализация фильтра может сделать REPLACE раньше,
  // чем React успел отрисовать PUSH. Нативный idx различает эти посещения.
  if (action === 'REPLACE' && position !== undefined
      && history.entries[history.index].position !== position) {
    const index = history.entries.findIndex((entry) => entry.position === position)
    if (index >= 0) {
      const entries = [...history.entries]
      const entry = entries[index]
      entries[index] = { ...entry, key, aliases: [...entry.aliases, key] }
      return { entries, index }
    }
    if (position < history.entries[history.index].position) return startNavigationHistory(key, position)
    action = 'PUSH'
  }
  if (action === 'POP') {
    let index = history.entries.findIndex((entry) => entry.aliases.includes(key))
    if (index < 0 && position !== undefined) {
      index = history.entries.findIndex((entry) => entry.position === position)
    }
    if (index < 0) {
      // Быстрый Back может отменить первый рендер PUSH. При Forward запись
      // уже существует в браузере, хотя React ещё не добавлял её в свой список.
      if (position !== undefined && position > history.entries[0].position) {
        const entry = { key, id: key, aliases: [key], position }
        const entries = [...history.entries, entry].sort((a, b) => a.position - b.position)
        return { entries, index: entries.indexOf(entry) }
      }
      return startNavigationHistory(key, position)
    }
    const entries = [...history.entries]
    const entry = entries[index]
    entries[index] = { ...entry, key, aliases: entry.aliases.includes(key) ? entry.aliases : [...entry.aliases, key] }
    return { entries, index }
  }
  if (action === 'REPLACE') {
    const entries = [...history.entries]
    const current = entries[history.index]
    entries[history.index] = { ...current, key, aliases: [...current.aliases, key] }
    return { entries, index: history.index }
  }
  const entries = [...history.entries.slice(0, history.index + 1),
    { key, id: key, aliases: [key], position: position ?? history.entries[history.index].position + 1 }]
  return { entries, index: entries.length - 1 }
}

export function navigationEntryId(history: NavigationHistory, key: string): string {
  return history.entries.find((entry) => entry.aliases.includes(key))?.id ?? key
}

/** Значения живут до выхода из пространства; скрытые экраны не монтируются ради кэша. */
export class NavigationViewStore {
  private values: Map<string, unknown>
  private save?: (entries: [string, unknown][]) => void

  constructor(entries: [string, unknown][] = [], save?: (entries: [string, unknown][]) => void) {
    this.values = new Map(entries)
    this.save = save
  }

  get<T>(key: string, fallback: T): T {
    return this.values.has(key) ? this.values.get(key) as T : fallback
  }

  set<T>(key: string, value: T): void {
    this.values.set(key, value)
    this.save?.([...this.values])
  }
}
