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
import { ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen } from 'lucide-react'

const COLLAPSE_KEY = 'cl-mode-sidebar-collapsed'

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
      <nav className="flex flex-col items-center gap-1 py-2 px-1 border-r border-border/40 bg-muted/30 shrink-0 w-12 overflow-y-auto">
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
    <nav className="flex flex-col gap-0.5 py-2 px-1.5 border-r border-border/40 bg-muted/30 shrink-0 w-52 overflow-y-auto">
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

            {/* Под-разделы раскрытого раздела — гармошка */}
            {expanded && hasItems && (
              <div className="mt-0.5 mb-1 ml-4 pl-2 border-l border-border/40 flex flex-col gap-0.5">
                {section.items.map((item, i) => {
                  const subActive = item.key === activeSub
                  const showGroup = !!item.group && item.group !== section.items[i - 1]?.group
                  return (
                    <div key={item.key}>
                      {showGroup && (
                        <div className="px-3 pt-2 pb-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground/50">
                          {item.group}
                        </div>
                      )}
                      <button
                        onClick={() => setSub(item.key)}
                        className={`w-full px-3 py-1.5 rounded-md text-[13px] text-left whitespace-nowrap transition-colors ${
                          subActive
                            ? 'bg-primary/10 text-primary font-medium'
                            : 'text-muted-foreground hover:text-foreground hover:bg-accent/40'
                        }`}
                      >
                        {item.label}
                      </button>
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
