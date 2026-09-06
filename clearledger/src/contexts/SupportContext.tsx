/**
 * SupportContext — управление вспомогательной областью «Взаимодействие».
 *
 * Двухрежимная подача одних и тех же разделов (Чат / Задачи / Поддержка / Инфо):
 *  • mode='modal' — вызов из ВЕРХНЕГО хедера: окно поверх всего.
 *  • mode='dock'  — вызов ТАПОМ в правой области / контекстно из функции:
 *                   живёт вкладкой в правом доке, без модалки.
 * Переключатель режима (setInteractionMode) позволяет «закрепить справа» ↔
 * «открыть окном». Счётчик непрочитанных чата — живой (React Query).
 */
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getToken, isApiEnabled } from '@/services/apiClient'
import { getRooms } from '@/services/chatService'
import { listTasks } from '@/services/tasksService'
import { useCompany } from '@/contexts/CompanyContext'
import { useTasksApp } from '@/hooks/useTasksApp'
import { openSectionOf, searchWithoutOpen } from '@/lib/openSection'

// «Аудитор» здесь же, а не отдельным механизмом: он сквозной ровно как чат — его
// зовут из любого экрана, и он должен знать, откуда позвали (`openInteraction`
// передаёт контекст, панель добирает маршрут и продукт сама).
export type InteractionSection =
  | 'chat' | 'tasks' | 'calendar' | 'notes' | 'tickets' | 'help' | 'auditor'
export type InteractionMode = 'modal' | 'dock'

interface InteractionState {
  section: InteractionSection | null
  mode: InteractionMode
  /** Контекст вызова (для будущих контекстных чатов: id функции/экрана). */
  context?: string | null
}

interface SupportContextValue {
  interactionSection: InteractionSection | null
  interactionMode: InteractionMode
  interactionContext: string | null
  /** Хедер: открыть/закрыть в модалке (toggle). */
  toggleInteraction: (section: InteractionSection) => void
  /** Правая область / контекст: открыть в доке (можно передать контекст). */
  openInteraction: (section: InteractionSection, context?: string | null) => void
  /** Переключить подачу текущего раздела (окно ↔ док). */
  setInteractionMode: (mode: InteractionMode) => void
  closeInteraction: () => void
  unreadCounts: { chat: number; tasks: number; tickets: number }
}

const SupportContext = createContext<SupportContextValue | undefined>(undefined)

export function SupportProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<InteractionState>({ section: null, mode: 'modal', context: null })

  const toggleInteraction = useCallback((section: InteractionSection) => {
    setState((prev) =>
      prev.section === section && prev.mode === 'modal'
        ? { section: null, mode: 'modal', context: null }
        : { section, mode: 'modal', context: null })
  }, [])
  const openInteraction = useCallback((section: InteractionSection, context: string | null = null) => {
    setState({ section, mode: 'dock', context })
  }, [])
  const setInteractionMode = useCallback((mode: InteractionMode) => {
    setState((prev) => (prev.section ? { ...prev, mode } : prev))
  }, [])
  const closeInteraction = useCallback(() => setState((prev) => ({ ...prev, section: null })), [])

  // Дверь снаружи: `…/?open=chat` открывает раздел ОКНОМ. Так в пространство
  // ведёт шапка станционного агента: у станции своей переписки нет, а вести её
  // на `/messages` значит открывать оператору приложение «Чаты» — управление
  // каналами и составом, работа администратора. Параметр одноразовый: гасим его
  // в адресе, иначе обновление страницы открывает окно снова.
  useEffect(() => {
    const section = openSectionOf(window.location.search)
    if (!section) return
    setState({ section, mode: 'modal', context: null })
    window.history.replaceState({}, '',
      window.location.pathname + searchWithoutOpen(window.location.search) + window.location.hash)
  }, [])

  // Cmd/Ctrl+K — открыть/закрыть «Инфо» окном (как в TradeFrame).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'KeyK' || !(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return
      const t = e.target as HTMLElement | null
      const tag = t?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t?.isContentEditable) return
      e.preventDefault()
      setState((prev) => (prev.section === 'help' ? { ...prev, section: null } : { section: 'help', mode: 'modal', context: null }))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const { companyId } = useCompany()

  // Живой счётчик непрочитанных чата. Ключ ОБЯЗАН совпадать с тем, которым панель
  // берёт полный список (`['chat-rooms', companyId, false, 'all']`): пока ключи
  // расходились, шапка и список чатов держали разные ответы сервера — в шапке
  // горела единица, а в списке ни одного непрочитанного (замечание МАГа 13.08.2026).
  const { data: rooms } = useQuery({
    queryKey: ['chat-rooms', companyId, false, 'all'],
    queryFn: () => getRooms(false),
    enabled: isApiEnabled() && !!getToken(),
    refetchInterval: 60000,
  })
  // «Без звука» не красит общий счётчик: замьюченный чат человек откроет сам.
  const chatUnread = (rooms || []).reduce((a, r) => a + (
    r.mutedUntil && Date.parse(r.mutedUntil) > Date.now() ? 0 : (r.unreadCount || 0)), 0)

  // Задачи: на кнопке — только ПРОСРОЧЕННЫЕ. «Сколько всего на мне» в шапке ничего
  // не решает и горит у всех постоянно; красная цифра должна значить «уже опоздали».
  // Ключ и запрос те же, что у быстрой панели, — один кеш на кнопку и на её окно.
  const tasksOn = useTasksApp()
  const { data: myTasks } = useQuery({
    queryKey: ['tasks', companyId, 'mine', '', '', ''],
    queryFn: () => listTasks(companyId, 'mine'),
    enabled: isApiEnabled() && !!getToken() && !!companyId && tasksOn,
    refetchInterval: 300000,
  })
  const tasksOverdue = (myTasks?.tasks || []).filter((t) => t.status === 'open' && t.overdue).length

  const unreadCounts = { chat: chatUnread, tasks: tasksOverdue, tickets: 0 }

  return (
    <SupportContext.Provider
      value={{
        interactionSection: state.section,
        interactionMode: state.mode,
        interactionContext: state.context ?? null,
        toggleInteraction, openInteraction, setInteractionMode, closeInteraction, unreadCounts,
      }}
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
