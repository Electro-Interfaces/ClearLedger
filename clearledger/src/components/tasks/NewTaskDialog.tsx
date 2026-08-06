/**
 * Постановка задачи — полная форма.
 *
 * Строка «что сделать + Enter» хороша, когда мысль надо поймать на ходу, но
 * настоящую задачу ставят иначе: кому, к какому сроку, с описанием и со
 * скриншотом, на котором видно, о чём речь. Поэтому рядом с быстрой строкой
 * живёт эта форма, и всё, что человек уже знает в момент постановки,
 * записывается сразу — а не дописывается потом в карточке.
 *
 * Файлы: выбор, перетаскивание и вставка из буфера (Ctrl+V) — скриншот
 * попадает в задачу без промежуточного «сохранить на диск».
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Loader2, Paperclip, Plus, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import * as tasksService from '@/services/tasksService'
import { listSpaceObjects } from '@/services/spaceObjectsService'
import { PRIORITY_LABEL, fileSize } from './taskWords'

export function NewTaskDialog({ companyId, onCreated, defaultObjectId }: {
  companyId: string
  onCreated: (taskId: string) => void
  defaultObjectId?: string
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [typeId, setTypeId] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [objectId, setObjectId] = useState(defaultObjectId ?? '')
  const [priority, setPriority] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [labels, setLabels] = useState<string[]>([])
  const [files, setFiles] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const typesQ = useQuery({
    queryKey: ['task-types', companyId],
    queryFn: () => tasksService.listTaskTypes(companyId),
    enabled: open, staleTime: 5 * 60 * 1000,
  })
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    enabled: open, staleTime: 5 * 60 * 1000,
  })
  const objectsQ = useQuery({
    queryKey: ['space-objects', companyId],
    queryFn: () => listSpaceObjects(companyId),
    enabled: open, staleTime: 5 * 60 * 1000,
  })
  const labelsQ = useQuery({
    queryKey: ['task-labels', companyId],
    queryFn: () => tasksService.listTaskLabels(companyId),
    enabled: open, staleTime: 5 * 60 * 1000,
  })
  const type = (typesQ.data?.types ?? []).find((t) => t.id === typeId)

  const reset = () => {
    setTitle(''); setDescription(''); setTypeId(''); setAssigneeId('')
    setObjectId(defaultObjectId ?? ''); setPriority(''); setDueAt('')
    setLabels([]); setFiles([])
  }

  const addFiles = (list: FileList | File[] | null) => {
    const picked = Array.from(list ?? [])
    if (picked.length) setFiles((f) => [...f, ...picked])
  }

  const create = useMutation({
    mutationFn: async () => {
      const task = await tasksService.createTask({
        companyId, title: title.trim(),
        description: description.trim() || undefined,
        typeId: typeId || undefined, assigneeId: assigneeId || undefined,
        objectId: objectId || undefined, priority: priority || undefined,
        // Срок вводят датой — на сервер уходит начало суток в поясе браузера.
        dueAt: dueAt ? new Date(`${dueAt}T00:00`).toISOString() : undefined,
      })
      // Файлы и метки цепляются после создания: задача должна существовать,
      // чтобы к ней было что прикреплять. Неудача здесь не отменяет задачу —
      // она уже поставлена, и терять её из-за сорвавшейся загрузки нельзя.
      for (const id of labels) {
        await tasksService.taskAction(task.id, { companyId, addLabelId: id })
          .catch(() => toast.warning('Метка не прикрепилась — поставьте её в карточке'))
      }
      for (const file of files) {
        await tasksService.uploadTaskFile(task.id, companyId, file)
          .catch(() => toast.warning(`Файл «${file.name}» не загрузился — приложите в карточке`))
      }
      return task
    },
    onSuccess: (task) => {
      toast.success(`Задача №${task.number} поставлена`)
      qc.invalidateQueries({ queryKey: ['tasks'] })
      setOpen(false); reset()
      onCreated(task.id)
    },
    onError: (e) => toast.error(`Не удалось поставить задачу: ${(e as Error).message}`),
  })

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) reset() }}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" className="h-9">
          <Plus className="mr-1.5 h-3.5 w-3.5" />Поставить подробно
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader><DialogTitle>Новая задача</DialogTitle></DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Наименование</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus
              placeholder="Коротко: что нужно сделать" maxLength={300} />
          </div>

          <div className="space-y-1.5">
            <Label>Описание</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)}
              rows={4} maxLength={8000}
              placeholder="Подробности: что именно, где, к какому результату. Скриншот можно вставить прямо сюда — Ctrl+V"
              // Вставка изображения из буфера: скриншот попадает в задачу без
              // промежуточного «сохранить на диск», как в чате.
              onPaste={(e) => {
                const imgs = Array.from(e.clipboardData.files).filter(
                  (f) => f.type.startsWith('image/'))
                if (imgs.length) {
                  e.preventDefault()
                  addFiles(imgs)
                  toast.success(imgs.length === 1
                    ? 'Скриншот приложен к задаче' : `Приложено изображений: ${imgs.length}`)
                }
              }} />
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label>Тип</Label>
              <Select value={typeId || 'none'}
                onValueChange={(v) => setTypeId(v === 'none' ? '' : v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Поручение (без типа)</SelectItem>
                  {(typesQ.data?.types ?? []).filter((t) => t.is_active).map((t) => (
                    <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {type && (
                <p className="text-[11px] text-muted-foreground">
                  {type.route.map((s) => s.name).join(' → ')}
                  {type.due_days != null && ` · срок ${type.due_days} дн.`}
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label>Исполнитель</Label>
              <Select value={assigneeId || 'none'}
                onValueChange={(v) => setAssigneeId(v === 'none' ? '' : v)}>
                <SelectTrigger>
                  <SelectValue placeholder={peopleQ.isLoading ? 'Загрузка…' : 'Не назначен'} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Не назначен</SelectItem>
                  {(peopleQ.data?.people ?? []).map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Срок</Label>
              <Input type="date" value={dueAt} onChange={(e) => setDueAt(e.target.value)} />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Объект</Label>
              <Select value={objectId || 'none'}
                onValueChange={(v) => setObjectId(v === 'none' ? '' : v)}>
                <SelectTrigger><SelectValue placeholder="Без объекта" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Без объекта</SelectItem>
                  {(objectsQ.data ?? []).filter((o) => o.status !== 'closed').map((o) => (
                    <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Срочность</Label>
              <Select value={priority || 'default'}
                onValueChange={(v) => setPriority(v === 'default' ? '' : v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">
                    {type ? `Как у типа (${PRIORITY_LABEL[type.default_priority]})` : 'Обычная'}
                  </SelectItem>
                  {Object.entries(PRIORITY_LABEL).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {(labelsQ.data?.labels ?? []).length > 0 && (
            <div className="space-y-1.5">
              <Label>Метки</Label>
              <div className="flex flex-wrap gap-1">
                {(labelsQ.data?.labels ?? []).map((l) => (
                  <button key={l.id} type="button"
                    onClick={() => setLabels((cur) => cur.includes(l.id)
                      ? cur.filter((x) => x !== l.id) : [...cur, l.id])}
                    className={cn('rounded border px-1.5 py-0.5 text-[11px] transition-colors',
                      labels.includes(l.id)
                        ? 'border-primary/40 bg-primary/10 text-primary'
                        : 'text-muted-foreground hover:bg-muted/60')}>
                    {l.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Файлы и скриншоты: выбор, перетаскивание, вставка из буфера. */}
          <div className="space-y-1.5">
            <Label>Файлы и скриншоты</Label>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault(); setDragOver(false); addFiles(e.dataTransfer.files)
              }}
              className={cn('rounded-lg border border-dashed px-3 py-4 text-center transition-colors',
                dragOver ? 'border-primary bg-primary/5' : 'border-border')}>
              <input ref={fileRef} type="file" multiple className="hidden"
                onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
              <div className="flex flex-col items-center gap-1.5 text-xs text-muted-foreground">
                <Upload className="h-4 w-4" />
                <span>Перетащите файлы сюда или</span>
                <span className="flex gap-2">
                  <Button type="button" variant="outline" size="sm" className="h-7"
                    onClick={() => fileRef.current?.click()}>
                    <Paperclip className="mr-1.5 h-3 w-3" />Выбрать файлы
                  </Button>
                </span>
                <span className="flex items-center gap-1 text-[11px]">
                  <ImagePlus className="h-3 w-3" />
                  скриншот — Ctrl+V прямо в описание
                </span>
              </div>
            </div>
            {files.length > 0 && (
              <div className="space-y-1">
                {files.map((f, i) => (
                  <div key={`${f.name}-${i}`} className="flex items-center gap-2 text-xs">
                    <Paperclip className="h-3 w-3 shrink-0 text-muted-foreground" />
                    <span className="truncate">{f.name || 'скриншот.png'}</span>
                    <span className="shrink-0 text-muted-foreground">{fileSize(f.size)}</span>
                    <Button variant="ghost" size="sm" className="ml-auto h-6 px-1.5"
                      aria-label="Убрать файл"
                      onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))}>
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button disabled={title.trim().length < 3 || create.isPending}
            onClick={() => create.mutate()}>
            {create.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Поставить задачу
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default NewTaskDialog
