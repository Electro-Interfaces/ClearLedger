/**
 * Карточка документа: реквизиты, обработка, файлы, связи и доказуемая история.
 *
 * Состояние меняется только контекстными действиями. Регистрационный номер,
 * пакет согласования и редакции файла показываются как факты, а не поля формы.
 */
import { useId, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive, ArrowLeft, Ban, CheckCheck, FileCheck2, FileUp, KeyRound, Link2,
  ListChecks, LockKeyhole, Printer, Send, ShieldCheck, Stamp, Workflow,
} from 'lucide-react'
import { toast } from 'sonner'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import * as docsService from '@/services/docsService'
import { DOC_STATUS } from '@/services/docsService'
import type { DocKindField } from '@/services/docsService'
import { DocAcquaintTab } from './DocAcquaintTab'
import { DocAccessTab } from './DocAccessTab'
import { DocArchiveTab } from './DocArchiveTab'
import { DocApprovalTab } from './DocApprovalTab'
import { DocFileWorkspace } from './DocFileWorkspace'
import { DocSendTab } from './DocSendTab'
import { openAuthAttachment } from '@/lib/authFiles'
import { useCompany } from '@/contexts/CompanyContext'
import { DocRegisterDialog, type DocRegisterValues } from './DocRegisterDialog'

const EVENT_LABEL: Record<string, string> = {
  created: 'заведён',
  registered: 'зарегистрирован',
  version: 'файл',
  status: 'состояние',
  field: 'правка',
  approval: 'согласование',
  sign: 'подпись',
  dispatch: 'отправка',
  errand: 'поручение',
  relation: 'связь',
  access: 'права доступа',
  comment: 'реплика',
  mail: 'письмо',
}

const FIELD_LABEL: Record<string, string> = {
  title: 'Заголовок',
  summary: 'Краткое содержание',
  external_number: 'Их номер',
  external_date: 'Дата их документа',
  counterparty_name: 'Корреспондент',
  counterparty_id: 'Карточка корреспондента',
  confidentiality: 'Доступ',
  responsible_id: 'Ответственный',
  signatory_id: 'Подписант',
  object_id: 'Объект',
  attrs: 'Реквизиты вида',
  organization_id: 'Наше юрлицо',
  case_id: 'Дело номенклатуры',
}

const EVENT_VALUE: Record<string, string> = {
  draft: 'Черновик',
  registered: 'Зарегистрирован',
  in_force: 'Действует',
  executed: 'Исполнен',
  archived: 'В архиве',
  cancelled: 'Отменён',
  approved: 'Согласовано',
  rejected: 'Отказано',
  pending: 'Ожидает решения',
  waiting: 'Этап ещё не начат',
  skipped: 'Снято',
  company: 'Всё пространство',
  private: 'Ограниченный доступ',
  strict: 'Строгий доступ',
  body: 'Документ',
  appendix: 'Приложение',
  signed_scan: 'Подписанный экземпляр',
  attachment: 'Вложение',
}

const APPROVAL_LABEL: Record<string, string> = {
  none: 'Не запускалось',
  pending: 'Идёт согласование',
  approved: 'Согласовано',
  rejected: 'На доработке',
}

export function DocCardPanel({ id, companyId, onBack, onChanged, initialTab }: {
  id: string
  companyId: string
  onBack: () => void
  onChanged: () => void
  initialTab?: 'document' | 'processing' | 'files' | 'links' | 'archive' | 'feed'
}) {
  const qc = useQueryClient()
  const { organizations, isCompanyAdmin } = useCompany()
  const fileRef = useRef<HTMLInputElement>(null)
  const [registerOpen, setRegisterOpen] = useState(false)
  const [note, setNote] = useState('')
  const [activeTab, setActiveTab] = useState<string>(initialTab ?? 'document')
  const [fileRole, setFileRole] = useState('body')
  const [reasonMode, setReasonMode] = useState<'cancel' | 'cancel_approval' | null>(null)
  const [reason, setReason] = useState('')
  const [emergencyPassword, setEmergencyPassword] = useState('')
  const [emergencyReason, setEmergencyReason] = useState('')
  const [emergencyTtl, setEmergencyTtl] = useState(15)

  const q = useQuery({
    queryKey: ['doc', id, companyId],
    queryFn: () => docsService.getDoc(companyId, id),
  })
  const casesQ = useQuery({
    queryKey: ['doc-cases', companyId],
    queryFn: () => docsService.listCases(companyId),
    enabled: !!companyId,
  })
  const securityQ = useQuery({
    queryKey: ['doc-security', companyId, id],
    queryFn: () => docsService.getDocSecurity(companyId, id),
    enabled: q.isError,
    retry: false,
  })
  const emergencyAccess = useMutation({
    mutationFn: () => docsService.activateBreakGlass(companyId, id, {
      password: emergencyPassword,
      reason: emergencyReason.trim(),
      ttl_minutes: emergencyTtl,
    }),
    onSuccess: async () => {
      setEmergencyPassword('')
      setEmergencyReason('')
      toast.success('Временный аварийный доступ открыт')
      await securityQ.refetch()
      await q.refetch()
    },
    onError: (error) => toast.error((error as Error).message),
  })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['doc', id, companyId] })
    onChanged()
  }

  const register = useMutation({
    mutationFn: (values: DocRegisterValues) => docsService.registerDoc(companyId, id, {
      regDate: values.regDate,
      regNumber: values.regNumber,
      manualReason: values.manualReason,
    }),
    onSuccess: (d) => {
      toast.success(`Зарегистрирован: ${d.reg_number}`)
      setRegisterOpen(false)
      refresh()
    },
    onError: (e) => toast.error(`Не зарегистрирован: ${(e as Error).message}`),
  })

  const verification = useMutation({
    mutationFn: () => docsService.getVerificationLink(companyId, id),
    onSuccess: async (result) => {
      try {
        await navigator.clipboard.writeText(result.url)
        toast.success('Ссылка проверки скопирована')
      } catch {
        window.prompt('Скопируйте ссылку проверки', result.url)
      }
    },
    onError: (e) => toast.error(`Ссылка не получена: ${(e as Error).message}`),
  })

  const act = useMutation({
    mutationFn: (body: Record<string, unknown>) => docsService.docAction(companyId, id, body),
    onSuccess: (_, body) => {
      if (body.status) toast.success('Состояние документа изменено')
      setNote('')
      setReason('')
      setReasonMode(null)
      refresh()
    },
    onError: (e) => toast.error(`Не сохранилось: ${(e as Error).message}`),
  })

  const startApproval = useMutation({
    mutationFn: () => docsService.startApproval(companyId, id),
    onSuccess: (result) => {
      toast.success(`Круг ${result.round} запущен`)
      setActiveTab('processing')
      refresh()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const cancelApproval = useMutation({
    mutationFn: () => docsService.cancelApproval(companyId, id, reason.trim()),
    onSuccess: () => {
      toast.success('Круг согласования отменён')
      setReason('')
      setReasonMode(null)
      refresh()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const attach = useMutation({
    mutationFn: ({ file, role }: { file: File; role: string }) =>
      docsService.uploadVersion(companyId, id, file, role),
    onSuccess: (result) => {
      toast.success(result.duplicate ? 'Такой файл уже приложен' : `Редакция ${result.revision}`)
      refresh()
    },
    onError: (e) => toast.error(`Файл не принят: ${(e as Error).message}`),
  })

  const tombstone = useMutation({
    mutationFn: ({ versionId, reason }: { versionId: string; reason: string }) =>
      docsService.tombstoneVersion(companyId, versionId, reason),
    onSuccess: () => {
      toast.success('Редакция убрана из работы; причина сохранена в истории')
      refresh()
    },
    onError: (e) => toast.error(`Редакция не убрана: ${(e as Error).message}`),
  })

  const assignCase = useMutation({
    mutationFn: (caseId: string | null) => docsService.assignCase(companyId, id, caseId),
    onSuccess: (_, caseId) => {
      toast.success(caseId ? 'Документ подшит в дело' : 'Документ извлечён из дела')
      refresh()
    },
    onError: (e) => toast.error(`Дело не изменено: ${(e as Error).message}`),
  })

  if (q.isLoading) return <DocLoadState onBack={onBack} />
  if (q.isError && securityQ.data?.can_break_glass) return (
    <StrictAccessGate
      security={securityQ.data}
      password={emergencyPassword}
      reason={emergencyReason}
      ttl={emergencyTtl}
      pending={emergencyAccess.isPending}
      onBack={onBack}
      onPassword={setEmergencyPassword}
      onReason={setEmergencyReason}
      onTtl={setEmergencyTtl}
      onActivate={() => emergencyAccess.mutate()} />
  )
  if (q.isError) return (
    <DocLoadState onBack={onBack}
      error={securityQ.isLoading ? 'Проверяем режим доступа…' : (q.error as Error).message}
      onRetry={() => {
        securityQ.refetch()
        q.refetch()
      }} />
  )
  const d = q.data
  if (!d) return <DocLoadState onBack={onBack} error="Документ не найден" />

  const registered = Boolean(d.reg_number)
  const actions = new Set(d.available_actions ?? [])
  const editable = actions.has('edit')
  const approvalLocked = d.approval_status === 'pending'
  const canChangeFiles = editable && !approvalLocked && ['draft', 'registered'].includes(d.status)
  const cases = casesQ.data ?? []
  const caseOptions = cases.filter((item) => (
    item.id === d.case_id || (item.status === 'open'
      && (!item.organization_id || item.organization_id === d.organization_id)
      && (!d.reg_date || item.year === Number(d.reg_date.slice(0, 4))))
  ))
  const currentCaseMissing = Boolean(
    d.case_id && !caseOptions.some((item) => item.id === d.case_id),
  )
  const headerActions = (
    <>
      {registered && d.capabilities.send && (
        <Button size="sm" onClick={() => setActiveTab('send')}>
          <Send className="mr-1.5 h-4 w-4" />Отправка
        </Button>
      )}
      <Button size="sm" variant="outline" onClick={() => setActiveTab('access')}>
        <KeyRound className="mr-1.5 h-4 w-4" />Доступ
      </Button>
      {registered && d.capabilities.send && (
        <Button size="sm" variant="ghost" title="Ссылка проверки записи"
          aria-label="Ссылка проверки записи" onClick={() => verification.mutate()}
          disabled={verification.isPending}>
          <ShieldCheck className="h-4 w-4 md:mr-1.5" />
          <span className="hidden md:inline">Проверка</span>
        </Button>
      )}
      {registered && d.capabilities.print && (
        <Button size="sm" variant="ghost" title="Печатная форма" aria-label="Печатная форма"
          onClick={() => openAuthAttachment(
            `/api/docs/${d.id}/print?company_id=${companyId}`,
            { cache: false },
          ).catch((error) => toast.error(`Печатная форма не открыта: ${error.message}`))}>
          <Printer className="h-4 w-4 md:mr-1.5" /><span className="hidden md:inline">Печать</span>
        </Button>
      )}
    </>
  )

  const updateAttr = (field: DocKindField, value: unknown) => {
    act.mutate({ attrs: { ...d.attrs, [field.code]: value } })
  }

  const submitReason = () => {
    if (reason.trim().length < 3) {
      toast.error('Укажите причину — не менее трёх символов')
      return
    }
    if (reasonMode === 'cancel_approval') cancelApproval.mutate()
    if (reasonMode === 'cancel') act.mutate({ status: 'cancelled', note: reason.trim() })
  }

  return (
    <div className="space-y-4 pb-20 md:pb-0">
      <header className="sticky top-0 z-20 border-b border-border bg-background py-2 md:py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2">
            <Button variant="ghost" size="sm" onClick={onBack} className="mt-0.5 shrink-0"
              aria-label="Вернуться в реестр">
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="min-w-0 text-base font-semibold leading-6">{d.title}</h1>
                <StatusPill status={d.status} />
                {approvalLocked && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-xs text-primary">
                    <LockKeyhole className="h-3 w-3" />Пакет зафиксирован
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {d.kind_name || d.kind_code}
                {registered ? ` · ${d.reg_number} от ${d.reg_date}` : ' · номер не присвоен'}
                {d.organization_name ? ` · ${d.organization_name}` : ''}
                {d.counterparty_name ? ` · ${d.counterparty_name}` : ''}
              </p>
            </div>
          </div>
          <div className="hidden flex-wrap items-center justify-end gap-2 md:flex">{headerActions}</div>
        </div>
      </header>

      <section aria-label="Состояние и действия" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2 md:hidden">{headerActions}</div>
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border lg:grid-cols-4">
          <Fact label="Текущая редакция"
            value={d.current_revision ? `Редакция ${d.current_revision}` : 'Основной файл не приложен'} />
          <Fact label="Согласование" value={APPROVAL_LABEL[d.approval_status] ?? d.approval_status} />
          <Fact label="Хранение" value={d.storage_until ? `До ${d.storage_until}` : 'Срок не зафиксирован'} />
          <Fact label="Доступ"
            value={d.confidentiality === 'strict' ? 'Строгий'
              : d.confidentiality === 'private' ? 'Ограниченный' : 'Всё пространство'} />
        </div>

        <Lifecycle status={d.status} />

        <div className="flex flex-wrap items-center gap-2">
          {actions.has('register') && (
            <Button size="sm" onClick={() => setRegisterOpen(true)} disabled={register.isPending}>
              <Stamp className="mr-1.5 h-4 w-4" />Зарегистрировать
            </Button>
          )}
          {actions.has('start_approval') && (
            <Button size="sm" variant="outline" onClick={() => startApproval.mutate()}
              disabled={startApproval.isPending}>
              <Workflow className="mr-1.5 h-4 w-4" />На согласование
            </Button>
          )}
          {actions.has('cancel_approval') && (
            <Button size="sm" variant="outline" onClick={() => setReasonMode('cancel_approval')}>
              <Ban className="mr-1.5 h-4 w-4" />Отменить круг
            </Button>
          )}
          {actions.has('put_in_force') && (
            <Button size="sm" onClick={() => act.mutate({ status: 'in_force' })}
              disabled={act.isPending}>
              <FileCheck2 className="mr-1.5 h-4 w-4" />Ввести в действие
            </Button>
          )}
          {actions.has('execute') && (
            <Button size="sm" onClick={() => act.mutate({ status: 'executed' })}
              disabled={act.isPending}>
              <CheckCheck className="mr-1.5 h-4 w-4" />Отметить исполненным
            </Button>
          )}
          {actions.has('archive') && (
            <Button size="sm" onClick={() => act.mutate({ status: 'archived' })}
              disabled={act.isPending}>
              <Archive className="mr-1.5 h-4 w-4" />Передать в архив
            </Button>
          )}
          {actions.has('cancel') && (
            <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive"
              onClick={() => setReasonMode('cancel')}>
              Отменить документ
            </Button>
          )}
        </div>

        {reasonMode && (
          <div className="flex max-w-2xl flex-wrap items-center gap-2 rounded-md border border-border bg-muted/30 p-2">
            <Input value={reason} onChange={(event) => setReason(event.target.value)}
              placeholder={reasonMode === 'cancel' ? 'Причина отмены документа' : 'Почему отменяется круг'}
              aria-label={reasonMode === 'cancel' ? 'Причина отмены документа' : 'Причина отмены круга'}
              className="h-9 min-w-64 flex-1" autoFocus />
            <Button size="sm" variant={reasonMode === 'cancel' ? 'destructive' : 'default'}
              onClick={submitReason} disabled={act.isPending || cancelApproval.isPending}>
              Подтвердить
            </Button>
            <Button size="sm" variant="ghost" onClick={() => {
              setReasonMode(null)
              setReason('')
            }}>Не отменять</Button>
          </div>
        )}
      </section>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="h-auto max-w-full scroll-px-2 justify-start overflow-x-auto px-2">
          <TabsTrigger value="document">Документ</TabsTrigger>
          <TabsTrigger value="processing">
            Обработка{approvalLocked || d.acquaints.some((item) => item.status === 'pending') ? ' •' : ''}
          </TabsTrigger>
          <TabsTrigger value="files">Файлы и подписи{d.versions.length ? ` (${d.versions.length})` : ''}</TabsTrigger>
          <TabsTrigger value="links">Связи{d.relations.length ? ` (${d.relations.length})` : ''}</TabsTrigger>
          <TabsTrigger value="archive">Архив</TabsTrigger>
          <TabsTrigger value="feed">История</TabsTrigger>
        </TabsList>

        <TabsContent value="document" className="space-y-3 pt-3">
          {approvalLocked && (
            <Card className="flex items-start gap-2.5 border-primary/30 p-3 text-sm">
              <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <div>
                <div className="font-medium">Реквизиты защищены текущим кругом</div>
                <div className="text-xs text-muted-foreground">
                  Чтобы внести изменения, отмените круг с причиной и запустите новый после правок.
                </div>
              </div>
            </Card>
          )}
          <Card className="grid gap-3 p-4 sm:grid-cols-2">
            <Field label="Наше юрлицо">
              {(controlId) => <select id={controlId} value={d.organization_id ?? ''}
                disabled={!editable || registered}
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                onChange={(event) => act.mutate({ organization_id: event.target.value })}>
                <option value="">Не выбрано</option>
                {organizations.map((organization) => (
                  <option key={organization.id} value={organization.id}>{organization.name}</option>
                ))}
              </select>}
            </Field>
            <Field label="Заголовок">
              {(controlId) => <Input id={controlId} defaultValue={d.title} required aria-required="true"
                className="h-9 disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                disabled={!editable}
                onBlur={(event) => event.target.value.trim() !== d.title
                  && act.mutate({ title: event.target.value.trim() })} />}
            </Field>
            <Field label={d.direction === 'in' ? 'От кого' : 'Кому'}>
              {(controlId) => <Input id={controlId} defaultValue={d.counterparty_name}
                className="h-9 disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                disabled={!editable}
                onBlur={(event) => event.target.value !== d.counterparty_name
                  && act.mutate({ counterparty_name: event.target.value })} />}
            </Field>
            <Field label="Их номер">
              {(controlId) => <Input id={controlId} defaultValue={d.external_number ?? ''}
                className="h-9 disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                disabled={!editable}
                onBlur={(event) => event.target.value !== (d.external_number ?? '')
                  && act.mutate({ external_number: event.target.value })} />}
            </Field>
            <Field label="Дата их документа">
              {(controlId) => <Input id={controlId} type="date" defaultValue={d.external_date ?? ''}
                className="h-9 disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                disabled={!editable}
                onBlur={(event) => event.target.value !== (d.external_date ?? '')
                  && act.mutate({ external_date: event.target.value || null })} />}
            </Field>
            <div className="space-y-1.5">
              <div className="text-xs text-muted-foreground">Доступ</div>
              <div className="flex min-h-9 items-center rounded-md border border-input bg-muted/30 px-3 text-sm">
                {d.confidentiality === 'strict' ? 'Строгий — только явные разрешения'
                  : d.confidentiality === 'private' ? 'Ограниченный — участники и правила'
                    : 'Всё пространство'}
              </div>
              {d.can_manage_access && (
                <button type="button" className="text-xs text-primary underline underline-offset-2"
                  onClick={() => setActiveTab('access')}>Изменить политику доступа</button>
              )}
            </div>
            <Field label="Дело номенклатуры">
              {(controlId) => <div className="space-y-1.5">
                <select id={controlId} value={d.case_id ?? ''}
                  disabled={!actions.has('manage_case') || assignCase.isPending
                    || casesQ.isLoading || casesQ.isError}
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                  onChange={(event) => assignCase.mutate(event.target.value || null)}>
                  <option value="">Не подшит</option>
                  {currentCaseMissing && (
                    <option value={d.case_id ?? ''}>Текущее дело недоступно</option>
                  )}
                  {caseOptions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.year} · {item.index} · {item.title}{item.status === 'closed' ? ' (закрыто)' : ''}
                    </option>
                  ))}
                </select>
                {casesQ.isError && (
                  <div role="alert" className="flex items-center justify-between gap-2 text-xs text-destructive">
                    <span>Дела не загрузились</span>
                    <button type="button" className="underline underline-offset-2"
                      onClick={() => casesQ.refetch()}>Повторить</button>
                  </div>
                )}
              </div>}
            </Field>
            <div className="space-y-1.5">
              <div className="text-xs text-muted-foreground">Состояние</div>
              <div className="flex h-9 items-center rounded-md border border-input bg-muted/30 px-3 text-sm">
                {DOC_STATUS[d.status]?.label ?? d.status}
              </div>
            </div>
            {(d.kind?.fields ?? []).map((field) => (
              <AttrField key={field.code} field={field} value={d.attrs[field.code]}
                disabled={!editable} onCommit={(value) => updateAttr(field, value)} />
            ))}
            <div className="sm:col-span-2">
              <Field label="Краткое содержание">
                {(controlId) => <Textarea id={controlId} defaultValue={d.summary ?? ''}
                  rows={3} disabled={!editable}
                  className="disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                  onBlur={(event) => event.target.value !== (d.summary ?? '')
                    && act.mutate({ summary: event.target.value })} />}
              </Field>
            </div>
          </Card>

          <Card className="space-y-2 p-4">
            <Label htmlFor={`doc-note-${d.id}`} className="text-xs">Реплика в историю</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input id={`doc-note-${d.id}`} value={note} onChange={(event) => setNote(event.target.value)}
                placeholder="Что важно зафиксировать по документу" className="h-9"
                disabled={!editable} />
              <Button size="sm" variant="outline" disabled={!editable || !note.trim() || act.isPending}
                onClick={() => act.mutate({ note: note.trim() })}>
                Записать
              </Button>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="processing" className="space-y-5 pt-3">
          <section aria-labelledby="approval-heading">
            <h2 id="approval-heading" className="text-sm font-semibold">Согласование</h2>
            <DocApprovalTab doc={d} companyId={companyId} onChanged={refresh} />
          </section>
          <section aria-labelledby="acquaint-heading">
            <h2 id="acquaint-heading" className="text-sm font-semibold">Ознакомление</h2>
            <DocAcquaintTab doc={d} companyId={companyId} canEdit={editable} onChanged={refresh} />
          </section>
        </TabsContent>

        <TabsContent value="files" className="space-y-3 pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <input ref={fileRef} type="file" className="hidden" onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) attach.mutate({ file, role: fileRole })
              event.target.value = ''
            }} />
            <select value={fileRole} onChange={(event) => setFileRole(event.target.value)}
              aria-label="Роль прикладываемого файла"
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              disabled={!editable || attach.isPending}>
              <option value="body">Основной документ</option>
              <option value="appendix">Приложение</option>
              <option value="signed_scan">Подписанный экземпляр</option>
              <option value="attachment">Вложение</option>
            </select>
            <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()}
              disabled={!editable || attach.isPending}>
              <FileUp className="mr-1.5 h-4 w-4" />Приложить файл
            </Button>
            <span className="text-xs text-muted-foreground">
              Каждый файл опознаётся SHA-256; во время согласования набор неизменяем.
            </span>
          </div>
          <DocFileWorkspace versions={d.versions} canDownload={d.capabilities.download}
            sensitive={d.confidentiality === 'strict'}
            canRemove={canChangeFiles}
            removing={tombstone.isPending}
            onRemove={(versionId, reason) => tombstone.mutate({ versionId, reason })} />
        </TabsContent>

        <TabsContent value="links" className="pt-3">
          <Card className="divide-y divide-border/60">
            {d.relations.map((relation) => (
              <div key={relation.id} className="flex items-center gap-2 px-3 py-2 text-sm">
                {relation.target_ref.startsWith('task:')
                  ? <ListChecks className="h-3.5 w-3.5 text-muted-foreground" />
                  : <Link2 className="h-3.5 w-3.5 text-muted-foreground" />}
                <span className="text-muted-foreground">{relation.kind}</span>
                <span className="font-mono text-xs">{relation.target_ref}</span>
              </div>
            ))}
            {d.relations.length === 0 && (
              <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                Связей пока нет
              </div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="feed" className="pt-3">
          <Card className="divide-y divide-border/60">
            {d.events.map((event) => (
              <div key={event.id} className="px-3 py-2 text-sm">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-xs text-muted-foreground">
                    {formatEventTime(event.created_at)}
                  </span>
                  <span className="font-medium">{event.actor ?? 'Система'}</span>
                  <span className="text-muted-foreground">
                    {event.kind === 'field' && event.note
                      ? `изменил: ${FIELD_LABEL[event.note] ?? event.note}`
                      : EVENT_LABEL[event.kind] ?? event.kind}
                  </span>
                </div>
                {(event.from !== null || event.to !== null) && (
                  <div className="pt-1 text-[13px]">
                    {event.from !== null && <span>{formatEventValue(event.from)}</span>}
                    {event.from !== null && event.to !== null && (
                      <span className="px-1.5 text-muted-foreground" aria-label="стало">→</span>
                    )}
                    {event.to !== null && <span>{formatEventValue(event.to)}</span>}
                  </div>
                )}
                {event.note && event.kind !== 'field' && (
                  <div className="pt-0.5 text-[13px] text-muted-foreground">{event.note}</div>
                )}
              </div>
            ))}
          </Card>
        </TabsContent>

        <TabsContent value="send">
          <DocSendTab doc={d} companyId={companyId} onChanged={refresh} />
        </TabsContent>
        <TabsContent value="archive">
          <DocArchiveTab doc={d} companyId={companyId} />
        </TabsContent>
        <TabsContent value="access">
          <DocAccessTab doc={d} companyId={companyId} />
        </TabsContent>
      </Tabs>
      {registerOpen && (
        <DocRegisterDialog pending={register.isPending} allowManual={isCompanyAdmin}
          onClose={() => setRegisterOpen(false)}
          onConfirm={(values) => register.mutate(values)} />
      )}
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const label = DOC_STATUS[status]?.label ?? status
  const className = status === 'cancelled'
    ? 'bg-destructive/10 text-destructive'
    : status === 'in_force' || status === 'executed'
      ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
      : status === 'registered'
        ? 'bg-sky-500/10 text-sky-700 dark:text-sky-300'
        : 'bg-muted text-muted-foreground'
  return <span className={`rounded-md px-2 py-1 text-xs ${className}`}>{label}</span>
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 bg-card px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="truncate text-[13px] font-medium" title={value}>{value}</div>
    </div>
  )
}

function Lifecycle({ status }: { status: string }) {
  const normal = ['draft', 'registered', 'in_force', 'executed', 'archived']
  const current = normal.indexOf(status)
  return (
    <div className="scroll-px-2 overflow-x-auto px-2" aria-label="Жизненный цикл документа">
      <ol className="flex min-w-max items-center gap-1 pr-3">
        {normal.map((item, index) => {
          const reached = current >= index
          const active = status === item
          return (
            <li key={item} className="flex items-center">
              <span aria-current={active ? 'step' : undefined}
                className={active
                  ? 'rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground'
                  : reached
                    ? 'rounded-md bg-primary/10 px-2.5 py-1 text-xs text-primary'
                    : 'rounded-md px-2.5 py-1 text-xs text-muted-foreground'}>
                {DOC_STATUS[item].label}
              </span>
              {index < normal.length - 1 && <span className="mx-1 h-px w-4 bg-border" />}
            </li>
          )
        })}
        {status === 'cancelled' && (
          <li className="ml-2 rounded-md bg-destructive/10 px-2.5 py-1 text-xs text-destructive">
            Отменён
          </li>
        )}
      </ol>
    </div>
  )
}

function AttrField({ field, value, disabled, onCommit }: {
  field: DocKindField
  value: unknown
  disabled: boolean
  onCommit: (value: unknown) => void
}) {
  const label = `${field.label}${field.required ? ' *' : ''}`
  if (field.type === 'select') {
    return (
      <Field label={label}>
        {(controlId) => <select id={controlId} defaultValue={String(value ?? '')}
          disabled={disabled} required={field.required} aria-required={field.required}
          className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
          onChange={(event) => onCommit(event.target.value)}>
          <option value="">Не выбрано</option>
          {(field.options ?? []).map((option) => <option key={option}>{option}</option>)}
        </select>}
      </Field>
    )
  }
  if (field.type === 'boolean') {
    return (
      <Field label={label}>
        {(controlId) => <label htmlFor={controlId}
          className="flex h-9 items-center gap-2 rounded-md border border-input px-3 text-sm">
          <input id={controlId} type="checkbox" defaultChecked={value === true}
            disabled={disabled} aria-required={field.required}
            onChange={(event) => onCommit(event.target.checked)} />
          {value === true ? 'Да' : 'Нет'}
        </label>}
      </Field>
    )
  }
  if (field.type === 'textarea') {
    return (
      <div className="sm:col-span-2">
        <Field label={label}>
          {(controlId) => <Textarea id={controlId} defaultValue={String(value ?? '')}
            rows={2} disabled={disabled} required={field.required} aria-required={field.required}
            className="disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
            onBlur={(event) => event.target.value !== String(value ?? '')
              && onCommit(event.target.value)} />}
        </Field>
      </div>
    )
  }
  return (
    <Field label={label}>
      {(controlId) => <Input id={controlId}
        type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
        defaultValue={String(value ?? '')}
        className="h-9 disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
        disabled={disabled} required={field.required} aria-required={field.required}
        onBlur={(event) => {
          if (event.target.value === String(value ?? '')) return
          onCommit(field.type === 'number'
            ? event.target.value === '' ? null : Number(event.target.value)
            : event.target.value)
        }} />}
    </Field>
  )
}

function Field({ label, children }: {
  label: string
  children: (controlId: string) => React.ReactNode
}) {
  const controlId = useId()
  return (
    <div className="space-y-1.5">
      <Label htmlFor={controlId} className="text-xs text-muted-foreground">{label}</Label>
      {children(controlId)}
    </div>
  )
}

function DocLoadState({ onBack, error, onRetry }: {
  onBack: () => void
  error?: string
  onRetry?: () => void
}) {
  return (
    <div className="space-y-3 p-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft className="mr-1.5 h-4 w-4" />Вернуться в реестр
      </Button>
      {error ? (
        <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-4">
          <div className="text-sm font-medium text-destructive">Документ не загрузился</div>
          <div className="mt-1 text-sm text-muted-foreground">{error}</div>
          {onRetry && <Button size="sm" variant="outline" className="mt-3" onClick={onRetry}>Повторить</Button>}
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">Загрузка документа…</div>
      )}
    </div>
  )
}

function StrictAccessGate({ security, password, reason, ttl, pending, onBack,
  onPassword, onReason, onTtl, onActivate }: {
  security: docsService.DocSecurityState
  password: string
  reason: string
  ttl: number
  pending: boolean
  onBack: () => void
  onPassword: (value: string) => void
  onReason: (value: string) => void
  onTtl: (value: number) => void
  onActivate: () => void
}) {
  const ready = password.length > 0 && reason.trim().length >= 20
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft className="mr-1.5 h-4 w-4" />Вернуться в реестр
      </Button>
      <Card className="border-destructive/40">
        <div className="space-y-4 p-5">
          <div className="flex items-start gap-3">
            <LockKeyhole className="mt-0.5 h-5 w-5 text-destructive" />
            <div>
              <div className="font-semibold">Содержимое закрыто строгой политикой</div>
              <p className="mt-1 text-sm text-muted-foreground">
                {security.kind_code} · {security.reg_number || 'без регистрационного номера'} · {security.status}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                Аварийный режим разрешает только чтение, скачивание и печать. Правка,
                отправка, экспорт, согласование и управление доступом останутся запрещены.
              </p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor={`emergency-password-${security.id}`}>Подтвердите пароль</Label>
              <Input id={`emergency-password-${security.id}`} type="password"
                autoComplete="current-password" value={password}
                onChange={(event) => onPassword(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`emergency-ttl-${security.id}`}>Срок доступа</Label>
              <select id={`emergency-ttl-${security.id}`} value={ttl}
                onChange={(event) => onTtl(Number(event.target.value))}
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
                <option value={5}>5 минут</option>
                <option value={15}>15 минут</option>
                <option value={30}>30 минут</option>
                <option value={60}>60 минут</option>
              </select>
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor={`emergency-reason-${security.id}`}>
                Причина, не менее 20 символов
              </Label>
              <Textarea id={`emergency-reason-${security.id}`} value={reason}
                onChange={(event) => onReason(event.target.value)} rows={3}
                placeholder="Опишите инцидент и почему штатного доступа недостаточно" />
            </div>
          </div>
          <ConfirmActionDialog
            trigger={(
              <Button variant="destructive" disabled={!ready || pending}>
                <KeyRound className="mr-1.5 h-4 w-4" />Открыть аварийный доступ
              </Button>
            )}
            title={`Открыть доступ на ${ttl} минут?`}
            description="Действие и каждое использование будут записаны в аудит. Ответственные получат уведомление."
            confirmLabel="Открыть доступ"
            destructive
            onConfirm={onActivate}
          />
        </div>
      </Card>
    </div>
  )
}

function formatEventTime(value: string | null): string {
  if (!value) return 'время не указано'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short', timeStyle: 'short', timeZone: 'Europe/Moscow',
  }).format(date)
}

function formatEventValue(value: string): string {
  if (!value) return 'не заполнено'
  return EVENT_VALUE[value] ?? value
}

export default DocCardPanel
