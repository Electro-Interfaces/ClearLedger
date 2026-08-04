/**
 * Какой раздел рабочей области открыт прямо сейчас — для тех, кто стоит СНАРУЖИ
 * рабочей области.
 *
 * Левая рельса приложения живёт в общем макете, а `WorkspaceProvider` — внутри
 * рабочей области, и её состояние рельсе недоступно. Пока рельса угадывала
 * активный раздел по адресу, подсветка расходилась с тем, что человек видит на
 * экране: открыт «Каталог», а в меню не выбрано ничего.
 *
 * Провайдер поднят в макет, рабочая область публикует сюда свой раздел, рельса
 * его читает. Одно значение, один источник — расходиться больше нечему.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

interface ActiveModeValue {
  /** Открытый раздел рабочей области; null — рабочей области на экране нет. */
  activeMode: string | null
  publishMode: (mode: string | null) => void
}

const ActiveModeContext = createContext<ActiveModeValue>({
  activeMode: null,
  publishMode: () => {},
})

export function ActiveModeProvider({ children }: { children: ReactNode }) {
  const [activeMode, setActiveMode] = useState<string | null>(null)
  // Стабильная ссылка: публикация идёт из эффекта рабочей области, и новая
  // функция на каждый рендер гоняла бы этот эффект вхолостую.
  const publishMode = useCallback((mode: string | null) => {
    setActiveMode((cur) => (cur === mode ? cur : mode))
  }, [])
  const value = useMemo(() => ({ activeMode, publishMode }), [activeMode, publishMode])
  return <ActiveModeContext.Provider value={value}>{children}</ActiveModeContext.Provider>
}

export const useActiveMode = () => useContext(ActiveModeContext)
