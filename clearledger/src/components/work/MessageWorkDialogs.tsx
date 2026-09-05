import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import * as chat from '@/services/chatService'
import type { ChatMessage } from '@/services/chatService'
import * as docsService from '@/services/docsService'
import { listTaskPeople } from '@/services/tasksService'
import { resolveWorkContext } from '@/services/workContextService'
import { WorkContextPicker } from './WorkContextPicker'

export function TaskFromMessageDialog({ message, companyId, subjectRef, onClose, onDone }: {
  message: ChatMessage
  companyId: string
  subjectRef?: string | null
  onClose: () => void
  onDone: (result: Awaited<ReturnType<typeof chat.taskFromMessage>>) => void
}) {
  const [contextRef, setContextRef] = useState(subjectRef ?? null)
  const src = (message.content || message.fileName || '').trim()
  const [title, setTitle] = useState(() => src.slice(0, 300))
  const [assigneeId, setAssigneeId] = useState('')
  const [dueAt, setDueAt] = useState('')

  const contextQ = useQuery({ queryKey: ['work-context', companyId, contextRef], queryFn: () => resolveWorkContext(companyId, contextRef!), enabled: !!contextRef })
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => listTaskPeople(companyId),
    enabled: !!companyId, staleTime: 5 * 60 * 1000,
  })
  const send = useMutation({
    mutationFn: () => chat.taskFromMessage(message.id, {
      title: title.trim(),
      subjectRef: contextRef,
      assigneeId: assigneeId || undefined,
      dueAt: dueAt ? new Date(`${dueAt}T00:00`).toISOString() : undefined,
    }),
    onSuccess: onDone,
    onError: (e) => toast.error((e as Error).message || 'Не удалось поставить поручение'),
  })

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-sm gap-0 p-0 sm:max-w-sm">
        <DialogHeader className="border-b border-border/50 px-4 py-3">
          <DialogTitle className="text-sm">Поручение по сообщению</DialogTitle>
          <DialogDescription className="text-xs">
            Сообщение станет основанием: в чате останется ссылка на поручение.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 px-4 py-3">
          <WorkContextPicker companyId={companyId} value={contextRef} onChange={setContextRef} />
          {contextQ.data && <Button type="button" size="sm" variant="outline" onClick={() => { setAssigneeId(contextQ.data!.defaults.responsible_id || ''); setTitle(contextQ.data!.defaults.title || title) }}>Применить настройки приложения</Button>}
          {message.fileName && <p className="text-xs text-muted-foreground">Вложение: {message.fileName}</p>}
          <div className="space-y-1">
            <Label className="text-xs">Что сделать</Label>
            <Input aria-label="Тема работы" value={title} maxLength={300} className="h-8 text-xs"
              onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Кому</Label>
            <Select value={assigneeId || 'none'}
              onValueChange={(v) => setAssigneeId(v === 'none' ? '' : v)}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Пока никому</SelectItem>
                {(peopleQ.data?.people ?? []).map((person) => (
                  <SelectItem key={person.id} value={person.id}>{person.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">К какому сроку</Label>
            <Input aria-label="Срок" type="date" value={dueAt} className="h-8 text-xs"
              onChange={(e) => setDueAt(e.target.value)} />
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-border/50 px-4 py-3">
          <Button size="sm" variant="ghost" className="h-8" onClick={onClose}>Отмена</Button>
          <Button size="sm" className="h-8"
            disabled={title.trim().length < 3 || send.isPending}
            onClick={() => send.mutate()}>
            {send.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Поручить
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function ProcessFromMessageDialog({ message, companyId, subjectRef, onClose, onDone }: {
  message: ChatMessage
  companyId: string
  subjectRef?: string | null
  onClose: () => void
  onDone: (result: Awaited<ReturnType<typeof chat.processFromMessage>>) => void
}) {
  const [contextRef, setContextRef] = useState(subjectRef ?? null)
  const src = (message.content || message.fileName || '').trim()
  const [templateId, setTemplateId] = useState('')
  const [responsibleId, setResponsibleId] = useState('')
  const [title, setTitle] = useState(() => src.slice(0, 300))
  const [dueAt, setDueAt] = useState('')
  const [busy, setBusy] = useState(false)

  const templatesQ = useQuery({
    queryKey: ['process-templates', companyId],
    queryFn: () => docsService.listProcessTemplates(companyId),
    enabled: !!companyId, staleTime: 5 * 60 * 1000,
  })
  const contextQ = useQuery({ queryKey: ['work-context', companyId, contextRef], queryFn: () => resolveWorkContext(companyId, contextRef!), enabled: !!contextRef })
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => listTaskPeople(companyId),
    enabled: !!companyId, staleTime: 5 * 60 * 1000,
  })
  const templates = templatesQ.data?.templates ?? []
  const selected = templates.find((template) => template.id === templateId)

  const send = async () => {
    if (!templateId) return
    setBusy(true)
    try {
      const res = await chat.processFromMessage(message.id, {
        templateId,
        subjectRef: contextRef,
        dueAt: dueAt ? new Date(`${dueAt}T18:00`).toISOString() : undefined,
        responsibleId: responsibleId || undefined,
        title: selected?.kind === 'task' ? title.trim() : undefined,
      })
      onDone(res)
    } catch (e) {
      toast.error((e as Error).message || 'Не удалось запустить процесс')
    } finally { setBusy(false) }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-sm gap-0 p-0 sm:max-w-sm">
        <DialogHeader className="border-b border-border/50 px-4 py-3">
          <DialogTitle className="text-sm">Запустить процесс из сообщения</DialogTitle>
          <DialogDescription className="sr-only">
            Выберите шаблон процесса и первого ответственного сотрудника.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 p-4">
          <WorkContextPicker companyId={companyId} value={contextRef} onChange={setContextRef} />
          {contextQ.data && <Button type="button" size="sm" variant="outline" onClick={() => { setResponsibleId(contextQ.data!.defaults.responsible_id || ''); setTemplateId(contextQ.data!.defaults.template_ids?.[0] || templateId) }}>Применить настройки приложения</Button>}
          {message.fileName && <p className="text-xs text-muted-foreground">Вложение: {message.fileName}</p>}
          <label className="block space-y-1 text-sm">Срок<Input aria-label="Срок" type="date" value={dueAt} onChange={(e) => setDueAt(e.target.value)} /></label>
          <p className="max-h-20 overflow-hidden rounded-md bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground">
            {message.userName ? `${message.userName}: ` : ''}{src || 'вложение'}
          </p>
          <div className="space-y-1">
            <Label className="text-xs">Шаблон процесса</Label>
            <Select value={templateId} onValueChange={(value) => {
              setTemplateId(value)
              const template = templates.find((item) => item.id === value)
              setResponsibleId(template?.defaultResponsibleId ?? '')
              setTitle(template?.kind === 'task' ? src.slice(0, 300) : template?.title ?? '')
            }}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder={templatesQ.isLoading ? 'Загрузка…' : 'Выберите шаблон'} />
              </SelectTrigger>
              <SelectContent>
                {templates.map((template) => (
                  <SelectItem key={template.id} value={template.id}>{template.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {templatesQ.isError && (
            <p className="text-xs text-destructive">Не удалось загрузить доступные шаблоны.</p>
          )}
          {!templatesQ.isLoading && !templatesQ.isError && templates.length === 0 && (
            <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
              Доступных шаблонов процессов нет. Их создают в
              «Трек → Настройка → Шаблоны».
            </p>
          )}
          {selected && (
            <div className="rounded-md bg-muted/40 px-2.5 py-2 text-xs">
              <div className="font-medium">{selected.title}</div>
              <div className="mt-0.5 text-muted-foreground">
                {selected.kind === 'task' ? selected.taskTypeName : selected.docKindName}
                {' · '}этапов: {selected.steps}
                {selected.dueDays != null && ` · срок ${selected.dueDays} дн.`}
              </div>
              {selected.kind === 'task' && (
                <div className="mt-1 text-muted-foreground">
                  Исполнитель сможет передать работу дальше; комментарии и файлы останутся в истории.
                </div>
              )}
              {selected.requiresPreparation && (
                <div className="mt-1 text-amber-700 dark:text-amber-400">
                  Сначала подготовка: {selected.preparationReason}.
                </div>
              )}
            </div>
          )}
          {selected?.kind === 'task' && (
            <div className="space-y-1">
              <Label className="text-xs">Тема задачи</Label>
              <Input aria-label="Тема работы" value={title} onChange={(event) => setTitle(event.target.value)}
                maxLength={300} className="h-8 text-xs" placeholder="Что нужно сделать" />
            </div>
          )}
          <div className="space-y-1">
            <Label className="text-xs">
              {selected?.kind === 'task' ? 'Первый исполнитель' : 'Ответственный'}
            </Label>
            <Select value={responsibleId || 'self'}
              onValueChange={(value) => setResponsibleId(value === 'self' ? '' : value)}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="self">Я</SelectItem>
                {(peopleQ.data?.people ?? []).map((person) => (
                  <SelectItem key={person.id} value={person.id}>{person.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Сообщение попадёт в карточку как основание, а в чате останется ссылка на процесс.
          </p>
        </div>
        <DialogFooter className="border-t border-border/50 px-4 py-3">
          <Button size="sm" disabled={busy || !templateId
              || (selected?.kind === 'task' && title.trim().length < 3)} onClick={send}>
            {busy && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}Запустить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
