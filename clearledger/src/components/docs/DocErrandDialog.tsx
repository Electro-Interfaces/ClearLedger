import { useId, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ListChecks } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
  DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import * as docsService from '@/services/docsService'
import * as tasksService from '@/services/tasksService'

export function DocErrandDialog({ companyId, doc, onCreated }: {
  companyId: string
  doc: docsService.DocDetails
  onCreated: (taskId: string, number: number) => void
}) {
  const prefix = useId()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState(`Исполнить: ${doc.title}`)
  const [description, setDescription] = useState('')
  const [assigneeId, setAssigneeId] = useState(doc.responsible_id ?? '')
  const [dueAt, setDueAt] = useState(doc.due_at?.slice(0, 16) ?? '')
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })
  const create = useMutation({
    mutationFn: () => docsService.createErrand(companyId, doc.id, {
      title: title.trim(), assignee_id: assigneeId,
      description: description.trim() || null,
      due_at: dueAt ? new Date(dueAt).toISOString() : null,
    }),
    onSuccess: (result) => {
      toast.success(`Поручение №${result.number} поставлено`)
      setOpen(false)
      onCreated(result.task_id, result.number)
    },
    onError: (error) => toast.error((error as Error).message),
  })
  const people = peopleQ.data?.people ?? []
  const ready = title.trim().length >= 3 && !!assigneeId && peopleQ.isSuccess

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!create.isPending) setOpen(next) }}>
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="outline">
          <ListChecks className="mr-1.5 h-4 w-4" />Поручить
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Поручение по документу</DialogTitle>
          <DialogDescription>
            Задача появится в разделе «На мне» у исполнителя и останется связана с документом.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          {peopleQ.isError && (
            <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-destructive/30 p-3 text-sm">
              <span>Сотрудники не загрузились. Постановка заблокирована.</span>
              <Button type="button" size="sm" variant="outline" onClick={() => peopleQ.refetch()}>Повторить</Button>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor={`${prefix}-title`}>Что сделать</Label>
            <Input id={`${prefix}-title`} value={title} maxLength={300}
              onChange={(event) => setTitle(event.target.value)} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor={`${prefix}-assignee`}>Исполнитель</Label>
              <select id={`${prefix}-assignee`} value={assigneeId}
                disabled={!peopleQ.isSuccess} onChange={(event) => setAssigneeId(event.target.value)}
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
                <option value="">выберите сотрудника</option>
                {people.map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${prefix}-due`}>Срок</Label>
              <Input id={`${prefix}-due`} type="datetime-local" value={dueAt}
                onChange={(event) => setDueAt(event.target.value)} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${prefix}-description`}>Описание</Label>
            <Textarea id={`${prefix}-description`} rows={4} value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={`Основание: ${doc.reg_number ?? doc.title}`} />
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={create.isPending}>Отмена</Button>
          <Button type="button" onClick={() => create.mutate()} disabled={!ready || create.isPending}>
            {create.isPending ? 'Ставим…' : 'Поставить поручение'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
