/**
 * Каркас страницы пространства: вертикальное меню слева, содержимое справа.
 *
 * До этого «Объекты», «Загрузка», «Документы» и «Контрагенты» открывались одним
 * экраном, а внутреннее деление уезжало в табы под шапкой. На одном рабочем
 * столе получалось три языка навигации: рельса приложений, меню разделов и
 * табы — причём табы обрывались по ширине и терялись (замечание МАГа
 * 20.09.2026).
 *
 * Здесь та же схема, что у разделов продукта (`WorkspaceModeSidebar` в режиме
 * `lockedModes`): узкая колонка `bg-card` с группами и пунктами, активный пункт
 * подсвечен, панель сворачивается в иконку. Копия разметки, а не переиспользование
 * компонента: тот завязан на разделы рабочей области (`CoreMode`, доступы,
 * гармошка верхнего уровня), а страницам пространства нужен плоский список
 * пунктов одной страницы. Общий у них внешний вид — и он задан теми же классами.
 *
 * Активный пункт живёт в адресе (`?sub=`), как у продуктов: ссылку на конкретный
 * раздел можно дать, и она откроется там же.
 */
import { useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useSpacePageSub } from '@/hooks/useSpacePageSub'
import { spacePageMenu, type SpacePageItem } from '@/config/spacePageMenus'

const COLLAPSE_KEY = 'cl-space-page-menu-collapsed'

function groupItems(items: SpacePageItem[]): { name?: string; items: SpacePageItem[] }[] {
  const groups: { name?: string; items: SpacePageItem[] }[] = []
  for (const it of items) {
    const last = groups[groups.length - 1]
    if (last && last.name === it.group) last.items.push(it)
    else groups.push({ name: it.group, items: [it] })
  }
  return groups
}

export function SpacePageLayout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const [active, setActive, items] = useSpacePageSub()
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
  })
  const toggle = () => setCollapsed((c) => {
    const nv = !c
    try { localStorage.setItem(COLLAPSE_KEY, nv ? '1' : '0') } catch { /* ignore */ }
    return nv
  })
  const [свёрнуты, setСвёрнуты] = useState<Record<string, boolean>>({})

  const меню = spacePageMenu(pathname)
  // Страница без своего меню (или с единственным пунктом) обходится без колонки:
  // панель из одной строки занимает место и ничего не решает.
  if (!меню || items.length < 2) return <>{children}</>

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {collapsed ? (
        <nav data-zone="Разделы страницы" data-zone-side
          className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-border bg-card px-1 py-3">
          <button onClick={toggle} title={`${меню.title}: развернуть`}
            className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
            <PanelLeftOpen className="h-4 w-4" />
          </button>
          {items.map((it) => {
            const Icon = it.icon
            return (
              <button key={it.key} onClick={() => setActive(it.key)} title={it.label}
                className={`rounded-md p-2 transition-colors ${
                  it.key === active
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'}`}>
                {Icon ? <Icon className="h-4 w-4" /> : <span className="text-xs">{it.label[0]}</span>}
              </button>
            )
          })}
        </nav>
      ) : (
        <nav data-zone="Разделы страницы" data-zone-side
          className="flex w-56 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-border bg-card px-2.5 py-3">
          <div className="flex items-center justify-end gap-2 px-1 pb-1">
            <button onClick={toggle} title="Свернуть меню"
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </div>
          {groupItems(items).map((grp) => {
            const ключ = `${меню.path}:${grp.name ?? ''}`
            const скрыта = !!grp.name && !!свёрнуты[ключ]
            return (
              <div key={ключ}>
                {grp.name && (
                  <button
                    onClick={() => setСвёрнуты((p) => ({ ...p, [ключ]: !скрыта }))}
                    className="mt-1 flex w-full items-center gap-1.5 px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/75 transition-colors hover:text-foreground">
                    {скрыта
                      ? <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-60" />
                      : <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />}
                    <span className="flex-1 text-left">{grp.name}</span>
                  </button>
                )}
                {!скрыта && grp.items.map((it) => (
                  <button key={it.key} onClick={() => setActive(it.key)}
                    className={`w-full whitespace-nowrap rounded-md px-3 py-1.5 text-left text-[13px] transition-colors ${
                      it.key === active
                        ? 'bg-primary/10 font-medium text-primary'
                        : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground'}`}>
                    {it.label}
                  </button>
                ))}
              </div>
            )
          })}
        </nav>
      )}

      {/* Прокрутка живёт здесь, а не на внешней обёртке: иначе колонка меню
          уезжает вместе с содержимым, и получается два скролла в одном экране. */}
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">{children}</div>
    </div>
  )
}
