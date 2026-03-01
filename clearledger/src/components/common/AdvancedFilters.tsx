/**
 * Сворачиваемая панель расширенных фильтров.
 */

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ChevronDown, ChevronUp, X } from 'lucide-react'
import type { AdvancedFilters as AdvancedFiltersType } from '@/types'

interface AdvancedFiltersProps {
  filters: AdvancedFiltersType
  onFiltersChange: (filters: AdvancedFiltersType) => void
  /** Available counterparties for autocomplete */
  counterparties?: string[]
  /** Available sources */
  sources?: { value: string; label: string }[]
  /** Available statuses */
  statuses?: { value: string; label: string }[]
}

export function AdvancedFilters({ filters, onFiltersChange, counterparties = [], sources = [], statuses = [] }: AdvancedFiltersProps) {
  const [open, setOpen] = useState(false)

  const activeCount = Object.values(filters).filter((v) => v !== undefined && v !== '').length

  function update(patch: Partial<AdvancedFiltersType>) {
    onFiltersChange({ ...filters, ...patch })
  }

  function clearAll() {
    onFiltersChange({})
  }

  return (
    <div className="space-y-2">
      {/* Toggle + chips */}
      <div className="flex items-center gap-2 flex-wrap">
        <Button variant="outline" size="sm" onClick={() => setOpen(!open)}>
          Ещё фильтры
          {activeCount > 0 && (
            <Badge variant="secondary" className="ml-1 h-5 min-w-5 px-1">
              {activeCount}
            </Badge>
          )}
          {open ? <ChevronUp className="ml-1 size-4" /> : <ChevronDown className="ml-1 size-4" />}
        </Button>

        {/* Active filter chips */}
        {filters.dateFrom && (
          <Badge variant="outline" className="gap-1">
            от {filters.dateFrom}
            <X className="size-3 cursor-pointer" onClick={() => update({ dateFrom: undefined })} />
          </Badge>
        )}
        {filters.dateTo && (
          <Badge variant="outline" className="gap-1">
            до {filters.dateTo}
            <X className="size-3 cursor-pointer" onClick={() => update({ dateTo: undefined })} />
          </Badge>
        )}
        {filters.counterparty && (
          <Badge variant="outline" className="gap-1">
            {filters.counterparty}
            <X className="size-3 cursor-pointer" onClick={() => update({ counterparty: undefined })} />
          </Badge>
        )}
        {filters.amountMin !== undefined && (
          <Badge variant="outline" className="gap-1">
            от {filters.amountMin}
            <X className="size-3 cursor-pointer" onClick={() => update({ amountMin: undefined })} />
          </Badge>
        )}
        {filters.amountMax !== undefined && (
          <Badge variant="outline" className="gap-1">
            до {filters.amountMax}
            <X className="size-3 cursor-pointer" onClick={() => update({ amountMax: undefined })} />
          </Badge>
        )}
        {activeCount > 0 && (
          <Button variant="ghost" size="sm" onClick={clearAll} className="text-xs">
            Очистить все
          </Button>
        )}
      </div>

      {/* Expanded panel */}
      {open && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 p-4 border rounded-lg bg-muted/30">
          {/* Date range */}
          <div className="space-y-1.5">
            <Label className="text-xs">Дата от</Label>
            <Input
              type="date"
              value={filters.dateFrom ?? ''}
              onChange={(e) => update({ dateFrom: e.target.value || undefined })}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Дата до</Label>
            <Input
              type="date"
              value={filters.dateTo ?? ''}
              onChange={(e) => update({ dateTo: e.target.value || undefined })}
            />
          </div>

          {/* Amount range */}
          <div className="space-y-1.5">
            <Label className="text-xs">Сумма от</Label>
            <Input
              type="number"
              placeholder="0"
              value={filters.amountMin ?? ''}
              onChange={(e) => update({ amountMin: e.target.value ? Number(e.target.value) : undefined })}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Сумма до</Label>
            <Input
              type="number"
              placeholder="∞"
              value={filters.amountMax ?? ''}
              onChange={(e) => update({ amountMax: e.target.value ? Number(e.target.value) : undefined })}
            />
          </div>

          {/* Counterparty */}
          <div className="space-y-1.5">
            <Label className="text-xs">Контрагент</Label>
            <Input
              list="cp-list"
              placeholder="Название или ИНН"
              value={filters.counterparty ?? ''}
              onChange={(e) => update({ counterparty: e.target.value || undefined })}
            />
            {counterparties.length > 0 && (
              <datalist id="cp-list">
                {counterparties.map((cp) => (
                  <option key={cp} value={cp} />
                ))}
              </datalist>
            )}
          </div>

          {/* Status */}
          {statuses.length > 0 && (
            <div className="space-y-1.5">
              <Label className="text-xs">Статус</Label>
              <Select value={filters.status ?? ''} onValueChange={(v) => update({ status: v || undefined })}>
                <SelectTrigger>
                  <SelectValue placeholder="Все" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все</SelectItem>
                  {statuses.map((s) => (
                    <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Source */}
          {sources.length > 0 && (
            <div className="space-y-1.5">
              <Label className="text-xs">Источник</Label>
              <Select value={filters.source ?? ''} onValueChange={(v) => update({ source: v || undefined })}>
                <SelectTrigger>
                  <SelectValue placeholder="Все" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все</SelectItem>
                  {sources.map((s) => (
                    <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
