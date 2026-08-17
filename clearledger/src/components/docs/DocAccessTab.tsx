import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle, Clock3, KeyRound, Loader2, RotateCw, ShieldAlert, ShieldCheck, Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { useAuth } from '@/contexts/AuthContext'
import * as docsService from '@/services/docsService'
import type { DocDetails, DocPermission } from '@/services/docsService'
import { clearAuthFileCache } from '@/lib/authFiles'

const PERMISSIONS: Array<[DocPermission, string]> = [
  ['read', 'Чтение карточки'],
  ['edit', 'Правка'],
  ['approve', 'Согласование'],
  ['sign', 'Подписание'],
  ['download', 'Скачивание'],
  ['print', 'Печать'],
  ['export', 'Экспорт'],
  ['send', 'Отправка'],
  ['manage_acl', 'Управление доступом'],
  ['archive', 'Архивные действия'],
]

const CONFIDENTIALITY = {
  company: {
    label: 'Всё пространство',
    description: 'Чтение открыто участникам пространства, явные запреты сужают доступ.',
  },
  private: {
    label: 'Ограниченный',
    description: 'Доступ получают участники карточки и получатели разрешающих правил.',
  },
  strict: {
    label: 'Строгий',
    description: 'Только явные разрешения. Административная роль сама по себе не открывает содержимое.',
  },
} as const

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Moscow',
  }).format(date)
}

export function DocAccessTab({ doc, companyId }: { doc: DocDetails; companyId: string }) {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const canManageDoc = doc.can_manage_access
  const canManageKind = doc.can_manage_kind_access
  const [scopeType, setScopeType] = useState<'doc' | 'kind'>('doc')
  const [subjectType, setSubjectType] = useState<'user' | 'role' | 'department'>('user')
  const [subjectId, setSubjectId] = useState('')
  const [permissions, setPermissions] = useState<DocPermission[]>(['read'])
  const [deniedPermissions, setDeniedPermissions] = useState<DocPermission[]>([])
  const [confidentialityDraft, setConfidentialityDraft] = useState(doc.confidentiality)
  const [breakGlassPassword, setBreakGlassPassword] = useState('')
  const [breakGlassReason, setBreakGlassReason] = useState('')
  const [breakGlassTtl, setBreakGlassTtl] = useState(15)

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
  const securityQuery = useQuery({
    queryKey: ['doc-security', companyId, doc.id],
    queryFn: () => docsService.getDocSecurity(companyId, doc.id),
    enabled: doc.confidentiality === 'strict' && (canManageDoc || Boolean(user?.is_superadmin)),
  })

  const grants = useMemo(() => grantsQuery.data?.grants ?? [], [grantsQuery.data?.grants])
  const inheritKindAcl = grantsQuery.data?.inherit_kind_acl ?? doc.inherit_kind_acl
  const aclRevision = grantsQuery.data?.acl_revision ?? doc.acl_revision
  const subjects = useMemo(() => {
    if (subjectType === 'role') return subjectsQuery.data?.roles ?? []
    if (subjectType === 'department') return subjectsQuery.data?.departments ?? []
    return subjectsQuery.data?.people ?? []
  }, [subjectType, subjectsQuery.data])
  const currentGrant = useMemo(() => grants.find((grant) => (
    grant.scope_type === scopeType
    && grant.subject_type === subjectType
    && grant.subject_id === subjectId
  )), [grants, scopeType, subjectId, subjectType])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['doc-access', companyId, doc.id] })
    queryClient.invalidateQueries({ queryKey: ['doc-security', companyId, doc.id] })
    queryClient.invalidateQueries({ queryKey: ['doc', doc.id, companyId] })
  }
  const save = useMutation({
    mutationFn: () => docsService.saveAccessGrant(companyId, {
      scope_type: scopeType,
      scope_id: scopeType === 'doc' ? doc.id : doc.kind_id,
      subject_type: subjectType,
      subject_id: subjectId,
      permissions,
      denied_permissions: deniedPermissions,
      expected_acl_revision: scopeType === 'doc' ? aclRevision : undefined,
    }),
    onSuccess: () => {
      toast.success('Правило доступа сохранено')
      setSubjectId('')
      setPermissions(['read'])
      setDeniedPermissions([])
      refresh()
    },
    onError: (error) => toast.error((error as Error).message),
  })
  const remove = useMutation({
    mutationFn: ({ id, inherited }: { id: string; inherited: boolean }) =>
      docsService.deleteAccessGrant(companyId, id, inherited ? undefined : aclRevision),
    onSuccess: () => {
      toast.success('Правило удалено')
      refresh()
    },
    onError: (error) => toast.error((error as Error).message),
  })
  const policy = useMutation({
    mutationFn: (next: {
      inherit_kind_acl: boolean
      confidentiality: 'company' | 'private' | 'strict'
    }) => docsService.updateAccessPolicy(companyId, doc.id, {
      ...next,
      expected_acl_revision: aclRevision,
    }),
    onSuccess: (result) => {
      setConfidentialityDraft(result.confidentiality)
      if (result.confidentiality === 'strict') clearAuthFileCache()
      toast.success('Политика доступа сохранена')
      refresh()
    },
    onError: (error) => toast.error((error as Error).message),
  })
  const activateBreakGlass = useMutation({
    mutationFn: () => docsService.activateBreakGlass(companyId, doc.id, {
      password: breakGlassPassword,
      reason: breakGlassReason.trim(),
      ttl_minutes: breakGlassTtl,
    }),
    onSuccess: () => {
      toast.success('Аварийный доступ открыт на ограниченное время')
      setBreakGlassPassword('')
      setBreakGlassReason('')
      refresh()
    },
    onError: (error) => toast.error((error as Error).message),
  })
  const revokeBreakGlass = useMutation({
    mutationFn: (accessId: string) => docsService.revokeBreakGlass(companyId, accessId),
    onSuccess: () => {
      clearAuthFileCache()
      toast.success('Аварийный доступ отозван')
      refresh()
    },
    onError: (error) => toast.error((error as Error).message),
  })

  const togglePermission = (permission: DocPermission, mode: 'allow' | 'deny', checked: boolean) => {
    if (mode === 'allow') {
      setPermissions((current) => checked
        ? [...new Set([...current, permission])]
        : current.filter((value) => value !== permission))
      if (checked) setDeniedPermissions((current) => current.filter((value) => value !== permission))
      return
    }
    setDeniedPermissions((current) => checked
      ? [...new Set([...current, permission])]
      : current.filter((value) => value !== permission))
    if (checked) setPermissions((current) => current.filter((value) => value !== permission))
  }

  const security = securityQuery.data
  const activeBreakGlass = security?.active_break_glass
  const activeBreakGlassId = activeBreakGlass?.id
  const activeBreakGlassExpiresAt = activeBreakGlass?.expires_at
  const breakGlassReady = breakGlassPassword.length > 0
    && breakGlassReason.trim().length >= 20
    && breakGlassTtl >= 5
    && breakGlassTtl <= 60

  useEffect(() => {
    if (!activeBreakGlassId || !activeBreakGlassExpiresAt) return undefined
    const delay = Math.max(0, new Date(activeBreakGlassExpiresAt).getTime() - Date.now())
    const timer = window.setTimeout(() => {
      clearAuthFileCache()
      queryClient.invalidateQueries({ queryKey: ['doc-security', companyId, doc.id] })
      queryClient.invalidateQueries({ queryKey: ['doc', doc.id, companyId] })
    }, delay + 250)
    return () => window.clearTimeout(timer)
  }, [activeBreakGlassExpiresAt, activeBreakGlassId, companyId, doc.id, queryClient])

  return (
    <div className="flex flex-col gap-3 pt-3">
      <Card>
        <CardHeader>
          <CardTitle>Политика доступа</CardTitle>
          <CardDescription>
            Режим карточки задаёт базовую границу. Явный запрет всегда сильнее разрешения,
            а наследование добавляет правила вида документа.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
            <div className="space-y-1.5">
              <Label htmlFor={`doc-confidentiality-${doc.id}`}>Режим карточки</Label>
              <select id={`doc-confidentiality-${doc.id}`} value={confidentialityDraft}
                onChange={(event) => setConfidentialityDraft(
                  event.target.value as 'company' | 'private' | 'strict',
                )}
                disabled={!canManageDoc || policy.isPending}
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm disabled:opacity-70">
                <option value="company">Всё пространство</option>
                <option value="private">Ограниченный</option>
                <option value="strict">Строгий</option>
              </select>
              <p className="text-xs text-muted-foreground">
                {CONFIDENTIALITY[confidentialityDraft].description}
              </p>
            </div>
            {canManageDoc && confidentialityDraft !== doc.confidentiality && (
              <ConfirmActionDialog
                trigger={<Button size="sm" disabled={policy.isPending || !grantsQuery.isSuccess}>Сохранить режим</Button>}
                title={`Включить режим «${CONFIDENTIALITY[confidentialityDraft].label}»?`}
                description={confidentialityDraft === 'strict'
                  ? 'После сохранения содержимое увидят только получатели явных разрешений. Проверьте правило чтения до включения.'
                  : CONFIDENTIALITY[confidentialityDraft].description}
                confirmLabel="Сохранить"
                destructive={confidentialityDraft === 'strict'}
                onConfirm={() => policy.mutate({
                  confidentiality: confidentialityDraft,
                  inherit_kind_acl: inheritKindAcl,
                })}
              />
            )}
          </div>

          <div className="flex flex-col gap-3 rounded-md border border-border p-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-sm font-medium">Наследование правил вида</div>
              <p className="text-xs text-muted-foreground">
                {inheritKindAcl
                  ? `Правила вида «${doc.kind_name}» действуют вместе с правилами карточки.`
                  : 'Карточка использует только собственные правила.'}
              </p>
            </div>
            {canManageDoc ? (
              <ConfirmActionDialog
                trigger={(
                  <Button size="sm" variant="outline" disabled={policy.isPending || !grantsQuery.isSuccess}>
                    {inheritKindAcl ? 'Остановить наследование' : 'Включить наследование'}
                  </Button>
                )}
                title={inheritKindAcl ? 'Остановить наследование?' : 'Включить наследование?'}
                description={inheritKindAcl
                  ? 'Правила вида перестанут действовать на эту карточку. Собственные разрешения и запреты сохранятся.'
                  : `На карточку начнут действовать разрешения и запреты вида «${doc.kind_name}».`}
                confirmLabel={inheritKindAcl ? 'Остановить' : 'Включить'}
                destructive={inheritKindAcl}
                onConfirm={() => policy.mutate({
                  confidentiality: doc.confidentiality,
                  inherit_kind_acl: !inheritKindAcl,
                })}
              />
            ) : (
              <span className="text-sm font-medium">{inheritKindAcl ? 'Включено' : 'Отключено'}</span>
            )}
          </div>
        </CardContent>
      </Card>

      {doc.confidentiality === 'strict' && (canManageDoc || Boolean(user?.is_superadmin)) && (
        <Card className="border-amber-500/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-amber-600" />Аварийный доступ
            </CardTitle>
            <CardDescription>
              Только для исключительной ситуации. Причина, срок, уведомление и отзыв сохраняются в аудите.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {securityQuery.isLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />Проверяем аварийный доступ…
              </div>
            )}
            {securityQuery.isError && (
              <div role="alert" className="flex flex-wrap items-center justify-between gap-2 text-sm text-destructive">
                <span>Состояние аварийного доступа не загрузилось.</span>
                <Button size="sm" variant="outline" onClick={() => securityQuery.refetch()}>
                  <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
                </Button>
              </div>
            )}
            {activeBreakGlass && (
              <div className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="font-medium">Аварийный доступ активен</div>
                    <div className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
                      <Clock3 className="h-4 w-4" />До {formatDateTime(activeBreakGlass.expires_at)}
                    </div>
                  </div>
                  <ConfirmActionDialog
                    trigger={(
                      <Button size="sm" variant="destructive" disabled={revokeBreakGlass.isPending}>
                        Отозвать сейчас
                      </Button>
                    )}
                    title="Отозвать аварийный доступ?"
                    description="Содержимое снова станет недоступно по этой аварийной сессии. Отзыв будет записан в аудит."
                    confirmLabel="Отозвать"
                    destructive
                    onConfirm={() => revokeBreakGlass.mutate(activeBreakGlass.id)}
                  />
                </div>
                <p className="text-sm">Причина: {activeBreakGlass.reason}</p>
                <p className="text-xs text-muted-foreground">
                  Права: {activeBreakGlass.permissions.map((permission) => (
                    PERMISSIONS.find(([key]) => key === permission)?.[1] ?? permission
                  )).join(', ')}
                </p>
                {activeBreakGlass.notification_error && (
                  <p role="alert" className="text-sm text-destructive">
                    Уведомление не доставлено: {activeBreakGlass.notification_error}
                  </p>
                )}
              </div>
            )}
            {security?.can_break_glass && !activeBreakGlass && (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor={`break-glass-password-${doc.id}`}>Пароль</Label>
                  <Input id={`break-glass-password-${doc.id}`} type="password"
                    autoComplete="current-password" value={breakGlassPassword}
                    onChange={(event) => setBreakGlassPassword(event.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`break-glass-ttl-${doc.id}`}>Срок доступа</Label>
                  <select id={`break-glass-ttl-${doc.id}`} value={breakGlassTtl}
                    onChange={(event) => setBreakGlassTtl(Number(event.target.value))}
                    className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
                    <option value={5}>5 минут</option>
                    <option value={15}>15 минут</option>
                    <option value={30}>30 минут</option>
                    <option value={60}>60 минут</option>
                  </select>
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor={`break-glass-reason-${doc.id}`}>Причина, не менее 20 символов</Label>
                  <Textarea id={`break-glass-reason-${doc.id}`} value={breakGlassReason}
                    onChange={(event) => setBreakGlassReason(event.target.value)} rows={3}
                    placeholder="Опишите инцидент и почему штатного доступа недостаточно" />
                </div>
                <ConfirmActionDialog
                  trigger={(
                    <Button className="sm:col-span-2 sm:justify-self-start" variant="destructive"
                      disabled={!breakGlassReady || activateBreakGlass.isPending}>
                      <KeyRound className="mr-1.5 h-4 w-4" />Открыть аварийный доступ
                    </Button>
                  )}
                  title={`Открыть аварийный доступ на ${breakGlassTtl} минут?`}
                  description="Действие будет записано в аудит, ответственным уйдёт уведомление. Доступ можно отозвать раньше срока."
                  confirmLabel="Открыть доступ"
                  destructive
                  onConfirm={() => activateBreakGlass.mutate()}
                />
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Правила на документ</CardTitle>
          <CardDescription>
            Зелёные метки разрешают действие, красные запрещают. Запрет имеет приоритет
            независимо от источника правила.
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
          {grantsQuery.isSuccess && grants.map((grant) => (
            <div key={grant.id}
              className="flex flex-wrap items-start justify-between gap-2 border-b border-border py-3 last:border-0">
              <div className="min-w-0">
                <div className="text-sm font-medium">{grant.subject_name || 'Получатель удалён'}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {grant.inherited ? 'Унаследовано от вида' : 'Правило карточки'}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {grant.permissions.map((permission) => (
                    <span key={`allow-${permission}`}
                      className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-300">
                      Разрешено: {PERMISSIONS.find(([key]) => key === permission)?.[1] ?? permission}
                    </span>
                  ))}
                  {grant.denied_permissions.map((permission) => (
                    <span key={`deny-${permission}`}
                      className="rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
                      Запрещено: {PERMISSIONS.find(([key]) => key === permission)?.[1] ?? permission}
                    </span>
                  ))}
                </div>
              </div>
              {(grant.inherited ? canManageKind : canManageDoc) && (
                <ConfirmActionDialog
                  trigger={(
                    <Button size="icon" variant="ghost" aria-label="Удалить правило"
                      disabled={remove.isPending}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                  title={grant.inherited ? 'Удалить правило вида?' : 'Удалить правило карточки?'}
                  description={grant.inherited
                    ? `Доступ изменится у всех документов вида «${doc.kind_name}».`
                    : `Правило для «${grant.subject_name || 'получателя'}» перестанет действовать сразу.`}
                  confirmLabel="Удалить"
                  destructive
                  onConfirm={() => remove.mutate({ id: grant.id, inherited: grant.inherited })}
                />
              )}
            </div>
          ))}
          {grantsQuery.isSuccess && !grants.length && (
            <p className="py-3 text-sm text-muted-foreground">Отдельных правил пока нет.</p>
          )}
        </CardContent>
      </Card>

      {canManageDoc && (
        <Card>
          <CardHeader>
            <CardTitle>Добавить правило</CardTitle>
            <CardDescription>
              Разрешения и запреты независимы, но одно действие нельзя одновременно
              разрешить и запретить в одном правиле.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
                Область
                <select value={scopeType} onChange={(event) => {
                  setScopeType(event.target.value as 'doc' | 'kind')
                  setSubjectId('')
                  setPermissions(['read'])
                  setDeniedPermissions([])
                }} className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground">
                  <option value="doc">Этот документ</option>
                  {canManageKind && <option value="kind">Вид «{doc.kind_name}»</option>}
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
                Кому
                <select value={subjectType} onChange={(event) => {
                  setSubjectType(event.target.value as 'user' | 'role' | 'department')
                  setSubjectId('')
                  setPermissions(['read'])
                  setDeniedPermissions([])
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
                  const existing = grants.find((grant) => (
                    grant.scope_type === scopeType
                    && grant.subject_type === subjectType
                    && grant.subject_id === value
                  ))
                  setPermissions(existing?.permissions ?? ['read'])
                  setDeniedPermissions(existing?.denied_permissions ?? [])
                }} disabled={subjectsQuery.isLoading || subjectsQuery.isError || !grantsQuery.isSuccess}
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
            <div className="grid gap-3 lg:grid-cols-2">
              <fieldset className="rounded-md border border-emerald-500/30 p-3">
                <legend className="px-1 text-sm font-medium text-emerald-700 dark:text-emerald-300">
                  Разрешить
                </legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {PERMISSIONS.map(([key, label]) => (
                    <Label key={key} htmlFor={`allow-${doc.id}-${key}`}
                      className="flex items-center gap-2 text-sm">
                      <Checkbox id={`allow-${doc.id}-${key}`} checked={permissions.includes(key)}
                        onCheckedChange={(checked) => togglePermission(key, 'allow', checked === true)} />
                      {label}
                    </Label>
                  ))}
                </div>
              </fieldset>
              <fieldset className="rounded-md border border-destructive/40 bg-destructive/[0.025] p-3">
                <legend className="px-1 text-sm font-medium text-destructive">Запретить</legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {PERMISSIONS.map(([key, label]) => (
                    <Label key={key} htmlFor={`deny-${doc.id}-${key}`}
                      className="flex items-center gap-2 text-sm text-destructive">
                      <Checkbox id={`deny-${doc.id}-${key}`} checked={deniedPermissions.includes(key)}
                        onCheckedChange={(checked) => togglePermission(key, 'deny', checked === true)} />
                      {label}
                    </Label>
                  ))}
                </div>
              </fieldset>
            </div>
            <Button size="sm" className="self-start" disabled={
              !subjectId || (!permissions.length && !deniedPermissions.length) || save.isPending
            } onClick={() => save.mutate()}>
              <ShieldCheck className="mr-1.5 h-4 w-4" />
              {currentGrant ? 'Сохранить изменения' : 'Добавить правило'}
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default DocAccessTab
