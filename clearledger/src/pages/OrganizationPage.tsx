/**
 * Раздел «Загрузка» → «Организация».
 * Реквизиты юрлица компании (полное наим., ИНН/КПП/ОГРН/ОКПО, адреса,
 * контакты, руководитель/гл.бухгалтер) + банковские счета.
 * Для компаний с подключением 1С реквизиты приходят из синка организаций;
 * без 1С (например РусГидро) — заполняются вручную здесь.
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
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger,
} from '@/components/ui/dialog'
import { Building, Landmark, Loader2, Plus, Pencil, Trash2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import * as refs from '@/services/referenceService'
import type { Organization, BankAccount } from '@/types'

type OrgForm = {
  fullName: string
  name: string
  inn: string
  kpp: string
  ogrn: string
  okpo: string
  legalAddress: string
  actualAddress: string
  phone: string
  email: string
  directorName: string
  directorPosition: string
  accountantName: string
}

const EMPTY_FORM: OrgForm = {
  fullName: '', name: '', inn: '', kpp: '', ogrn: '', okpo: '',
  legalAddress: '', actualAddress: '', phone: '', email: '',
  directorName: '', directorPosition: '', accountantName: '',
}

function orgToForm(o: Organization): OrgForm {
  return {
    fullName: o.fullName ?? '', name: o.name ?? '', inn: o.inn ?? '',
    kpp: o.kpp ?? '', ogrn: o.ogrn ?? '', okpo: o.okpo ?? '',
    legalAddress: o.legalAddress ?? '', actualAddress: o.actualAddress ?? '',
    phone: o.phone ?? '', email: o.email ?? '',
    directorName: o.directorName ?? '', directorPosition: o.directorPosition ?? '',
    accountantName: o.accountantName ?? '',
  }
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

  const set = (k: keyof OrgForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const save = useMutation({
    mutationFn: async () => {
      if (org) {
        return refs.updateOrganization(companyId, org.id, { ...form })
      }
      return refs.createOrganization(companyId, { ...form })
    },
    onSuccess: () => {
      toast.success('Реквизиты организации сохранены')
      qc.invalidateQueries({ queryKey: ['organization', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const canSave = form.inn.trim() !== '' && form.name.trim() !== ''

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center gap-2">
        <Building className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Организация</h1>
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
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><Building className="h-5 w-5" /> Реквизиты организации</CardTitle>
              <CardDescription>
                {org ? 'Карточка юрлица' : 'Организация ещё не заведена — заполните реквизиты и сохраните'}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2 space-y-2">
                  <Label>Полное наименование</Label>
                  <Input value={form.fullName} onChange={set('fullName')}
                    placeholder="Общество с ограниченной ответственностью …" />
                </div>
                <div className="space-y-2">
                  <Label>Краткое наименование <span className="text-destructive">*</span></Label>
                  <Input value={form.name} onChange={set('name')} placeholder="ООО …" />
                </div>
                <div className="space-y-2">
                  <Label>ИНН <span className="text-destructive">*</span></Label>
                  <Input value={form.inn} onChange={set('inn')} placeholder="7839…" />
                </div>
                <div className="space-y-2">
                  <Label>КПП</Label>
                  <Input value={form.kpp} onChange={set('kpp')} />
                </div>
                <div className="space-y-2">
                  <Label>ОГРН</Label>
                  <Input value={form.ogrn} onChange={set('ogrn')} />
                </div>
                <div className="space-y-2">
                  <Label>ОКПО</Label>
                  <Input value={form.okpo} onChange={set('okpo')} />
                </div>
                <div className="space-y-2">
                  <Label>Телефон</Label>
                  <Input value={form.phone} onChange={set('phone')} placeholder="+7 …" />
                </div>
                <div className="col-span-2 space-y-2">
                  <Label>Юридический адрес</Label>
                  <Textarea value={form.legalAddress} onChange={set('legalAddress')} rows={2} />
                </div>
                <div className="col-span-2 space-y-2">
                  <Label>Фактический адрес</Label>
                  <Textarea value={form.actualAddress} onChange={set('actualAddress')} rows={2} />
                </div>
                <div className="space-y-2">
                  <Label>Email</Label>
                  <Input value={form.email} onChange={set('email')} placeholder="info@…" />
                </div>
                <div className="space-y-2">
                  <Label>Руководитель (ФИО)</Label>
                  <Input value={form.directorName} onChange={set('directorName')} />
                </div>
                <div className="space-y-2">
                  <Label>Должность руководителя</Label>
                  <Input value={form.directorPosition} onChange={set('directorPosition')}
                    placeholder="Генеральный директор" />
                </div>
                <div className="space-y-2">
                  <Label>Главный бухгалтер (ФИО)</Label>
                  <Input value={form.accountantName} onChange={set('accountantName')} />
                </div>
              </div>
              <Button onClick={() => save.mutate()} disabled={!canSave || save.isPending}>
                {save.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Сохранить
              </Button>
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
