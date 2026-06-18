/**
 * Команда компании: сотрудники (роль-на-компанию) + приглашения по email.
 * Используется в админ-разделе (мастер-деталь) для выбранной компании.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from '@/components/ui/dialog'
import {
  Users, Mail, UserPlus, Trash2, Loader2, ShieldCheck, Send, RotateCw, X,
} from 'lucide-react'
import * as userService from '@/services/userService'
import * as invitationService from '@/services/invitationService'

const ROLE_LABEL: Record<string, string> = { admin: 'Администратор', user: 'Сотрудник' }

export function CompanyTeam({
  companyId, canManage, selfId,
}: { companyId: string; canManage: boolean; selfId: string }) {
  return (
    <div className="space-y-6">
      <MembersCard companyId={companyId} canManage={canManage} selfId={selfId} />
      {canManage && <InvitationsCard companyId={companyId} />}
    </div>
  )
}

function MembersCard({
  companyId, canManage, selfId,
}: { companyId: string; canManage: boolean; selfId: string }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['team-members', companyId],
    queryFn: () => userService.listUsers(companyId),
  })

  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: 'user' | 'admin' }) =>
      userService.updateUser(id, { companyId, role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['team-members', companyId] }),
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const remove = useMutation({
    mutationFn: (id: string) => userService.removeUser(id, companyId),
    onSuccess: () => {
      toast.success('Сотрудник убран из компании')
      qc.invalidateQueries({ queryKey: ['team-members', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const members = q.data ?? []

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2"><Users className="h-5 w-5" /> Сотрудники</CardTitle>
          <CardDescription>Участники компании и их роли</CardDescription>
        </div>
        {canManage && (
          <div className="flex items-center gap-2">
            <InviteDialog companyId={companyId} />
            <AddUserDialog companyId={companyId} />
          </div>
        )}
      </CardHeader>
      <CardContent>
        {q.isLoading && <Loading />}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Сотрудник</TableHead>
              <TableHead className="w-[160px]">Роль</TableHead>
              <TableHead className="w-10"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.map((u) => {
              const locked = u.is_superadmin || u.id === selfId || !canManage
              return (
                <TableRow key={u.id}>
                  <TableCell>
                    <div className="font-medium flex items-center gap-2">
                      {u.name}
                      {u.is_superadmin && (
                        <Badge variant="outline" className="gap-1 text-[10px]"><ShieldCheck className="h-3 w-3" /> супер</Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">{u.email}</div>
                  </TableCell>
                  <TableCell>
                    <Select value={u.role} disabled={locked}
                      onValueChange={(v) => setRole.mutate({ id: u.id, role: v as 'user' | 'admin' })}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="user">Сотрудник</SelectItem>
                        <SelectItem value="admin">Администратор</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    {!locked && (
                      <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive"
                        title="Убрать из компании" disabled={remove.isPending}
                        onClick={() => remove.mutate(u.id)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
            {!q.isLoading && members.length === 0 && (
              <TableRow><TableCell colSpan={3} className="text-sm text-muted-foreground text-center py-4">Нет сотрудников</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function InvitationsCard({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['team-invites', companyId],
    queryFn: () => invitationService.listInvitations(companyId),
  })
  const resend = useMutation({
    mutationFn: (id: string) => invitationService.resendInvitation(id),
    onSuccess: () => { toast.success('Приглашение отправлено повторно') },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const revoke = useMutation({
    mutationFn: (id: string) => invitationService.revokeInvitation(id),
    onSuccess: () => {
      toast.success('Приглашение отозвано')
      qc.invalidateQueries({ queryKey: ['team-invites', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const invites = q.data ?? []
  if (!q.isLoading && invites.length === 0) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Mail className="h-5 w-5" /> Приглашения</CardTitle>
        <CardDescription>Ожидают принятия</CardDescription>
      </CardHeader>
      <CardContent>
        {q.isLoading && <Loading />}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead className="w-[140px]">Роль</TableHead>
              <TableHead className="w-[120px]">Отправлено</TableHead>
              <TableHead className="w-20"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {invites.map((i) => (
              <TableRow key={i.id}>
                <TableCell className="text-sm">{i.email}</TableCell>
                <TableCell><Badge variant="secondary" className="text-[10px]">{ROLE_LABEL[i.role] ?? i.role}</Badge></TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {new Date(i.created_at).toLocaleDateString('ru')}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1">
                    <Button variant="ghost" size="icon" className="h-7 w-7" title="Отправить повторно"
                      disabled={resend.isPending} onClick={() => resend.mutate(i.id)}>
                      <RotateCw className="h-3.5 w-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      title="Отозвать" disabled={revoke.isPending} onClick={() => revoke.mutate(i.id)}>
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function InviteDialog({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'user' | 'admin'>('user')

  const invite = useMutation({
    mutationFn: () => invitationService.createInvitation(companyId, email, role),
    onSuccess: () => {
      toast.success(`Приглашение отправлено на ${email}`)
      setEmail(''); setRole('user'); setOpen(false)
      qc.invalidateQueries({ queryKey: ['team-invites', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm"><Send className="h-4 w-4 mr-2" /> Пригласить</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Пригласить сотрудника</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-2">
            <Label>Email сотрудника</Label>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="employee@company.ru" />
          </div>
          <div className="space-y-2">
            <Label>Роль</Label>
            <Select value={role} onValueChange={(v) => setRole(v as 'user' | 'admin')}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="user">Сотрудник</SelectItem>
                <SelectItem value="admin">Администратор</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <p className="text-xs text-muted-foreground">
            На указанный email придёт ссылка-приглашение; сотрудник сам задаст пароль.
          </p>
        </div>
        <DialogFooter>
          <Button disabled={!email || invite.isPending} onClick={() => invite.mutate()}>
            {invite.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Отправить приглашение
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AddUserDialog({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'user' as 'user' | 'admin' })

  const create = useMutation({
    mutationFn: () => userService.createUser({ companyId, ...form }),
    onSuccess: () => {
      toast.success('Сотрудник добавлен')
      setForm({ name: '', email: '', password: '', role: 'user' }); setOpen(false)
      qc.invalidateQueries({ queryKey: ['team-members', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline"><UserPlus className="h-4 w-4 mr-2" /> Вручную</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Добавить сотрудника вручную</DialogTitle></DialogHeader>
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
                  <SelectItem value="user">Сотрудник</SelectItem>
                  <SelectItem value="admin">Администратор</SelectItem>
                </SelectContent>
              </Select></div>
          </div>
        </div>
        <DialogFooter>
          <Button disabled={!form.email || !form.name || form.password.length < 6 || create.isPending}
            onClick={() => create.mutate()}>
            {create.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Добавить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Loading() {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
      <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
    </div>
  )
}
