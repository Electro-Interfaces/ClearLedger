import { useSyncExternalStore } from 'react'

const KEY = 'report-kit.v1.rows'
const DEFAULT = 50
const PRESETS = [25, 50, 100, 200, 500]
const clamp = (n: number) => (n === 0 ? 0 : Math.min(5000, Math.max(10, Math.round(n))))

function read() {
  try {
    const raw = localStorage.getItem(KEY)
    const n = Number(raw)
    return raw !== null && Number.isFinite(n) && n >= 0 ? clamp(n) : DEFAULT
  } catch {
    return DEFAULT
  }
}

let size = read()
const subs = new Set<() => void>()

function setSize(n: number) {
  size = clamp(n)
  try {
    localStorage.setItem(KEY, String(size))
  } catch {
    size = clamp(n)
  }
  subs.forEach((f) => f())
}

export function usePageSize() {
  return useSyncExternalStore(
    (f) => {
      subs.add(f)
      return () => subs.delete(f)
    },
    () => size,
  )
}

export function PageSizeField() {
  const value = usePageSize()
  const opts = PRESETS.includes(value) || value === 0 ? PRESETS : [...PRESETS, value].sort((a, b) => a - b)
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      <span>Строк на странице</span>
      <select
        value={value}
        onChange={(e) => setSize(Number(e.target.value))}
        title="Действует во всех таблицах с инструментами"
        className="h-8 rounded-md border border-border bg-background px-2 text-sm text-foreground outline-none focus:border-primary"
      >
        {opts.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
        <option value={0}>Все строки</option>
      </select>
    </label>
  )
}
