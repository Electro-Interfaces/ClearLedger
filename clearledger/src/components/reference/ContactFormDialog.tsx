import { useId, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import * as refs from '@/services/referenceService'

export function ContactFormDialog({ counterpartyId, edit, onSaved, children }: {
  counterpartyId: string
  edit?: refs.CounterpartyContact
  onSaved: (contact: refs.CounterpartyContact) => void
  children: React.ReactNode
}) {
  const id = useId()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({
    name: edit?.name ?? '', position: edit?.position ?? '', role: edit?.role ?? 'other',
    phone: edit?.phone ?? '', email: edit?.email ?? '', notes: edit?.notes ?? '',
  })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name.trim(), position: f.position.trim() || null, role: f.role,
        phone: f.phone.trim() || null, email: f.email.trim() || null,
        notes: f.notes.trim() || null,
      }
      return edit
        ? refs.updateCounterpartyContact(counterpartyId, edit.id, body)
        : refs.createCounterpartyContact(counterpartyId, body)
    },
    onSuccess: (contact) => {
      toast.success(edit ? 'Контакт обновлён' : 'Контакт добавлен'); setOpen(false); onSaved(contact)
      void qc.invalidateQueries({ queryKey: ['location-contacts'] })
      void qc.invalidateQueries({ queryKey: ['location-contact-options'] })
      void qc.invalidateQueries({ queryKey: ['cp-contacts', counterpartyId] })
    },
    onError: (e: unknown) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  return (
    <Dialog open={open} onOpenChange={(value) => {
      if (value) setF({ name: edit?.name ?? '', position: edit?.position ?? '', role: edit?.role ?? 'other',
        phone: edit?.phone ?? '', email: edit?.email ?? '', notes: edit?.notes ?? '' })
      setOpen(value)
    }}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{edit ? 'Изменить контакт' : 'Новый контакт'}</DialogTitle>
          <DialogDescription>Данные человека хранятся в общем реестре. Изменения будут видны на всех связанных объектах.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5"><Label htmlFor={`${id}-name`}>ФИО <span className="text-destructive">*</span></Label>
            <Input className="min-h-11" id={`${id}-name`} value={f.name} onChange={(e) => setF((s) => ({ ...s, name: e.target.value }))} /></div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5"><Label htmlFor={`${id}-position`}>Должность</Label>
              <Input className="min-h-11" id={`${id}-position`} value={f.position} onChange={(e) => setF((s) => ({ ...s, position: e.target.value }))} /></div>
            <div className="flex flex-col gap-1.5"><Label htmlFor={`${id}-role`}>Роль</Label>
              <Select value={f.role} onValueChange={(v) => setF((s) => ({ ...s, role: v }))}>
                <SelectTrigger className="min-h-11" id={`${id}-role`}><SelectValue /></SelectTrigger>
                <SelectContent><SelectGroup>
                  {Object.entries(refs.CONTACT_ROLE_LABEL).map(([k, label]) => (
                    <SelectItem key={k} value={k}>{label}</SelectItem>
                  ))}
                </SelectGroup></SelectContent>
              </Select></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5"><Label htmlFor={`${id}-phone`}>Телефон</Label>
              <Input className="min-h-11" id={`${id}-phone`} value={f.phone} onChange={(e) => setF((s) => ({ ...s, phone: e.target.value }))} placeholder="+7 …" /></div>
            <div className="flex flex-col gap-1.5"><Label htmlFor={`${id}-email`}>Почта</Label>
              <Input className="min-h-11" id={`${id}-email`} value={f.email} onChange={(e) => setF((s) => ({ ...s, email: e.target.value }))} /></div>
          </div>
          <div className="flex flex-col gap-1.5"><Label htmlFor={`${id}-notes`}>Примечание</Label>
            <Textarea id={`${id}-notes`} value={f.notes} onChange={(e) => setF((s) => ({ ...s, notes: e.target.value }))} rows={2} /></div>
        </div>
        <DialogFooter>
          <Button className="min-h-11" disabled={!f.name.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending && <Loader2 className="size-4 animate-spin mr-2" />} Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

