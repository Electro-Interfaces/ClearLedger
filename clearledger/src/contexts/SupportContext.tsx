/**
 * SupportContext — лёгкий аналог модуля «Взаимодействие» из TradeFrame.
 *
 * Управляет открытием модалок Чат / Заявки / Инфо из шапки (toggle: повторное
 * нажатие или крестик закрывают). Без бэкенда поддержки (Matrix/TSupport) —
 * счётчики непрочитанных пока нулевые, структура оставлена для будущей привязки.
 */
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react'

export type InteractionSection = 'chat' | 'tickets' | 'help'

interface SupportContextValue {
  interactionSection: InteractionSection | null
  toggleInteraction: (section: InteractionSection) => void
  closeInteraction: () => void
  unreadCounts: { chat: number; tickets: number }
}

const SupportContext = createContext<SupportContextValue | undefined>(undefined)

export function SupportProvider({ children }: { children: ReactNode }) {
  const [interactionSection, setInteractionSection] = useState<InteractionSection | null>(null)

  const toggleInteraction = useCallback(
    (section: InteractionSection) =>
      setInteractionSection((prev) => (prev === section ? null : section)),
    [],
  )
  const closeInteraction = useCallback(() => setInteractionSection(null), [])

  // Cmd/Ctrl+K — открыть/закрыть «Инфо» с любого экрана (как в TradeFrame).
  // e.code='KeyK' не зависит от раскладки; в полях ввода не перехватываем.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'KeyK' || !(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return
      const t = e.target as HTMLElement | null
      const tag = t?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t?.isContentEditable) return
      e.preventDefault()
      setInteractionSection((prev) => (prev === 'help' ? null : 'help'))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Пока без живого бэкенда — счётчики нулевые (бейджи не рисуются).
  const unreadCounts = { chat: 0, tickets: 0 }

  return (
    <SupportContext.Provider
      value={{ interactionSection, toggleInteraction, closeInteraction, unreadCounts }}
    >
      {children}
    </SupportContext.Provider>
  )
}

export function useSupportContext() {
  const ctx = useContext(SupportContext)
  if (!ctx) throw new Error('useSupportContext must be used within SupportProvider')
  return ctx
}
