import { useId, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Mail, Phone, Users, Plus, Pencil, Unlink } from 'lucide-react'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { ContactFormDialog } from '@/components/reference/ContactFormDialog'
import { CONTACT_ROLE_LABEL, type CounterpartyContact } from '@/services/referenceService'
import { assignLocationContact, getLocationContactOptions, getLocationContacts, removeLocationContact, type LocationContact, type LocationContactOptions } from '@/services/locationContactsService'
import { SectionCard } from './shared'

function Person({ contact, children }: { contact: LocationContact; children?: ReactNode }) {
  const phone = contact.phone?.replace(/[^\d+]/g, '')
  return <article className="flex flex-col gap-2 border-b py-3 last:border-0">
    <div className="flex flex-col gap-2">
      <div className="min-w-0 flex-1">
        {contact.responsibility && <p className="font-medium break-words">{contact.responsibility}</p>}
        <p className="text-sm break-words">{contact.name}{contact.position && <> · {contact.position}</>}</p>
        <p className="text-sm text-muted-foreground break-words">{contact.counterpartyName}</p>
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
      {phone ? <a href={`tel:${phone}`} className="inline-flex min-h-11 items-center gap-1.5 underline underline-offset-4"><Phone className="size-4 shrink-0" />{contact.phone}</a> : <span className="text-muted-foreground">Телефон не указан</span>}
      {contact.email && <a href={`mailto:${encodeURIComponent(contact.email)}`} className="inline-flex min-h-11 max-w-full items-center gap-1.5 underline underline-offset-4"><Mail className="size-4 shrink-0" /><span className="break-all">{contact.email}</span></a>}
    </div>
    {contact.notes && <p className="text-sm text-muted-foreground whitespace-pre-wrap break-words">{contact.notes}</p>}
    {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
  </article>
}

export function LocationContactsBlock({ locationId }: { locationId: string }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const id = useId()
  const key = ['location-contacts', companyId, locationId]
  const optionsKey = ['location-contact-options', companyId, locationId]
  const q = useQuery({ queryKey: key, queryFn: () => getLocationContacts(locationId), enabled: !!companyId })
  const [form, setForm] = useState<{ contactId: string; cpId: string; responsibility: string; editing: boolean } | null>(null)
  const [search, setSearch] = useState('')
  const options = useQuery({ queryKey: optionsKey, queryFn: () => getLocationContactOptions(locationId), enabled: !!companyId && !!form })
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: key })
    void qc.invalidateQueries({ queryKey: optionsKey })
  }
  const save = useMutation({
    mutationFn: () => assignLocationContact(locationId, form!.contactId, form!.responsibility.trim()),
    onSuccess: () => { refresh(); setForm(null); toast.success('Контакт назначен на объект') },
    onError: (e: Error) => toast.error('Назначение не сохранено', { description: e.message }),
  })
  const remove = useMutation({
    mutationFn: (contactId: string) => removeLocationContact(locationId, contactId),
    onSuccess: () => { refresh(); toast.success('Назначение убрано. Контакт сохранён в реестре') },
    onError: (e: Error) => toast.error('Не удалось убрать назначение', { description: e.message }),
  })
  const open = (contact?: LocationContact, editing = false) => {
    save.reset(); setSearch('')
    setForm({ contactId: contact?.id ?? '', cpId: contact?.counterpartyId ?? '', responsibility: contact?.responsibility ?? '', editing })
  }
  const newContact = (contact: CounterpartyContact) => {
    qc.setQueryData<LocationContactOptions>(optionsKey, old => old ? { ...old,
      contacts: [...old.contacts.filter(c => c.id !== contact.id), { ...contact, responsibility: null,
        counterpartyName: old.counterparties.find(cp => cp.id === contact.counterpartyId)?.name ?? '' }],
    } : old)
    setForm(old => old ? { ...old, contactId: contact.id } : old)
  }
  const organizations = options.data?.counterparties.filter(cp => cp.name.toLocaleLowerCase('ru').includes(search.trim().toLocaleLowerCase('ru'))) ?? []
  const people = options.data?.contacts.filter(c => c.counterpartyId === form?.cpId) ?? []
  const selected = options.data?.contacts.find(c => c.id === form?.contactId)
  const disabled = save.isPending

  return <SectionCard title="Контакты объекта" icon={Users} action={
    <Button variant="outline" size="sm" className="min-h-11" aria-label="Назначить контакт" disabled={!q.data || !!form} onClick={() => open()}><Plus className="size-4" />Назначить</Button>
  }>
    <div className="flex flex-col gap-3">
      {q.isPending && <p role="status" className="text-sm text-muted-foreground">Загрузка контактов…</p>}
      {q.isError && <Alert variant="destructive"><AlertDescription>Не удалось загрузить контакты объекта. <Button variant="outline" onClick={() => void q.refetch()}>Повторить загрузку</Button></AlertDescription></Alert>}
      {q.data && q.data.assigned.length === 0 && <p className="text-sm text-muted-foreground">Ответственные по объекту не назначены. Выберите человека из реестра и укажите, за что он отвечает на этой площадке.</p>}
      {q.data?.assigned.map(contact => <Person key={contact.id} contact={contact}>
        <Button variant="outline" size="icon" className="size-11" disabled={save.isPending} aria-label={`Изменить назначение: ${contact.name}`} onClick={() => open(contact, true)}><Pencil className="size-4" /></Button>
        {q.data.canEditContacts && <ContactFormDialog counterpartyId={contact.counterpartyId} edit={contact} onSaved={refresh}><Button variant="outline" size="sm" className="min-h-11">Данные контакта</Button></ContactFormDialog>}
        <AlertDialog><AlertDialogTrigger asChild><Button variant="outline" size="icon" className="size-11" disabled={remove.isPending} aria-label={`Убрать с объекта: ${contact.name}`}><Unlink className="size-4" /></Button></AlertDialogTrigger>
          <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Убрать контакт с объекта?</AlertDialogTitle><AlertDialogDescription>Назначение {contact.name} будет убрано с этой площадки. Человек останется в реестре и на других объектах.</AlertDialogDescription></AlertDialogHeader>
            <AlertDialogFooter><AlertDialogCancel>Отмена</AlertDialogCancel><AlertDialogAction onClick={() => remove.mutate(contact.id)}>Убрать назначение</AlertDialogAction></AlertDialogFooter>
          </AlertDialogContent></AlertDialog>
      </Person>)}
      {form && <fieldset disabled={disabled} className="flex min-w-0 flex-col gap-3 rounded-md border p-3">
        <legend className="px-1 text-sm font-medium">{form.editing ? 'Изменить назначение' : 'Назначить контакт'}</legend>
        {options.isPending && <p role="status" className="text-sm">Загрузка реестра…</p>}
        {options.isError && <Alert variant="destructive"><AlertDescription>Реестр контактов не загрузился. <Button variant="outline" onClick={() => void options.refetch()}>Повторить загрузку реестра</Button></AlertDescription></Alert>}
        {options.data && <>
          {form.editing ? <p className="text-sm break-words">{selected?.name} · {selected?.counterpartyName}</p> : <>
            <Label htmlFor={`${id}-search`}>Поиск организации</Label><Input id={`${id}-search`} value={search} onChange={e => setSearch(e.target.value)} placeholder="Название организации" />
            <Label htmlFor={`${id}-org`}>Организация</Label>
            <Select value={form.cpId} onValueChange={cpId => setForm({ ...form, cpId, contactId: '' })} disabled={disabled}>
              <SelectTrigger id={`${id}-org`} className="w-full min-h-11"><SelectValue placeholder="Выберите организацию" /></SelectTrigger>
              <SelectContent><SelectGroup>{organizations.map(cp => <SelectItem key={cp.id} value={cp.id}>{cp.name}</SelectItem>)}{!organizations.length && <SelectItem value="no-match" disabled>Организации не найдены</SelectItem>}</SelectGroup></SelectContent>
            </Select>
            {form.cpId && <>
              <Label htmlFor={`${id}-person`}>Контакт</Label><Select value={form.contactId} onValueChange={contactId => setForm({ ...form, contactId })} disabled={disabled || !people.length}>
                <SelectTrigger id={`${id}-person`} className="w-full min-h-11"><SelectValue placeholder={people.length ? 'Выберите человека' : 'Контактных лиц пока нет'} /></SelectTrigger>
                <SelectContent><SelectGroup>{people.map(c => <SelectItem key={c.id} value={c.id}>{c.name}{c.position ? ` · ${c.position}` : ''}</SelectItem>)}</SelectGroup></SelectContent>
              </Select>
              {options.data.canEditContacts && <ContactFormDialog key={form.cpId} counterpartyId={form.cpId} onSaved={newContact}><Button variant="outline" className="min-h-11 self-start whitespace-normal">Новый контакт этой организации</Button></ContactFormDialog>}
            </>}
          </>}
          <Label htmlFor={`${id}-responsibility`}>За что отвечает на этом объекте</Label><Input id={`${id}-responsibility`} maxLength={200} value={form.responsibility} onChange={e => setForm({ ...form, responsibility: e.target.value })} placeholder="Например, энергоснабжение или допуск на площадку" />
        </>}
        {save.isError && <p role="alert" className="text-sm text-destructive">Назначение не сохранено. Проверьте связь и повторите. Введённые данные сохранены в форме.</p>}
        <div className="flex flex-wrap gap-2"><Button className="min-h-11" disabled={disabled || !options.data || options.isError || !form.contactId || !form.responsibility.trim()} onClick={() => save.mutate()}>{disabled ? 'Сохранение…' : 'Сохранить назначение'}</Button><Button className="min-h-11" variant="outline" disabled={disabled} onClick={() => setForm(null)}>Отмена</Button></div>
      </fieldset>}
      {!!q.data?.organizationContacts.length && <details>
        <summary className="min-h-11 cursor-pointer text-sm">Контакты связанных организаций · {q.data.organizationContacts.length}</summary>
        <p className="text-sm text-muted-foreground">Это общие контакты организаций по договорам. Ответственность за эту площадку им не назначена.</p>
        {q.data.organizationContacts.map(contact => <Person key={contact.id} contact={contact}><Badge variant="secondary">Общий контакт · {CONTACT_ROLE_LABEL[contact.role] ?? contact.role}</Badge><Button variant="outline" size="sm" className="min-h-11" disabled={!!form} onClick={() => open(contact)}>Назначить на объект</Button></Person>)}
      </details>}
    </div>
  </SectionCard>
}
