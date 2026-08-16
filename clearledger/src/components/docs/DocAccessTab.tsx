import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { useCanManage } from '@/hooks/useCanManage'
import { listDepartments } from '@/services/departmentsService'
import { listRoles } from '@/services/roleService'
import * as tasksService from '@/services/tasksService'
import * as docsService from '@/services/docsService'
import type { DocDetails } from '@/services/docsService'

const PERMISSIONS = [
  ['read', 'Чтение'], ['edit', 'Правка'], ['approve', 'Виза'], ['sign', 'Подписание'],
] as const

export function DocAccessTab({ doc, companyId }: { doc: DocDetails; companyId: string }) {
  const queryClient = useQueryClient()
  const { canManage } = useCanManage()
  const [scopeType, setScopeType] = useState<'doc' | 'kind'>('doc')
  const [subjectType, setSubjectType] = useState<'user' | 'role' | 'department'>('user')
  const [subjectId, setSubjectId] = useState('')
  const [permissions, setPermissions] = useState<string[]>(['read'])

  const grantsQuery = useQuery({
    queryKey: ['doc-access', companyId, doc.id],
    queryFn: () => docsService.listAccessGrants(companyId, doc.id),
  })
  const peopleQuery = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const rolesQuery = useQuery({
    queryKey: ['company-roles', companyId],
    queryFn: () => listRoles(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const departmentsQuery = useQuery({
    queryKey: ['departments', companyId],
    queryFn: () => listDepartments(companyId),
    staleTime: 5 * 60 * 1000,
  })

  const subjects = useMemo(() => {
    if (subjectType === 'role') return rolesQuery.data ?? []
    if (subjectType === 'department') return departmentsQuery.data ?? []
    return peopleQuery.data?.people ?? []
  }, [subjectType, peopleQuery.data, rolesQuery.data, departmentsQuery.data])

  const refresh = () => queryClient.invalidateQueries({
    queryKey: ['doc-access', companyId, doc.id],
  })
  const save = useMutation({
    mutationFn: () => docsService.saveAccessGrant(companyId, {
      scope_type: scopeType,
      scope_id: scopeType === 'doc' ? doc.id : doc.kind_id,
      subject_type: subjectType,
      subject_id: subjectId,
      permissions,
    }),
    onSuccess: () => {
      toast.success('Права сохранены')
      setSubjectId('')
      refresh()
    },
    onError: (error) => toast.error((error as Error).message),
  })
  const remove = useMutation({
    mutationFn: (id: string) => docsService.deleteAccessGrant(companyId, id),
    onSuccess: () => refresh(),
    onError: (error) => toast.error((error as Error).message),
  })

  const toggle = (permission: string, checked: boolean) => setPermissions((current) => (
    checked ? [...new Set([...current, permission])] : current.filter((value) => value !== permission)
  ))

  return (
    <div className="flex flex-col gap-3 pt-3">
      <Card>
        <CardHeader>
          <CardTitle>Права на документ</CardTitle>
          <CardDescription>
            Для закрытого документа доступ получают автор, ответственный, подписант и строки ниже.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {(grantsQuery.data ?? []).map((grant) => (
            <div key={grant.id}
              className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 last:border-0">
              <div>
                <div className="text-sm font-medium">{grant.subject_name || 'Получатель удалён'}</div>
                <div className="text-xs text-muted-foreground">
                  {grant.inherited ? 'Правило вида документа' : 'Правило карточки'} ·{' '}
                  {grant.permissions.map((permission) => (
                    PERMISSIONS.find(([key]) => key === permission)?.[1] ?? permission
                  )).join(', ')}
                </div>
              </div>
              {canManage && (
                <Button size="icon" variant="ghost" aria-label="Удалить правило"
                  onClick={() => remove.mutate(grant.id)} disabled={remove.isPending}>
                  <Trash2 />
                </Button>
              )}
            </div>
          ))}
          {!grantsQuery.isLoading && !grantsQuery.data?.length && (
            <p className="py-3 text-sm text-muted-foreground">Отдельных правил пока нет.</p>
          )}
        </CardContent>
      </Card>

      {canManage && <Card>
        <CardHeader>
          <CardTitle>Добавить правило</CardTitle>
          <CardDescription>Правило вида действует на все документы этого вида.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Область
              <select value={scopeType} onChange={(event) => setScopeType(
                event.target.value as 'doc' | 'kind')}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground">
                <option value="doc">Этот документ</option>
                <option value="kind">Вид «{doc.kind_name}»</option>
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Кому
              <select value={subjectType} onChange={(event) => {
                setSubjectType(event.target.value as 'user' | 'role' | 'department')
                setSubjectId('')
              }} className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground">
                <option value="user">Человеку</option>
                <option value="role">Роли</option>
                <option value="department">Подразделению</option>
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Получатель
              <select value={subjectId} onChange={(event) => setSubjectId(event.target.value)}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground">
                <option value="">Выберите</option>
                {subjects.map((subject) => (
                  <option key={subject.id} value={subject.id}>{subject.name}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="flex flex-wrap gap-4">
            {PERMISSIONS.map(([key, label]) => (
              <Label key={key} className="flex items-center gap-2 text-sm">
                <Checkbox checked={permissions.includes(key)}
                  onCheckedChange={(checked) => toggle(key, checked === true)} />
                {label}
              </Label>
            ))}
          </div>
          <Button size="sm" className="self-start" disabled={
            !subjectId || !permissions.length || save.isPending
          } onClick={() => save.mutate()}>
            <ShieldCheck data-icon="inline-start" />Добавить правило
          </Button>
        </CardContent>
      </Card>}
    </div>
  )
}

export default DocAccessTab
