/**
 * Редактор одной грани договора по разрезу (Фаза 3): мультиселект элементов
 * разреза (номенклатура/каналы/…). Пусто = договор не ограничен по разрезу.
 * Самодостаточный: грузит текущую грань и сохраняет её отдельной кнопкой.
 */
import { useState, useEffect, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Search, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useContractDimensions, useSetContractDimension } from '@/hooks/useReferences'

export interface DimItem {
  id: string
  label: string
  sub?: string
}

export function ContractDimensionEditor({
  contractId,
  dimType,
  title,
  items,
  hint,
}: {
  contractId: string
  dimType: string
  title: string
  items: DimItem[]
  hint?: string
}) {
  const { data } = useContractDimensions(contractId)
  const saveMut = useSetContractDimension()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [touched, setTouched] = useState(false)

  const current = data?.dimensions[dimType]
  useEffect(() => {
    if (current && !touched) setSelected(new Set(current))
  }, [current, touched])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const base = q
      ? items.filter((i) => i.label.toLowerCase().includes(q) || (i.sub ?? '').toLowerCase().includes(q))
      : items
    return base.slice(0, 50) // лимит рендера (номенклатуры могут быть тысячи)
  }, [items, search])

  function toggle(id: string) {
    setTouched(true)
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  async function save() {
    try {
      await saveMut.mutateAsync({ contractId, dimType, refs: [...selected] })
      toast.success(`${title}: ограничение сохранено`)
      setTouched(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить ограничение')
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label>{title}</Label>
        <span className="text-xs text-muted-foreground">
          {selected.size === 0 ? 'без ограничения' : `выбрано: ${selected.size}`}
        </span>
      </div>
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Поиск..." className="pl-8 h-9" />
      </div>
      <div className="max-h-48 overflow-y-auto space-y-1 rounded-md border border-border/50 p-2">
        {filtered.length === 0 && (
          <p className="text-xs text-muted-foreground p-1">Ничего не найдено.</p>
        )}
        {filtered.map((i) => (
          <label key={i.id}
            className="flex items-center gap-2 text-sm py-1 px-1.5 rounded hover:bg-muted cursor-pointer">
            <input type="checkbox" checked={selected.has(i.id)} onChange={() => toggle(i.id)} />
            <span className="font-medium">{i.label}</span>
            {i.sub && <span className="text-xs text-muted-foreground font-mono">{i.sub}</span>}
          </label>
        ))}
        {search.trim() === '' && items.length > 50 && (
          <p className="text-[11px] text-muted-foreground p-1">
            …показаны первые 50, уточните поиском
          </p>
        )}
      </div>
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={save} disabled={!touched || saveMut.isPending}>
          {saveMut.isPending && <Loader2 className="size-3.5 mr-1.5 animate-spin" />}
          Применить
        </Button>
      </div>
    </div>
  )
}
