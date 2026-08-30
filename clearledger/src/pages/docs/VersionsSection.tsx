/**
 * Настройка версий «Трека» (этап 10 трекерного контура).
 *
 * Версия отвечает заявителю на вопрос «когда это будет исправлено»: поручение
 * закрывается с версией, версия выпускается — и номер уезжает в заявку сам.
 *
 * Версия принадлежит проекту, поэтому экран начинается с выбора проекта: «1.4»
 * у фронта и «1.4» у бэкенда — разные вещи. Версия не удаляется, а отменяется:
 * её номер уже назван заявителю, и стереть его задним числом значит соврать.
 */
import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ChevronDown, ChevronRight, Copy, Loader2, Pencil, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { QueryError } from '@/components/common/QueryError'
import * as tasksService from '@/services/tasksService'
import { taskKey, type TaskVersion } from '@/services/tasksService'
import { cn } from '@/lib/utils'

const STATE_LABEL: Record<TaskVersion['state'], string> = {
  open: 'набирается', released: 'выпущена', cancelled: 'отменена',
}

export function VersionsSection({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [projectId, setProjectId] = useState('')
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<TaskVersion | null>(null)
  const [opened, setOpened] = useState<string | null>(null)

  const projectsQ = useQuery({
    queryKey: ['task-projects', companyId, false],
    queryFn: () => tasksService.listTaskProjects(companyId),
  })
  const projects = projectsQ.data?.projects ?? []
  // Пока проект не выбран, показываем первый: экран без выбора выглядит пустым
  // и человек решает, что версий нет вовсе.
  const current = projectId || projects[0]?.id || ''

  const q = useQuery({
    queryKey: ['task-versions', companyId, current],
    queryFn: () => tasksService.listTaskVersions(companyId, current),
    enabled: !!current,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['task-versions'] })

  const setState = useMutation({
    mutationFn: (v: { id: string; state: TaskVersion['state'] }) =>
      tasksService.updateTaskVersion(v.id, { companyId, state: v.state }),
    onSuccess: () => { refresh(); toast.success('Готово') },
    onError: (e) => toast.error((e as Error).message),
  })

  const versions = q.data?.versions ?? []

  if (projectsQ.isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Загрузка…
      </div>
    )
  }
  if (projects.length === 0) {
    return (
      <div className="space-y-3 p-4">
        <h1 className="text-lg font-semibold">Версии</h1>
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Версии живут на проекте, а проектов пока нет. Заведите первый в разделе
          «Проекты» — тогда у него появятся версии вида{' '}
          <span className="font-mono">1.4.2</span>.
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Версии</h1>
          <p className="mt-0.5 max-w-2xl text-xs text-muted-foreground">
            «Исправлено в <span className="font-mono">1.4.2</span>» — то, чего ждёт
            заявитель. Задача закрывается с версией, версия выпускается — и её номер
            уезжает в заявку Поддержки сам. Состав версии годится списком изменений.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={current} onValueChange={(v) => { setProjectId(v); setOpened(null) }}>
            <SelectTrigger className="h-8 w-[220px] text-xs">
              <SelectValue placeholder="Проект" />
            </SelectTrigger>
            <SelectContent>
              {projects.map((p) => (
                <SelectItem key={p.id} value={p.id}>{p.code} · {p.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button size="sm" className="h-8" onClick={() => { setEditing(null); setAdding(true) }}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />Завести версию
          </Button>
        </div>
      </div>

      {(adding || editing) && (
        <VersionEditor companyId={companyId} projectId={current} version={editing}
          onClose={() => { setAdding(false); setEditing(null) }}
          onSaved={() => { setAdding(false); setEditing(null); refresh() }} />
      )}

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка версий…
        </div>
      ) : q.isError ? (
        <QueryError message="Не удалось загрузить версии" error={q.error} onRetry={() => void q.refetch()} />
      ) : versions.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          В этом проекте версий пока нет. Заведите ближайшую — например{' '}
          <span className="font-mono">1.4.2</span>: задачи можно будет закрывать в неё,
          а заявителю отвечать номером, а не «скоро».
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="w-8 px-2 py-2" />
                <th className="px-3 py-2 text-left font-medium">Версия</th>
                <th className="px-3 py-2 text-left font-medium">Состояние</th>
                <th className="px-3 py-2 text-left font-medium">Выпуск</th>
                <th className="px-3 py-2 text-right font-medium">Сделано</th>
                <th className="px-3 py-2 text-right font-medium">Осталось</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <Fragment key={v.id}>
                  <tr className={cn('border-t', v.state === 'cancelled' && 'opacity-60')}>
                    <td className="px-2 py-2">
                      <Button size="sm" variant="ghost" className="h-7 w-7 px-0"
                        title="Состав версии"
                        onClick={() => setOpened(opened === v.id ? null : v.id)}>
                        {opened === v.id
                          ? <ChevronDown className="h-3.5 w-3.5" />
                          : <ChevronRight className="h-3.5 w-3.5" />}
                      </Button>
                    </td>
                    <td className="px-3 py-2">
                      <span className="font-mono font-semibold">{v.name}</span>
                      {v.description && (
                        <div className="text-xs text-muted-foreground">{v.description}</div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={v.state === 'released' ? 'default' : 'outline'}
                        className="h-5 px-1.5 text-xs">
                        {STATE_LABEL[v.state]}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {v.released_on ?? '—'}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{v.fixed || '—'}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{v.open || '—'}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">
                      {v.state === 'open' && (
                        <Button size="sm" variant="ghost" className="h-7 px-2"
                          disabled={setState.isPending} title="Выпустить"
                          onClick={() => setState.mutate({ id: v.id, state: 'released' })}>
                          <CheckCircle2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" className="h-7 px-2"
                        onClick={() => { setAdding(false); setEditing(v) }}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      {v.state !== 'cancelled' && (
                        <Button size="sm" variant="ghost" className="h-7 px-2"
                          disabled={setState.isPending} title="Отменить версию"
                          onClick={() => setState.mutate({ id: v.id, state: 'cancelled' })}>
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </td>
                  </tr>
                  {opened === v.id && (
                    <tr className="border-t bg-muted/20">
                      <td />
                      <td colSpan={6} className="px-3 py-3">
                        <VersionBody versionId={v.id} companyId={companyId} name={v.name} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** Состав версии: что вошло, что висит, что в ней обнаружено. */
function VersionBody({ versionId, companyId, name }: {
  versionId: string; companyId: string; name: string
}) {
  const q = useQuery({
    queryKey: ['task-version-summary', versionId],
    queryFn: () => tasksService.taskVersionSummary(versionId, companyId),
  })

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />Собираем состав…
      </div>
    )
  }
  if (q.isError) {
    return <QueryError message="Состав версии не загрузился" error={q.error} onRetry={() => void q.refetch()} />
  }

  const { done = [], left = [], found = [] } = q.data ?? {}
  // Черновик списка изменений: ровно то, что уходит в описание релиза и в ответ
  // заявителю. Отдаём текстом, а не разметкой — его вставляют куда угодно.
  const changelog = [`Версия ${name}`, ...done.map((t) => `— ${taskKey(t)} ${t.title}`)].join('\n')

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          Вошло: {done.length} · осталось: {left.length}
          {found.length > 0 && ` · обнаружено в версии: ${found.length}`}
        </span>
        <Button size="sm" variant="ghost" className="h-7 text-xs"
          disabled={done.length === 0}
          onClick={() => {
            void navigator.clipboard.writeText(changelog)
            toast.success('Список изменений скопирован')
          }}>
          <Copy className="mr-1.5 h-3.5 w-3.5" />Список изменений
        </Button>
      </div>
      <Column title="Вошло в версию" tasks={done} empty="Пока ничего не закрыто." />
      <Column title="Осталось" tasks={left} empty="Всё закрыто — версию можно выпускать." />
      {found.length > 0 && <Column title="Обнаружено в этой версии" tasks={found} empty="" />}
    </div>
  )
}

function Column({ title, tasks, empty }: {
  title: string; tasks: tasksService.SpaceTask[]; empty: string
}) {
  return (
    <div className="space-y-1">
      <div className="text-xs font-semibold">{title}</div>
      {tasks.length === 0 ? (
        <div className="text-xs text-muted-foreground">{empty}</div>
      ) : (
        <ul className="space-y-0.5">
          {tasks.map((t) => (
            <li key={t.id} className="text-xs">
              <span className="font-mono text-muted-foreground">{taskKey(t)}</span>{' '}
              {t.title}
              {t.assignee && <span className="text-muted-foreground"> · {t.assignee}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function VersionEditor({ companyId, projectId, version, onClose, onSaved }: {
  companyId: string
  projectId: string
  version: TaskVersion | null
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(version?.name ?? '')
  const [description, setDescription] = useState(version?.description ?? '')
  const [releasedOn, setReleasedOn] = useState(version?.released_on ?? '')

  const save = useMutation({
    mutationFn: () => (version
      ? tasksService.updateTaskVersion(version.id, {
        companyId, name: name.trim(), description: description.trim(),
        releasedOn: releasedOn || undefined,
      })
      : tasksService.createTaskVersion({
        companyId, projectId, name: name.trim(),
        description: description.trim() || undefined, releasedOn: releasedOn || undefined,
      })),
    onSuccess: () => { toast.success(version ? 'Версия сохранена' : 'Версия заведена'); onSaved() },
    onError: (e) => toast.error((e as Error).message),
  })

  return (
    <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          {version ? `Версия ${version.name}` : 'Новая версия'}
        </h2>
        <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-[160px_180px_1fr]">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Имя</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={40}
            placeholder="1.4.2" className="h-8 font-mono text-xs" />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Выпуск</label>
          {/* Дата, а не отметка времени: релиз называют днём. Нативное поле —
              календарь браузера уже умеет всё, что здесь нужно. */}
          <Input type="date" value={releasedOn} className="h-8 text-xs"
            onChange={(e) => setReleasedOn(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Что в ней</label>
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)}
            rows={1} className="text-xs" placeholder="Необязательно" />
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" className="h-8" onClick={onClose}>Отмена</Button>
        <Button size="sm" className="h-8" disabled={!name.trim() || save.isPending}
          onClick={() => save.mutate()}>
          {save.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
          {version ? 'Сохранить' : 'Завести'}
        </Button>
      </div>
    </div>
  )
}
