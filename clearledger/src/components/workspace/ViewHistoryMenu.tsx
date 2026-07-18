/**
 * История видов рабочей области — единый снимок (фильтр раздела + активный пункт
 * + его параметры). «Сохранить вид» фиксирует текущее, клик по записи — возвращает.
 */

import { useState } from 'react'
import { Bookmark, Plus, X, Star } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Input } from '@/components/ui/input'
import { useViewHistory } from '@/hooks/useViewHistory'
import { useFilters } from '@/contexts/FilterContext'
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
  const { history, saveCurrentView, applyView, deleteView, setDefaultView } = useViewHistory()
  // Единая точка «Виды» (§6.4): показываем и полные виды, и наборы фильтра (пресеты)
  // в одном меню — раньше они жили порознь (пресеты — в модалке фильтра).
  const { presets, applyState, deletePreset } = useFilters()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')

  function handleSave() {
    saveCurrentView(name.trim() || undefined)
    setName('')
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-9 shrink-0 rounded-lg px-2.5" aria-label="Сохранённые виды">
          <Bookmark data-icon="inline-start" />
          <span className="hidden lg:inline">Виды</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[340px] p-2">
        <div className="mb-2 px-1">
          <span className="text-xs font-medium text-muted-foreground">Сохранённые виды</span>
          <div className="mt-1.5 flex items-center gap-1.5">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSave() }}
              placeholder="Имя вида (напр. «Дебиторка, июнь»)"
              className="h-7 text-xs"
            />
            <Button variant="outline" size="sm" className="h-7 shrink-0 gap-1 px-2 text-xs" onClick={handleSave}>
              <Plus data-icon="inline-start" />Сохранить
            </Button>
          </div>
        </div>
        {history.length === 0 ? (
          <div className="px-2 py-6 text-center text-xs text-muted-foreground">
            Пока нет сохранённых видов. «Сохранить вид» запомнит фильтр раздела и настройки текущего пункта.
          </div>
        ) : (
          <div className="max-h-[320px] overflow-y-auto space-y-0.5">
            {[...history].sort((a, b) => (b.isDefault ? 1 : 0) - (a.isDefault ? 1 : 0)).map((snap) => (
              <div key={snap.id} className="group flex items-center gap-1 rounded hover:bg-accent/50">
                <button
                  className="flex-1 text-left px-2 py-1.5 min-w-0"
                  onClick={() => { applyView(snap); setOpen(false) }}
                >
                  <div className="flex items-center gap-1.5 text-xs font-medium">
                    <span className="truncate">{snap.name || snapLabel(snap)}</span>
                    {snap.isDefault && (
                      <span className="shrink-0 rounded bg-primary/10 px-1 text-[9px] text-primary">по умолчанию</span>
                    )}
                  </div>
                  <div className="text-[10px] text-muted-foreground truncate">
                    {snap.name ? snapLabel(snap) : fmtTime(snap.at)}
                  </div>
                </button>
                <Button
                  variant="ghost" size="icon"
                  className={`h-6 w-6 shrink-0 ${snap.isDefault ? 'text-primary' : 'text-muted-foreground opacity-0 group-hover:opacity-100'}`}
                  onClick={() => setDefaultView(snap.id)}
                  title={snap.isDefault ? 'Убрать «по умолчанию»' : 'Сделать видом по умолчанию'}
                >
                  <Star className={snap.isDefault ? 'fill-current' : ''} />
                </Button>
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

        {presets.length > 0 && (
          <div className="mt-2 border-t border-border/40 pt-2">
            <div className="mb-1 px-1 text-[11px] font-medium text-muted-foreground">Наборы фильтра</div>
            <div className="max-h-[160px] overflow-y-auto space-y-0.5">
              {presets.map((p) => (
                <div key={p.id} className="group flex items-center gap-1 rounded hover:bg-accent/50">
                  <button
                    className="flex-1 text-left px-2 py-1.5 min-w-0"
                    onClick={() => { applyState(p.state); setOpen(false) }}
                  >
                    <div className="text-xs truncate font-medium">{p.name}</div>
                    <div className="text-[10px] text-muted-foreground truncate">только фильтр раздела</div>
                  </button>
                  <Button
                    variant="ghost" size="icon"
                    className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground"
                    onClick={() => deletePreset(p.id)}
                    title="Удалить набор"
                  >
                    <X />
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}
