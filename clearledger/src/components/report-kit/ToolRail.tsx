import {
  ArrowLeftRight, Calculator, CircleHelp, ClipboardList, Columns3, MessageSquareShare, SquareFunction, TextSearch, type LucideIcon,
} from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { closePanel, getRail, togglePanel, useRail, type Panel } from './rail'

type Item = { key: Panel; short: string; label: string; icon: LucideIcon; table?: boolean }

const TOOLS: Item[] = [
  { key: 'calc', short: 'Счёт', label: 'Калькулятор и сумма по выделению', icon: Calculator, table: true },
  { key: 'formula', short: 'Формулы', label: 'Свои столбцы: формулы из других столбцов', icon: SquareFunction, table: true },
  { key: 'search', short: 'Поиск', label: 'Поиск по таблице', icon: TextSearch, table: true },
  { key: 'columns', short: 'Столбцы', label: 'Столбцы: показать, скрыть, порядок', icon: Columns3, table: true },
  { key: 'compare', short: 'Сравнить', label: 'Сравнить с прошлым днём или неделей', icon: ArrowLeftRight },
  { key: 'pins', short: 'Цифры', label: 'Отложенные цифры', icon: ClipboardList },
]

function ToolButton({ icon: Icon, short, label, on, off, onClick, strip }: {
  icon: LucideIcon; short: string; label: string; on?: boolean; off?: string; onClick: () => void; strip?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!!off}
      aria-pressed={on}
      aria-label={label}
      title={off ?? label}
      className={cn(
        'relative flex shrink-0 flex-col items-center justify-center gap-1 rounded-lg px-1 py-1.5 text-center text-xs leading-tight transition-colors disabled:cursor-not-allowed disabled:opacity-35',
        strip ? 'min-h-[52px] min-w-14' : 'min-h-[52px] w-16',
        on ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground disabled:hover:bg-transparent disabled:hover:text-muted-foreground',
      )}
    >
      <Icon className="pointer-events-none size-5" aria-hidden />
      <span className="pointer-events-none" aria-hidden>
        {short}
      </span>
    </button>
  )
}

export function ToolButtons({ strip, onDiscuss }: { strip?: boolean; onDiscuss?: (text: string) => void }) {
  const rail = useRail()
  if (!rail.available) return null
  const open = (p: Panel) => {
    togglePanel(p)
    if (strip) requestAnimationFrame(() => document.getElementById('report-kit-panel')?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
  }
  const why = !rail.tools ? 'Инструменты включатся, когда таблица соберётся' : undefined
  const rule = strip ? <span className="mx-1 w-px self-stretch bg-border" aria-hidden /> : <span className="my-1 h-px w-8 bg-border" aria-hidden />
  return (
    <>
      <ToolButton
        icon={CircleHelp}
        short="Помощь"
        label={`Помощь по экрану: ${rail.title}`}
        on={rail.panel === 'help'}
        onClick={() => open('help')}
        strip={strip}
      />
      {rule}
      {TOOLS.map((x) => (
        <ToolButton
          key={x.key}
          icon={x.icon}
          short={x.short}
          label={x.label}
          on={rail.panel === x.key}
          off={why ?? (rail.pivot && x.table ? 'Работает в виде «Список»' : undefined)}
          onClick={() => open(x.key)}
          strip={strip}
        />
      ))}
      {onDiscuss && (
        <ToolButton
          icon={MessageSquareShare}
          short="Обсудить"
          label="Обсудить в чате: описание экрана с отбором копируется для вставки"
          off={why}
          onClick={() => {
            closePanel()
            onDiscuss(getRail().share)
          }}
          strip={strip}
        />
      )}
    </>
  )
}

export function ToolStrip({ onDiscuss }: { onDiscuss?: (text: string) => void }) {
  return (
    <div className="-mx-1 flex items-stretch gap-1 overflow-x-auto px-1 pb-1 lg:hidden" role="toolbar" aria-label="Инструменты таблицы">
      <ToolButtons strip onDiscuss={onDiscuss} />
    </div>
  )
}

export function ToolPanel({ children }: { children: ReactNode }) {
  const { panel } = useRail()
  useEffect(() => {
    if (!panel) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && closePanel()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [panel])
  if (!panel) return null
  return (
    <div
      id="report-kit-panel"
      className={cn(
        'scroll-mt-4 rounded-xl border border-di-outline-variant/70 bg-di-surface-mid',
        'lg:fixed lg:right-[84px] lg:top-[calc(var(--header-height)+12px)] lg:z-40 lg:max-h-[calc(100dvh-var(--header-height)-24px)] lg:w-[360px] lg:overflow-y-auto lg:shadow-xl',
      )}
    >
      {children}
    </div>
  )
}
