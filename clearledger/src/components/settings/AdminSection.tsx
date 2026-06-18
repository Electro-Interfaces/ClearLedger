/**
 * Раздел Настроек: Профиль организации + Управление пользователями.
 * Видимость/правка — по роли (админ/суперадмин), требует API-режим.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Building2, Users, UserPlus, Trash2, Loader2, ShieldCheck } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import * as userService from '@/services/userService'

export function AdminSection() {
  const { user } = useAuth()
  const { company, companyId } = useCompany()
  const canManage = !!user && (user.is_superadmin || user.role === 'admin')

  if (!isApiEnabled()) return null  // управление требует бэкенд

  return (
    <>
      <OrgProfileCard companyId={companyId} canEdit={canManage} initialName={company.name} initialInn={company.inn} />
      {canManage && <UsersCard companyId={companyId} selfId={user!.id} />}
    </>
  )
}

// ─── Профиль организации ───────────────────────────────────────────────────
function OrgProfileCard({
  companyId, canEdit, initialName, initialInn,
}: { companyId: string; canEdit: boolean; initialName: string; initialInn?: string }) {
  const qc = useQueryClient()
  const [name, setName] = useState(initialName)
  const [inn, setInn] = useState(initialInn ?? '')

  const save = useMutation({
    mutationFn: () => userService.updateCompany(companyId, { name, inn: inn || undefined }),
    onSuccess: () => {
      toast.success('Профиль организации сохранён')
      qc.invalidateQueries()
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Building2 className="h-5 w-5" />
          Профиль организации
        </CardTitle>
        <CardDescription>Реквизиты текущей компании</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="orgName">Наименование</Label>
            <Input id="orgName" value={name} disabled={!canEdit}
              onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="orgInn">ИНН</Label>
            <Input id="orgInn" value={inn} disabled={!canEdit}
              onChange={(e) => setInn(e.target.value)} placeholder="—" />
          </div>
        </div>
        {canEdit && (
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            Сохранить
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

// ─── Пользователи ──────────────────────────────────────────────────────────
function UsersCard({ companyId, selfId }: { companyId: string; selfId: string }) {
  const qc = useQueryClient()
  const usersQuery = useQuery({
    queryKey: ['admin-users', companyId],
    queryFn: () => userService.listUsers(companyId),
  })

  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ email: '', name: '', password: '', role: 'user' as 'user' | 'admin' })

  const create = useMutation({
    mutationFn: () => userService.createUser({ companyId, ...form }),
    onSuccess: () => {
      toast.success('Пользователь добавлен')
      setForm({ email: '', name: '', password: '', role: 'user' })
      setAdding(false)
      qc.invalidateQueries({ queryKey: ['admin-users', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: 'user' | 'admin' }) =>
      userService.updateUser(id, { companyId, role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users', companyId] }),
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const remove = useMutation({
    mutationFn: (id: string) => userService.removeUser(id, companyId),
    onSuccess: () => {
      toast.success('Пользователь удалён из компании')
      qc.invalidateQueries({ queryKey: ['admin-users', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const users = usersQuery.data ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Users className="h-5 w-5" />
          Пользователи и доступ
        </CardTitle>
        <CardDescription>Пользователи текущей компании и их роли</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {usersQuery.isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
          </div>
        )}
        {usersQuery.isError && (
          <div className="text-sm text-destructive">Не удалось загрузить пользователей</div>
        )}

        {users.map((u) => (
          <div key={u.id} className="flex items-center justify-between gap-2 py-1.5 border-b border-border/30 last:border-0">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-medium truncate">
                {u.name}
                {u.is_superadmin && (
                  <Badge variant="outline" className="gap-1 text-[10px]">
                    <ShieldCheck className="h-3 w-3" /> супер
                  </Badge>
                )}
              </div>
              <div className="text-xs text-muted-foreground truncate">{u.email}</div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Select
                value={u.role}
                onValueChange={(v) => setRole.mutate({ id: u.id, role: v as 'user' | 'admin' })}
                disabled={u.is_superadmin || u.id === selfId}
              >
                <SelectTrigger className="h-8 w-[110px] text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">Пользователь</SelectItem>
                  <SelectItem value="admin">Администратор</SelectItem>
                </SelectContent>
              </Select>
              <Button
                variant="ghost" size="icon"
                className="h-8 w-8 text-muted-foreground hover:text-destructive"
                disabled={u.is_superadmin || u.id === selfId || remove.isPending}
                onClick={() => remove.mutate(u.id)}
                title="Убрать из компании"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}

        {adding ? (
          <div className="space-y-3 rounded-lg border border-border/50 p-3 mt-2">
            <div className="grid grid-cols-2 gap-3">
              <Input placeholder="Имя" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} />
              <Input placeholder="Email" type="email" value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
              <Input placeholder="Пароль (мин. 6)" type="password" value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })} />
              <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v as 'user' | 'admin' })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">Пользователь</SelectItem>
                  <SelectItem value="admin">Администратор</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm"
                disabled={!form.email || !form.name || form.password.length < 6 || create.isPending}
                onClick={() => create.mutate()}>
                {create.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                Добавить
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>Отмена</Button>
            </div>
          </div>
        ) : (
          <Button variant="outline" size="sm" className="mt-2" onClick={() => setAdding(true)}>
            <UserPlus className="h-4 w-4 mr-2" /> Добавить пользователя
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
