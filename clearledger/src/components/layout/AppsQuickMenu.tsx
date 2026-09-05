/**
 * Быстрый выбор приложения прямо в левом рельсе (просьба МАГа 05.09.2026).
 *
 * Пункт «Приложения» открывает панель поверх рабочей области — это про «посмотреть,
 * что вообще есть в пространстве». Но когда человек знает, куда идёт, панель с
 * плашками между ним и целью лишняя: стрелка справа от пункта разворачивает список
 * прямо здесь, и переход происходит одним нажатием, не покидая экрана.
 *
 * Состав и порядок — из той же раскладки, что и стол (`hooks/useSpaceApps`), и
 * открывается приложение тем же способом (`useOpenApp`): внутренний продукт —
 * переходом, чужой домен — новой вкладкой. Второго правила входа тут нет.
 */
import { useState } from 'react'
import { ChevronRight, Loader2 } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SidebarMenuAction } from '@/components/ui/sidebar'
import { useSpaceApps } from '@/hooks/useSpaceApps'
import { useOpenApp } from '@/hooks/useOpenApp'
import { appIcon, isOptionalApp } from '@/config/spaceLauncher'
import { productReadiness, READINESS_LABEL, type Readiness } from '@/config/spaceProducts'
import { useCompany } from '@/contexts/CompanyContext'
import type { SsoApp } from '@/services/ssoService'

/** Точка готовности — та же, что на столе: зелёная · жёлтая · красная. */
const DOT_CLASS: Record<Readiness, string> = {
  ready: 'bg-emerald-500',
  partial: 'bg-amber-400',
  draft: 'bg-red-500',
}

export function AppsQuickMenu({ onNavigate }: {
  /** Мобильная шторка закрывается вслед за выбором — как у обычного пункта меню. */
  onNavigate?: () => void
}) {
  const [open, setOpen] = useState(false)
  const { sections, isLoading } = useSpaceApps()
  const { openApp, busy } = useOpenApp()
  const { company } = useCompany()
  const visible = sections.filter((s) => s.apps.length > 0)

  async function choose(a: SsoApp) {
    setOpen(false)
    onNavigate?.()
    await openApp(a)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <SidebarMenuAction
          title="Выбрать приложение"
          aria-label="Выбрать приложение"
          className="text-muted-foreground hover:text-foreground"
        >
          <ChevronRight className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`} />
        </SidebarMenuAction>
      </PopoverTrigger>
      {/* Список раскрывается сбоку от рельса и живёт своей прокруткой: продуктов
          в пространстве полтора десятка, и все они должны быть достижимы без
          того, чтобы меню упёрлось в низ экрана. */}
      <PopoverContent side="right" align="start" sideOffset={8}
        className="max-h-[70vh] w-72 overflow-y-auto p-1.5">
        {isLoading && (
          <div className="flex items-center gap-2 px-2 py-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Загрузка каталога…
          </div>
        )}
        {!isLoading && visible.length === 0 && (
          <div className="px-2 py-2 text-sm text-muted-foreground">
            Приложения не подключены.
          </div>
        )}
        {visible.map((s) => (
          <div key={s.key} className="py-0.5">
            <div className="px-2 pb-1 pt-1.5 text-[10px] font-semibold uppercase
                            tracking-widest text-muted-foreground/60">
              {s.title}
            </div>
            {s.apps.map((a) => {
              const Icon = appIcon(a.icon)
              // Продукт без экранов в этом стеке открыть нечем — показываем, но не даём
              // нажать: иначе выбор молча ничего не делает.
              const optional = isOptionalApp(a)
              const readiness = optional ? undefined : productReadiness(a.code, company.profileId)
              return (
                <button
                  key={a.code}
                  type="button"
                  disabled={optional || busy === a.code}
                  onClick={() => { void choose(a) }}
                  title={[a.name, a.description, readiness && READINESS_LABEL[readiness]]
                    .filter(Boolean).join(' · ')}
                  className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm
                              transition-colors
                              ${optional
                                ? 'cursor-default text-muted-foreground/70'
                                : 'hover:bg-accent hover:text-foreground'}`}
                >
                  {busy === a.code
                    ? <Loader2 className="size-4 shrink-0 animate-spin" />
                    : <Icon className="size-4 shrink-0 text-primary" />}
                  <span className="min-w-0 flex-1 truncate">{a.name}</span>
                  {optional && (
                    <span className="shrink-0 rounded-full border border-dashed border-border
                                     px-1.5 py-0.5 text-[10px]">
                      отдельно
                    </span>
                  )}
                  {readiness && (
                    <span aria-hidden="true"
                      className={`size-2 shrink-0 rounded-full ${DOT_CLASS[readiness]}`} />
                  )}
                </button>
              )
            })}
          </div>
        ))}
      </PopoverContent>
    </Popover>
  )
}
