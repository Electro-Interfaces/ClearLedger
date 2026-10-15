import { useSyncExternalStore, type ReactNode } from 'react'

export type Tool = 'calc' | 'formula' | 'search' | 'columns' | 'compare' | 'pins'
export type Panel = 'help' | Tool
export type RailState = {
  available: boolean
  title: string
  panel: Panel | null
  tools: boolean
  pivot: boolean
  help: ReactNode
  slot: HTMLElement | null
}

let state: RailState = { available: false, title: '', panel: null, tools: false, pivot: false, help: null, slot: null }
const subs = new Set<() => void>()

export function setRail(patch: Partial<RailState>) {
  const next = { ...state, ...patch }
  if ((Object.keys(next) as (keyof RailState)[]).every((k) => next[k] === state[k])) return
  state = next
  subs.forEach((f) => f())
}

export const getRail = () => state
export const togglePanel = (p: Panel) => setRail({ panel: state.panel === p ? null : p })
export const closePanel = () => setRail({ panel: null })

export function useRail() {
  return useSyncExternalStore(
    (f) => {
      subs.add(f)
      return () => subs.delete(f)
    },
    () => state,
  )
}
