/**
 * Карточка документа: реквизиты, обработка, файлы, связи и доказуемая история.
 *
 * Состояние меняется только контекстными действиями. Регистрационный номер,
 * пакет согласования и редакции файла показываются как факты, а не поля формы.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive, ArrowLeft, Ban, CheckCheck, FileCheck2, FileUp, KeyRound, Link2,
  ListChecks, LockKeyhole, Paperclip, Printer, Send, Stamp, Workflow,
} from 'lucide-react'
import { toast } from 'sonner'
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
import { DocApprovalTab } from './DocApprovalTab'
import { DocSendTab } from './DocSendTab'

const ROLE_LABEL: Record<string, string> = {
  body: 'Документ',
  appendix: 'Приложение',
  signed_scan: 'Подписанный экземпляр',
  attachment: 'Вложение',
}

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

export function DocCardPanel({ id, companyId, onBack, onChanged }: {
  id: string
  companyId: string
  onBack: () => void
  onChanged: () => void
}) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [manualNumber, setManualNumber] = useState('')
  const [note, setNote] = useState('')
  const [activeTab, setActiveTab] = useState('document')
  const [reasonMode, setReasonMode] = useState<'cancel' | 'cancel_approval' | null>(null)
  const [reason, setReason] = useState('')

  const q = useQuery({
    queryKey: ['doc', id, companyId],
    queryFn: () => docsService.getDoc(companyId, id),
  })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['doc', id, companyId] })
    onChanged()
  }

  const register = useMutation({
    mutationFn: () => docsService.registerDoc(companyId, id, manualNumber.trim() || undefined),
    onSuccess: (d) => {
      toast.success(`Зарегистрирован: ${d.reg_number}`)
      setManualNumber('')
      refresh()
    },
    onError: (e) => toast.error(`Не зарегистрирован: ${(e as Error).message}`),
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
    mutationFn: (file: File) => docsService.uploadVersion(companyId, id, file),
    onSuccess: (result) => {
      toast.success(result.duplicate ? 'Такой файл уже приложен' : `Редакция ${result.revision}`)
      refresh()
    },
    onError: (e) => toast.error(`Файл не принят: ${(e as Error).message}`),
  })

  if (q.isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  if (q.isError) {
    return <div className="p-6 text-sm text-destructive">{(q.error as Error).message}</div>
  }
  const d = q.data
  if (!d) return <div className="p-6 text-sm text-muted-foreground">Документ не найден</div>

  const registered = Boolean(d.reg_number)
  const actions = new Set(d.available_actions ?? [])
  const editable = actions.has('edit')
  const approvalLocked = d.approval_status === 'pending'

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
    <div className="space-y-4">
      <header className="border-b border-border bg-background py-3 md:sticky md:top-0 md:z-20">
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
                {d.counterparty_name ? ` · ${d.counterparty_name}` : ''}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {registered && (
              <Button size="sm" variant="outline" onClick={() => setActiveTab('send')}>
                <Send className="mr-1.5 h-4 w-4" />Отправка
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => setActiveTab('access')}>
              <KeyRound className="mr-1.5 h-4 w-4" />Доступ
            </Button>
            {registered && (
              <Button size="sm" variant="outline" title="Печатная форма"
                onClick={() => window.open(
                  `/api/docs/${d.id}/print?company_id=${companyId}`, '_blank')}>
                <Printer className="mr-1.5 h-4 w-4" />Печать
              </Button>
            )}
          </div>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="Текущая редакция"
            value={d.current_revision ? `Редакция ${d.current_revision}` : 'Основной файл не приложен'} />
          <Fact label="Согласование" value={APPROVAL_LABEL[d.approval_status] ?? d.approval_status} />
          <Fact label="Хранение" value={d.storage_until ? `До ${d.storage_until}` : 'Срок не зафиксирован'} />
          <Fact label="Доступ"
            value={d.confidentiality === 'private' ? 'Ограниченный' : 'Всё пространство'} />
        </div>

        <Lifecycle status={d.status} />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {actions.has('register') && (
            <>
              <Input value={manualNumber} onChange={(event) => setManualNumber(event.target.value)}
                placeholder="или номер вручную" className="h-9 w-44 text-sm" />
              <Button size="sm" onClick={() => register.mutate()} disabled={register.isPending}>
                <Stamp className="mr-1.5 h-4 w-4" />Зарегистрировать
              </Button>
            </>
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
          <div className="mt-2 flex max-w-2xl flex-wrap items-center gap-2 rounded-md border border-border bg-muted/30 p-2">
            <Input value={reason} onChange={(event) => setReason(event.target.value)}
              placeholder={reasonMode === 'cancel' ? 'Причина отмены документа' : 'Почему отменяется круг'}
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
      </header>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="h-auto max-w-full justify-start overflow-x-auto">
          <TabsTrigger value="document">Документ</TabsTrigger>
          <TabsTrigger value="processing">
            Обработка{approvalLocked || d.acquaints.some((item) => item.status === 'pending') ? ' •' : ''}
          </TabsTrigger>
          <TabsTrigger value="files">Файлы и подписи{d.versions.length ? ` (${d.versions.length})` : ''}</TabsTrigger>
          <TabsTrigger value="links">Связи{d.relations.length ? ` (${d.relations.length})` : ''}</TabsTrigger>
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
            <Field label="Заголовок">
              <Input defaultValue={d.title}
                className="h-9 disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                disabled={!editable}
                onBlur={(event) => event.target.value.trim() !== d.title
                  && act.mutate({ title: event.target.value.trim() })} />
            </Field>
            <Field label={d.direction === 'in' ? 'От кого' : 'Кому'}>
              <Input defaultValue={d.counterparty_name}
                className="h-9 disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                disabled={!editable}
                onBlur={(event) => event.target.value !== d.counterparty_name
                  && act.mutate({ counterparty_name: event.target.value })} />
            </Field>
            <Field label="Их номер">
              <Input defaultValue={d.external_number ?? ''}
                className="h-9 disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                disabled={!editable}
                onBlur={(event) => event.target.value !== (d.external_number ?? '')
                  && act.mutate({ external_number: event.target.value })} />
            </Field>
            <Field label="Дата их документа">
              <Input type="date" defaultValue={d.external_date ?? ''}
                className="h-9 disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                disabled={!editable}
                onBlur={(event) => event.target.value !== (d.external_date ?? '')
                  && act.mutate({ external_date: event.target.value || null })} />
            </Field>
            <Field label="Доступ">
              <select value={d.confidentiality} disabled={!editable}
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                onChange={(event) => act.mutate({ confidentiality: event.target.value })}>
                <option value="company">Всё пространство</option>
                <option value="private">Ограниченный доступ</option>
              </select>
            </Field>
            <Field label="Состояние">
              <div className="flex h-9 items-center rounded-md border border-input bg-muted/30 px-3 text-sm">
                {DOC_STATUS[d.status]?.label ?? d.status}
              </div>
            </Field>
            {(d.kind?.fields ?? []).map((field) => (
              <AttrField key={field.code} field={field} value={d.attrs[field.code]}
                disabled={!editable} onCommit={(value) => updateAttr(field, value)} />
            ))}
            <div className="sm:col-span-2">
              <Field label="Краткое содержание">
                <Textarea defaultValue={d.summary ?? ''} rows={3} disabled={!editable}
                  className="disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
                  onBlur={(event) => event.target.value !== (d.summary ?? '')
                    && act.mutate({ summary: event.target.value })} />
              </Field>
            </div>
          </Card>

          <Card className="space-y-2 p-4">
            <Label className="text-xs">Реплика в историю</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input value={note} onChange={(event) => setNote(event.target.value)}
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
            <DocAcquaintTab doc={d} companyId={companyId} onChanged={refresh} />
          </section>
        </TabsContent>

        <TabsContent value="files" className="space-y-3 pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <input ref={fileRef} type="file" className="hidden" onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) attach.mutate(file)
              event.target.value = ''
            }} />
            <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()}
              disabled={!editable || attach.isPending}>
              <FileUp className="mr-1.5 h-4 w-4" />Приложить файл
            </Button>
            <span className="text-xs text-muted-foreground">
              Каждый файл опознаётся SHA-256; во время согласования набор неизменяем.
            </span>
          </div>
          <Card className="divide-y divide-border/60">
            {d.versions.map((version) => (
              <div key={version.id} className="flex items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <a href={`/api/files/${version.file_id}`} target="_blank" rel="noreferrer"
                    className="flex items-center gap-1.5 text-sm hover:underline">
                    <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{version.file_name}</span>
                  </a>
                  <div className="text-[11px] text-muted-foreground">
                    {ROLE_LABEL[version.role] ?? version.role} · редакция {version.revision}
                    {version.is_current ? ' · действующая' : ''}
                    {' · '}{Math.round(version.size / 1024)} КБ
                  </div>
                </div>
                <span className="shrink-0 font-mono text-[10px] text-muted-foreground"
                  title={version.sha256}>{version.sha256.slice(0, 12)}…</span>
              </div>
            ))}
            {d.versions.length === 0 && (
              <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                Файлов пока нет
              </div>
            )}
          </Card>
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
        <TabsContent value="access">
          <DocAccessTab doc={d} companyId={companyId} />
        </TabsContent>
      </Tabs>
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
    <div className="min-w-0 rounded-md border border-border bg-card px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="truncate text-xs font-medium" title={value}>{value}</div>
    </div>
  )
}

function Lifecycle({ status }: { status: string }) {
  const normal = ['draft', 'registered', 'in_force', 'executed', 'archived']
  const current = normal.indexOf(status)
  return (
    <div className="mt-3 overflow-x-auto" aria-label="Жизненный цикл документа">
      <ol className="flex min-w-max items-center gap-1">
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
        <select defaultValue={String(value ?? '')} disabled={disabled}
          className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
          onChange={(event) => onCommit(event.target.value)}>
          <option value="">Не выбрано</option>
          {(field.options ?? []).map((option) => <option key={option}>{option}</option>)}
        </select>
      </Field>
    )
  }
  if (field.type === 'boolean') {
    return (
      <Field label={label}>
        <label className="flex h-9 items-center gap-2 rounded-md border border-input px-3 text-sm">
          <input type="checkbox" defaultChecked={value === true} disabled={disabled}
            onChange={(event) => onCommit(event.target.checked)} />
          {value === true ? 'Да' : 'Нет'}
        </label>
      </Field>
    )
  }
  if (field.type === 'textarea') {
    return (
      <div className="sm:col-span-2">
        <Field label={label}>
          <Textarea defaultValue={String(value ?? '')} rows={2} disabled={disabled}
            className="disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
            onBlur={(event) => event.target.value !== String(value ?? '')
              && onCommit(event.target.value)} />
        </Field>
      </div>
    )
  }
  return (
    <Field label={label}>
      <Input type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
        defaultValue={String(value ?? '')}
        className="h-9 disabled:cursor-default disabled:opacity-100 disabled:text-foreground"
        disabled={disabled}
        onBlur={(event) => {
          if (event.target.value === String(value ?? '')) return
          onCommit(field.type === 'number'
            ? event.target.value === '' ? null : Number(event.target.value)
            : event.target.value)
        }} />
    </Field>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
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
