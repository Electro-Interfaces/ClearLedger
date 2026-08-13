/**
 * Реквизиты компании и подключение новой компании к контейнеру.
 * Раньше жили внутри `pages/AdminPage.tsx` вместе с каркасом Центра управления;
 * каркас переехал в `AdminLayout` (разделы = маршруты), карточки — сюда.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Building2, Landmark, Loader2, Plus, Users } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import * as userService from '@/services/userService'
import type { OrgProfile } from '@/services/userService'
import * as referenceService from '@/services/referenceService'
import { PROFILES } from '@/config/companyProfiles'
import { Req } from '@/components/admin/Counterparties'

export function CompanyProfileCard({ company, canEdit }: { company: OrgProfile; canEdit: boolean }) {
  const qc = useQueryClient()
  const [name, setName] = useState(company.name)
  const [shortName, setShortName] = useState(company.short_name ?? '')
  const [inn, setInn] = useState(company.inn ?? '')
  const [profileId, setProfileId] = useState(company.profile_id)

  // Перезаполнение при смене выбранной компании.
  const key = company.id
  const [boundKey, setBoundKey] = useState(key)
  if (boundKey !== key) {
    setBoundKey(key); setName(company.name); setShortName(company.short_name ?? '')
    setInn(company.inn ?? ''); setProfileId(company.profile_id)
  }

  const save = useMutation({
    mutationFn: () => userService.updateCompany(company.id, {
      name, short_name: shortName || undefined, inn: inn || undefined, profile_id: profileId,
    }),
    onSuccess: () => {
      toast.success('Реквизиты сохранены')
      qc.invalidateQueries({ queryKey: ['admin-companies'] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Building2 className="h-5 w-5" /> Реквизиты организации</CardTitle>
        <CardDescription>Код <span className="font-mono">{company.slug}</span></CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-2"><Label>Наименование</Label>
            <Input value={name} disabled={!canEdit} onChange={(e) => setName(e.target.value)} /></div>
          <div className="space-y-2"><Label>Краткое имя</Label>
            <Input value={shortName} disabled={!canEdit} onChange={(e) => setShortName(e.target.value)} /></div>
          <div className="space-y-2"><Label>ИНН</Label>
            <Input value={inn} disabled={!canEdit} onChange={(e) => setInn(e.target.value)} placeholder="—" /></div>
          <div className="space-y-2"><Label>Профиль</Label>
            <Select value={profileId} disabled={!canEdit} onValueChange={setProfileId}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {PROFILES.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}
              </SelectContent>
            </Select></div>
        </div>
        {canEdit && (
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />} Сохранить
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * Карточка собственной организации — та, от чьего имени ведётся учёт.
 * Компания пространства (выше) — это разрез доступа, а здесь юрлицо со всеми
 * реквизитами из бухгалтерии: регистрация, налоговый орган, фонды, банк, адреса.
 */
export function OwnOrganizationCard({ companyId }: { companyId: string }) {
  const orgsQ = useQuery({
    queryKey: ['own-organizations', companyId],
    queryFn: () => referenceService.getOrganizations(companyId),
  })
  const orgs = orgsQ.data ?? []
  if (orgsQ.isLoading || orgs.length === 0) return null

  return (
    <>
      {orgs.map((o) => {
        const bank = [o.bankAccount, o.bankBik && `БИК ${o.bankBik}`].filter(Boolean).join(' · ')
        const ifns = [o.ifnsName, o.ifnsCode && `код ${o.ifnsCode}`].filter(Boolean).join(' · ')
        return (
          <Card key={o.id}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Landmark className="h-5 w-5" /> {o.name}
              </CardTitle>
              <CardDescription>
                {o.fullName && o.fullName !== o.name ? o.fullName : 'Организация, от имени которой ведётся учёт'}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                <Req label="ИНН" value={o.inn} />
                <Req label="КПП" value={o.kpp} />
                <Req label="ОГРН" value={o.ogrn} />
                <Req label="ОКПО" value={o.okpo} />
                <Req label="Вид" value={o.vid} />
                <Req label="Дата регистрации" value={o.regDate} />
                <Req label="ОКВЭД" value={o.okved} />
                <Req label="Префикс" value={o.prefix} />
              </div>
              <div className="space-y-3">
                <Req label="Юридический адрес" value={o.legalAddress} />
                <Req label="Фактический адрес"
                  value={o.actualAddress && o.actualAddress !== o.legalAddress ? o.actualAddress : null} />
                <Req label="Почтовый адрес"
                  value={o.postalAddress && o.postalAddress !== o.legalAddress ? o.postalAddress : null} />
                <Req label="Телефон" value={o.phone} />
                <Req label="Почта" value={o.email} />
              </div>
              <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2">
                <Req label="Банк" value={bank || null} />
                <Req label="Налоговый орган" value={ifns || null} />
                <Req label="Регистрация в ПФР" value={o.pfrRegNumber} />
                <Req label="Регистрация в ФСС" value={o.fssRegNumber} />
                <Req label="Руководитель"
                  value={[o.directorPosition, o.directorName].filter(Boolean).join(' · ') || null} />
                <Req label="Главный бухгалтер" value={o.accountantName} />
              </div>
            </CardContent>
          </Card>
        )
      })}
    </>
  )
}

/** Подключение компании к контейнеру — только суперадмину-владельцу. */
export function AddCompanyDialog({ onCreated }: { onCreated: (c: OrgProfile) => void }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', slug: '', profile_id: 'fuel', inn: '', color: '#3b82f6' })

  const create = useMutation({
    mutationFn: () => userService.createCompany(form),
    onSuccess: (c) => {
      toast.success('Организация подключена')
      setForm({ name: '', slug: '', profile_id: 'fuel', inn: '', color: '#3b82f6' })
      setOpen(false)
      qc.invalidateQueries({ queryKey: ['admin-companies'] })
      onCreated(c)
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline"><Plus className="mr-2 h-4 w-4" /> Подключить организацию</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle className="flex items-center gap-2"><Users className="h-5 w-5" /> Новая организация</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-2"><Label>Наименование</Label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="ООО …" /></div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2"><Label>Код (slug)</Label>
              <Input value={form.slug}
                onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '') })}
                placeholder="gig" /></div>
            <div className="space-y-2"><Label>ИНН</Label>
              <Input value={form.inn} onChange={(e) => setForm({ ...form, inn: e.target.value })} /></div>
          </div>
          <div className="space-y-2"><Label>Профиль</Label>
            <Select value={form.profile_id} onValueChange={(v) => setForm({ ...form, profile_id: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {PROFILES.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}
              </SelectContent>
            </Select></div>
        </div>
        <DialogFooter>
          <Button disabled={!form.name || !form.slug || create.isPending} onClick={() => create.mutate()}>
            {create.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />} Создать
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
