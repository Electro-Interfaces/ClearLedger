import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { ChatMessage } from '@/services/chatService'
import { resolveWorkContext, runContextAction } from '@/services/workContextService'
import { WorkContextPicker } from './WorkContextPicker'

export function WorkContextActions({ companyId, subjectRef, message, onClose }: {
  companyId: string; subjectRef?: string | null; message: ChatMessage; onClose: () => void
}) {
  const qc = useQueryClient()
  const [ref, setRef] = useState(subjectRef || null)
  const [action, setAction] = useState('')
  const [text, setText] = useState(message.content || '')
  const context = useQuery({ queryKey: ['work-context', companyId, ref], queryFn: () => resolveWorkContext(companyId, ref!), enabled: !!ref })
  const selected = context.data?.actions.find((a) => a.code === action)
  const save = useMutation({ mutationFn: () => runContextAction(companyId, { ref: ref!, action, message_id: message.id, text }),
    onSuccess: async () => { await qc.invalidateQueries(); toast.success('Передано в приложение'); onClose() }, onError: (e) => toast.error(e.message) })
  return <Dialog open onOpenChange={(open) => { if (!open && !save.isPending) onClose() }}><DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
    <DialogHeader><DialogTitle>Действие приложения</DialogTitle><DialogDescription>Сообщение останется основанием выбранного действия.</DialogDescription></DialogHeader>
    <WorkContextPicker companyId={companyId} value={ref} onChange={(value) => { setRef(value); setAction('') }} />
    {context.data && <label className="space-y-2 text-sm">Действие<select aria-label="Действие" className="h-10 w-full rounded-md border bg-background px-3" value={action} onChange={(e) => setAction(e.target.value)}>
      <option value="">Выберите действие</option>{context.data.actions.filter((a) => !a.requires_file || !!message.fileUrl).map((a) => <option key={a.code} value={a.code}>{a.label}</option>)}
    </select></label>}
    {context.data?.actions.length === 0 && <p className="text-sm text-muted-foreground">Приложение поддерживает поручения и процессы по сообщению. Дополнительных действий нет.</p>}
    {selected?.requires_file && <p className="text-sm">Файл: {message.fileName}. Он станет доступен участникам выбранного приложения.</p>}
    {selected?.text_required && <label className="space-y-2 text-sm">Текст решения<Textarea aria-label="Текст решения" value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} /></label>}
    <Button disabled={!ref || !selected || save.isPending || (!!selected.text_required && text.trim().length < 3)} onClick={() => save.mutate()}>{save.isPending ? 'Сохранение…' : selected?.label || 'Выполнить'}</Button>
  </DialogContent></Dialog>
}

export function WorkContextBadge({ companyId, subjectRef }: { companyId: string; subjectRef: string }) {
  const q = useQuery({ queryKey: ['work-context', companyId, subjectRef], queryFn: () => resolveWorkContext(companyId, subjectRef) })
  if (!q.data) return null
  return <Link className="block truncate px-3 py-1.5 text-sm text-primary underline underline-offset-4" to={q.data.url} title={q.data.title}>{q.data.title}</Link>
}
