/**
 * Вкладка «Объекты» Центра управления — реестр объектов пространства (docs/SPACE.md §5).
 *
 * Объекты компании общие для всех приложений-разрезов, поэтому заводятся и правятся
 * здесь, в единственной админке пространства. Рабочая часть (операционный статус, карта,
 * связь со сменами и заявками) остаётся в приложениях — сюда не тянем.
 */
import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, MapPin, Plus, Search, Pencil, Share2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  listSpaceObjects, createSpaceObject, updateSpaceObject, projectSpaceObjects,
  OBJECT_TYPE_LABELS, OBJECT_STATUS_LABELS,
  type SpaceObject, type SpaceObjectInput, type ObjectImpact,
} from '@/services/spaceObjectsService'

const EMPTY: SpaceObjectInput = { code: '', name: '', type: 'fuel_station', status: 'active' }

export function SpaceObjects({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<SpaceObject | null>(null)
  const [form, setForm] = useState<SpaceObjectInput | null>(null)

  const key = ['space-objects', companyId]
  const q = useQuery({ queryKey: key, queryFn: () => listSpaceObjects(companyId) })

  // Проекция в приложения-разрезы: объект, заведённый здесь, должен появиться там,
  // где по нему работают (заявки Координатора), без ручного заведения второй раз.
  const project = useMutation({
    mutationFn: () => projectSpaceObjects(companyId, 'support'),
    onSuccess: (r) => toast.success(
      `Поддержка обновлена: создано ${r.created}, обновлено ${r.updated}`,
      { description: `Отправлено объектов: ${r.sent}` },
    ),
    onError: (e) => toast.error('Проекция не выполнена', { description: (e as Error).message }),
  })

  // Вывод объекта из эксплуатации: сервер такой переход без подтверждения не
  // проводит и возвращает, сколько работы закроется вместе с объектом. Держим
  // это состояние здесь — диалог показывает цифру и спрашивает согласие.
  const [leaving, setLeaving] = useState<{ data: SpaceObjectInput; impact: ObjectImpact } | null>(null)

  const save = useMutation({
    mutationFn: async ({ data, confirm }: { data: SpaceObjectInput; confirm?: boolean }) => {
      if (!editing) return createSpaceObject(companyId, data)
      return updateSpaceObject(companyId, editing.id, data, confirm)
    },
    onSuccess: () => {
      toast.success(editing ? 'Объект обновлён' : 'Объект добавлен')
      qc.invalidateQueries({ queryKey: key })
      // Прикладной разрез читает те же данные — обновляем и его кеш.
      qc.invalidateQueries({ queryKey: ['locations'] })
      setForm(null); setEditing(null); setLeaving(null)
    },
    onError: async (e) => {
      const detail = (e as { detail?: unknown }).detail as
        { code?: string; willArchive?: ObjectImpact['support'] } | undefined
      if (detail?.code === 'object_leaves_operation' && pendingRef.current) {
        setLeaving({ data: pendingRef.current, impact: { support: detail.willArchive ?? { known: false } } })
        return
      }
      toast.error((e as Error).message || 'Не удалось сохранить')
    },
  })

  // Что именно сохраняли, когда сервер попросил подтверждение.
  const pendingRef = useRef<SpaceObjectInput | null>(null)
  const submit = (data: SpaceObjectInput) => { pendingRef.current = data; save.mutate({ data }) }

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 py-8 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
      </div>
    )
  }

  const objects = q.data ?? []
  const term = search.trim().toLowerCase()
  const shown = term
    ? objects.filter((o) => o.code.toLowerCase().includes(term) || o.name.toLowerCase().includes(term))
    : objects

  function openCreate() { setEditing(null); setForm({ ...EMPTY }) }
  function openEdit(o: SpaceObject) {
    setEditing(o)
    setForm({
      code: o.code, name: o.name, type: o.type, status: o.status,
      address: o.address ?? '', description: o.description ?? '',
      latitude: o.latitude ?? null, longitude: o.longitude ?? null,
    })
  }

  // Смысл раздела подписан в шапке рабочей области «Управления» — здесь только работа.
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Код или наименование" className="pl-8" />
        </div>
        <div className="flex-1" />
        {canManage && objects.length > 0 && (
          <Button size="sm" variant="outline" onClick={() => project.mutate()}
            disabled={project.isPending} className="gap-1.5" title="Отправить объекты в Поддержку">
            {project.isPending
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <Share2 className="h-4 w-4" />}
            В приложения
          </Button>
        )}
        {canManage && (
          <Button size="sm" onClick={openCreate} className="gap-1.5">
            <Plus className="h-4 w-4" /> Добавить объект
          </Button>
        )}
      </div>

      {shown.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
          {objects.length === 0
            ? 'В пространстве пока нет объектов. Добавьте первый — он станет виден всем приложениям.'
            : 'Ничего не найдено'}
        </div>
      ) : (
        <div className="rounded-xl border border-border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[140px]">Код</TableHead>
                <TableHead>Наименование</TableHead>
                <TableHead className="w-[120px]">Тип</TableHead>
                <TableHead className="w-[130px]">Статус</TableHead>
                <TableHead>Адрес</TableHead>
                {canManage && <TableHead className="w-[60px]" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((o) => (
                <TableRow key={o.id}>
                  <TableCell className="font-mono text-xs">{o.code}</TableCell>
                  <TableCell className="font-medium">{o.name}</TableCell>
                  <TableCell>{OBJECT_TYPE_LABELS[o.type] ?? o.type}</TableCell>
                  <TableCell>
                    <Badge variant={o.status === 'active' ? 'default' : 'secondary'}>
                      {OBJECT_STATUS_LABELS[o.status] ?? o.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {o.address || <span className="opacity-60">—</span>}
                  </TableCell>
                  {canManage && (
                    <TableCell>
                      <Button variant="ghost" size="icon" onClick={() => openEdit(o)} title="Изменить">
                        <Pencil className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <MapPin className="h-3.5 w-3.5" /> Всего объектов: {objects.length}
      </div>

      <Dialog open={form !== null} onOpenChange={(open) => { if (!open) { setForm(null); setEditing(null) } }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? 'Изменение объекта' : 'Новый объект'}</DialogTitle>
            <DialogDescription>
              Паспорт объекта пространства. Прикладные характеристики (оборудование,
              резервуары, обслуживание) ведутся в приложениях.
            </DialogDescription>
          </DialogHeader>

          {form && (
            <div className="grid gap-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-1.5">
                  <Label htmlFor="obj-code">Код</Label>
                  <Input id="obj-code" value={form.code}
                    onChange={(e) => setForm({ ...form, code: e.target.value })}
                    placeholder="АЗС-208" />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="obj-type">Тип</Label>
                  <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                    <SelectTrigger id="obj-type"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {Object.entries(OBJECT_TYPE_LABELS).map(([v, label]) => (
                        <SelectItem key={v} value={v}>{label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="obj-name">Наименование</Label>
                <Input id="obj-name" value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="АЗС №208, Выборгское шоссе" />
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="obj-address">Адрес</Label>
                <Input id="obj-address" value={form.address ?? ''}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                  placeholder="Санкт-Петербург, Выборгское шоссе, 25" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-1.5">
                  <Label htmlFor="obj-status">Статус</Label>
                  <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                    <SelectTrigger id="obj-status"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {Object.entries(OBJECT_STATUS_LABELS).map(([v, label]) => (
                        <SelectItem key={v} value={v}>{label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="obj-geo">Координаты</Label>
                  <div className="flex gap-2">
                    <Input id="obj-geo" inputMode="decimal" value={form.latitude ?? ''}
                      onChange={(e) => setForm({ ...form, latitude: e.target.value ? Number(e.target.value) : null })}
                      placeholder="59.93" />
                    <Input inputMode="decimal" value={form.longitude ?? ''}
                      onChange={(e) => setForm({ ...form, longitude: e.target.value ? Number(e.target.value) : null })}
                      placeholder="30.31" />
                  </div>
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => { setForm(null); setEditing(null) }}>Отмена</Button>
            <Button
              disabled={!form?.code.trim() || !form?.name.trim() || save.isPending}
              onClick={() => form && submit(form)}
            >
              {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editing ? 'Сохранить' : 'Добавить'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Вывод из эксплуатации. Не «вы уверены?»: диалог называет последствие
          числом, потому что решение зависит именно от него — одно дело закрыть
          станцию без работы, другое вместе с десятком открытых заявок. */}
      <Dialog open={!!leaving} onOpenChange={(o) => !o && setLeaving(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Объект уходит из эксплуатации</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              Состав объектов приложений задаёт этот реестр. После перевода в состояние
              «{OBJECT_STATUS_LABELS[leaving?.data.status ?? ''] ?? leaving?.data.status}» объект
              пропадёт из «Поддержки», а открытая по нему работа закроется.
            </p>
            {leaving?.impact.support.known ? (
              <div className="rounded-md border border-border bg-muted/30 px-3 py-2.5">
                <div className="text-foreground">
                  Заявок по объекту: <b>{leaving.impact.support.total ?? 0}</b>
                  {(leaving.impact.support.open ?? 0) > 0 && (
                    <>, из них открытых <b className="text-amber-500">{leaving.impact.support.open}</b></>
                  )}
                </div>
                {(leaving.impact.support.open ?? 0) > 0 && (
                  <div className="mt-1 text-xs text-muted-foreground">
                    Они будут отменены с причиной «объект выведен из эксплуатации».
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs">
                Поддержка не ответила, сколько работы связано с объектом
                {leaving?.impact.support.reason ? `: ${leaving.impact.support.reason}` : ''}.
                Последствия неизвестны — лучше повторить позже.
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLeaving(null)}>Отмена</Button>
            <Button
              variant="destructive"
              disabled={save.isPending}
              onClick={() => leaving && save.mutate({ data: leaving.data, confirm: true })}
            >
              {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Вывести из эксплуатации
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
