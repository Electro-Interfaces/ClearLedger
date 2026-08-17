import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle, Archive, CalendarClock, FileCheck2, Loader2, RotateCw, ShieldAlert,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/contexts/AuthContext'
import * as docsService from '@/services/docsService'
import type {
  DocArchiveDecision, DocArchiveHold, DocDestructionAct, DocDetails,
} from '@/services/docsService'

const RETENTION_STATE: Record<string, { label: string; description: string }> = {
  working: { label: 'В работе', description: 'Документ находится в рабочем хранении.' },
  archive_pending: { label: 'Ожидает приёма', description: 'Документ подготовлен к передаче во внутренний архив.' },
  archived: { label: 'В архиве', description: 'Документ принят во внутренний архив.' },
  legacy_review: { label: 'Требует разбора', description: 'Срок и основание нужно проверить по прежним данным.' },
  under_expertise: { label: 'На экспертизе', description: 'Архивная комиссия рассматривает дальнейшее хранение.' },
  permanent: { label: 'Постоянное хранение', description: 'Уничтожение документа не планируется.' },
  destruction_ready: { label: 'Разрешён к включению в акт', description: 'Есть решение экспертизы об уничтожении.' },
  destruction_authorized: { label: 'Уничтожение утверждено', description: 'Акт утверждён, удаление ещё не выполнено.' },
  primary_purged: {
    label: 'Удалён из рабочего хранилища',
    description: 'Рабочие файлы удалены. Документ ещё не считается уничтоженным: требуется отдельное подтверждение резервных копий.',
  },
  destroyed: {
    label: 'Уничтожен',
    description: 'Удаление из рабочего хранилища и резервных копий подтверждено разными действиями.',
  },
}

const RETENTION_CLASS: Record<string, string> = {
  temporary: 'Временное хранение',
  epk: 'До решения ЭПК',
  permanent: 'Постоянное хранение',
  unclassified: 'Срок не классифицирован',
}

const DECISION_LABEL: Record<string, string> = {
  destroy: 'Уничтожить после оформления акта',
  extend: 'Продлить срок хранения',
  permanent: 'Передать на постоянное хранение',
}

const ACT_STATUS: Record<string, string> = {
  draft: 'Черновик',
  approved: 'Утверждён',
  executing: 'Удаление выполняется',
  failed: 'Ошибка удаления из рабочего хранилища',
  primary_purged: 'Удалено из рабочего хранилища',
  destroyed: 'Уничтожено, резервные копии подтверждены',
  cancelled: 'Отменён до утверждения',
}

const ARCHIVE_EVENT: Record<string, string> = {
  hold_placed: 'Установлен запрет уничтожения',
  hold_released: 'Запрет уничтожения снят',
  retention_decided: 'Зафиксировано решение экспертизы',
  legacy_retention_confirmed: 'Подтверждено основание прежнего архива',
  act_created: 'Создан акт об уничтожении',
  act_approved: 'Акт утверждён и запечатан',
  primary_purged: 'Файлы удалены из рабочего хранилища',
  act_primary_purged: 'Исполнение акта завершено в рабочем хранилище',
  act_execution_failed: 'Исполнение акта завершилось ошибкой',
  act_destroyed: 'Подтверждено окончательное уничтожение',
  act_cancelled: 'Черновик акта отменён',
  external_export_resolved: 'Уточнён исход внешней отправки',
}

function displayDate(value: string | null): string {
  if (!value) return 'не зафиксирован'
  const date = new Date(`${value.slice(0, 10)}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium' }).format(date)
}

function displayDateTime(value: string | null): string {
  if (!value) return 'не зафиксировано'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Moscow',
  }).format(date)
}

function mutationMessage(error: unknown): string {
  return (error as Error).message || 'Действие не выполнено'
}

function todayInMoscow(): string {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Moscow' }).format(new Date())
}

export function DocArchiveTab({ doc, companyId }: { doc: DocDetails; companyId: string }) {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [actionError, setActionError] = useState('')
  const [holdAuthority, setHoldAuthority] = useState('')
  const [holdReference, setHoldReference] = useState('')
  const [holdReason, setHoldReason] = useState('')
  const [releaseTarget, setReleaseTarget] = useState<string | null>(null)
  const [releaseReason, setReleaseReason] = useState('')
  const [decision, setDecision] = useState<'destroy' | 'extend' | 'permanent'>('extend')
  const [decisionReason, setDecisionReason] = useState('')
  const [epkReference, setEpkReference] = useState('')
  const [newStorageUntil, setNewStorageUntil] = useState('')
  const [legacyClass, setLegacyClass] = useState<'temporary' | 'epk' | 'permanent' | 'unclassified'>('temporary')
  const [legacyBasis, setLegacyBasis] = useState('')
  const [legacyReason, setLegacyReason] = useState('')
  const [actNumber, setActNumber] = useState('')
  const [actDate, setActDate] = useState(todayInMoscow)
  const [actBasis, setActBasis] = useState('')
  const [committee, setCommittee] = useState('')
  const [backupEvidence, setBackupEvidence] = useState<Record<string, string>>({})
  const [externalCopiesEvidence, setExternalCopiesEvidence] = useState<Record<string, string>>({})
  const [actCancelReasons, setActCancelReasons] = useState<Record<string, string>>({})
  const [exportResolutions, setExportResolutions] = useState<
    Record<string, 'placed' | 'failed'>
  >({})
  const [exportEvidence, setExportEvidence] = useState<Record<string, string>>({})
  const [exportNoLocalCopy, setExportNoLocalCopy] = useState<Record<string, boolean>>({})

  const archiveQuery = useQuery({
    queryKey: ['doc-archive', companyId, doc.id],
    queryFn: () => docsService.getDocArchive(companyId, doc.id),
  })
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['doc-archive', companyId, doc.id] })
    queryClient.invalidateQueries({ queryKey: ['doc', doc.id, companyId] })
  }
  const succeeded = (message: string) => {
    setActionError('')
    toast.success(message)
    refresh()
  }
  const failed = (error: unknown) => {
    const message = mutationMessage(error)
    setActionError(message)
    toast.error(message)
  }

  const placeHold = useMutation({
    mutationFn: () => docsService.placeArchiveHold(companyId, doc.id, {
      authority: holdAuthority.trim(),
      reference: holdReference.trim() || null,
      reason: holdReason.trim(),
    }),
    onSuccess: () => {
      setHoldAuthority('')
      setHoldReference('')
      setHoldReason('')
      succeeded('Запрет уничтожения установлен')
    },
    onError: failed,
  })
  const releaseHold = useMutation({
    mutationFn: (holdId: string) => docsService.releaseArchiveHold(
      companyId, holdId, releaseReason.trim(),
    ),
    onSuccess: () => {
      setReleaseTarget(null)
      setReleaseReason('')
      succeeded('Запрет уничтожения снят')
    },
    onError: failed,
  })
  const decide = useMutation({
    mutationFn: () => docsService.makeArchiveDecision(companyId, doc.id, {
      decision,
      reason: decisionReason.trim(),
      epk_reference: epkReference.trim() || null,
      new_storage_until: decision === 'extend' ? newStorageUntil || null : null,
    }),
    onSuccess: () => {
      setDecisionReason('')
      setEpkReference('')
      setNewStorageUntil('')
      succeeded('Решение экспертизы сохранено')
    },
    onError: failed,
  })
  const confirmLegacy = useMutation({
    mutationFn: () => docsService.confirmLegacyArchive(companyId, doc.id, {
      retention_class: legacyClass,
      basis: legacyBasis.trim(),
      reason: legacyReason.trim(),
    }),
    onSuccess: () => {
      setLegacyBasis('')
      setLegacyReason('')
      succeeded('Основание прежнего архива подтверждено')
    },
    onError: failed,
  })
  const createAct = useMutation({
    mutationFn: () => docsService.createDestructionAct(companyId, {
      act_number: actNumber.trim(),
      act_date: actDate,
      basis: actBasis.trim(),
      committee: committee.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      doc_ids: [doc.id],
    }),
    onSuccess: () => {
      setActNumber('')
      setActBasis('')
      setCommittee('')
      succeeded('Черновик акта создан')
    },
    onError: failed,
  })
  const approveAct = useMutation({
    mutationFn: (actId: string) => docsService.approveDestructionAct(companyId, actId),
    onSuccess: () => succeeded('Акт утверждён'),
    onError: failed,
  })
  const cancelAct = useMutation({
    mutationFn: (actId: string) => docsService.cancelDestructionAct(
      companyId, actId, (actCancelReasons[actId] ?? '').trim(),
    ),
    onSuccess: (_, actId) => {
      setActCancelReasons((current) => ({ ...current, [actId]: '' }))
      succeeded('Черновик акта отменён')
    },
    onError: failed,
  })
  const executeAct = useMutation({
    mutationFn: (actId: string) => docsService.executeDestructionAct(companyId, actId),
    onSuccess: () => succeeded('Файлы удалены из рабочего хранилища'),
    onError: failed,
  })
  const confirmBackup = useMutation({
    mutationFn: (actId: string) => docsService.confirmBackupPurge(
      companyId,
      actId,
      (backupEvidence[actId] ?? '').trim(),
      (externalCopiesEvidence[actId] ?? '').trim(),
    ),
    onSuccess: (_, actId) => {
      setBackupEvidence((current) => ({ ...current, [actId]: '' }))
      setExternalCopiesEvidence((current) => ({ ...current, [actId]: '' }))
      succeeded('Уничтожение подтверждено с учётом резервных копий')
    },
    onError: failed,
  })
  const resolveExport = useMutation({
    mutationFn: (exportId: string) => docsService.resolveArchiveExport(
      companyId,
      exportId,
      exportResolutions[exportId] ?? 'failed',
      (exportEvidence[exportId] ?? '').trim(),
      exportNoLocalCopy[exportId] ?? false,
    ),
    onSuccess: (_, exportId) => {
      setExportEvidence((current) => ({ ...current, [exportId]: '' }))
      setExportNoLocalCopy((current) => ({ ...current, [exportId]: false }))
      succeeded('Исход внешней отправки зафиксирован')
    },
    onError: failed,
  })

  if (archiveQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Загружаем архивные сведения…
      </div>
    )
  }
  if (archiveQuery.isError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-4">
        <div className="flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4" />Архивные сведения не загрузились: {mutationMessage(archiveQuery.error)}
        </div>
        <Button size="sm" variant="outline" onClick={() => archiveQuery.refetch()}>
          <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
        </Button>
      </div>
    )
  }
  const archiveState = archiveQuery.data
  if (!archiveState) return null

  const state = RETENTION_STATE[archiveState.retention_state] ?? {
    label: archiveState.retention_state,
    description: 'Архивное состояние зафиксировано системой.',
  }
  const snapshot = archiveState.retention_snapshot ?? {}
  const snapshotBasis = [
    typeof snapshot.case_index === 'string' ? `дело ${snapshot.case_index}` : null,
    typeof snapshot.storage_term === 'string' ? snapshot.storage_term : null,
    typeof snapshot.storage_years === 'number' ? `${snapshot.storage_years} лет` : null,
    snapshot.epk === true ? 'ЭПК' : null,
  ].filter(Boolean).join(' · ')
  const activeHolds = archiveState.holds.filter((hold) => !hold.released_at)
  const unresolvedExports = archiveState.unresolved_exports ?? []
  const hasOpenAct = archiveState.acts.some((act) => (
    !['destroyed', 'cancelled'].includes(act.status)
  ))
  const committeeMembers = committee.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
  const decisionReady = decisionReason.trim().length >= 10
    && (decision !== 'extend' || Boolean(newStorageUntil))
  const actReady = actNumber.trim().length > 0 && Boolean(actDate)
    && actBasis.trim().length >= 10 && committeeMembers.length >= 2
  const canCreateDecision = archiveState.can_manage && doc.status === 'archived'
    && archiveState.retention_state !== 'legacy_review'
    && !['primary_purged', 'destroyed'].includes(archiveState.retention_state)
    && activeHolds.length === 0 && !hasOpenAct
  const canPlaceHold = archiveState.can_manage
    && archiveState.retention_state !== 'destroyed'

  return (
    <div className="space-y-3 pt-3">
      {actionError && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{actionError}
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Archive className="h-5 w-5" />{state.label}
              </CardTitle>
              <CardDescription className="mt-1">{state.description}</CardDescription>
            </div>
            <span className="rounded-md bg-muted px-2 py-1 text-xs font-medium">
              {RETENTION_CLASS[archiveState.retention_class] ?? archiveState.retention_class}
            </span>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
            <ArchiveFact label="Исходный срок" value={displayDate(archiveState.storage_until)} />
            <ArchiveFact label="Продлённый срок"
              value={archiveState.retention_extended_until
                ? displayDate(archiveState.retention_extended_until) : 'не продлевался'} />
            <ArchiveFact label="Принят в архив" value={displayDateTime(archiveState.archive_accepted_at)} />
            <ArchiveFact label="Основание срока" value={snapshotBasis || 'не зафиксировано'} />
          </dl>
          {archiveState.primary_purged_at && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
              <div className="font-medium">Удалено из рабочего хранилища</div>
              <p className="mt-1 text-muted-foreground">
                {displayDateTime(archiveState.primary_purged_at)}. Это ещё не окончательное уничтожение:
                требуется независимое подтверждение очистки резервных копий.
              </p>
            </div>
          )}
          {archiveState.destroyed_at && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
              <div className="font-medium text-destructive">Уничтожено с подтверждением резервных копий</div>
              <p className="mt-1 text-muted-foreground">{displayDateTime(archiveState.destroyed_at)}</p>
            </div>
          )}
          {archiveState.blocker && (
            <div className="flex items-start gap-2 rounded-md border border-border bg-muted/30 p-3 text-sm">
              <CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              <div><span className="font-medium">До уничтожения:</span> {archiveState.blocker}</div>
            </div>
          )}
        </CardContent>
      </Card>

      {unresolvedExports.length > 0 && (
        <Card className="border-amber-500/40">
          <CardHeader>
            <CardTitle>Неопределённые внешние отправки</CardTitle>
            <CardDescription>
              Пока исход отправки не подтверждён, документ нельзя включить в акт уничтожения.
              Решение сохраняется с автором, временем и доказательством.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {unresolvedExports.map((item) => {
              const resolution = exportResolutions[item.id] ?? 'failed'
              const evidence = exportEvidence[item.id] ?? ''
              const needsMailAttestation = item.channel === 'mail' && resolution === 'placed'
              return (
                <div key={item.id} className="rounded-md border border-border p-3">
                  <div className="text-sm font-medium">{item.package_name || 'Внешняя отправка'}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {item.status === 'pending' ? 'Процесс прерван до фиксации результата' : 'Результат доставки неизвестен'}
                    {item.error ? ` · ${item.error}` : ''}
                  </div>
                  {archiveState.can_manage && (
                    <div className="mt-3 grid gap-2 sm:grid-cols-[180px_minmax(0,1fr)_auto]">
                      <select value={resolution}
                        aria-label="Уточнённый исход внешней отправки"
                        onChange={(event) => setExportResolutions((current) => ({
                          ...current,
                          [item.id]: event.target.value as 'placed' | 'failed',
                        }))}
                        className="h-9 rounded-md border border-input bg-background px-2 text-sm">
                        <option value="failed">Не отправлено</option>
                        <option value="placed">Доставлено наружу</option>
                      </select>
                      <Input value={evidence}
                        aria-label="Доказательство исхода отправки"
                        placeholder="Журнал SMTP, ответ получателя или номер инцидента"
                        onChange={(event) => setExportEvidence((current) => ({
                          ...current, [item.id]: event.target.value,
                        }))} />
                      <Button type="button" size="sm"
                        disabled={evidence.trim().length < 10 || resolveExport.isPending}
                        onClick={() => resolveExport.mutate(item.id)}>
                        Зафиксировать
                      </Button>
                      {needsMailAttestation && (
                        <label className="flex items-start gap-2 text-xs text-muted-foreground sm:col-span-3">
                          <input type="checkbox" className="mt-0.5"
                            checked={exportNoLocalCopy[item.id] ?? false}
                            onChange={(event) => setExportNoLocalCopy((current) => ({
                              ...current, [item.id]: event.target.checked,
                            }))} />
                          Подтверждаю отсутствие локальной копии письма. Если копия найдена,
                          система отклонит это подтверждение.
                        </label>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </CardContent>
        </Card>
      )}

      {archiveState.retention_state === 'legacy_review' && archiveState.can_manage && (
        <Card className="border-amber-500/40">
          <CardHeader>
            <CardTitle>Подтвердить основание прежнего архива</CardTitle>
            <CardDescription>
              Старые данные нельзя автоматически допустить к экспертизе и уничтожению.
              Укажите проверенный источник срока хранения и причину ручного подтверждения.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="grid gap-3 sm:grid-cols-2" onSubmit={(event) => {
              event.preventDefault()
              confirmLegacy.mutate()
            }}>
              <div className="space-y-1.5">
                <Label htmlFor={`legacy-class-${doc.id}`}>Класс хранения</Label>
                <select id={`legacy-class-${doc.id}`} value={legacyClass}
                  onChange={(event) => setLegacyClass(event.target.value as typeof legacyClass)}
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
                  <option value="temporary">Временное</option>
                  <option value="epk">До решения ЭПК</option>
                  <option value="permanent">Постоянное</option>
                  <option value="unclassified">Не классифицировано</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor={`legacy-basis-${doc.id}`}>Проверенное основание</Label>
                <Input id={`legacy-basis-${doc.id}`} value={legacyBasis}
                  onChange={(event) => setLegacyBasis(event.target.value)} required minLength={3}
                  placeholder="Номенклатура, статья перечня, дело" />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor={`legacy-reason-${doc.id}`}>Причина ручного подтверждения, не менее 10 символов</Label>
                <Textarea id={`legacy-reason-${doc.id}`} value={legacyReason}
                  onChange={(event) => setLegacyReason(event.target.value)} required minLength={10} rows={3} />
              </div>
              <Button size="sm" className="sm:col-span-2 sm:justify-self-start"
                disabled={confirmLegacy.isPending || legacyBasis.trim().length < 3
                  || legacyReason.trim().length < 10}>
                Подтвердить основание
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Запреты уничтожения</CardTitle>
          <CardDescription>
            Предписание суда, регулятора или внутреннее расследование останавливает экспертизу
            и уничтожение до явного снятия с причиной.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {archiveState.holds.length === 0 && (
            <p className="text-sm text-muted-foreground">Запретов не зарегистрировано.</p>
          )}
          {archiveState.holds.map((hold) => (
            <HoldRow key={hold.id} hold={hold} canManage={archiveState.can_manage}
              selected={releaseTarget === hold.id} releaseReason={releaseReason}
              pending={releaseHold.isPending}
              onSelect={() => {
                setReleaseTarget(hold.id)
                setReleaseReason('')
              }}
              onCancel={() => {
                setReleaseTarget(null)
                setReleaseReason('')
              }}
              onReason={setReleaseReason}
              onRelease={() => releaseHold.mutate(hold.id)} />
          ))}
          {canPlaceHold && (
            <form className="grid gap-3 border-t border-border pt-4 sm:grid-cols-2"
              onSubmit={(event) => {
                event.preventDefault()
                placeHold.mutate()
              }}>
              <div className="space-y-1.5">
                <Label htmlFor={`hold-authority-${doc.id}`}>Кем установлен</Label>
                <Input id={`hold-authority-${doc.id}`} value={holdAuthority}
                  onChange={(event) => setHoldAuthority(event.target.value)}
                  placeholder="Суд, регулятор, служба безопасности" required minLength={3} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor={`hold-reference-${doc.id}`}>Номер или ссылка на основание</Label>
                <Input id={`hold-reference-${doc.id}`} value={holdReference}
                  onChange={(event) => setHoldReference(event.target.value)} />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor={`hold-reason-${doc.id}`}>Причина</Label>
                <Textarea id={`hold-reason-${doc.id}`} value={holdReason}
                  onChange={(event) => setHoldReason(event.target.value)} required minLength={3} rows={2} />
              </div>
              <Button size="sm" className="sm:col-span-2 sm:justify-self-start"
                disabled={placeHold.isPending || holdAuthority.trim().length < 3 || holdReason.trim().length < 3}>
                <ShieldAlert className="mr-1.5 h-4 w-4" />Установить запрет
              </Button>
            </form>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Экспертиза ценности</CardTitle>
          <CardDescription>
            Решение фиксирует состояние карточки и файлов на момент экспертизы. Старые решения
            не переписываются при продлении срока.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {archiveState.decisions.length === 0 ? (
            <p className="text-sm text-muted-foreground">Решений экспертизы пока нет.</p>
          ) : archiveState.decisions.map((item) => <DecisionRow key={item.id} decision={item} />)}
          {archiveState.can_manage && !canCreateDecision && (
            <p className="border-t border-border pt-3 text-sm text-muted-foreground">
              Новое решение сейчас недоступно: {archiveState.blocker
                ?? (activeHolds.length > 0 ? 'действует запрет уничтожения'
                  : hasOpenAct ? 'документ уже включён в незавершённый акт'
                    : 'текущее состояние документа не допускает экспертизу')}.
            </p>
          )}
          {canCreateDecision && (
            <form className="grid gap-3 border-t border-border pt-4 sm:grid-cols-2"
              onSubmit={(event) => {
                event.preventDefault()
                decide.mutate()
              }}>
              <div className="space-y-1.5">
                <Label htmlFor={`archive-decision-${doc.id}`}>Решение</Label>
                <select id={`archive-decision-${doc.id}`} value={decision}
                  onChange={(event) => setDecision(
                    event.target.value as 'destroy' | 'extend' | 'permanent',
                  )}
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
                  <option value="extend">Продлить срок</option>
                  <option value="permanent">Постоянное хранение</option>
                  <option value="destroy">Разрешить уничтожение</option>
                </select>
              </div>
              {decision === 'extend' && (
                <div className="space-y-1.5">
                  <Label htmlFor={`archive-until-${doc.id}`}>Новый срок хранения</Label>
                  <Input id={`archive-until-${doc.id}`} type="date" value={newStorageUntil}
                    onChange={(event) => setNewStorageUntil(event.target.value)} required />
                </div>
              )}
              {(decision === 'destroy' || archiveState.retention_class === 'epk') && (
                <div className="space-y-1.5">
                  <Label htmlFor={`epk-reference-${doc.id}`}>Решение ЭПК</Label>
                  <Input id={`epk-reference-${doc.id}`} value={epkReference}
                    onChange={(event) => setEpkReference(event.target.value)}
                    required={decision === 'destroy' && archiveState.retention_class === 'epk'} />
                </div>
              )}
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor={`decision-reason-${doc.id}`}>Основание, не менее 10 символов</Label>
                <Textarea id={`decision-reason-${doc.id}`} value={decisionReason}
                  onChange={(event) => setDecisionReason(event.target.value)} minLength={10} required rows={3} />
              </div>
              <Button size="sm" className="sm:col-span-2 sm:justify-self-start"
                variant={decision === 'destroy' ? 'destructive' : 'default'}
                disabled={!decisionReady || decide.isPending
                  || (decision === 'destroy' && archiveState.retention_class === 'epk'
                    && !epkReference.trim())}>
                Сохранить решение
              </Button>
            </form>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Акты об уничтожении</CardTitle>
          <CardDescription>
            Утверждение, удаление из рабочего хранилища и подтверждение резервных копий —
            отдельные контролируемые действия.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {archiveState.acts.length === 0 && (
            <p className="text-sm text-muted-foreground">Документ ещё не включён в акт.</p>
          )}
          {archiveState.acts.map((act) => (
            <ActRow key={act.id} act={act} canManage={archiveState.can_manage}
              userId={user?.id ?? null}
              evidence={backupEvidence[act.id] ?? ''}
              externalEvidence={externalCopiesEvidence[act.id] ?? ''}
              cancelReason={actCancelReasons[act.id] ?? ''}
              knownExternalCopies={Boolean(act.has_known_external_copies)}
              pending={approveAct.isPending || cancelAct.isPending
                || executeAct.isPending || confirmBackup.isPending}
              onEvidence={(value) => setBackupEvidence((current) => ({ ...current, [act.id]: value }))}
              onExternalEvidence={(value) => setExternalCopiesEvidence((current) => ({
                ...current, [act.id]: value,
              }))}
              onCancelReason={(value) => setActCancelReasons((current) => ({
                ...current, [act.id]: value,
              }))}
              onCancel={() => cancelAct.mutate(act.id)}
              onApprove={() => approveAct.mutate(act.id)}
              onExecute={() => executeAct.mutate(act.id)}
              onConfirmBackup={() => confirmBackup.mutate(act.id)} />
          ))}
          {archiveState.can_manage && archiveState.retention_state === 'destruction_ready'
            && !hasOpenAct && (
            <form className="grid gap-3 border-t border-border pt-4 sm:grid-cols-2"
              onSubmit={(event) => {
                event.preventDefault()
                createAct.mutate()
              }}>
              <div className="space-y-1.5">
                <Label htmlFor={`act-number-${doc.id}`}>Номер акта</Label>
                <Input id={`act-number-${doc.id}`} value={actNumber}
                  onChange={(event) => setActNumber(event.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor={`act-date-${doc.id}`}>Дата акта</Label>
                <Input id={`act-date-${doc.id}`} type="date" value={actDate}
                  max={todayInMoscow()}
                  onChange={(event) => setActDate(event.target.value)} required />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor={`act-basis-${doc.id}`}>Основание, не менее 10 символов</Label>
                <Textarea id={`act-basis-${doc.id}`} value={actBasis}
                  onChange={(event) => setActBasis(event.target.value)} minLength={10} required rows={2} />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor={`act-committee-${doc.id}`}>Комиссия — один участник в строке</Label>
                <Textarea id={`act-committee-${doc.id}`} value={committee}
                  onChange={(event) => setCommittee(event.target.value)} rows={4} required
                  placeholder={'Председатель комиссии\nЧлен комиссии'} />
                <p className="text-xs text-muted-foreground">Не менее двух участников.</p>
              </div>
              <Button size="sm" className="sm:col-span-2 sm:justify-self-start"
                disabled={!actReady || createAct.isPending}>
                <FileCheck2 className="mr-1.5 h-4 w-4" />Создать акт для этого документа
              </Button>
            </form>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Неизменяемый архивный журнал</CardTitle>
          <CardDescription>
            События связаны последовательными SHA-256 хешами и не редактируются задним числом.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {archiveState.events.length === 0 && (
            <p className="text-sm text-muted-foreground">Архивных событий пока нет.</p>
          )}
          {archiveState.events.map((event) => (
            <div key={event.id} className="border-l-2 border-border pl-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="text-sm font-medium">
                  {ARCHIVE_EVENT[event.kind] ?? event.kind}
                </div>
                <div className="text-xs text-muted-foreground">
                  {displayDateTime(event.created_at)}
                </div>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {event.actor_name} · хеш {event.event_hash.slice(0, 12)}…
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

function ArchiveFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 bg-card p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-sm font-medium">{value}</dd>
    </div>
  )
}

function HoldRow({ hold, canManage, selected, releaseReason, pending, onSelect, onCancel,
  onReason, onRelease }: {
  hold: DocArchiveHold
  canManage: boolean
  selected: boolean
  releaseReason: string
  pending: boolean
  onSelect: () => void
  onCancel: () => void
  onReason: (value: string) => void
  onRelease: () => void
}) {
  const active = !hold.released_at
  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-medium">{hold.authority}</div>
          <p className="mt-1 text-sm text-muted-foreground">
            {hold.reference ? `${hold.reference} · ` : ''}{hold.reason}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Установлен {displayDateTime(hold.placed_at)}
            {hold.released_at ? ` · снят ${displayDateTime(hold.released_at)}` : ''}
          </p>
          {hold.release_reason && <p className="mt-1 text-xs">Причина снятия: {hold.release_reason}</p>}
        </div>
        <span className={active
          ? 'rounded-md bg-destructive/10 px-2 py-1 text-xs font-medium text-destructive'
          : 'rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground'}>
          {active ? 'Действует' : 'Снят'}
        </span>
      </div>
      {active && canManage && !selected && (
        <Button size="sm" variant="outline" className="mt-3" onClick={onSelect}>Снять запрет</Button>
      )}
      {active && canManage && selected && (
        <div className="mt-3 space-y-2 border-t border-border pt-3">
          <Label htmlFor={`release-hold-${hold.id}`}>Причина снятия, не менее 3 символов</Label>
          <Textarea id={`release-hold-${hold.id}`} value={releaseReason}
            onChange={(event) => onReason(event.target.value)} rows={2} autoFocus />
          <div className="flex flex-wrap gap-2">
            <ConfirmActionDialog
              trigger={(
                <Button size="sm" variant="destructive"
                  disabled={releaseReason.trim().length < 3 || pending}>Снять запрет</Button>
              )}
              title="Снять запрет уничтожения?"
              description="После снятия документ снова сможет пройти экспертизу и быть включён в акт уничтожения. Причина сохранится в аудите."
              confirmLabel="Снять запрет"
              destructive
              onConfirm={onRelease}
            />
            <Button size="sm" variant="ghost" onClick={onCancel}>Отмена</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function DecisionRow({ decision }: { decision: DocArchiveDecision }) {
  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="font-medium">{DECISION_LABEL[decision.decision] ?? decision.decision}</div>
        <span className="text-xs text-muted-foreground">{displayDateTime(decision.created_at)}</span>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{decision.reason}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {decision.new_storage_until && <span>Новый срок: {displayDate(decision.new_storage_until)}</span>}
        {decision.epk_reference && <span>ЭПК: {decision.epk_reference}</span>}
        <span title={decision.snapshot_sha256}>Снимок: {decision.snapshot_sha256.slice(0, 12)}…</span>
      </div>
    </div>
  )
}

function ActRow({ act, canManage, userId, evidence, externalEvidence, cancelReason,
  knownExternalCopies, pending, onEvidence, onExternalEvidence, onCancelReason,
  onApprove, onCancel, onExecute, onConfirmBackup }: {
  act: DocDestructionAct
  canManage: boolean
  userId: string | null
  evidence: string
  externalEvidence: string
  cancelReason: string
  knownExternalCopies: boolean
  pending: boolean
  onEvidence: (value: string) => void
  onExternalEvidence: (value: string) => void
  onCancelReason: (value: string) => void
  onApprove: () => void
  onCancel: () => void
  onExecute: () => void
  onConfirmBackup: () => void
}) {
  const canApprove = act.status === 'draft' && userId !== act.created_by
  const canExecute = (act.status === 'approved' || act.status === 'failed'
    || (act.status === 'executing' && userId === act.executed_by))
    && userId !== act.created_by && userId !== act.approved_by
  const canConfirmBackup = act.status === 'primary_purged'
    && ![act.created_by, act.approved_by, act.executed_by].includes(userId)
  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-medium">Акт № {act.act_number} от {displayDate(act.act_date)}</div>
          <p className="mt-1 text-sm text-muted-foreground">{act.basis}</p>
        </div>
        <span className={act.status === 'failed'
          ? 'rounded-md bg-destructive/10 px-2 py-1 text-xs font-medium text-destructive'
          : 'rounded-md bg-muted px-2 py-1 text-xs font-medium'}>
          {ACT_STATUS[act.status] ?? act.status}
        </span>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        Комиссия: {act.committee.join(', ')}
      </div>
      {act.error && <p role="alert" className="mt-2 text-sm text-destructive">{act.error}</p>}
      {act.item_error && <p role="alert" className="mt-2 text-sm text-destructive">{act.item_error}</p>}
      {act.cancellation_reason && (
        <p className="mt-2 text-sm text-muted-foreground">
          Причина отмены: {act.cancellation_reason}
        </p>
      )}
      {act.status === 'primary_purged' && (
        <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
          <div className="font-medium">Удалено только из рабочего хранилища</div>
          <p className="mt-1 text-muted-foreground">
            До независимого подтверждения резервных копий документ не считается уничтоженным.
          </p>
        </div>
      )}
      {act.status === 'destroyed' && (
        <div className="mt-3 text-sm font-medium text-destructive">
          Уничтожено с подтверждением резервных копий
          {act.backup_attested_at ? ` · ${displayDateTime(act.backup_attested_at)}` : ''}
        </div>
      )}
      {canManage && (
        <div className="mt-3 flex flex-col items-start gap-3 border-t border-border pt-3">
          {canApprove && (
            <Button size="sm" onClick={onApprove} disabled={pending}>Утвердить акт</Button>
          )}
          {act.status === 'draft' && !canApprove && (
            <p className="text-sm text-muted-foreground">Составитель акта не может сам его утвердить.</p>
          )}
          {act.status === 'draft' && (
            <div className="w-full space-y-2">
              <Label htmlFor={`cancel-act-${act.id}`}>Причина отмены черновика</Label>
              <Textarea id={`cancel-act-${act.id}`} value={cancelReason}
                onChange={(event) => onCancelReason(event.target.value)} rows={2} />
              <ConfirmActionDialog
                trigger={(
                  <Button size="sm" variant="outline"
                    disabled={pending || cancelReason.trim().length < 10}>
                    Отменить черновик акта
                  </Button>
                )}
                title="Отменить черновик акта?"
                description="Документ можно будет включить в новый акт. Причина останется в неизменяемом архивном журнале."
                confirmLabel="Отменить акт"
                destructive
                onConfirm={onCancel}
              />
            </div>
          )}
          {canExecute && (
            <ConfirmActionDialog
              trigger={(
                <Button size="sm" variant="destructive" disabled={pending}>
                  <Trash2 className="mr-1.5 h-4 w-4" />
                  {act.status === 'failed' ? 'Повторить удаление' : 'Удалить рабочие файлы'}
                </Button>
              )}
              title="Удалить файлы из рабочего хранилища?"
              description="Файлы карточки станут недоступны в рабочем хранилище. Это действие не подтверждает очистку резервных копий и ещё не означает окончательное уничтожение."
              confirmLabel="Удалить рабочие файлы"
              destructive
              onConfirm={onExecute}
            />
          )}
          {canConfirmBackup && (
            <div className="w-full space-y-2">
              <Label htmlFor={`backup-evidence-${act.id}`}>
                Подтверждение очистки резервных копий, не менее 10 символов
              </Label>
              <Textarea id={`backup-evidence-${act.id}`} value={evidence}
                onChange={(event) => onEvidence(event.target.value)} rows={3}
                placeholder="Укажите журнал, операцию, дату и ответственное лицо" />
              <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
                <div className="font-medium">Проверьте известные внешние копии и выгрузки</div>
                <p className="mt-1 text-muted-foreground">
                  Финальный статус «Уничтожен» допустим только после удаления или документированного
                  учёта всех известных выгрузок вне рабочего и резервного хранилищ.
                </p>
              </div>
              <Label htmlFor={`external-evidence-${act.id}`}>
                Учёт внешних копий{knownExternalCopies ? ', обязательно' : ', если они известны'}
              </Label>
              <Textarea id={`external-evidence-${act.id}`} value={externalEvidence}
                onChange={(event) => onExternalEvidence(event.target.value)} rows={3}
                placeholder="Где находились копии и как подтверждено их удаление или дальнейший учёт" />
              <ConfirmActionDialog
                trigger={(
                  <Button size="sm" variant="destructive"
                    disabled={pending || evidence.trim().length < 10
                      || (knownExternalCopies && externalEvidence.trim().length < 10)}>
                    Подтвердить окончательное уничтожение
                  </Button>
                )}
                title="Подтвердить уничтожение резервных копий?"
                description="После подтверждения документ получит окончательный статус «Уничтожен». Доказательство сохранится в акте и аудите."
                confirmLabel="Подтвердить уничтожение"
                destructive
                onConfirm={onConfirmBackup}
              />
            </div>
          )}
          {act.status === 'primary_purged' && !canConfirmBackup && (
            <p className="text-sm text-muted-foreground">
              Подтверждение резервных копий выполняет четвёртый независимый сотрудник.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default DocArchiveTab
