/**
 * Подразделения — штатная структура организации: дерево с руководителями.
 *
 * Отвечает на вопрос «кто кому подчиняется и кто за что отвечает»: по руководителю
 * подразделения идёт первая эскалация («не сразу директору»), по дереву — подача
 * людей и, дальше, права уровня подразделения. Людей в подразделение назначают
 * в карточке участника — здесь сами узлы структуры.
 */
import { Fragment, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Loader2, Network, Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import * as departmentsService from '@/services/departmentsService'
import type { Department } from '@/services/departmentsService'
import * as userService from '@/services/userService'

/** Дерево отступами: план глубже трёх уровней в компании этого размера не живёт. */
function flatten(deps: Department[]): { d: Department; depth: number }[] {
  const byParent = new Map<string | null, Department[]>()
  for (const d of deps) {
    const key = d.parent_id
    if (!byParent.has(key)) byParent.set(key, [])
    byParent.get(key)!.push(d)
  }
  const out: { d: Department; depth: number }[] = []
  const walk = (parent: string | null, depth: number) => {
    for (const d of byParent.get(parent) ?? []) {
      out.push({ d, depth })
      walk(d.id, depth + 1)
    }
  }
  walk(null, 0)
  // Узлы с потерянным родителем (родителя удалили) — в конец, верхним уровнем.
  const seen = new Set(out.map((x) => x.d.id))
  for (const d of deps) if (!seen.has(d.id)) out.push({ d, depth: 0 })
  return out
}

export function DepartmentsPanel({ companyId, canManage }: {
  companyId: string; canManage: boolean
}) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['departments', companyId],
    queryFn: () => departmentsService.listDepartments(companyId),
  })
  // Люди организации: кандидаты в руководители и состав раскрытых подразделений.
  const membersQ = useQuery({
    queryKey: ['team-members', companyId],
    queryFn: () => userService.listUsers(companyId),
  })
  const people = useMemo(
    () => (membersQ.data ?? []).filter((m) => (m.party_type ?? 'internal') === 'internal'),
    [membersQ.data])

  const [editing, setEditing] = useState<Department | 'new' | null>(null)
  // Раскрытые подразделения: строка разворачивается в состав — кто здесь работает.
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const refresh = () => qc.invalidateQueries({ queryKey: ['departments', companyId] })

  const remove = useMutation({
    mutationFn: (d: Department) => departmentsService.deleteDepartment(d.id, companyId),
    onSuccess: () => { toast.success('Подразделение убрано; люди остались без подразделения'); refresh() },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const rows = flatten(q.data ?? [])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs text-muted-foreground">
          Штатная структура: по руководителю подразделения идёт эскалация — сначала
          начальник, потом выше. Подразделение сотруднику назначается в его карточке.
        </p>
        {canManage && (
          <Button size="sm" className="ml-auto h-8" onClick={() => setEditing('new')}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />Добавить
          </Button>
        )}
      </div>

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка структуры…
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Структура пока не заведена. Добавьте первые подразделения — дирекцию, отделы,
          службы — и назначьте руководителей: эскалации и подача людей пойдут по ним.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[640px] text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="p-2.5 text-left font-medium">Подразделение</th>
                <th className="p-2.5 text-left font-medium">Руководитель</th>
                <th className="p-2.5 text-right font-medium">Людей</th>
                {canManage && <th className="w-20 p-2.5" />}
              </tr>
            </thead>
            <tbody>
              {rows.map(({ d, depth }) => {
                const staff = people.filter((m) => m.department_id === d.id)
                const isOpen = !!open[d.id]
                return (
                  <Fragment key={d.id}>
                    {/* Строка раскрывается в состав: «кто здесь работает» — первый
                        вопрос к подразделению, за ним не ходят в общий список. */}
                    <tr
                      tabIndex={0}
                      onClick={() => setOpen((o) => ({ ...o, [d.id]: !o[d.id] }))}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          setOpen((o) => ({ ...o, [d.id]: !o[d.id] }))
                        }
                      }}
                      className="cursor-pointer border-t transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                    >
                      <td className="p-2.5">
                        <span style={{ paddingLeft: depth * 20 }} className="flex items-center gap-1.5">
                          {isOpen
                            ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                          <Network className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                          <span className="font-medium text-foreground">{d.name}</span>
                        </span>
                      </td>
                      <td className="p-2.5">
                        {d.head_name ?? <span className="text-amber-500/90">не назначен — эскалировать некому</span>}
                      </td>
                      <td className="p-2.5 text-right tabular-nums">{d.people || '—'}</td>
                      {canManage && (
                        <td className="p-2.5 text-right">
                          <Button variant="ghost" size="icon" className="h-6 w-6" title="Изменить"
                            onClick={(e) => { e.stopPropagation(); setEditing(d) }}>
                            <Pencil className="h-3 w-3" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-destructive"
                            title="Убрать подразделение" disabled={remove.isPending}
                            onClick={(e) => { e.stopPropagation(); remove.mutate(d) }}>
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </td>
                      )}
                    </tr>
                    {isOpen && (
                      <tr className="border-t border-dashed bg-muted/20">
                        <td colSpan={canManage ? 4 : 3} className="px-2.5 py-2">
                          <div style={{ paddingLeft: depth * 20 + 24 }} className="space-y-1">
                            {staff.length === 0 && (
                              <p className="text-[11px] text-muted-foreground">
                                Людей пока нет — подразделение назначается в карточке сотрудника.
                              </p>
                            )}
                            {staff.map((m) => (
                              <div key={m.id} className="flex flex-wrap items-baseline gap-x-2 text-xs">
                                <span className="font-medium text-foreground">{m.name || m.email}</span>
                                {d.head_user_id === m.id && (
                                  <span className="rounded border border-primary/40 px-1 text-[10px] text-primary">руководитель</span>
                                )}
                                <span className="text-muted-foreground">
                                  {m.position || '— должность —'}
                                  {m.last_seen_at
                                    ? ` · вход: ${new Date(m.last_seen_at).toLocaleString('ru-RU',
                                        { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}`
                                    : ' · не заходил(а)'}
                                </span>
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <DepartmentDialog
          companyId={companyId}
          dep={editing === 'new' ? null : editing}
          all={q.data ?? []}
          people={people.map((p) => ({ id: p.id, name: p.name || p.email }))}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); refresh() }}
        />
      )}
    </div>
  )
}

function DepartmentDialog({ companyId, dep, all, people, onClose, onSaved }: {
  companyId: string
  dep: Department | null
  all: Department[]
  people: { id: string; name: string }[]
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(dep?.name ?? '')
  const [parentId, setParentId] = useState(dep?.parent_id ?? '')
  const [headId, setHeadId] = useState(dep?.head_user_id ?? '')
  // Себя и своих потомков в родители не предлагаем — сервер петлю тоже отвергнет.
  const parents = all.filter((d) => d.id !== dep?.id)

  const save = useMutation({
    mutationFn: async () => {
      if (dep) {
        await departmentsService.updateDepartment(dep.id, companyId,
          { name: name.trim(), parentId, headUserId: headId })
      } else {
        await departmentsService.createDepartment(companyId,
          { name: name.trim(), parentId: parentId || undefined, headUserId: headId || undefined })
      }
    },
    onSuccess: () => { toast.success(dep ? 'Сохранено' : 'Подразделение добавлено'); onSaved() },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{dep ? 'Подразделение' : 'Новое подразделение'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Название</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)}
              placeholder="напр. Отдел эксплуатации" maxLength={200} />
          </div>
          <div className="space-y-1.5">
            <Label>Входит в</Label>
            <Select value={parentId || 'root'} onValueChange={(v) => setParentId(v === 'root' ? '' : v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="root">— верхний уровень —</SelectItem>
                {parents.map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Руководитель</Label>
            <Select value={headId || 'none'} onValueChange={(v) => setHeadId(v === 'none' ? '' : v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">— не назначен —</SelectItem>
                {people.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <p className="text-[11px] text-muted-foreground">
              К нему идёт первая эскалация по людям подразделения.
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {dep ? 'Сохранить' : 'Добавить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
