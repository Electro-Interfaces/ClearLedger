/**
 * Универсальный селектор станций для каналов и глобальных фильтров.
 *
 * Работает в сетях любого размера — у партнёров может быть 400+ объектов.
 * Inline-чекбоксы в карточке не подходят: список не помещается, выбор
 * руками неудобен. Решение:
 *  - снаружи (на карточке/в шапке) показывается компактная сводка;
 *  - изменение выбора — в диалоге с поиском, фильтрами и bulk-кнопками.
 *
 * Унифицированная модель «ключа» — `{systemId, code}`. Источник данных
 * — справочник ServiceLocation (через STS-привязки), плюс ручные станции
 * из текущего набора.
 */

import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
  DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Search, X } from 'lucide-react'
import { getLocations } from '@/services/locationService'

export interface StationKey {
  code: number
  systemId: number
}

export interface StationOption extends StationKey {
  name: string
  locationId?: string
}

interface StationsSelectorDialogProps {
  trigger: React.ReactNode
  /** Источник options. Если undefined — собираем из справочника + selected. */
  options?: StationOption[]
  /** Конкретный STS-source для фильтра привязок (необязательно). */
  stsSourceId?: string
  /** Текущий выбор. */
  selected: StationKey[]
  /** Подтверждение выбора. */
  onSave: (next: StationOption[]) => void
}

const SYS_FILTER_ALL = 'all'

function keyOf(k: StationKey): string {
  return `${k.systemId}|${k.code}`
}

/** Универсум станций — из справочника + те что в текущем выборе. */
function collectUniverse(
  stsSourceId: string | undefined,
  selected: StationKey[],
): StationOption[] {
  const seen = new Set<string>()
  const out: StationOption[] = []
  for (const loc of getLocations()) {
    if (loc.type !== 'fuel_station') continue
    for (const b of loc.sourceBindings) {
      if (stsSourceId && b.sourceId !== stsSourceId) continue
      const systemId = Number(b.config?.system_id ?? b.config?.systemId)
      const code = Number(b.config?.station ?? b.config?.code ?? loc.code)
      if (!systemId || !code) continue
      const key = keyOf({ systemId, code })
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ systemId, code, name: loc.name, locationId: loc.id })
    }
  }
  for (const s of selected) {
    const key = keyOf(s)
    if (seen.has(key)) continue
    seen.add(key)
    out.push({
      systemId: s.systemId, code: s.code,
      name: `Станция ${s.code}`,
    })
  }
  out.sort((a, b) => a.systemId - b.systemId || a.code - b.code)
  return out
}

export function StationsSelectorDialog({
  trigger, options, stsSourceId, selected, onSave,
}: StationsSelectorDialogProps) {
  const [open, setOpen] = useState(false)
  const universe = useMemo(
    () => options ?? collectUniverse(stsSourceId, selected),
    [options, stsSourceId, selected.length, open],
  )

  // Локальное состояние выбора в диалоге — пишем в onSave при клике «Сохранить»
  const initialSelected = useMemo(() => {
    const s = new Set<string>()
    for (const k of selected) s.add(keyOf(k))
    return s
  }, [selected, open])
  const [checked, setChecked] = useState<Set<string>>(initialSelected)

  // Сброс к текущему выбору каждый раз при открытии
  useMemo(() => {
    if (open) setChecked(new Set(initialSelected))
  }, [open, initialSelected])

  const [query, setQuery] = useState('')
  const [sysFilter, setSysFilter] = useState<string>(SYS_FILTER_ALL)

  // Доступные системы по universe
  const systems = useMemo(() => {
    const set = new Set<number>()
    for (const o of universe) set.add(o.systemId)
    return Array.from(set).sort((a, b) => a - b)
  }, [universe])

  // Фильтрация и поиск
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const sys = sysFilter === SYS_FILTER_ALL ? null : Number(sysFilter)
    return universe.filter((o) => {
      if (sys !== null && o.systemId !== sys) return false
      if (!q) return true
      return (
        o.name.toLowerCase().includes(q) ||
        String(o.code).includes(q)
      )
    })
  }, [universe, query, sysFilter])

  function toggle(o: StationOption) {
    setChecked((prev) => {
      const next = new Set(prev)
      const k = keyOf(o)
      if (next.has(k)) next.delete(k)
      else next.add(k)
      return next
    })
  }

  function selectVisible(on: boolean) {
    setChecked((prev) => {
      const next = new Set(prev)
      for (const o of filtered) {
        const k = keyOf(o)
        if (on) next.add(k)
        else next.delete(k)
      }
      return next
    })
  }

  function clearAll() {
    setChecked(new Set())
  }

  function handleSave() {
    const result = universe.filter((o) => checked.has(keyOf(o)))
    onSave(result)
    setOpen(false)
  }

  // Чекбокс «выбрать все видимые»: indeterminate если часть выбрана
  const visAllOn = filtered.length > 0 && filtered.every((o) => checked.has(keyOf(o)))
  const visSomeOn = filtered.some((o) => checked.has(keyOf(o)))
  const visState: boolean | 'indeterminate' = visAllOn ? true : (visSomeOn ? 'indeterminate' : false)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] flex flex-col p-0 gap-0">
        <DialogHeader className="p-4 pb-3 border-b border-border/40">
          <DialogTitle>Выбрать станции</DialogTitle>
          <DialogDescription className="text-xs">
            Всего в справочнике {universe.length} объектов · выбрано {checked.size}
          </DialogDescription>
        </DialogHeader>

        {/* Поиск + фильтр system_id */}
        <div className="px-4 py-2 border-b border-border/40 flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск по имени или коду…"
              className="h-8 pl-7 text-xs"
            />
            {query && (
              <button
                onClick={() => setQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                type="button"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant={sysFilter === SYS_FILTER_ALL ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 text-xs px-2"
              onClick={() => setSysFilter(SYS_FILTER_ALL)}
            >
              Все
            </Button>
            {systems.map((s) => (
              <Button
                key={s}
                variant={sysFilter === String(s) ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 text-xs px-2"
                onClick={() => setSysFilter(String(s))}
              >
                sys {s}
              </Button>
            ))}
          </div>
        </div>

        {/* Bulk action bar */}
        <div className="px-4 py-2 border-b border-border/40 flex items-center justify-between bg-muted/30">
          <label className="flex items-center gap-2 text-xs cursor-pointer">
            <Checkbox
              checked={visState as any}
              onCheckedChange={(v) => selectVisible(!!v)}
              className="h-3.5 w-3.5"
            />
            <span className="font-medium">Видимые ({filtered.length})</span>
            {visSomeOn && (
              <Badge variant="secondary" className="text-[10px] h-4 px-1">
                из них выбрано {filtered.filter((o) => checked.has(keyOf(o))).length}
              </Badge>
            )}
          </label>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-[10px] px-2"
              onClick={() => selectVisible(true)}
            >
              Выбрать видимые
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-[10px] px-2 text-muted-foreground"
              onClick={clearAll}
              disabled={checked.size === 0}
            >
              Снять все
            </Button>
          </div>
        </div>

        {/* Список */}
        <div className="flex-1 overflow-y-auto px-2 py-1 min-h-[280px]">
          {filtered.length === 0 ? (
            <p className="text-xs text-muted-foreground py-8 text-center">
              {universe.length === 0
                ? 'Нет точек в справочнике. Откройте «Настройки → Точки обслуживания».'
                : 'Нет станций по фильтру.'}
            </p>
          ) : (
            <div className="space-y-0.5">
              {filtered.map((o) => {
                const k = keyOf(o)
                const on = checked.has(k)
                return (
                  <label
                    key={k}
                    className="flex items-center gap-2 py-1 px-2 rounded text-xs hover:bg-accent/30 cursor-pointer"
                  >
                    <Checkbox
                      checked={on}
                      onCheckedChange={() => toggle(o)}
                      className="h-3.5 w-3.5"
                    />
                    <span className="font-mono w-10 shrink-0 text-muted-foreground">
                      {o.code}
                    </span>
                    <span className="truncate flex-1">{o.name}</span>
                    <Badge variant="outline" className="text-[9px] h-4 px-1 ml-auto shrink-0">
                      sys {o.systemId}
                    </Badge>
                  </label>
                )
              })}
            </div>
          )}
        </div>

        <DialogFooter className="p-3 border-t border-border/40">
          <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
            Отмена
          </Button>
          <Button size="sm" onClick={handleSave}>
            Сохранить ({checked.size})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
