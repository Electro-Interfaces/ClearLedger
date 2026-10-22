import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

/** Поиск — по всему каталогу контура, отбор применяется только после подтверждения. */
export function ConnectorFilter({ label, options, value, onChange, disabled }: {
  label: string
  options: { id: string; label: string }[]
  value: string[]
  onChange: (value: string[]) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState(value)
  const selected = new Set(draft)
  const query = search.trim().toLocaleLowerCase('ru')
  const filtered = options.filter(o => o.label.toLocaleLowerCase('ru').includes(query))
  return <Popover open={open} onOpenChange={next => {
    setOpen(next)
    if (next) { setDraft(value); setSearch('') }
  }}>
    <PopoverTrigger asChild>
      <Button variant="outline" size="sm" disabled={disabled} aria-label={`${label}: ${value.length ? `выбрано ${value.length}` : 'все'}`}
        className="min-h-11 max-w-full justify-between gap-2 sm:min-h-9">
        {label}: {value.length || 'все'}<ChevronDown className="size-3.5 shrink-0" aria-hidden="true" />
      </Button>
    </PopoverTrigger>
    <PopoverContent align="start" className="w-[min(26rem,calc(100vw-2rem))] space-y-3" aria-label={label}>
      <Input value={search} onChange={e => setSearch(e.target.value)} placeholder={`Поиск: ${label.toLowerCase()}`}
        aria-label={`Поиск: ${label.toLowerCase()}`} className="h-11 sm:h-9" />
      <div className="max-h-64 overflow-y-auto">
        {filtered.length ? filtered.map(o => <label key={o.id} className="flex min-h-11 cursor-pointer items-center gap-2 rounded px-1 py-2 text-sm hover:bg-muted sm:min-h-10">
          <Checkbox checked={selected.has(o.id)} onCheckedChange={checked => setDraft(prev => checked ? [...prev, o.id] : prev.filter(id => id !== o.id))} />
          <span className="min-w-0 break-words">{o.label}</span>
        </label>) : <p className="py-3 text-sm text-muted-foreground">{options.length ? 'Ничего не найдено' : 'В контуре нет известных коннекторов'}</p>}
      </div>
      <p className="text-xs text-muted-foreground">Выбрано: {draft.length}. Пустой выбор означает все.</p>
      <div className="flex flex-wrap gap-2 border-t pt-3">
        <Button variant="ghost" size="sm" className="h-11 sm:h-9" onClick={() => setDraft([])}>Сбросить</Button>
        <Button variant="outline" size="sm" className="h-11 sm:h-9" onClick={() => setOpen(false)}>Отмена</Button>
        <Button size="sm" className="h-11 sm:h-9" onClick={() => { onChange([...new Set(draft)].sort()); setOpen(false) }}>Применить</Button>
      </div>
    </PopoverContent>
  </Popover>
}
