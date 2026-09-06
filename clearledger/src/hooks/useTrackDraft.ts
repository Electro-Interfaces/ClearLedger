import { useRef, useState } from 'react'

const memory = new Map<string, unknown>()

export function useTrackDraft<T>(key: string, initial: T, persistent = true) {
  const [error, setError] = useState(false)
  const [value, setValue] = useState<T>(() => {
    if (memory.has(key)) return memory.get(key) as T
    if (persistent) {
      try {
        const saved = sessionStorage.getItem(key)
        if (saved) { const parsed = JSON.parse(saved) as T; memory.set(key, parsed); return parsed }
      } catch { /* При недоступном хранилище буфер остаётся в памяти. */ }
    }
    return initial
  })
  const current = useRef(value)
  const save = (next: T | ((previous: T) => T)) => {
    const updated = typeof next === 'function' ? (next as (previous: T) => T)(current.current) : next
    current.current = updated
    memory.set(key, updated)
    if (persistent) {
      try { sessionStorage.setItem(key, JSON.stringify(updated)); setError(false) }
      catch { setError(true) }
    }
    setValue(updated)
  }
  const clear = (expected?: T) => {
    if (expected !== undefined && memory.get(key) !== expected) return
    memory.delete(key)
    try { sessionStorage.removeItem(key) } catch { /* Буфер памяти уже очищен. */ }
    current.current = initial
    setValue(initial)
    setError(false)
  }
  return { value, save, clear, error }
}
