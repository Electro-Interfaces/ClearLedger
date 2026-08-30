/**
 * Настройка проектов «Трека».
 *
 * Проект — контейнер работы со своим номером (`TF-42`), своими типами задач и
 * своим составом. Заведён 22.08.2026 под трекерный контур: без проекта не
 * собирается ни бэклог, ни релиз — всё лежит одной кучей на пространство.
 *
 * Код проекта не редактируется после создания: он уже стоит в номерах задач и в
 * переписке, и его смена превратила бы ссылку из чужого письма в пустое место.
 * Проект не удаляется, а уходит в архив — работа по нему остаётся историей.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, Loader2, Pencil, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { QueryError } from '@/components/common/QueryError'
import * as tasksService from '@/services/tasksService'
import type { TaskProject } from '@/services/tasksService'
import { cn } from '@/lib/utils'

export function ProjectsSection({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [showArchived, setShowArchived] = useState(false)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<TaskProject | null>(null)

  const q = useQuery({
    queryKey: ['task-projects', companyId, showArchived],
    queryFn: () => tasksService.listTaskProjects(companyId, showArchived),
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['task-projects'] })

  const archive = useMutation({
    mutationFn: (p: TaskProject) =>
      tasksService.updateTaskProject(p.id, { companyId, isArchived: !p.is_archived }),
    onSuccess: () => { refresh(); toast.success('Готово') },
    onError: (e) => toast.error((e as Error).message),
  })

  const projects = q.data?.projects ?? []

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Проекты</h1>
          <p className="mt-0.5 max-w-2xl text-xs text-muted-foreground">
            Проект собирает работу вокруг продукта или направления: задачи получают
            свой номер вида <span className="font-mono">TF-42</span>, у проекта могут
            быть собственные типы задач с маршрутами. Код в номере не меняется — он
            уже разошёлся по переписке и коммитам.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" className="h-8 text-xs"
            onClick={() => setShowArchived((v) => !v)}>
            {showArchived ? 'Скрыть архив' : 'Показать архив'}
          </Button>
          <Button size="sm" className="h-8" onClick={() => { setEditing(null); setAdding(true) }}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />Завести проект
          </Button>
        </div>
      </div>

      {(adding || editing) && (
        <ProjectEditor companyId={companyId} project={editing}
          onClose={() => { setAdding(false); setEditing(null) }}
          onSaved={() => { setAdding(false); setEditing(null); refresh() }} />
      )}

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка проектов…
        </div>
      ) : q.isError ? (
        <QueryError message="Не удалось загрузить проекты" error={q.error} onRetry={() => void q.refetch()} />
      ) : projects.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Проектов пока нет. Заведите первый — например <span className="font-mono">TF</span>{' '}
          «TradeFrame»: задачи в нём получат номера {' '}
          <span className="font-mono">TF-1</span>, <span className="font-mono">TF-2</span> и так далее.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Код</th>
                <th className="px-3 py-2 text-left font-medium">Название</th>
                <th className="px-3 py-2 text-right font-medium">В работе</th>
                <th className="px-3 py-2 text-right font-medium">Всего</th>
                <th className="px-3 py-2 text-right font-medium">Последний номер</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className={cn('border-t', p.is_archived && 'opacity-60')}>
                  <td className="px-3 py-2">
                    <span className="font-mono font-semibold">{p.code}</span>
                    {p.is_archived && (
                      <Badge variant="outline" className="ml-2 h-5 px-1.5 text-xs">архив</Badge>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {p.name}
                    {p.description && (
                      <div className="text-xs text-muted-foreground">{p.description}</div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{p.open || '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{p.tasks || '—'}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-muted-foreground">
                    {p.counter ? `${p.code}-${p.counter}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Button size="sm" variant="ghost" className="h-7 px-2"
                      onClick={() => { setAdding(false); setEditing(p) }}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="sm" variant="ghost" className="h-7 px-2"
                      disabled={archive.isPending}
                      title={p.is_archived ? 'Вернуть из архива' : 'В архив'}
                      onClick={() => archive.mutate(p)}>
                      {p.is_archived
                        ? <ArchiveRestore className="h-3.5 w-3.5" />
                        : <Archive className="h-3.5 w-3.5" />}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function ProjectEditor({ companyId, project, onClose, onSaved }: {
  companyId: string
  project: TaskProject | null
  onClose: () => void
  onSaved: () => void
}) {
  const [code, setCode] = useState(project?.code ?? '')
  const [name, setName] = useState(project?.name ?? '')
  const [description, setDescription] = useState(project?.description ?? '')

  const save = useMutation({
    mutationFn: () => (project
      ? tasksService.updateTaskProject(project.id, {
        companyId, name: name.trim(), description: description.trim(),
      })
      : tasksService.createTaskProject({
        companyId, code: code.trim().toUpperCase(), name: name.trim(),
        description: description.trim() || undefined,
      })),
    onSuccess: () => { toast.success(project ? 'Проект сохранён' : 'Проект заведён'); onSaved() },
    onError: (e) => toast.error((e as Error).message),
  })

  // Код нужен только при создании: латиница в верхнем регистре, потому что он
  // идёт в номер задачи и в коммит — `TF-42` читается, `тф-42` нет.
  const codeBad = !project && !/^[A-Z][A-Z0-9]{1,9}$/.test(code.trim().toUpperCase())

  return (
    <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          {project ? `Проект ${project.code}` : 'Новый проект'}
        </h2>
        <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-[140px_1fr]">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Код</label>
          <Input value={project?.code ?? code} disabled={!!project} maxLength={10}
            placeholder="TF" className="h-8 font-mono text-xs uppercase"
            onChange={(e) => setCode(e.target.value.toUpperCase())} />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Название</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={150}
            placeholder="TradeFrame" className="h-8 text-xs" />
        </div>
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Чем занимается</label>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)}
          rows={2} className="text-xs" placeholder="Необязательно" />
      </div>
      {codeBad && code.trim() !== '' && (
        <p className="text-xs text-destructive">
          Код — от двух до десяти латинских заглавных букв и цифр, первая буква.
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" className="h-8" onClick={onClose}>Отмена</Button>
        <Button size="sm" className="h-8" disabled={!name.trim() || codeBad || save.isPending}
          onClick={() => save.mutate()}>
          {save.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
          {project ? 'Сохранить' : 'Завести'}
        </Button>
      </div>
    </div>
  )
}
