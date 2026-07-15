/**
 * RightDock — правая вспомогательная область «Взаимодействие».
 *
 * Всегда виден тонкий РЕЙЛ на правом краю (иконки Чат / Заявки / Инфо) — это
 * «тап в правой области»: клик разворачивает ДОК с вкладками (mode='dock', без
 * модалки). Хедер сверху открывает то же модалкой (mode='modal') — обе подачи
 * сосуществуют. Десктоп: пристыкованная панель с resize-ручкой (двигает контент).
 * Мобайл: рейла нет (вход из хедера/низа), док при открытии — полноэкранный оверлей.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MessageCircle, LifeBuoy, HelpCircle, X, Maximize2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useMaxWidth } from '@/hooks/use-mobile'
import { useSupportContext, type InteractionSection } from '@/contexts/SupportContext'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { TicketsPanel, InfoPanel } from './InteractionPanels'

const TABS: { key: InteractionSection; label: string; icon: typeof MessageCircle }[] = [
  { key: 'chat', label: 'Чат', icon: MessageCircle },
  { key: 'tickets', label: 'Заявки', icon: LifeBuoy },
  { key: 'help', label: 'Инфо', icon: HelpCircle },
]

const DOCK_WIDTH_KEY = 'ledger-dock-width'
const MIN_W = 340
const MAX_W = 760

export function RightDock() {
  const {
    interactionSection: section, interactionMode: mode,
    openInteraction, setInteractionMode, closeInteraction, unreadCounts,
  } = useSupportContext()
  const isMobile = useMaxWidth(1024)
  const [width, setWidth] = useState<number>(() => {
    const saved = Number(localStorage.getItem(DOCK_WIDTH_KEY))
    return saved >= MIN_W && saved <= MAX_W ? saved : 420
  })
  const draggingRef = useRef(false)

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    draggingRef.current = true
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
  }, [])
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return
      setWidth(Math.min(MAX_W, Math.max(MIN_W, window.innerWidth - e.clientX)))
    }
    const onUp = () => {
      if (!draggingRef.current) return
      draggingRef.current = false
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      localStorage.setItem(DOCK_WIDTH_KEY, String(width))
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
  }, [width])

  const badgeOf = (key: InteractionSection) =>
    key === 'chat' ? unreadCounts.chat : key === 'tickets' ? unreadCounts.tickets : 0

  const dockOpen = !!section && mode === 'dock'

  // ── Мобайл: рейла нет; при открытии дока — полноэкранный оверлей ──
  if (isMobile) {
    if (!dockOpen) return null
    return createPortal(
      <div className="fixed inset-0 z-50 flex flex-col bg-card mobile-safe-top mobile-safe-bottom">
        <DockHead tabs={TABS} section={section} badgeOf={badgeOf} isMobile
          onTab={openInteraction} onPop={() => setInteractionMode('modal')} onClose={closeInteraction} />
        <DockBody section={section} />
      </div>,
      document.body,
    )
  }

  // ── Десктоп: свёрнутый рейл (док закрыт) ──
  if (!dockOpen) {
    return (
      <div className="flex h-full w-12 shrink-0 flex-col items-center gap-1 border-l border-border/50 bg-card py-2">
        {TABS.map((t) => {
          const active = section === t.key   // подсвечиваем, если открыт модалкой
          const badge = badgeOf(t.key)
          return (
            <button key={t.key} onClick={() => openInteraction(t.key)} title={`${t.label} — открыть справа`}
              className={cn('relative flex w-11 flex-col items-center gap-0.5 rounded-lg px-1 py-2 text-[10px] transition-colors',
                active ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
              <t.icon className="size-4" />
              <span>{t.label}</span>
              {badge > 0 && (
                <span className="absolute right-1 top-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-600 px-1 text-[9px] font-bold leading-none text-white">{badge}</span>
              )}
            </button>
          )
        })}
      </div>
    )
  }

  // ── Десктоп: развёрнутый док с resize-ручкой ──
  return (
    <div className="relative flex h-full shrink-0 flex-col border-l border-border/50 bg-card" style={{ width }}>
      <div onMouseDown={onDragStart}
        className="absolute left-0 top-0 z-10 h-full w-1 -translate-x-1/2 cursor-col-resize bg-transparent transition-colors hover:bg-primary/40" />
      <DockHead tabs={TABS} section={section} badgeOf={badgeOf}
        onTab={openInteraction} onPop={() => setInteractionMode('modal')} onClose={closeInteraction} />
      <DockBody section={section} />
    </div>
  )
}

function DockHead({ tabs, section, badgeOf, isMobile, onTab, onPop, onClose }: {
  tabs: typeof TABS
  section: InteractionSection
  badgeOf: (k: InteractionSection) => number
  isMobile?: boolean
  onTab: (k: InteractionSection) => void
  onPop: () => void
  onClose: () => void
}) {
  return (
    <div className="flex shrink-0 items-center gap-1 border-b border-border/50 bg-card px-2 py-1.5">
      {tabs.map((t) => {
        const active = section === t.key
        const badge = badgeOf(t.key)
        return (
          <button key={t.key} onClick={() => onTab(t.key)}
            className={cn('relative inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors',
              active ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
            <t.icon className="size-4" />
            <span>{t.label}</span>
            {badge > 0 && (
              <span className="ml-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">{badge}</span>
            )}
          </button>
        )
      })}
      <div className="flex-1" />
      {!isMobile && (
        <button onClick={onPop} title="Открыть окном"
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
          <Maximize2 className="size-4" />
        </button>
      )}
      <button onClick={onClose} title="Закрыть"
        className="inline-flex size-7 max-md:size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
        <X className="size-4" />
      </button>
    </div>
  )
}

function DockBody({ section }: { section: InteractionSection }) {
  return (
    <div className="min-h-0 flex-1 overflow-hidden">
      {section === 'chat' && <ChatPanel compact />}
      {section === 'tickets' && <TicketsPanel />}
      {section === 'help' && <div className="h-full overflow-y-auto"><InfoPanel /></div>}
    </div>
  )
}
