/**
 * Быстрый выбор приложения прямо в левом рельсе (просьба МАГа 05.09.2026).
 *
 * Пункт «Приложения» открывает панель поверх рабочей области — это про «посмотреть,
 * что вообще есть в пространстве». Но когда человек знает, куда идёт, панель с
 * плашками между ним и целью лишняя: стрелка справа от пункта разворачивает список
 * прямо здесь, и переход происходит одним нажатием, не покидая экрана.
 *
 * Стрелка отделена от подписи чертой и своим полем нажатия (замечание МАГа
 * 06.09.2026): это два разных действия в одной строке, и человек должен видеть
 * границу, а не догадываться, что нажатие у правого края ведёт не туда, куда
 * нажатие на слово.
 *
 * Состав, порядок и расклад «свёрнуто/раскрыто» — те же, что в каталоге
 * пространства (`hooks/useSpaceApps`, `hooks/useSectionOpen`), и открывается
 * приложение тем же способом (`useOpenApp`). Второго правила входа тут нет.
 */
import { useState } from 'react'
import { ChevronDown, ChevronRight, Loader2, Star } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SidebarMenuAction } from '@/components/ui/sidebar'
import { useSpaceApps } from '@/hooks/useSpaceApps'
import { useOpenApp } from '@/hooks/useOpenApp'
import { useTouchInput } from '@/hooks/use-mobile'
import { useSectionOpen } from '@/hooks/useSectionOpen'
import { useFavoriteApps } from '@/hooks/useFavoriteApps'
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

/**
 * Строка меню: подпись, счётчик и — под пальцем — сворачивание.
 *
 * На десктопе строки раскрыты всегда (решение МАГа 06.09.2026): места хватает, и
 * прятать там приложения незачем. Сворачивание нужно телефону, где иначе список
 * занимает несколько экранов.
 */
function QuickSection({ title, count, storageKey, collapsible, children }: {
  title: string; count: number; storageKey: string
  collapsible: boolean; children: React.ReactNode
}) {
  const [open, toggle] = useSectionOpen(storageKey, !collapsible)
  const shown = collapsible ? open : true
  return (
    <div className="py-0.5">
      {collapsible ? (
        <button type="button" onClick={toggle} aria-expanded={open}
          className="flex min-h-9 w-full items-center gap-1.5 px-2 text-left text-[10px] font-semibold
                     uppercase tracking-widest text-muted-foreground/60 transition-colors
                     hover:text-foreground">
          <ChevronDown className={`size-3 shrink-0 transition-transform ${open ? '' : '-rotate-90'}`} />
          {title}
          {count > 0 && (
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium
                             tabular-nums text-muted-foreground/80">
              {count}
            </span>
          )}
        </button>
      ) : (
        <div className="px-2 pb-1 pt-1.5 text-[10px] font-semibold uppercase
                        tracking-widest text-muted-foreground/60">
          {title}
        </div>
      )}
      {shown && children}
    </div>
  )
}

export function AppsQuickMenu({ onNavigate }: {
  /** Мобильная шторка закрывается вслед за выбором — как у обычного пункта меню. */
  onNavigate?: () => void
}) {
  const [open, setOpen] = useState(false)
  const { sections, apps, isLoading } = useSpaceApps()
  const { openApp, busy } = useOpenApp()
  const { company } = useCompany()
  const touch = useTouchInput()
  const { favorites, ready: favReady } = useFavoriteApps()
  const visible = sections.filter((s) => s.apps.length > 0)
  // Избранное — тем же составом и порядком, что в каталоге пространства.
  const picked = favorites.flatMap((code) => apps.filter((a) => a.code === code))

  async function choose(a: SsoApp) {
    setOpen(false)
    onNavigate?.()
    await openApp(a)
  }

  function appRow(a: SsoApp, starred = false) {
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
        className={`flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left text-sm
                    transition-colors
                    ${optional
                      ? 'cursor-default text-muted-foreground/70'
                      : 'hover:bg-accent hover:text-foreground'}`}
      >
        {busy === a.code
          ? <Loader2 className="size-4 shrink-0 animate-spin" />
          : <Icon className="size-4 shrink-0 text-primary" />}
        <span className="min-w-0 flex-1 truncate">{a.name}</span>
        {starred && <Star className="size-3.5 shrink-0 fill-current text-amber-400" />}
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
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {/* Своё поле нажатия с чертой слева: стрелка живёт в той же строке, что
            подпись «Приложения», но делает другое — и это должно быть видно. */}
        <SidebarMenuAction
          title="Быстрый переход в приложение"
          aria-label="Быстрый переход в приложение"
          className="bottom-1 right-0.5 top-1 aspect-auto h-auto w-9 rounded-md border-l
                     border-border/60 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <ChevronRight className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`} />
        </SidebarMenuAction>
      </PopoverTrigger>
      {/* Под пальцем список выпадает вниз и по ширине экрана: сбоку от рельса он
          не помещался и уезжал за левый край, обрезая названия (замечание МАГа
          06.09.2026). Курсору по-прежнему удобнее сбоку. */}
      <PopoverContent side={touch ? 'bottom' : 'right'} align={touch ? 'center' : 'start'}
        sideOffset={8} collisionPadding={12}
        className="max-h-[70vh] w-[min(20rem,calc(100vw-1.5rem))] overflow-y-auto p-1.5">
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
        {favReady && picked.length > 0 && (
          <QuickSection title="Избранное" count={picked.length}
            storageKey="favorites" collapsible={false}>
            {picked.map((a) => appRow(a, true))}
          </QuickSection>
        )}
        {visible.map((s) => (
          <QuickSection key={s.key} title={s.title} count={s.apps.length}
            storageKey={s.key} collapsible={touch}>
            {s.apps.map((a) => appRow(a, favorites.includes(a.code)))}
          </QuickSection>
        ))}
      </PopoverContent>
    </Popover>
  )
}
