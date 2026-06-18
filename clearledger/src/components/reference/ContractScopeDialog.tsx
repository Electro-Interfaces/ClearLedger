/**
 * Управление охватом договора по торговым точкам (ось договор↔точки, Фаза 2).
 * Режимы: «Вся компания» / «Выбранные точки» (мультиселект) / «Не распределён».
 */
import { useState, useEffect, useMemo, type ReactNode } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Loader2, Search } from 'lucide-react'
import { toast } from 'sonner'
import { useLocations } from '@/hooks/useLocations'
import { useContractLocations, useSetContractScope } from '@/hooks/useReferences'
import type { Contract, ContractScopeType } from '@/types'

export function ContractScopeDialog({
  contract,
  children,
  onSaved,
}: {
  contract: Contract
  children: ReactNode
  onSaved?: () => void
}) {
  const [open, setOpen] = useState(false)
  const locations = useLocations()
  const { data: current = [] } = useContractLocations(open ? contract.id : null)
  const saveMut = useSetContractScope()

  const [scopeType, setScopeType] = useState<ContractScopeType>(contract.scopeType ?? 'unassigned')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')

  useEffect(() => {
    if (open) setScopeType(contract.scopeType ?? 'unassigned')
  }, [open, contract.scopeType])

  useEffect(() => {
    if (open && current.length) setSelected(new Set(current.map((l) => l.id)))
  }, [open, current])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return locations
    return locations.filter(
      (l) => l.name.toLowerCase().includes(q) || l.code.toLowerCase().includes(q),
    )
  }, [locations, search])

  function toggle(id: string) {
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  async function handleSave() {
    if (scopeType === 'locations' && selected.size === 0) {
      toast.error('Выберите хотя бы одну точку или смените режим охвата')
      return
    }
    try {
      await saveMut.mutateAsync({
        contractId: contract.id,
        scopeType,
        locationIds: scopeType === 'locations' ? [...selected] : [],
      })
      toast.success('Охват договора сохранён')
      setOpen(false)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить охват')
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Охват договора {contract.number}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          <div className="space-y-1.5">
            <Label>Режим охвата</Label>
            <Select value={scopeType} onValueChange={(v) => setScopeType(v as ContractScopeType)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="company">Вся компания (все точки, в т.ч. будущие)</SelectItem>
                <SelectItem value="locations">Выбранные точки</SelectItem>
                <SelectItem value="unassigned">Не распределён</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {scopeType === 'locations' && (
            <div className="space-y-2 border-t border-border/50 pt-3">
              <div className="flex items-center justify-between">
                <Label>Торговые точки</Label>
                <span className="text-xs text-muted-foreground">выбрано: {selected.size}</span>
              </div>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                <Input value={search} onChange={(e) => setSearch(e.target.value)}
                  placeholder="Поиск точки..." className="pl-8 h-9" />
              </div>
              <div className="max-h-64 overflow-y-auto space-y-1 rounded-md border border-border/50 p-2">
                {filtered.length === 0 && (
                  <p className="text-xs text-muted-foreground p-2">Точки не найдены.</p>
                )}
                {filtered.map((l) => (
                  <label key={l.id}
                    className="flex items-center gap-2 text-sm py-1 px-1.5 rounded hover:bg-muted cursor-pointer">
                    <input type="checkbox" checked={selected.has(l.id)} onChange={() => toggle(l.id)} />
                    <span className="font-medium">{l.name}</span>
                    <span className="text-xs text-muted-foreground font-mono">{l.code}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {scopeType === 'company' && (
            <p className="text-xs text-muted-foreground">
              Договор действует на все торговые точки компании, включая открытые в будущем.
            </p>
          )}
          {scopeType === 'unassigned' && (
            <p className="text-xs text-muted-foreground">
              Охват не задан — договор не привязан к точкам (требует распределения).
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={saveMut.isPending}>
            Отмена
          </Button>
          <Button onClick={handleSave} disabled={saveMut.isPending}>
            {saveMut.isPending && <Loader2 className="size-4 mr-2 animate-spin" />}
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Бейдж охвата для строки договора. */
export function ContractScopeBadgeLabel(scopeType?: ContractScopeType): string {
  switch (scopeType) {
    case 'company': return 'Вся компания'
    case 'locations': return 'Выбранные точки'
    default: return 'Не распределён'
  }
}
