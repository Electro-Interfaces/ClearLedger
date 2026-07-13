/**
 * История видов рабочей области — единый снимок (фильтр раздела + активный пункт
 * + его параметры). «Сохранить вид» фиксирует текущее, клик по записи — возвращает.
 */

import { useState } from 'react'
import { Bookmark, Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useViewHistory } from '@/hooks/useViewHistory'
import { workspaceTitle, isCoreMode } from '@/config/workspaceViews'
import type { ViewSnapshot } from '@/services/viewSnapshot'

function fmtShort(iso: string): string {
  const [, m, d] = iso.split('-')
  return d && m ? `${d}.${m}` : iso
}

function snapLabel(snap: ViewSnapshot): string {
  const mode = isCoreMode(snap.mode) ? snap.mode : 'management'
  const title = workspaceTitle(mode, snap.sub || undefined)
  return `${title} · ${fmtShort(snap.section.period.from)}–${fmtShort(snap.section.period.to)}`
}

function fmtTime(at: number): string {
  try {
    return new Date(at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

export function ViewHistoryMenu() {
  const { history, saveCurrentView, applyView, deleteView } = useViewHistory()
  const [open, setOpen] = useState(false)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-9 shrink-0 rounded-lg px-2.5" aria-label="Сохранённые виды">
          <Bookmark data-icon="inline-start" />
          <span className="hidden lg:inline">Виды</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[320px] p-2">
        <div className="flex items-center justify-between mb-2 px-1">
          <span className="text-xs font-medium text-muted-foreground">История видов</span>
          <Button variant="outline" size="sm" className="h-7 text-xs px-2 gap-1" onClick={saveCurrentView}>
            <Plus data-icon="inline-start" />Сохранить вид
          </Button>
        </div>
        {history.length === 0 ? (
          <div className="px-2 py-6 text-center text-xs text-muted-foreground">
            Пока нет сохранённых видов. «Сохранить вид» запомнит фильтр раздела и настройки текущего пункта.
          </div>
        ) : (
          <div className="max-h-[320px] overflow-y-auto space-y-0.5">
            {history.map((snap) => (
              <div key={snap.id} className="group flex items-center gap-1 rounded hover:bg-accent/50">
                <button
                  className="flex-1 text-left px-2 py-1.5 min-w-0"
                  onClick={() => { applyView(snap); setOpen(false) }}
                >
                  <div className="text-xs truncate">{snapLabel(snap)}</div>
                  <div className="text-[10px] text-muted-foreground">{fmtTime(snap.at)}</div>
                </button>
                <Button
                  variant="ghost" size="icon"
                  className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground"
                  onClick={() => deleteView(snap.id)}
                  title="Удалить"
                >
                  <X />
                </Button>
              </div>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}
