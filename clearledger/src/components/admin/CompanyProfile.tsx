/**
 * Реквизиты компании и подключение новой компании к контейнеру.
 * Раньше жили внутри `pages/AdminPage.tsx` вместе с каркасом Центра управления;
 * каркас переехал в `AdminLayout` (разделы = маршруты), карточки — сюда.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Building2, Loader2, Plus, Users } from 'lucide-react'
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
import { PROFILES } from '@/config/companyProfiles'

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
        <CardTitle className="flex items-center gap-2"><Building2 className="h-5 w-5" /> Реквизиты компании</CardTitle>
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

/** Подключение компании к контейнеру — только суперадмину-владельцу. */
export function AddCompanyDialog({ onCreated }: { onCreated: (c: OrgProfile) => void }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', slug: '', profile_id: 'fuel', inn: '', color: '#3b82f6' })

  const create = useMutation({
    mutationFn: () => userService.createCompany(form),
    onSuccess: (c) => {
      toast.success('Компания подключена')
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
        <Button size="sm" variant="outline"><Plus className="mr-2 h-4 w-4" /> Подключить компанию</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle className="flex items-center gap-2"><Users className="h-5 w-5" /> Новая компания</DialogTitle></DialogHeader>
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
