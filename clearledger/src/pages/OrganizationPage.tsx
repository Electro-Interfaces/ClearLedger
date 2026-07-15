/**
 * Раздел «Данные» → «Организация».
 * Полная карточка юрлица как в справочнике «Организации» БП 3.0: идентификация,
 * гос. регистрация, налоговый орган и фонды, адреса, контакты, ответственные
 * лица + банковские счета. Для компаний с 1С реквизиты приходят из синка;
 * без 1С (например РусГидро) — заполняются вручную.
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Building, Landmark, Loader2, Plus, Pencil, Trash2, Database } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import * as refs from '@/services/referenceService'
import type { Organization, BankAccount } from '@/types'

// Поля формы = расширенные реквизиты Organization (кроме служебных id/ref/дат).
type OrgForm = Pick<Organization,
  | 'vid' | 'fullName' | 'name' | 'prefix' | 'inn' | 'kpp' | 'ogrn' | 'okpo'
  | 'regDate' | 'okved' | 'oktmo' | 'okato' | 'okopf' | 'okfs' | 'registrationCert'
  | 'ifnsCode' | 'ifnsName' | 'pfrRegNumber' | 'fssRegNumber' | 'fssSubordination'
  | 'legalAddress' | 'actualAddress' | 'postalAddress' | 'phone' | 'fax' | 'email'
  | 'directorName' | 'directorPosition' | 'accountantName' | 'cashierName'
>

const FORM_KEYS: (keyof OrgForm)[] = [
  'vid', 'fullName', 'name', 'prefix', 'inn', 'kpp', 'ogrn', 'okpo',
  'regDate', 'okved', 'oktmo', 'okato', 'okopf', 'okfs', 'registrationCert',
  'ifnsCode', 'ifnsName', 'pfrRegNumber', 'fssRegNumber', 'fssSubordination',
  'legalAddress', 'actualAddress', 'postalAddress', 'phone', 'fax', 'email',
  'directorName', 'directorPosition', 'accountantName', 'cashierName',
]

const EMPTY_FORM: OrgForm = Object.fromEntries(FORM_KEYS.map((k) => [k, ''])) as OrgForm

function orgToForm(o: Organization): OrgForm {
  return Object.fromEntries(FORM_KEYS.map((k) => [k, o[k] ?? ''])) as OrgForm
}

const VID_OPTIONS = [
  { value: 'ЮЛ', label: 'Юридическое лицо' },
  { value: 'ИП', label: 'Индивидуальный предприниматель' },
  { value: 'ОП', label: 'Обособленное подразделение' },
  { value: 'ФЛ', label: 'Физическое лицо' },
]

// Подпись группы полей — в стиле заголовков боковой навигации.
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">{title}</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3">{children}</div>
    </div>
  )
}

function Field({ label, required, span, children }: {
  label: string; required?: boolean; span?: boolean; children: React.ReactNode
}) {
  return (
    <div className={`space-y-1.5 ${span ? 'col-span-2' : ''}`}>
      <Label className="text-xs text-muted-foreground">
        {label}{required && <span className="text-destructive"> *</span>}
      </Label>
      {children}
    </div>
  )
}

export function OrganizationPage() {
  const { company, companyId } = useCompany()
  const qc = useQueryClient()

  const orgQuery = useQuery({
    queryKey: ['organization', companyId],
    queryFn: () => refs.getOrganizations(companyId),
    enabled: !!companyId,
  })
  // Основная организация компании = первая в списке (в этом продукте 1 юрлицо).
  const org = orgQuery.data?.[0]

  const [form, setForm] = useState<OrgForm>(EMPTY_FORM)
  // Перезаполняем форму при загрузке/смене организации или компании.
  const key = `${companyId}:${org?.id ?? 'new'}:${org?.updatedAt ?? ''}`
  useEffect(() => {
    setForm(org ? orgToForm(org) : EMPTY_FORM)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const setField = (k: keyof OrgForm, v: string) => setForm((f) => ({ ...f, [k]: v }))
  const set = (k: keyof OrgForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setField(k, e.target.value)

  const save = useMutation({
    mutationFn: async () => {
      if (org) return refs.updateOrganization(companyId, org.id, { ...form })
      return refs.createOrganization(companyId, { ...form })
    },
    onSuccess: () => {
      toast.success('Реквизиты организации сохранены')
      qc.invalidateQueries({ queryKey: ['organization', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const canSave = (form.inn ?? '').trim() !== '' && (form.name ?? '').trim() !== ''

  return (
    <div className="max-w-4xl space-y-6 p-4 lg:p-6">
      <div className="flex items-center gap-2">
        <Building className="h-6 w-6 text-primary shrink-0" />
        <div>
          <h1 className="text-xl font-semibold">Организация</h1>
          <p className="text-sm text-muted-foreground">
            Реквизиты юрлица {company?.shortName ? `· ${company.shortName}` : ''}
          </p>
        </div>
      </div>

      {orgQuery.isLoading ? (
        <div className="flex items-center justify-center h-40 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : (
        <>
          {/* Реквизиты организации */}
          <Card>
            <CardHeader className="flex-row items-start justify-between space-y-0 gap-3">
              <div className="space-y-1.5">
                <CardTitle className="flex items-center gap-2"><Building className="h-5 w-5" /> Реквизиты организации</CardTitle>
                <CardDescription>
                  {org ? 'Карточка юрлица' : 'Организация ещё не заведена — заполните реквизиты и сохраните'}
                </CardDescription>
              </div>
              {org && (
                org.externalRef
                  ? <Badge variant="secondary" className="gap-1 shrink-0"><Database className="h-3 w-3" /> Из 1С</Badge>
                  : <Badge variant="outline" className="gap-1 shrink-0 text-muted-foreground"><Pencil className="h-3 w-3" /> Вручную</Badge>
              )}
            </CardHeader>
            <CardContent className="space-y-5 [&_input]:bg-muted/60! [&_textarea]:bg-muted/60! [&_[data-slot=select-trigger]]:bg-muted/60! [&_input]:border-border! [&_textarea]:border-border! [&_[data-slot=select-trigger]]:border-border!">
              <Section title="Идентификация">
                <Field label="Вид">
                  <Select value={form.vid || undefined} onValueChange={(v) => setField('vid', v)}>
                    <SelectTrigger><SelectValue placeholder="Не указан" /></SelectTrigger>
                    <SelectContent>
                      {VID_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Префикс"><Input value={form.prefix} onChange={set('prefix')} placeholder="напр. РГ" /></Field>
                <Field label="Полное наименование" span>
                  <Input value={form.fullName} onChange={set('fullName')}
                    placeholder="Общество с ограниченной ответственностью …" />
                </Field>
                <Field label="Сокращённое наименование" required>
                  <Input value={form.name} onChange={set('name')} placeholder="ООО …" />
                </Field>
                <Field label="ИНН" required>
                  <Input value={form.inn} onChange={set('inn')} placeholder="7839…" />
                </Field>
                <Field label="КПП"><Input value={form.kpp} onChange={set('kpp')} /></Field>
                <Field label="ОКПО"><Input value={form.okpo} onChange={set('okpo')} /></Field>
              </Section>

              <div className="h-px bg-border/60" />

              <Section title="Государственная регистрация">
                <Field label="ОГРН / ОГРНИП"><Input value={form.ogrn} onChange={set('ogrn')} /></Field>
                <Field label="Дата регистрации"><Input value={form.regDate} onChange={set('regDate')} placeholder="дд.мм.гггг" /></Field>
                <Field label="ОКВЭД"><Input value={form.okved} onChange={set('okved')} /></Field>
                <Field label="ОКТМО"><Input value={form.oktmo} onChange={set('oktmo')} /></Field>
                <Field label="ОКАТО"><Input value={form.okato} onChange={set('okato')} /></Field>
                <Field label="ОКОПФ"><Input value={form.okopf} onChange={set('okopf')} /></Field>
                <Field label="ОКФС"><Input value={form.okfs} onChange={set('okfs')} /></Field>
                <Field label="Свидетельство о гос. регистрации" span>
                  <Input value={form.registrationCert} onChange={set('registrationCert')}
                    placeholder="серия, №, дата, кем выдано" />
                </Field>
              </Section>

              <div className="h-px bg-border/60" />

              <Section title="Налоговый орган и фонды">
                <Field label="Код ИФНС"><Input value={form.ifnsCode} onChange={set('ifnsCode')} /></Field>
                <Field label="Наименование ИФНС" span><Input value={form.ifnsName} onChange={set('ifnsName')} /></Field>
                <Field label="Рег. номер ПФР"><Input value={form.pfrRegNumber} onChange={set('pfrRegNumber')} /></Field>
                <Field label="Рег. номер ФСС"><Input value={form.fssRegNumber} onChange={set('fssRegNumber')} /></Field>
                <Field label="Код подчинённости ФСС"><Input value={form.fssSubordination} onChange={set('fssSubordination')} /></Field>
              </Section>

              <div className="h-px bg-border/60" />

              <Section title="Адреса">
                <Field label="Юридический адрес" span>
                  <Textarea value={form.legalAddress} onChange={set('legalAddress')} rows={2} />
                </Field>
                <Field label="Фактический адрес" span>
                  <Textarea value={form.actualAddress} onChange={set('actualAddress')} rows={2} />
                </Field>
                <Field label="Почтовый адрес" span>
                  <Textarea value={form.postalAddress} onChange={set('postalAddress')} rows={2} />
                </Field>
              </Section>

              <div className="h-px bg-border/60" />

              <Section title="Контакты">
                <Field label="Телефон"><Input value={form.phone} onChange={set('phone')} placeholder="+7 …" /></Field>
                <Field label="Факс"><Input value={form.fax} onChange={set('fax')} /></Field>
                <Field label="Email" span><Input value={form.email} onChange={set('email')} placeholder="info@…" /></Field>
              </Section>

              <div className="h-px bg-border/60" />

              <Section title="Ответственные лица">
                <Field label="Руководитель (ФИО)"><Input value={form.directorName} onChange={set('directorName')} /></Field>
                <Field label="Должность руководителя">
                  <Input value={form.directorPosition} onChange={set('directorPosition')} placeholder="Генеральный директор" />
                </Field>
                <Field label="Главный бухгалтер (ФИО)"><Input value={form.accountantName} onChange={set('accountantName')} /></Field>
                <Field label="Кассир (ФИО)"><Input value={form.cashierName} onChange={set('cashierName')} /></Field>
              </Section>

              <div className="flex justify-end pt-1">
                <Button onClick={() => save.mutate()} disabled={!canSave || save.isPending}>
                  {save.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Сохранить
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Банковские счета */}
          <BankAccountsCard companyId={companyId} organizationId={org?.id} disabled={!org} />
        </>
      )}
    </div>
  )
}

// ─── Банковские счета ────────────────────────────────────────────────────────
type BankForm = { number: string; bankName: string; bik: string; corrAccount: string; currency: string }
const EMPTY_BANK: BankForm = { number: '', bankName: '', bik: '', corrAccount: '', currency: 'RUB' }

function BankAccountsCard({ companyId, organizationId, disabled }: {
  companyId: string; organizationId?: string; disabled: boolean
}) {
  const qc = useQueryClient()
  const accountsQuery = useQuery({
    queryKey: ['bank-accounts', companyId],
    queryFn: () => refs.getBankAccounts(companyId),
    enabled: !!companyId,
  })
  // Счета этой организации (без привязки показываем тоже — могли завести вручную).
  const accounts = (accountsQuery.data ?? []).filter(
    (a) => !organizationId || !a.organizationId || a.organizationId === organizationId,
  )

  const remove = useMutation({
    mutationFn: (id: string) => refs.deleteBankAccount(companyId, id),
    onSuccess: () => {
      toast.success('Счёт удалён')
      qc.invalidateQueries({ queryKey: ['bank-accounts', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2"><Landmark className="h-5 w-5" /> Банковские счета</CardTitle>
          <CardDescription>
            {disabled ? 'Сначала сохраните реквизиты организации' : 'Расчётные счета организации'}
          </CardDescription>
        </div>
        <BankAccountDialog companyId={companyId} organizationId={organizationId} disabled={disabled} />
      </CardHeader>
      <CardContent>
        {accountsQuery.isLoading ? (
          <div className="flex items-center justify-center h-20 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : accounts.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Счета не добавлены.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Расчётный счёт</TableHead>
                <TableHead>Банк</TableHead>
                <TableHead>БИК</TableHead>
                <TableHead>Корр. счёт</TableHead>
                <TableHead>Валюта</TableHead>
                <TableHead className="w-20" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="font-mono text-xs">{a.number}</TableCell>
                  <TableCell>{a.bankName}</TableCell>
                  <TableCell className="font-mono text-xs">{a.bik}</TableCell>
                  <TableCell className="font-mono text-xs">{a.corrAccount ?? '—'}</TableCell>
                  <TableCell>{a.currency}</TableCell>
                  <TableCell>
                    <div className="flex gap-1 justify-end">
                      <BankAccountDialog companyId={companyId} organizationId={organizationId}
                        disabled={false} edit={a} />
                      <Button variant="ghost" size="icon" className="h-8 w-8"
                        onClick={() => remove.mutate(a.id)} disabled={remove.isPending}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function BankAccountDialog({ companyId, organizationId, disabled, edit }: {
  companyId: string; organizationId?: string; disabled: boolean; edit?: BankAccount
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<BankForm>(
    edit
      ? { number: edit.number, bankName: edit.bankName, bik: edit.bik, corrAccount: edit.corrAccount ?? '', currency: edit.currency }
      : EMPTY_BANK,
  )

  const set = (k: keyof BankForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const save = useMutation({
    mutationFn: async () => {
      const payload = { ...form, corrAccount: form.corrAccount || undefined }
      if (edit) return refs.updateBankAccount(companyId, edit.id, payload)
      return refs.createBankAccount(companyId, { ...payload, organizationId })
    },
    onSuccess: () => {
      toast.success(edit ? 'Счёт обновлён' : 'Счёт добавлен')
      qc.invalidateQueries({ queryKey: ['bank-accounts', companyId] })
      setOpen(false)
      if (!edit) setForm(EMPTY_BANK)
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const canSave = form.number.trim() !== '' && form.bik.trim() !== ''

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {edit ? (
          <Button variant="ghost" size="icon" className="h-8 w-8"><Pencil className="h-4 w-4" /></Button>
        ) : (
          <Button size="sm" disabled={disabled}><Plus className="h-4 w-4 mr-2" /> Добавить счёт</Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Landmark className="h-5 w-5" /> {edit ? 'Изменить счёт' : 'Новый банковский счёт'}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-2">
            <Label>Расчётный счёт <span className="text-destructive">*</span></Label>
            <Input value={form.number} onChange={set('number')} placeholder="40702810…" />
          </div>
          <div className="space-y-2">
            <Label>Банк</Label>
            <Input value={form.bankName} onChange={set('bankName')} placeholder="ПАО Сбербанк" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>БИК <span className="text-destructive">*</span></Label>
              <Input value={form.bik} onChange={set('bik')} placeholder="044…" />
            </div>
            <div className="space-y-2">
              <Label>Валюта</Label>
              <Input value={form.currency} onChange={set('currency')} placeholder="RUB" />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Корреспондентский счёт</Label>
            <Input value={form.corrAccount} onChange={set('corrAccount')} placeholder="30101…" />
          </div>
        </div>
        <DialogFooter>
          <Button disabled={!canSave || save.isPending} onClick={() => save.mutate()}>
            {save.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default OrganizationPage
