import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Loader2, RotateCw, ShieldCheck, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { useCanManage } from '@/hooks/useCanManage'
import * as docsService from '@/services/docsService'
import type { DocDetails } from '@/services/docsService'

const PERMISSIONS = [
  ['read', 'Чтение'], ['edit', 'Правка'],
  ['approve', 'Допуск к визе'], ['sign', 'Допуск к подписанию'],
] as const

export function DocAccessTab({ doc, companyId }: { doc: DocDetails; companyId: string }) {
  const queryClient = useQueryClient()
  const { canManage } = useCanManage()
  const canManageDoc = doc.can_manage_access
  const [scopeType, setScopeType] = useState<'doc' | 'kind'>('doc')
  const [subjectType, setSubjectType] = useState<'user' | 'role' | 'department'>('user')
  const [subjectId, setSubjectId] = useState('')
  const [permissions, setPermissions] = useState<string[]>(['read'])

  const grantsQuery = useQuery({
    queryKey: ['doc-access', companyId, doc.id],
    queryFn: () => docsService.listAccessGrants(companyId, doc.id),
  })
  const subjectsQuery = useQuery({
    queryKey: ['doc-access-subjects', companyId, doc.id],
    queryFn: () => docsService.listAccessSubjects(companyId, doc.id),
    staleTime: 5 * 60 * 1000,
    enabled: canManageDoc,
  })

  const subjects = useMemo(() => {
    if (subjectType === 'role') return subjectsQuery.data?.roles ?? []
    if (subjectType === 'department') return subjectsQuery.data?.departments ?? []
    return subjectsQuery.data?.people ?? []
  }, [subjectType, subjectsQuery.data])
  const currentGrant = useMemo(() => (grantsQuery.data ?? []).find((grant) => (
    grant.scope_type === scopeType
    && grant.subject_type === subjectType
    && grant.subject_id === subjectId
  )), [grantsQuery.data, scopeType, subjectId, subjectType])
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
    onSuccess: () => {
      toast.success('Правило удалено')
      refresh()
    },
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
            {canManageDoc
              ? 'Для закрытого документа доступ получают участники карточки и правила ниже. Администратор управляет правилами, но не читает документ автоматически.'
              : 'Показаны только правила, по которым карточка доступна вам.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {grantsQuery.isLoading && (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />Загружаем правила…
            </div>
          )}
          {grantsQuery.isError && (
            <div role="alert" className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm text-destructive">
              <span className="flex items-center gap-2">
                <AlertCircle className="h-4 w-4" />Правила не загрузились
              </span>
              <Button size="sm" variant="outline" onClick={() => grantsQuery.refetch()}>
                <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
              </Button>
            </div>
          )}
          {grantsQuery.isSuccess && grantsQuery.data.map((grant) => (
            <div key={grant.id}
              className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-2 last:border-0">
              <div>
                <div className="text-sm font-medium">{grant.subject_name || 'Получатель удалён'}</div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  <span>{grant.inherited ? 'Унаследовано от вида' : 'Правило карточки'}</span>
                  {grant.permissions.map((permission) => (
                    <span key={permission} className="rounded-full bg-muted px-2 py-0.5 text-foreground">
                      {PERMISSIONS.find(([key]) => key === permission)?.[1] ?? permission}
                    </span>
                  ))}
                </div>
              </div>
              {(grant.inherited ? canManage : canManageDoc) && (
                <ConfirmActionDialog
                  trigger={(
                    <Button size="icon" variant="ghost" aria-label="Удалить правило"
                      disabled={remove.isPending}>
                      <Trash2 />
                    </Button>
                  )}
                  title={grant.inherited ? 'Удалить правило вида?' : 'Удалить правило карточки?'}
                  description={grant.inherited
                    ? `Доступ изменится у всех документов вида «${doc.kind_name}».`
                    : `Доступ для «${grant.subject_name || 'получателя'}» будет отозван сразу.`}
                  confirmLabel="Удалить"
                  destructive
                  onConfirm={() => remove.mutate(grant.id)}
                />
              )}
            </div>
          ))}
          {grantsQuery.isSuccess && !grantsQuery.data.length && (
            <p className="py-3 text-sm text-muted-foreground">Отдельных правил пока нет.</p>
          )}
        </CardContent>
      </Card>

      {canManageDoc && <Card>
        <CardHeader>
          <CardTitle>Добавить правило</CardTitle>
          <CardDescription>
            Правка также открывает карточку. Допуски ограничивают назначенных согласующих
            и подписанта, но не заменяют маршрут, реквизит подписанта или замещение.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Область
              <select value={scopeType} onChange={(event) => {
                setScopeType(event.target.value as 'doc' | 'kind')
                setSubjectId('')
                setPermissions(['read'])
              }}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground">
                <option value="doc">Этот документ</option>
                {canManage && <option value="kind">Вид «{doc.kind_name}»</option>}
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Кому
              <select value={subjectType} onChange={(event) => {
                setSubjectType(event.target.value as 'user' | 'role' | 'department')
                setSubjectId('')
                setPermissions(['read'])
              }} className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground">
                <option value="user">Человеку</option>
                <option value="role">Роли</option>
                <option value="department">Подразделению</option>
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Получатель
              <select value={subjectId} onChange={(event) => {
                const value = event.target.value
                setSubjectId(value)
                const existing = (grantsQuery.data ?? []).find((grant) => (
                  grant.scope_type === scopeType
                  && grant.subject_type === subjectType
                  && grant.subject_id === value
                ))
                setPermissions(existing?.permissions ?? ['read'])
              }} disabled={subjectsQuery.isLoading || subjectsQuery.isError
                || !grantsQuery.isSuccess}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground">
                <option value="">
                  {subjectsQuery.isLoading ? 'Загрузка…'
                    : subjectsQuery.isError ? 'Не удалось загрузить'
                      : subjects.length ? 'Выберите' : 'Нет получателей'}
                </option>
                {subjects.map((subject) => (
                  <option key={subject.id} value={subject.id}>{subject.name}</option>
                ))}
              </select>
            </label>
          </div>
          {subjectsQuery.isError && (
            <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4" />Список получателей не загрузился.
              <Button size="sm" variant="outline" onClick={() => subjectsQuery.refetch()}>
                <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
              </Button>
            </div>
          )}
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
            <ShieldCheck data-icon="inline-start" />
            {currentGrant ? 'Сохранить изменения' : 'Добавить правило'}
          </Button>
        </CardContent>
      </Card>}
    </div>
  )
}

export default DocAccessTab
