/**
 * Лист ознакомления: кому документ доведён и кто расписался.
 *
 * Отдельно от согласования намеренно. Виза это «не возражаю» до подписания,
 * ознакомление — «прочитал» после. Приказ, с которым никого не ознакомили, не
 * работает, а вопрос «а он знал?» должен решаться списком, а не памятью.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, CircleDashed, RotateCw, Search, UserPlus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/contexts/AuthContext'
import * as docsService from '@/services/docsService'
import type { DocDetails } from '@/services/docsService'
import { formatDate } from '@/lib/formatDate'

function moscowToday(date: Date): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(date)
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${value.year}-${value.month}-${value.day}`
}

export function DocAcquaintTab({ doc, companyId, canEdit, onChanged }: {
  doc: DocDetails
  companyId: string
  canEdit: boolean
  onChanged: () => void
}) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [picked, setPicked] = useState<string[]>([])
  const [departmentId, setDepartmentId] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [search, setSearch] = useState('')
  const [renderedAt] = useState(() => Date.now())

  const subjectsQ = useQuery({
    queryKey: ['docs-acquaint-subjects', companyId],
    queryFn: () => docsService.acquaintSubjects(companyId),
    enabled: canEdit,
    staleTime: 5 * 60 * 1000,
  })

  const add = useMutation({
    mutationFn: () => docsService.addAcquaint(companyId, doc.id, {
      user_ids: picked,
      department_id: departmentId || null,
      due_at: dueDate ? `${dueDate}T23:59:59+03:00` : null,
    }),
    onSuccess: (r) => {
      const skipped = r.skipped ? `, пропущено без доступа: ${r.skipped}` : ''
      toast.success(r.added ? `Направлено: ${r.added}${skipped}` : 'Эти люди уже в листе')
      setPicked([])
      setDepartmentId('')
      setDueDate('')
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const read = useMutation({
    mutationFn: () => docsService.markAcquainted(companyId, doc.id, mine?.id),
    onSuccess: () => {
      toast.success('Отметка поставлена')
      qc.invalidateQueries({ queryKey: ['docs-my-acquaints', companyId] })
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const people = subjectsQ.data?.people ?? []
  const departments = subjectsQ.data?.departments ?? []
  const visiblePeople = people.filter((person) => person.name.toLocaleLowerCase('ru')
    .includes(search.trim().toLocaleLowerCase('ru')))
  const nameOf = (id: string) =>
    people.find((p) => p.id === id)?.name ?? 'участник пространства'

  const rows = doc.acquaints ?? []
  const activeRows = rows.filter((row) => row.status !== 'superseded')
  const mine = activeRows.find((a) => a.user_id === user?.id && a.status === 'pending')
  const done = activeRows.filter((a) => a.status === 'done').length

  return (
    <div className="space-y-3 pt-3">
      {mine && mine.status === 'pending' && (
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="text-sm">
            Документ направлен вам на ознакомление
            {mine.due_at ? ` · до ${formatDate(mine.due_at)}` : ''}
          </div>
          <Button size="sm" onClick={() => read.mutate()} disabled={read.isPending}>
            Я ознакомлен
          </Button>
        </Card>
      )}

      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-medium">Лист ознакомления</div>
          {activeRows.length > 0 && (
            <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs">
              расписались {done} из {activeRows.length}
            </span>
          )}
        </div>
        <div className="mt-2 space-y-1">
          {rows.map((a) => {
            const overdue = a.status === 'pending' && !!a.due_at
              && new Date(a.due_at).getTime() < renderedAt
            return <div key={a.id} className={`flex items-start gap-2 text-[13px] ${
              a.status === 'superseded' ? 'opacity-55' : ''}`}>
              {a.status === 'done'
                ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-600" />
                : <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
              <div className="min-w-0">
                <span>{nameOf(a.user_id)}</span>
                <span className="text-muted-foreground">
                  {a.status === 'done'
                    ? ` · ознакомлен ${formatDate(a.read_at ?? '')}`
                    : a.status === 'superseded' ? ' · заменено новой редакцией'
                    : overdue ? ' · просрочено' : ' · ждём'}
                </span>
                <div className={overdue ? 'text-destructive' : 'text-muted-foreground'}>
                  {a.revision ? `редакция ${a.revision}` : 'редакция без номера'}
                  {a.reason_name ? ` · ${a.reason_name}` : ''}
                  {a.due_at ? ` · срок ${formatDate(a.due_at)}` : ''}
                  {a.reminded_at ? ` · напомнили ${formatDate(a.reminded_at)}` : ''}
                </div>
                {a.reminder_error && (
                  <div className="text-destructive">
                    Напоминание не доставлено: {a.reminder_error}
                  </div>
                )}
                {a.note && <div className="text-muted-foreground">{a.note}</div>}
              </div>
            </div>
          })}
          {rows.length === 0 && (
            <div className="py-3 text-sm text-muted-foreground">
              Никого не знакомили. Приказ, доведённый только до автора, не работает.
            </div>
          )}
        </div>
      </Card>

      {canEdit && <Card className="flex flex-col gap-3 p-4">
        <Label className="text-xs">Направить на ознакомление</Label>
        {subjectsQ.isError && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/30 p-3 text-sm">
            <span className="flex items-center gap-2 text-destructive">
              <AlertCircle className="h-4 w-4" />Список получателей не загрузился
            </span>
            <Button size="sm" variant="outline" onClick={() => subjectsQ.refetch()}>
              <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
            </Button>
          </div>
        )}
        {subjectsQ.isLoading && <div className="text-sm text-muted-foreground">Загрузка получателей…</div>}
        {subjectsQ.isSuccess && people.length === 0 && (
          <div className="text-sm text-muted-foreground">
            Нет сотрудников с доступом к «Треку».
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="acquaint-department" className="text-xs text-muted-foreground">
              Подразделение целиком
            </Label>
            <select id="acquaint-department" value={departmentId}
              onChange={(e) => setDepartmentId(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm">
              <option value="">Не выбрано</option>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name} · {department.people}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="acquaint-due" className="text-xs text-muted-foreground">
              Ознакомиться до
            </Label>
            <input id="acquaint-due" type="date" value={dueDate}
              min={moscowToday(new Date(renderedAt))}
              onChange={(e) => setDueDate(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm" />
          </div>
        </div>
        <Label htmlFor="acquaint-search" className="text-xs text-muted-foreground">
          Или отдельные люди
        </Label>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input id="acquaint-search" value={search} onChange={(event) => setSearch(event.target.value)}
            placeholder="Найти сотрудника" className="pl-8" />
        </div>
        <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2">
          {visiblePeople.map((person) => (
            <label key={person.id} className="flex min-h-9 cursor-pointer items-center gap-2 rounded px-2 text-sm hover:bg-muted/60">
              <input type="checkbox" checked={picked.includes(person.id)}
                onChange={(event) => setPicked((current) => event.target.checked
                  ? [...current, person.id] : current.filter((id) => id !== person.id))} />
              <span>{person.name}</span>
            </label>
          ))}
          {subjectsQ.isSuccess && visiblePeople.length === 0 && (
            <div className="px-2 py-3 text-sm text-muted-foreground">Никого не найдено</div>
          )}
        </div>
        <Button size="sm" variant="outline"
          disabled={subjectsQ.isError || (!picked.length && !departmentId) || add.isPending}
          onClick={() => add.mutate()}>
          <UserPlus className="mr-1.5 h-4 w-4" />Направить
        </Button>
      </Card>}
    </div>
  )
}

export default DocAcquaintTab
