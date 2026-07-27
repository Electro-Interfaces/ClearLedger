/**
 * Скоуп данных участника: по каким объектам он видит данные.
 *
 * Второй, ортогональный правам слой доступа. Права (`роль`) отвечают «какие экраны
 * открыты», скоуп — «по каким объектам на них видны данные»: подрядчику нужен «Парк
 * оборудования», но только на его пяти станциях, а не на всех 619.
 *
 * По умолчанию скоупа нет — вся сеть компании. Это осознанный дефолт: сотрудник
 * заказчика работает со всей сетью, сужение — исключение для внешних и филиалов.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Check, Loader2, MapPin, Search } from 'lucide-react'
import * as userService from '@/services/userService'
import type { AdminUser } from '@/services/userService'
import { listSpaceObjects } from '@/services/spaceObjectsService'

export function ObjectScopeDialog({ member, companyId, onSaved }: {
  member: AdminUser; companyId: string; onSaved: () => void
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [all, setAll] = useState(!member.object_scope?.length)
  const [sel, setSel] = useState<Set<string>>(new Set(member.object_scope ?? []))

  const objectsQ = useQuery({
    queryKey: ['space-objects-scope', companyId],
    queryFn: () => listSpaceObjects(companyId),
    enabled: open,
    staleTime: 5 * 60_000,
  })
  const objects = objectsQ.data ?? []

  // Состояние сбрасывается при открытии, а не эффектом на open: эффект дал бы лишний
  // рендер и предупреждение линтера, а открытие — это и есть событие.
  const openChange = (v: boolean) => {
    if (v) {
      setAll(!member.object_scope?.length)
      setSel(new Set(member.object_scope ?? []))
      setSearch('')
    }
    setOpen(v)
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return objects
    return objects.filter((o) => `${o.code} ${o.name} ${o.address ?? ''}`.toLowerCase().includes(q))
  }, [objects, search])

  const save = useMutation({
    mutationFn: () => userService.setMemberScope(member.id, companyId, all ? null : [...sel]),
    onSuccess: () => {
      toast.success(all ? 'Доступ ко всей сети' : `Объектов в доступе: ${sel.size}`)
      qc.invalidateQueries({ queryKey: ['team-members', companyId] })
      onSaved(); setOpen(false)
    },
    onError: (e) => toast.error('Не сохранено', { description: (e as Error).message }),
  })

  const toggle = (id: string) => setSel((s) => {
    const n = new Set(s)
    if (n.has(id)) n.delete(id); else n.add(id)
    return n
  })
  const label = member.object_scope?.length ? `${member.object_scope.length}` : 'вся сеть'

  return (
    <Dialog open={open} onOpenChange={openChange}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="h-6 gap-1 px-1.5 text-[11px] text-muted-foreground hover:text-foreground"
          title="Объекты, по которым человек видит данные">
          <MapPin className="h-3.5 w-3.5" /> {label}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Объекты в доступе: {member.name}</DialogTitle></DialogHeader>
        <p className="text-xs text-muted-foreground -mt-1">
          Данные на всех экранах — сессии, оборудование, объекты — сузятся до выбранных.
          Что именно человек открывает, задаёт роль.
        </p>
        <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} className="h-4 w-4" />
          Вся сеть компании
        </label>
        <div className={all ? 'opacity-40 pointer-events-none' : ''}>
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Код, название или адрес" className="h-8 pl-8 text-sm" />
          </div>
          <div className="flex items-center justify-between mb-1.5 text-[11px] text-muted-foreground">
            <span>Выбрано: {sel.size} из {objects.length}</span>
            <span className="flex gap-2">
              <button type="button" className="hover:text-foreground"
                onClick={() => setSel(new Set(filtered.map((o) => o.id)))}>выбрать найденные</button>
              <button type="button" className="hover:text-foreground"
                onClick={() => setSel(new Set())}>снять все</button>
            </span>
          </div>
          <div className="max-h-72 overflow-y-auto pr-1 flex flex-col gap-1">
            {objectsQ.isLoading && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Загрузка объектов…
              </div>
            )}
            {!objectsQ.isLoading && filtered.length === 0 && (
              <div className="text-xs text-muted-foreground py-2">Ничего не найдено</div>
            )}
            {filtered.map((o) => {
              const on = sel.has(o.id)
              return (
                <button key={o.id} type="button" onClick={() => toggle(o.id)}
                  className={`flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-md border text-left transition-colors ${
                    on ? 'bg-primary/10 border-primary/40' : 'border-border hover:bg-accent/40'
                  }`}>
                  <span className="min-w-0">
                    <span className="text-[13px] font-medium">{o.code}</span>
                    <span className="text-[13px] text-muted-foreground"> · {o.name}</span>
                  </span>
                  {on && <Check className="h-3.5 w-3.5 text-primary shrink-0" />}
                </button>
              )
            })}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Отмена</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || (!all && sel.size === 0)}>
            {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />}Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
