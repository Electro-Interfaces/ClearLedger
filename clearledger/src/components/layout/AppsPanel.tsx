/**
 * Панель «Приложения» — меню пространства ВНУТРИ рабочей области.
 *
 * Идеология переходов (решение МАГа 06.08.2026): кнопка в шапке — это пункт меню,
 * а не переход. Она показывает плашки поверх текущего экрана, человек остаётся
 * там, где работал. Уход на другой экран происходит ТОЛЬКО по нажатию плашки.
 *
 * До этого «Приложения» открывали выпадающий список строк, а «Стол» уводил на
 * отдельный экран: чтобы просто посмотреть, что есть в пространстве, приходилось
 * покинуть свою работу и возвращаться назад.
 *
 * Состав плашек — тот же, что на столе (`EcosystemHomePage` во встроенном виде):
 * один каталог, один порядок слоёв, никакого второго списка приложений.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { EcosystemHomePage } from '@/pages/EcosystemHomePage'

interface AppsPanelApi {
  open: boolean
  toggle: () => void
  close: () => void
}

const Ctx = createContext<AppsPanelApi>({ open: false, toggle: () => {}, close: () => {} })

/** Кнопке в шапке — управление панелью; панель рисует провайдер рабочей области. */
export function useAppsPanel(): AppsPanelApi {
  return useContext(Ctx)
}

export function AppsPanelProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), [])
  const toggle = useCallback(() => setOpen((v) => !v), [])
  const api = useMemo(() => ({ open, toggle, close }), [open, toggle, close])

  // Esc — выход из режима, как и везде в пространстве: открытая поверх работы
  // панель обязана закрываться тем же жестом, что и любое временное окно.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, close])

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>
}

/**
 * Поверхность панели — ставится ВНУТРИ рабочей области.
 *
 * Провайдер и поверхность разделены намеренно: кнопка живёт в шапке, а шапка вне
 * рабочей области. Пока провайдер оборачивал только контент, кнопка читала
 * контекст-заглушку и нажатие не делало ничего.
 */
export function AppsPanelSurface() {
  const { open, close } = useAppsPanel()
  if (!open) return null
  return (
    <div className="absolute inset-0 z-40 flex flex-col bg-background/95 backdrop-blur-sm">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-2 sm:px-6">
        <div className="min-w-0">
          <div className="text-sm font-semibold">Приложения пространства</div>
          {/* Пояснение — только там, где оно помещается: на телефоне строка
              обрывалась на «экран под панелью ос…» и объясняла ровно ничего. */}
          <div className="hidden truncate text-xs text-muted-foreground sm:block">
            Выберите, куда перейти — экран под панелью останется на месте
          </div>
        </div>
        <button type="button" onClick={close} aria-label="Закрыть приложения"
          className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <EcosystemHomePage embedded onNavigate={close} />
      </div>
    </div>
  )
}
