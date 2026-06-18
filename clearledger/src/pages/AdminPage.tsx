/**
 * Административный раздел: управление компаниями, пользователями, ролями,
 * членством. Компании — только суперадмин; пользователи — суперадмин (все) или
 * админ компании (своя). Требует API-режим.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Building2, Users, Plus, Trash2, Loader2, ShieldCheck, X } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import * as userService from '@/services/userService'

const PROFILES = [
  { id: 'fuel', label: 'Топливо (АЗС)' },
  { id: 'trade', label: 'Оптовая торговля' },
  { id: 'retail', label: 'Розница' },
  { id: 'energy', label: 'Энергетика' },
  { id: 'general', label: 'Общий' },
]

export function AdminPage() {
  const { user } = useAuth()
  const isSuper = !!user?.is_superadmin
  const canAdmin = isSuper || user?.role === 'admin'
  const [tab, setTab] = useState<string>(isSuper ? 'companies' : 'users')

  if (!isApiEnabled() || !canAdmin) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-2 text-muted-foreground">
        <ShieldCheck className="h-8 w-8" />
        <p>Раздел доступен только администраторам.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-6 w-6 text-primary" />
        <h1 className="text-2xl font-bold">Администрирование</h1>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          {isSuper && <TabsTrigger value="companies">Компании</TabsTrigger>}
          <TabsTrigger value="users">Пользователи</TabsTrigger>
        </TabsList>
        {isSuper && (
          <TabsContent value="companies" className="mt-4">
            <CompaniesTab />
          </TabsContent>
        )}
        <TabsContent value="users" className="mt-4">
          <UsersTab isSuper={isSuper} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ─── Компании ──────────────────────────────────────────────────────────────
function CompaniesTab() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['admin-companies'], queryFn: userService.listCompanies })
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', slug: '', profile_id: 'fuel', inn: '', color: '#3b82f6' })

  const create = useMutation({
    mutationFn: () => userService.createCompany(form),
    onSuccess: () => {
      toast.success('Компания подключена')
      setForm({ name: '', slug: '', profile_id: 'fuel', inn: '', color: '#3b82f6' })
      setOpen(false)
      qc.invalidateQueries({ queryKey: ['admin-companies'] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const companies = q.data ?? []

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2"><Building2 className="h-5 w-5" /> Компании</CardTitle>
          <CardDescription>Организации в системе</CardDescription>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm"><Plus className="h-4 w-4 mr-2" /> Подключить компанию</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>Новая компания</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div className="space-y-2">
                <Label>Наименование</Label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="ООО ..." />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>Код (slug)</Label>
                  <Input value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '') })} placeholder="gig" />
                </div>
                <div className="space-y-2">
                  <Label>ИНН</Label>
                  <Input value={form.inn} onChange={(e) => setForm({ ...form, inn: e.target.value })} />
                </div>
              </div>
              <div className="space-y-2">
                <Label>Профиль</Label>
                <Select value={form.profile_id} onValueChange={(v) => setForm({ ...form, profile_id: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PROFILES.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button disabled={!form.name || !form.slug || create.isPending} onClick={() => create.mutate()}>
                {create.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Создать
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent>
        {q.isLoading && <Loading />}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Компания</TableHead>
              <TableHead>Код</TableHead>
              <TableHead>ИНН</TableHead>
              <TableHead>Профиль</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {companies.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-medium flex items-center gap-2">
                  <span className="size-2.5 rounded-full" style={{ background: c.color ?? '#888' }} />
                  {c.name}
                </TableCell>
                <TableCell className="font-mono text-xs">{c.slug}</TableCell>
                <TableCell>{c.inn ?? '—'}</TableCell>
                <TableCell>{PROFILES.find((p) => p.id === c.profile_id)?.label ?? c.profile_id}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

// ─── Пользователи ──────────────────────────────────────────────────────────
function UsersTab({ isSuper }: { isSuper: boolean }) {
  const qc = useQueryClient()
  const { companyId } = useCompany()
  // Суперадмин — все пользователи; админ — своей компании.
  const usersQuery = useQuery({
    queryKey: ['admin-users', isSuper ? 'all' : companyId],
    queryFn: () => (isSuper ? userService.listAllUsers() : userService.listUsers(companyId)),
  })
  const companiesQuery = useQuery({ queryKey: ['admin-companies'], queryFn: userService.listCompanies })

  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ email: '', name: '', password: '', role: 'user' as 'user' | 'admin', company: '' })

  const companies = companiesQuery.data ?? []
  const defaultCompany = isSuper ? (companies[0]?.slug ?? '') : companyId

  const create = useMutation({
    mutationFn: () => userService.createUser({
      companyId: form.company || defaultCompany,
      email: form.email, name: form.name, password: form.password, role: form.role,
    }),
    onSuccess: () => {
      toast.success('Пользователь создан')
      setForm({ email: '', name: '', password: '', role: 'user', company: '' })
      setOpen(false)
      qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: 'user' | 'admin' }) =>
      userService.updateUser(id, isSuper ? { role } : { companyId, role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const grant = useMutation({
    mutationFn: ({ id, slug }: { id: string; slug: string }) => userService.grantCompany(id, slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const revoke = useMutation({
    mutationFn: ({ id, slug }: { id: string; slug: string }) => userService.revokeCompany(id, slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const del = useMutation({
    mutationFn: ({ id, slug }: { id: string; slug: string }) => userService.removeUser(id, slug),
    onSuccess: () => {
      toast.success('Пользователь удалён из компании')
      qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const users = usersQuery.data ?? []
  const selfId = useAuth().user?.id

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2"><Users className="h-5 w-5" /> Пользователи</CardTitle>
          <CardDescription>{isSuper ? 'Все пользователи системы' : 'Пользователи компании'}</CardDescription>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm"><Plus className="h-4 w-4 mr-2" /> Добавить пользователя</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>Новый пользователь</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2"><Label>Имя</Label>
                  <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
                <div className="space-y-2"><Label>Email</Label>
                  <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
                <div className="space-y-2"><Label>Пароль (мин. 6)</Label>
                  <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
                <div className="space-y-2"><Label>Роль</Label>
                  <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v as 'user' | 'admin' })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="user">Пользователь</SelectItem>
                      <SelectItem value="admin">Администратор</SelectItem>
                    </SelectContent>
                  </Select></div>
              </div>
              {isSuper && (
                <div className="space-y-2"><Label>Компания</Label>
                  <Select value={form.company || defaultCompany} onValueChange={(v) => setForm({ ...form, company: v })}>
                    <SelectTrigger><SelectValue placeholder="Выберите компанию" /></SelectTrigger>
                    <SelectContent>
                      {companies.map((c) => <SelectItem key={c.id} value={c.slug}>{c.name}</SelectItem>)}
                    </SelectContent>
                  </Select></div>
              )}
            </div>
            <DialogFooter>
              <Button disabled={!form.email || !form.name || form.password.length < 6 || create.isPending}
                onClick={() => create.mutate()}>
                {create.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Создать
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent>
        {usersQuery.isLoading && <Loading />}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Пользователь</TableHead>
              <TableHead>Роль</TableHead>
              <TableHead>Компании</TableHead>
              <TableHead className="w-10"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((u) => {
              const locked = u.is_superadmin || u.id === selfId
              const available = companies.filter((c) => !u.companies.includes(c.slug))
              return (
                <TableRow key={u.id}>
                  <TableCell>
                    <div className="font-medium flex items-center gap-2">
                      {u.name}
                      {u.is_superadmin && <Badge variant="outline" className="gap-1 text-[10px]"><ShieldCheck className="h-3 w-3" /> супер</Badge>}
                    </div>
                    <div className="text-xs text-muted-foreground">{u.email}</div>
                  </TableCell>
                  <TableCell>
                    <Select value={u.role} disabled={locked}
                      onValueChange={(v) => setRole.mutate({ id: u.id, role: v as 'user' | 'admin' })}>
                      <SelectTrigger className="h-8 w-[120px] text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="user">Пользователь</SelectItem>
                        <SelectItem value="admin">Администратор</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-1">
                      {u.companies.map((slug) => (
                        <Badge key={slug} variant="secondary" className="gap-1 text-[10px]">
                          {slug}
                          {isSuper && !u.is_superadmin && (
                            <button onClick={() => revoke.mutate({ id: u.id, slug })} title="Отозвать">
                              <X className="h-3 w-3 hover:text-destructive" />
                            </button>
                          )}
                        </Badge>
                      ))}
                      {isSuper && !u.is_superadmin && available.length > 0 && (
                        <Select value="" onValueChange={(slug) => grant.mutate({ id: u.id, slug })}>
                          <SelectTrigger className="h-6 w-6 p-0 border-dashed [&>svg]:hidden justify-center" title="Добавить в компанию">
                            <Plus className="h-3 w-3" />
                          </SelectTrigger>
                          <SelectContent>
                            {available.map((c) => <SelectItem key={c.id} value={c.slug}>{c.name}</SelectItem>)}
                          </SelectContent>
                        </Select>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    {!locked && (
                      <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive"
                        title={isSuper ? 'Удалить из всех компаний' : 'Убрать из компании'}
                        onClick={() => {
                          const slug = isSuper ? (u.companies[0] ?? '') : companies.find((c) => c.id === companyId)?.slug ?? companyId
                          if (slug) del.mutate({ id: u.id, slug })
                        }}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function Loading() {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
      <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
    </div>
  )
}

export default AdminPage
