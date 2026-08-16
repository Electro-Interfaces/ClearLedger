/**
 * Лист ознакомления: кому документ доведён и кто расписался.
 *
 * Отдельно от согласования намеренно. Виза это «не возражаю» до подписания,
 * ознакомление — «прочитал» после. Приказ, с которым никого не ознакомили, не
 * работает, а вопрос «а он знал?» должен решаться списком, а не памятью.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleDashed, UserPlus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/contexts/AuthContext'
import * as docsService from '@/services/docsService'
import * as tasksService from '@/services/tasksService'
import { listDepartments } from '@/services/departmentsService'
import type { DocDetails } from '@/services/docsService'

export function DocAcquaintTab({ doc, companyId, onChanged }: {
  doc: DocDetails
  companyId: string
  onChanged: () => void
}) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [picked, setPicked] = useState<string[]>([])
  const [departmentId, setDepartmentId] = useState('')
  const [dueDate, setDueDate] = useState('')

  // Люди пространства — тот же справочник, что у поручений: второго списка
  // сотрудников в одном продукте быть не должно.
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const departmentsQ = useQuery({
    queryKey: ['departments', companyId],
    queryFn: () => listDepartments(companyId),
    staleTime: 5 * 60 * 1000,
  })

  const add = useMutation({
    mutationFn: () => docsService.addAcquaint(companyId, doc.id, {
      user_ids: picked,
      department_id: departmentId || null,
      due_at: dueDate ? `${dueDate}T23:59:00` : null,
    }),
    onSuccess: (r) => {
      toast.success(r.added ? `Направлено: ${r.added}` : 'Эти люди уже в листе')
      setPicked([])
      setDepartmentId('')
      setDueDate('')
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const read = useMutation({
    mutationFn: () => docsService.markAcquainted(companyId, doc.id),
    onSuccess: () => {
      toast.success('Отметка поставлена')
      qc.invalidateQueries({ queryKey: ['docs-my-acquaints', companyId] })
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const people = peopleQ.data?.people ?? []
  const departments = departmentsQ.data ?? []
  const nameOf = (id: string) =>
    people.find((p) => p.id === id)?.name ?? 'участник пространства'

  const rows = doc.acquaints ?? []
  const mine = rows.find((a) => a.user_id === user?.id)
  const done = rows.filter((a) => a.status === 'done').length

  return (
    <div className="space-y-3 pt-3">
      {mine && mine.status === 'pending' && (
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="text-sm">
            Документ направлен вам на ознакомление
            {mine.due_at ? ` · до ${mine.due_at.slice(0, 10)}` : ''}
          </div>
          <Button size="sm" onClick={() => read.mutate()} disabled={read.isPending}>
            Я ознакомлен
          </Button>
        </Card>
      )}

      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-medium">Лист ознакомления</div>
          {rows.length > 0 && (
            <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs">
              расписались {done} из {rows.length}
            </span>
          )}
        </div>
        <div className="mt-2 space-y-1">
          {rows.map((a) => (
            <div key={a.id} className="flex items-start gap-2 text-[13px]">
              {a.status === 'done'
                ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-600" />
                : <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
              <div className="min-w-0">
                <span>{nameOf(a.user_id)}</span>
                <span className="text-muted-foreground">
                  {a.status === 'done'
                    ? ` · ознакомлен ${(a.read_at ?? '').slice(0, 10)}`
                    : ' · ждём'}
                </span>
                {a.note && <div className="text-muted-foreground">{a.note}</div>}
              </div>
            </div>
          ))}
          {rows.length === 0 && (
            <div className="py-3 text-sm text-muted-foreground">
              Никого не знакомили. Приказ, доведённый только до автора, не работает.
            </div>
          )}
        </div>
      </Card>

      <Card className="flex flex-col gap-3 p-4">
        <Label className="text-xs">Направить на ознакомление</Label>
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
                <option key={department.id} value={department.id}>{department.name}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="acquaint-due" className="text-xs text-muted-foreground">
              Ознакомиться до
            </Label>
            <input id="acquaint-due" type="date" value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm" />
          </div>
        </div>
        <Label htmlFor="acquaint-people" className="text-xs text-muted-foreground">
          Или отдельные люди
        </Label>
        <select id="acquaint-people" multiple value={picked}
          size={Math.min(6, Math.max(3, people.length))}
          onChange={(e) => setPicked(
            Array.from(e.target.selectedOptions).map((o) => o.value))}
          className="w-full rounded-md border border-input bg-background p-2 text-sm">
          {people.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <Button size="sm" variant="outline"
          disabled={(!picked.length && !departmentId) || add.isPending}
          onClick={() => add.mutate()}>
          <UserPlus className="mr-1.5 h-4 w-4" />Направить
        </Button>
      </Card>
    </div>
  )
}

export default DocAcquaintTab
