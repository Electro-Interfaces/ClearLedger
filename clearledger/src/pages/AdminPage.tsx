/**
 * Раздел «Компании, команда и доступ» (мастер-деталь).
 * Слева — список компаний (суперадмину все + подключить новую; админу — свои).
 * Справа — выбранная компания: реквизиты (правка) + команда (сотрудники,
 * приглашения по email, роли и RBAC-доступ к модулям учёта). Требует API-режим.
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
import { Building2, Plus, Loader2, ShieldCheck, Users, Mail, KeyRound, History, Blocks, Boxes, Gauge, MapPin, Library } from 'lucide-react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { usePersistentState } from '@/hooks/usePersistentState'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import * as userService from '@/services/userService'
import type { OrgProfile } from '@/services/userService'
import { MembersCard, InvitationsCard, RolesAccessTab, AuditTab } from '@/components/admin/CompanyTeam'
import { CompanyApps } from '@/components/admin/CompanyApps'
import { SpaceObjects } from '@/components/admin/SpaceObjects'
import { SpaceRefs } from '@/components/admin/SpaceRefs'
import { EcosystemConsole } from '@/components/admin/EcosystemConsole'

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
  const [tab, setTab] = usePersistentState('cl-admin-tab', 'members')
  // Двухуровневая навигация Центра управления: Экосистема (Ур.1) ⇄ Компания (Ур.2).
  // Уровень экосистемы — только суперадмину; админ компании видит сразу свою компанию.
  const [scope, setScope] = usePersistentState('cl-admin-scope', 'ecosystem')
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

  // Ур. 2 — управление выбранной компанией (селектор + вкладки). Показывается под
  // scope «Компания» суперадмину и как единственный вид — админу компании.
  const companyBlock = (
    <div className="space-y-4">
      {/* Панель выбора компании */}
      <div className="flex items-center gap-3 flex-wrap border-b border-border/50 pb-3">
        <span className="text-sm font-medium text-muted-foreground">Компания:</span>
        {companiesQuery.isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : (
          <Select value={selected?.id ?? ''} onValueChange={setSelectedId}>
            <SelectTrigger className="w-72"><SelectValue placeholder="Выберите компанию" /></SelectTrigger>
            <SelectContent>
              {companies.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  <span className="flex items-center gap-2">
                    <span className="size-2 rounded-full shrink-0" style={{ background: c.color ?? '#888' }} />
                    {c.short_name || c.name}
                    <span className="text-muted-foreground font-mono text-[11px]">{c.slug}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {isSuper && <AddCompanyDialog onCreated={(c) => setSelectedId(c.id)} />}
        <span className="text-xs text-muted-foreground ml-auto">Компаний: {companies.length}</span>
      </div>

      {selected ? (
        <Tabs value={tab} onValueChange={setTab} className="w-full">
          <TabsList>
            <TabsTrigger value="members" className="gap-1.5"><Users className="h-4 w-4" /> Сотрудники</TabsTrigger>
            <TabsTrigger value="roles" className="gap-1.5"><KeyRound className="h-4 w-4" /> Роли и доступ</TabsTrigger>
            <TabsTrigger value="apps" className="gap-1.5"><Blocks className="h-4 w-4" /> Приложения</TabsTrigger>
            {/* Объекты — общая сущность пространства: ведутся один раз для всех приложений. */}
            <TabsTrigger value="objects" className="gap-1.5"><MapPin className="h-4 w-4" /> Объекты</TabsTrigger>
            <TabsTrigger value="refs" className="gap-1.5"><Library className="h-4 w-4" /> Справочники</TabsTrigger>
            <TabsTrigger value="profile" className="gap-1.5"><Building2 className="h-4 w-4" /> Реквизиты</TabsTrigger>
            {canManageSelected(selected.id) && (
              <TabsTrigger value="invites" className="gap-1.5"><Mail className="h-4 w-4" /> Приглашения</TabsTrigger>
            )}
            {canManageSelected(selected.id) && (
              <TabsTrigger value="audit" className="gap-1.5"><History className="h-4 w-4" /> Журнал</TabsTrigger>
            )}
          </TabsList>
          <TabsContent value="members" className="mt-4">
            <MembersCard companyId={selected.id} canManage={canManageSelected(selected.id)} selfId={user!.id} />
          </TabsContent>
          <TabsContent value="roles" className="mt-4">
            <RolesAccessTab companyId={selected.id} canManage={canManageSelected(selected.id)} />
          </TabsContent>
          <TabsContent value="apps" className="mt-4">
            <CompanyApps companyId={selected.id} canManage={canManageSelected(selected.id)} />
          </TabsContent>
          <TabsContent value="objects" className="mt-4">
            <SpaceObjects companyId={selected.id} canManage={canManageSelected(selected.id)} />
          </TabsContent>
          <TabsContent value="refs" className="mt-4">
            <SpaceRefs companyId={selected.id} canManage={canManageSelected(selected.id)} />
          </TabsContent>
          <TabsContent value="profile" className="mt-4">
            <CompanyProfileCard company={selected} canEdit={canManageSelected(selected.id)} />
          </TabsContent>
          {canManageSelected(selected.id) && (
            <TabsContent value="invites" className="mt-4">
              <InvitationsCard companyId={selected.id} />
            </TabsContent>
          )}
          {canManageSelected(selected.id) && (
            <TabsContent value="audit" className="mt-4">
              <AuditTab companyId={selected.id} />
            </TabsContent>
          )}
        </Tabs>
      ) : (
        <Card><CardContent className="py-10 text-center text-muted-foreground">
          {companies.length === 0 ? 'Нет доступных компаний' : 'Выберите компанию'}
        </CardContent></Card>
      )}
    </div>
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Gauge className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold leading-tight">Центр управления</h1>
          <p className="text-sm text-muted-foreground">Экосистема и компании: приложения, пользователи, доступ, состояние</p>
        </div>
      </div>

      {isSuper ? (
        // Ур. 1 (Экосистема) — только суперадмину; иначе сразу управление своей компанией.
        <Tabs value={scope} onValueChange={setScope} className="w-full">
          <TabsList>
            <TabsTrigger value="ecosystem" className="gap-1.5"><Boxes className="h-4 w-4" /> Экосистема</TabsTrigger>
            <TabsTrigger value="company" className="gap-1.5"><Building2 className="h-4 w-4" /> Компания</TabsTrigger>
          </TabsList>
          <TabsContent value="ecosystem" className="mt-4"><EcosystemConsole /></TabsContent>
          <TabsContent value="company" className="mt-4">{companyBlock}</TabsContent>
        </Tabs>
      ) : companyBlock}
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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
        <Button size="sm" variant="outline"><Plus className="h-4 w-4 mr-2" /> Подключить компанию</Button>
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
