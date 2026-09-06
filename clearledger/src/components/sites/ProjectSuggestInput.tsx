import { useEffect, useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Input } from '@/components/ui/input'
import { getProjectSuggestions, type ProjectSuggestion, type ProjectSuggestionField } from '@/services/sitesService'

export function ProjectSuggestInput({ companyId, field, label, value, placeholder, region, city, onChange, onSelect }: {
  companyId: string; field: ProjectSuggestionField; label: string; value: string; placeholder?: string
  region?: string; city?: string; onChange: (value: string) => void; onSelect: (item: ProjectSuggestion) => void
}) {
  const id = useId()
  const [focused, setFocused] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(-1)
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(value.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [value])
  const ready = focused && query.length >= 2 && query === value.trim()
  const suggestions = useQuery({
    queryKey: ['pr-suggestions', companyId, field, query, region, city],
    queryFn: () => getProjectSuggestions(companyId, field, query, region, city),
    enabled: ready, staleTime: 60_000, retry: false,
  })
  const items = ready ? suggestions.data?.items ?? [] : []
  useEffect(() => {
    if (active >= 0) document.getElementById(`${id}-${active}`)?.scrollIntoView({ block: 'nearest' })
  }, [active, id])
  const choose = (item: ProjectSuggestion) => { onSelect(item); setFocused(false); setActive(-1) }
  const addressField = ['region', 'city', 'address'].includes(field)
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="block text-xs uppercase tracking-wide text-muted-foreground mb-1">{label}</label>
      <Input id={id} role="combobox" aria-autocomplete="list" aria-expanded={items.length > 0}
        aria-controls={`${id}-list`} aria-activedescendant={items[active] ? `${id}-${active}` : undefined}
        autoComplete="off" className="h-9 text-sm" value={value} placeholder={placeholder}
        onChange={(event) => { onChange(event.target.value); setFocused(true); setActive(-1) }}
        onFocus={() => setFocused(true)} onBlur={() => { setFocused(false); setActive(-1) }}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && focused) { event.preventDefault(); event.stopPropagation(); setFocused(false) }
          if (items.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
            event.preventDefault()
            setActive((current) => event.key === 'ArrowDown' ? (current + 1) % items.length
              : current <= 0 ? items.length - 1 : current - 1)
          }
          if (event.key === 'Enter' && items[active]) { event.preventDefault(); choose(items[active]) }
        }} />
      {items.length > 0 && (
        <ul id={`${id}-list`} role="listbox" aria-label={`Подсказки: ${label}`}
          className="mt-1 max-h-40 overflow-y-auto rounded-md border bg-popover p-1">
          {items.map((item, index) => (
            <li key={`${item.source}-${item.value}`} id={`${id}-${index}`} role="option" aria-selected={index === active}
              onPointerDown={(event) => event.preventDefault()} onClick={() => choose(item)}
              className={`cursor-pointer rounded px-2 py-2 text-sm break-words hover:bg-accent ${index === active ? 'bg-accent' : ''}`}>
              {item.label ?? item.value}
              <span className="block text-[11px] text-muted-foreground">{item.source === 'registry' ? 'Адресный реестр' : 'Из проектов пространства'}</span>
            </li>
          ))}
        </ul>
      )}
      {ready && <p role="status" className="mt-1 text-[11px] text-muted-foreground">
        {suggestions.isFetching ? 'Ищем подсказки…' : suggestions.isError ? 'Подсказки недоступны. Можно ввести вручную.'
          : addressField && suggestions.data?.registry === 'unavailable' ? 'Адресный сервис недоступен. Показаны адреса из проектов.'
          : addressField && suggestions.data?.registry === 'local' ? 'Подсказки по адресам проектов пространства.'
          : items.length === 0 ? 'Совпадений нет. Можно ввести новое значение.' : ''}
      </p>}
    </div>
  )
}
