/**
 * Раздел «Компании и команда» (мастер-деталь).
 * Слева — список компаний (суперадмину все + подключить новую; админу — свои).
 * Справа — выбранная компания: реквизиты (правка) + команда (сотрудники +
 * приглашения по email). Требует API-режим.
 */
import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from '@/components/ui/dialog'
import { Building2, Plus, Loader2, ShieldCheck, Users } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import * as userService from '@/services/userService'
import type { OrgProfile } from '@/services/userService'
import { CompanyTeam } from '@/components/admin/CompanyTeam'

const PROFILES = [
  { id: 'fuel', label: 'Топливо (АЗС)' },
  { id: 'trade', label: 'Оптовая торговля' },
  { id: 'retail', label: 'Розница' },
  { id: 'energy', label: 'Энергетика' },
  { id: 'general', label: 'Общий' },
]

export function AdminPage() {
  const { user } = useAuth()
  const { companyId: activeId } = useCompany()
  const isSuper = !!user?.is_superadmin
  const canAdminAny = isSuper || (user?.companies ?? []).some((c) => c.role === 'admin')

  const companiesQuery = useQuery({ queryKey: ['admin-companies'], queryFn: userService.listCompanies })
  const companies = companiesQuery.data ?? []

  const [selectedId, setSelectedId] = useState<string>('')
  const selected = useMemo(
    () => companies.find((c) => c.id === (selectedId || activeId)) ?? companies[0],
    [companies, selectedId, activeId],
  )

  // Может ли текущий пользователь администрировать выбранную компанию.
  const canManageSelected = (id?: string) =>
    isSuper || (user?.companies ?? []).some((c) => c.id === id && c.role === 'admin')

  if (!isApiEnabled() || !canAdminAny) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-2 text-muted-foreground">
        <ShieldCheck className="h-8 w-8" />
        <p>Раздел доступен только администраторам.</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-6 w-6 text-primary" />
        <h1 className="text-2xl font-bold">Компании и команда</h1>
      </div>

      <div className="flex gap-6 items-start">
        {/* Левый рейл — компании */}
        <div className="w-64 shrink-0 space-y-2">
          {isSuper && <AddCompanyDialog onCreated={(c) => setSelectedId(c.id)} />}
          <div className="rounded-lg border border-border/50 divide-y divide-border/40 overflow-hidden">
            {companiesQuery.isLoading && (
              <div className="p-3 text-sm text-muted-foreground flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
              </div>
            )}
            {companies.map((c) => {
              const active = selected?.id === c.id
              return (
                <button key={c.id} onClick={() => setSelectedId(c.id)}
                  className={`w-full text-left px-3 py-2.5 flex items-center gap-2 transition-colors ${
                    active ? 'bg-primary/10 text-primary' : 'hover:bg-accent'
                  }`}>
                  <span className="size-2.5 rounded-full shrink-0" style={{ background: c.color ?? '#888' }} />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium truncate">{c.short_name || c.name}</span>
                    <span className="block text-[11px] text-muted-foreground font-mono">{c.slug}</span>
                  </span>
                </button>
              )
            })}
            {!companiesQuery.isLoading && companies.length === 0 && (
              <div className="p-3 text-sm text-muted-foreground">Нет компаний</div>
            )}
          </div>
        </div>

        {/* Деталь — выбранная компания */}
        <div className="flex-1 min-w-0 space-y-6">
          {selected ? (
            <>
              <CompanyProfileCard company={selected} canEdit={canManageSelected(selected.id)} />
              <CompanyTeam
                companyId={selected.id}
                canManage={canManageSelected(selected.id)}
                selfId={user!.id}
              />
            </>
          ) : (
            <Card><CardContent className="py-10 text-center text-muted-foreground">
              Выберите компанию слева
            </CardContent></Card>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Реквизиты компании ──────────────────────────────────────────────────────
function CompanyProfileCard({ company, canEdit }: { company: OrgProfile; canEdit: boolean }) {
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
        <div className="grid grid-cols-2 gap-4">
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
            {save.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Сохранить
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

// ─── Подключение компании (суперадмин) ───────────────────────────────────────
function AddCompanyDialog({ onCreated }: { onCreated: (c: OrgProfile) => void }) {
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
        <Button className="w-full" size="sm"><Plus className="h-4 w-4 mr-2" /> Подключить компанию</Button>
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
            {create.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Создать
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default AdminPage
