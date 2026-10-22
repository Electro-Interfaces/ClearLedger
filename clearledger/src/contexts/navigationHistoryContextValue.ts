import { createContext, useContext } from 'react'
import type { NavigationHistory, NavigationViewStore } from '@/lib/navigationHistory'

export const NavigationHistoryContext = createContext<{
  history: NavigationHistory
  views: NavigationViewStore
} | null>(null)

export function useNavigationHistory() {
  const context = useContext(NavigationHistoryContext)
  if (!context) throw new Error('NavigationHistoryProvider is required')
  return context
}
