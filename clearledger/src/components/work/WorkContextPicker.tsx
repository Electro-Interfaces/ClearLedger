import { useDeferredValue, useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { listWorkContexts, resolveWorkContext, searchWorkContexts } from '@/services/workContextService'

export function WorkContextPicker({ companyId, value, onChange }: { companyId: string; value: string | null; onChange: (ref: string | null) => void }) {
  const id = useId()
  const [prefix, setPrefix] = useState(value?.split(':')[0] || '')
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const deferred = useDeferredValue(search)
  const providers = useQuery({ queryKey: ['work-context-providers', companyId], queryFn: () => listWorkContexts(companyId) })
  const selectedPrefix = prefix || providers.data?.providers[0]?.prefix || ''
  const matches = useQuery({ queryKey: ['work-context-search', companyId, selectedPrefix, deferred],
    queryFn: () => searchWorkContexts(companyId, selectedPrefix, deferred), enabled: open && !!selectedPrefix })
  const selected = useQuery({ queryKey: ['work-context', companyId, value], queryFn: () => resolveWorkContext(companyId, value!), enabled: !!value })
  return <div className="space-y-2">
    <label htmlFor={id} className="text-sm font-medium">Контекст работы</label>
    {value && <div className="flex items-start justify-between gap-2 text-sm"><span>{selected.data?.title || (selected.isError ? 'Контекст недоступен' : 'Загрузка…')}</span><Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)}>Убрать</Button></div>}
    <select aria-label="Приложение контекста" className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={selectedPrefix}
      onChange={(e) => { setPrefix(e.target.value); setOpen(true); setSearch('') }}>{providers.data?.providers.map((p) => <option key={p.prefix} value={p.prefix}>{p.label}</option>)}</select>
    {providers.isError && <Button type="button" variant="outline" onClick={() => void providers.refetch()}>Не удалось загрузить приложения. Повторить</Button>}
    <Input id={id} placeholder="Номер, название или адрес" value={search} onFocus={() => setOpen(true)}
      onChange={(e) => { setSearch(e.target.value); setOpen(true) }} aria-controls={`${id}-results`} aria-expanded={open} />
    {open && <div id={`${id}-results`} className="max-h-48 overflow-y-auto rounded-md border p-1">
      {matches.isPending && <p className="p-2 text-sm">Поиск…</p>}
      {matches.isError && <Button type="button" variant="ghost" onClick={() => void matches.refetch()}>Ошибка поиска. Повторить</Button>}
      {matches.data?.items.length === 0 && <p className="p-2 text-sm text-muted-foreground">Ничего не найдено</p>}
      {matches.data?.items.map((r) => <button key={r.ref} type="button" className="block w-full rounded p-2 text-left text-sm hover:bg-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
        onClick={() => { onChange(r.ref); setSearch(''); setOpen(false) }}><span className="font-medium">{r.title}</span><span className="block text-xs text-muted-foreground">{r.hint}</span></button>)}
      <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>Закрыть поиск</Button>
    </div>}
  </div>
}
