/**
 * Карточка документа: реквизиты, регистрация, редакции файла, связи и след.
 *
 * Регистрация — отдельная кнопка, а не поле формы: номер выдаётся счётчиком
 * компании, остаётся за документом навсегда и не переписывается даже при отмене.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, FileUp, ListChecks, Paperclip, Printer, Stamp,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { toast } from 'sonner'
import * as docsService from '@/services/docsService'
import { DOC_STATUS } from '@/services/docsService'
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
  errand: 'поручение',
  relation: 'связь',
  comment: 'реплика',
  mail: 'письмо',
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
    onSuccess: () => { setNote(''); refresh() },
    onError: (e) => toast.error(`Не сохранилось: ${(e as Error).message}`),
  })

  const attach = useMutation({
    mutationFn: (file: File) => docsService.uploadVersion(companyId, id, file),
    onSuccess: (r) => {
      toast.success(r.duplicate ? 'Такой файл уже приложен' : `Редакция ${r.revision}`)
      refresh()
    },
    onError: (e) => toast.error(`Файл не принят: ${(e as Error).message}`),
  })

  if (q.isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  const d = q.data
  if (!d) return <div className="p-6 text-sm text-muted-foreground">Документ не найден</div>

  const registered = !!d.reg_number

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <Button variant="ghost" size="sm" onClick={onBack} className="mt-0.5">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold">{d.title}</h1>
              <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs">
                {DOC_STATUS[d.status]?.label ?? d.status}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              {d.kind_name}
              {registered
                ? ` · ${d.reg_number} от ${d.reg_date}`
                : ' · номер не присвоен'}
              {d.counterparty_name ? ` · ${d.counterparty_name}` : ''}
              {d.storage_until ? ` · хранить до ${d.storage_until}` : ''}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {registered && (
            <Button size="sm" variant="outline" title="Печатная форма"
              onClick={() => window.open(
                `/api/docs/${d.id}/print?company_id=${companyId}`, '_blank')}>
              <Printer className="mr-1.5 h-4 w-4" />Печать
            </Button>
          )}
        </div>
        {!registered && (
          <div className="flex items-center gap-2">
            <Input value={manualNumber} onChange={(e) => setManualNumber(e.target.value)}
              placeholder="или номер вручную" className="h-9 w-44 text-sm" />
            <Button size="sm" onClick={() => register.mutate()} disabled={register.isPending}>
              <Stamp className="mr-1.5 h-4 w-4" />Зарегистрировать
            </Button>
          </div>
        )}
      </div>

      <Tabs defaultValue="card">
        <TabsList>
          <TabsTrigger value="card">Карточка</TabsTrigger>
          <TabsTrigger value="approval">
            Согласование{d.approval?.status === 'pending' ? ' •' : ''}
          </TabsTrigger>
          <TabsTrigger value="files">
            Файлы{d.versions.length ? ` (${d.versions.length})` : ''}
          </TabsTrigger>
          <TabsTrigger value="links">
            Связи{d.relations.length ? ` (${d.relations.length})` : ''}
          </TabsTrigger>
          <TabsTrigger value="send">Отправка</TabsTrigger>
          <TabsTrigger value="feed">История</TabsTrigger>
        </TabsList>

        <TabsContent value="card" className="space-y-3 pt-3">
          <Card className="grid gap-3 p-4 sm:grid-cols-2">
            <Field label="Заголовок">
              <Input defaultValue={d.title} className="h-9"
                onBlur={(e) => e.target.value.trim() !== d.title
                  && act.mutate({ title: e.target.value.trim() })} />
            </Field>
            <Field label={d.direction === 'in' ? 'От кого' : 'Кому'}>
              <Input defaultValue={d.counterparty_name} className="h-9"
                onBlur={(e) => e.target.value !== d.counterparty_name
                  && act.mutate({ counterparty_name: e.target.value })} />
            </Field>
            <Field label="Их номер">
              <Input defaultValue={d.external_number ?? ''} className="h-9"
                onBlur={(e) => e.target.value !== (d.external_number ?? '')
                  && act.mutate({ external_number: e.target.value })} />
            </Field>
            <Field label="Дата их документа">
              <Input type="date" defaultValue={d.external_date ?? ''} className="h-9"
                onBlur={(e) => e.target.value !== (d.external_date ?? '')
                  && act.mutate({ external_date: e.target.value || null })} />
            </Field>
            <Field label="Состояние">
              <select value={d.status} className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                onChange={(e) => act.mutate({ status: e.target.value })}>
                {Object.entries(DOC_STATUS).map(([k, v]) => (
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Доступ">
              <select value={d.confidentiality}
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                onChange={(e) => act.mutate({ confidentiality: e.target.value })}>
                <option value="company">Всё пространство</option>
                <option value="private">Только автор, ответственный и подписант</option>
              </select>
            </Field>
            <div className="sm:col-span-2">
              <Field label="Краткое содержание">
                <Textarea defaultValue={d.summary ?? ''} rows={2}
                  onBlur={(e) => e.target.value !== (d.summary ?? '')
                    && act.mutate({ summary: e.target.value })} />
              </Field>
            </div>
          </Card>

          <Card className="space-y-2 p-4">
            <Label className="text-xs">Реплика в историю</Label>
            <div className="flex gap-2">
              <Input value={note} onChange={(e) => setNote(e.target.value)}
                placeholder="Что важно зафиксировать по документу" className="h-9" />
              <Button size="sm" variant="outline" disabled={!note.trim() || act.isPending}
                onClick={() => act.mutate({ note: note.trim() })}>
                Записать
              </Button>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="approval">
          <DocApprovalTab doc={d} companyId={companyId} onChanged={refresh} />
        </TabsContent>

        <TabsContent value="files" className="space-y-3 pt-3">
          <div className="flex items-center gap-2">
            <input ref={fileRef} type="file" className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) attach.mutate(f)
                e.target.value = ''
              }} />
            <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()}
              disabled={attach.isPending}>
              <FileUp className="mr-1.5 h-4 w-4" />Приложить файл
            </Button>
            <span className="text-xs text-muted-foreground">
              Тот же файл повторно новой редакции не создаёт
            </span>
          </div>
          <Card className="divide-y divide-border/60">
            {d.versions.map((v) => (
              <div key={v.id} className="flex items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <a href={`/api/files/${v.file_id}`} target="_blank" rel="noreferrer"
                    className="flex items-center gap-1.5 text-sm hover:underline">
                    <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{v.file_name}</span>
                  </a>
                  <div className="text-[11px] text-muted-foreground">
                    {ROLE_LABEL[v.role] ?? v.role} · редакция {v.revision}
                    {v.is_current ? ' · действующая' : ''}
                    {' · '}{Math.round(v.size / 1024)} КБ
                  </div>
                </div>
              </div>
            ))}
            {d.versions.length === 0 && (
              <div className="px-3 py-6 text-center text-sm text-muted-foreground">
                Файлов пока нет
              </div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="links" className="pt-3">
          <Card className="divide-y divide-border/60">
            {d.relations.map((r) => (
              <div key={r.id} className="flex items-center gap-2 px-3 py-2 text-sm">
                <ListChecks className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-muted-foreground">{r.kind}</span>
                <span className="font-mono text-xs">{r.target_ref}</span>
              </div>
            ))}
            {d.relations.length === 0 && (
              <div className="px-3 py-6 text-center text-sm text-muted-foreground">
                Связей пока нет
              </div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="send">
          <DocSendTab doc={d} companyId={companyId} onChanged={refresh} />
        </TabsContent>

        <TabsContent value="feed" className="pt-3">
          <Card className="divide-y divide-border/60">
            {d.events.map((e) => (
              <div key={e.id} className="px-3 py-2 text-sm">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-xs text-muted-foreground">
                    {(e.created_at ?? '').slice(0, 16).replace('T', ' ')}
                  </span>
                  <span className="font-medium">{e.actor ?? 'Система'}</span>
                  <span className="text-muted-foreground">
                    {EVENT_LABEL[e.kind] ?? e.kind}
                  </span>
                  {e.to && <span className="text-xs">{e.to}</span>}
                </div>
                {e.note && <div className="pt-0.5 text-[13px]">{e.note}</div>}
              </div>
            ))}
          </Card>
        </TabsContent>
      </Tabs>
    </div>
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

export default DocCardPanel
