/**
 * Вертикальное меню разделов рабочей области — гармошка.
 *
 * Разделы верхнего уровня (виды учёта + «Выгрузка») по клику активируются, и под
 * активным разделом раскрываются его под-разделы (те, что раньше были отдельной
 * колонкой `CentralPanelLayout` внутри панели). Клик по под-разделу пишет `?sub=`.
 */

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useWorkspace, type CoreMode } from '@/contexts/WorkspaceContext'
import { useCompany } from '@/contexts/CompanyContext'
import { modeAllowed } from '@/config/accessModules'
import { useWorkspaceSections } from './workspaceSections'
import type { CentralMenuItem } from './CentralPanelLayout'
import { ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen } from 'lucide-react'

const COLLAPSE_KEY = 'cl-mode-sidebar-collapsed'
const GROUPS_KEY = 'cl-mode-sidebar-groups-v2'

/** Сгруппировать под-разделы по полю group, сохраняя порядок. */
function groupItems(items: CentralMenuItem[]): { name?: string; items: CentralMenuItem[] }[] {
  const groups: { name?: string; items: CentralMenuItem[] }[] = []
  for (const it of items) {
    const last = groups[groups.length - 1]
    if (last && last.name === it.group) last.items.push(it)
    else groups.push({ name: it.group, items: [it] })
  }
  return groups
}

export function WorkspaceModeSidebar() {
  const { companyModules } = useCompany()
  // RBAC: показываем только доступные режимы учёта (admin/суперадмин → все).
  const sections = useWorkspaceSections().filter((s) => modeAllowed(s.mode, companyModules))
  const { coreMode, setCoreMode } = useWorkspace()
  // Если активный режим недоступен по модулям — переключаемся на первый доступный.
  useEffect(() => {
    if (sections.length && !sections.some((s) => s.mode === coreMode)) {
      setCoreMode(sections[0].mode)
    }
  }, [sections, coreMode, setCoreMode])
  const [searchParams, setSearchParams] = useSearchParams()
  const urlSub = searchParams.get('sub')

  // Раскрытый раздел гармошки (по умолчанию — активный). Отделён от coreMode,
  // чтобы активный раздел можно было свернуть, не меняя показываемого контента.
  const [expandedMode, setExpandedMode] = useState<CoreMode | null>(coreMode)
  // Следовать за активным разделом при внешней смене (навигация/закладки).
  useEffect(() => { setExpandedMode(coreMode) }, [coreMode])

  // Свёрнутость всей панели в узкий рельс (иконки) — с запоминанием.
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
  })
  const toggleCollapsed = () => setCollapsed((c) => {
    const nv = !c
    try { localStorage.setItem(COLLAPSE_KEY, nv ? '1' : '0') } catch { /* ignore */ }
    return nv
  })

  // Явные переключения групп пользователем (ключ mode:group → свёрнута?). Персист
  // между сессиями. Дефолт (нет override) — группа СВЁРНУТА, кроме активной.
  const [groupOverrides, setGroupOverrides] = useState<Record<string, boolean>>(() => {
    try {
      const p = JSON.parse(localStorage.getItem(GROUPS_KEY) || '{}')
      return p && typeof p === 'object' && !Array.isArray(p) ? p as Record<string, boolean> : {}
    } catch { return {} }
  })
  const setGroupCollapsed = (k: string, collapsed: boolean) => setGroupOverrides((prev) => {
    const n = { ...prev, [k]: collapsed }
    try { localStorage.setItem(GROUPS_KEY, JSON.stringify(n)) } catch { /* ignore */ }
    return n
  })

  const setSub = (key: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('sub', key)
      return next
    }, { replace: true })
  }

  function handleSectionClick(mode: CoreMode) {
    if (mode === coreMode) {
      // активный раздел — сворачиваем/разворачиваем под-пункты
      setExpandedMode((cur) => (cur === mode ? null : mode))
    } else {
      // другой раздел — активируем (эффект раскроет его)
      setCoreMode(mode)
    }
  }

  // Свёрнутый рельс: только иконки разделов, клик — активировать раздел.
  if (collapsed) {
    return (
      <nav data-zone="Разделы" data-zone-side className="flex flex-col items-center gap-1 py-3 px-1 border-r border-border bg-card shrink-0 w-14 overflow-y-auto">
        <button
          onClick={toggleCollapsed}
          title="Развернуть меню"
          className="p-2 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
        >
          <PanelLeftOpen className="h-4 w-4" />
        </button>
        <div className="my-1 w-6 h-px bg-border/40" />
        {sections.map((section) => {
          const active = coreMode === section.mode
          const Icon = section.icon
          return (
            <div key={section.mode} className="flex flex-col items-center">
              {section.mode === 'export' && <div className="my-1 w-6 h-px bg-border/40" />}
              <button
                onClick={() => setCoreMode(section.mode)}
                title={section.label}
                className={`p-2 rounded-md transition-colors ${
                  active ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                }`}
              >
                <Icon className="h-4 w-4" />
              </button>
            </div>
          )
        })}
      </nav>
    )
  }

  return (
    <nav data-zone="Разделы учёта" data-zone-side className="flex flex-col gap-0.5 py-3 px-2.5 border-r border-border bg-card shrink-0 w-56 overflow-y-auto">
      <div className="flex justify-end px-1 pb-1">
        <button
          onClick={toggleCollapsed}
          title="Свернуть меню"
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>
      {sections.map((section) => {
        const active = coreMode === section.mode
        const expanded = expandedMode === section.mode
        const Icon = section.icon
        const hasItems = section.items.length > 0
        // Активный под-раздел: из URL если валиден, иначе первый.
        const activeSub = urlSub && section.items.some((i) => i.key === urlSub)
          ? urlSub
          : section.items[0]?.key

        return (
          <div key={section.mode}>
            {section.mode === 'export' && <div className="my-1.5 mx-2 h-px bg-border/40" />}

            {/* Раздел */}
            <button
              onClick={() => handleSectionClick(section.mode)}
              className={`flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm font-medium text-left whitespace-nowrap transition-colors ${
                active
                  ? 'bg-primary/15 text-primary'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="flex-1">{section.label}</span>
              {hasItems && (
                expanded
                  ? <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-70" />
                  : <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-50" />
              )}
            </button>

            {/* Под-разделы раскрытого раздела — гармошка со сворачиваемыми группами */}
            {expanded && hasItems && (
              <div className="mt-0.5 mb-1 ml-4 pl-2 border-l border-border/40 flex flex-col gap-0.5">
                {groupItems(section.items).map((grp) => {
                  const gKey = `${section.mode}:${grp.name ?? ''}`
                  const groupActive = grp.items.some((i) => i.key === activeSub)
                  const override = grp.name ? groupOverrides[gKey] : undefined
                  // Дефолт: свёрнута, если НЕ содержит активный под-раздел; override переопределяет.
                  const gCollapsed = !!grp.name && (override !== undefined ? override : !groupActive)
                  return (
                    <div key={gKey}>
                      {grp.name && (
                        <button
                          onClick={() => setGroupCollapsed(gKey, !gCollapsed)}
                          className="flex items-center gap-1.5 w-full px-2 py-1.5 mt-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/75 hover:text-foreground transition-colors"
                        >
                          {gCollapsed
                            ? <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-60" />
                            : <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />}
                          <span className="flex-1 text-left">{grp.name}</span>
                        </button>
                      )}
                      {!gCollapsed && grp.items.map((item) => {
                        const subActive = item.key === activeSub
                        return (
                          <button
                            key={item.key}
                            onClick={() => setSub(item.key)}
                            className={`w-full px-3 py-1.5 rounded-md text-[13px] text-left whitespace-nowrap transition-colors ${
                              subActive
                                ? 'bg-primary/10 text-primary font-medium'
                                : 'text-muted-foreground hover:text-foreground hover:bg-accent/40'
                            }`}
                          >
                            {item.label}
                          </button>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </nav>
  )
}
