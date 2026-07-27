/**
 * Команда компании: сотрудники (роль-на-компанию) + приглашения по email.
 * Используется в админ-разделе (мастер-деталь) для выбранной компании.
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardAction, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
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
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Mail, UserPlus, Trash2, Loader2, ShieldCheck, Send, RotateCw, X, Check, SlidersHorizontal, Search,
  KeyRound, Plus, Pencil, Copy, History, Share2, Users, ChevronDown, ChevronRight,
} from 'lucide-react'
import * as userService from '@/services/userService'
import type { AdminUser } from '@/services/userService'
import * as invitationService from '@/services/invitationService'
import { InviteLinkPanel } from './InviteLinkPanel'
import * as roleService from '@/services/roleService'
import type { CompanyRole } from '@/services/roleService'
import { ALL_ACCESS_KEYS, moduleLabels } from '@/config/accessModules'
import { AccessMatrix, AccessSummary } from './AccessMatrix'
import { ObjectScopeDialog } from './ObjectScopeDialog'
import { useAccessTree } from '@/hooks/useAccessTree'
import { projectSpaceUsers, listSpaceOrganizations } from '@/services/spaceObjectsService'
import { PartyBadge } from '@/components/chat/PartyBadge'

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

export function MembersCard({
  companyId, canManage, selfId,
}: { companyId: string; canManage: boolean; selfId: string }) {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const q = useQuery({
    queryKey: ['team-members', companyId],
    queryFn: () => userService.listUsers(companyId),
  })
  const rolesQ = useQuery({
    queryKey: ['company-roles', companyId],
    queryFn: () => roleService.listRoles(companyId),
    enabled: canManage,
  })
  const roles = rolesQ.data ?? []

  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: 'user' | 'admin' }) =>
      userService.updateUser(id, { companyId, role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['team-members', companyId] }),
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const update = useMutation({
    mutationFn: ({ id, name, position }: { id: string; name?: string; position?: string }) =>
      userService.updateUser(id, { companyId, name, position }),
    onSuccess: () => { toast.success('Сохранено'); qc.invalidateQueries({ queryKey: ['team-members', companyId] }) },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  // Организации пространства нужны, чтобы указать, КОГО представляет внешний участник.
  const orgsQ = useQuery({
    queryKey: ['space-orgs', companyId],
    queryFn: () => listSpaceOrganizations(companyId),
    enabled: canManage,
    retry: false,
  })
  const setParty = useMutation({
    mutationFn: ({ id, partyType, organizationId }: {
      id: string; partyType?: 'internal' | 'partner' | 'vendor'; organizationId?: string
    }) => userService.updateUser(id, { companyId, partyType, organizationId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['team-members', companyId] }),
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const projectUsers = useMutation({
    mutationFn: () => projectSpaceUsers(companyId, 'support'),
    onSuccess: (r) => toast.success(
      `Поддержка обновлена: создано ${r.created}, обновлено ${r.updated}`,
      { description: `Отправлено сотрудников: ${r.sent}` },
    ),
    onError: (e) => toast.error('Проекция не выполнена', { description: (e as Error).message }),
  })
  const remove = useMutation({
    mutationFn: (id: string) => userService.removeUser(id, companyId),
    onSuccess: () => {
      toast.success('Сотрудник убран из организации')
      qc.invalidateQueries({ queryKey: ['team-members', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const members = q.data ?? []
  const filtered = search.trim()
    ? members.filter((m) => `${m.name} ${m.email} ${m.position ?? ''}`.toLowerCase().includes(search.trim().toLowerCase()))
    : members

  return (
    <Card>
      {/* Название раздела и его смысл — в шапке рабочей области («Управление»),
          здесь только поиск, действия и сам состав: заголовок дважды не нужен. */}
      <CardContent className="pt-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="relative w-full max-w-xs">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск: ФИО, email, должность…"
              className="h-8 pl-8 text-sm" />
          </div>
          {canManage && (
            <div className="flex items-center gap-2">
              {/* Люди пространства должны быть и в приложениях-разрезах: заводим один
                  раз здесь, проекция доносит их до Координатора (docs/SPACE.md). */}
              <Button variant="outline" size="sm" className="gap-1.5"
                disabled={projectUsers.isPending} onClick={() => projectUsers.mutate()}
                title="Отправить сотрудников в приложения экосистемы">
                {projectUsers.isPending
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <Share2 className="h-4 w-4" />}
                В приложения
              </Button>
              <InviteDialog companyId={companyId} />
              <AddUserDialog companyId={companyId} />
            </div>
          )}
        </div>
        {q.isLoading && <Loading />}
        {/* Колонки (роль + принадлежность + доступ + объекты) шире рабочей области,
            поэтому таблица прокручивается вбок сама, а не обрезается краем карточки. */}
        <div className="overflow-x-auto">
        <Table className="min-w-[1100px]">
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[220px]">ФИО / Email</TableHead>
              <TableHead className="w-[160px]">Должность</TableHead>
              <TableHead className="w-[130px]">Роль</TableHead>
              <TableHead className="w-[210px]">Кто это</TableHead>
              <TableHead className="w-[300px]">Доступ и объекты</TableHead>
              <TableHead className="w-10"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {!q.isLoading && filtered.length === 0 && (
              <TableRow><TableCell colSpan={6} className="text-center text-sm text-muted-foreground py-6">
                {members.length === 0 ? 'Нет сотрудников' : 'Ничего не найдено'}
              </TableCell></TableRow>
            )}
            {filtered.map((u) => {
              const locked = u.is_superadmin || u.id === selfId || !canManage
              return (
                <TableRow key={u.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <EditableText value={u.name} disabled={locked} placeholder="ФИО"
                        onSave={(name) => update.mutate({ id: u.id, name })} className="font-medium" />
                      {u.is_superadmin && (
                        <Badge variant="outline" className="gap-1 text-[10px] shrink-0"><ShieldCheck className="h-3 w-3" /> супер</Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">{u.email}</div>
                  </TableCell>
                  <TableCell>
                    <EditableText value={u.position ?? ''} disabled={locked} placeholder="— должность —"
                      onSave={(position) => update.mutate({ id: u.id, position })} />
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
                    {/* Принадлежность к пространству — не права, а «кто он»: в чатах и
                        заявках внешнего участника надо отличать от своего сотрудника. */}
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-1.5">
                        <PartyBadge party={{
                          partyType: u.party_type ?? 'internal', role: u.role,
                          orgName: u.organization_name, position: u.position,
                        }} />
                        {canManage && !u.is_superadmin && (
                          <Select value={u.party_type ?? 'internal'} disabled={setParty.isPending}
                            onValueChange={(v) => setParty.mutate({ id: u.id, partyType: v as 'internal' | 'partner' | 'vendor' })}>
                            <SelectTrigger className="h-7 w-[132px] text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value="internal">Свой сотрудник</SelectItem>
                              <SelectItem value="partner">Внешний участник</SelectItem>
                              {/* Инженер разработчика платформы: попадает в канал поддержки
                                  пространства и подписан «Поддержка» во всех чатах. */}
                              <SelectItem value="vendor">Поддержка платформы</SelectItem>
                            </SelectContent>
                          </Select>
                        )}
                      </div>
                      {canManage && (u.party_type === 'partner' || u.party_type === 'vendor') && (
                        <Select value={u.organization_id ?? 'none'} disabled={setParty.isPending}
                          onValueChange={(v) => setParty.mutate({ id: u.id, organizationId: v === 'none' ? '' : v })}>
                          <SelectTrigger className="h-7 w-[196px] text-xs">
                            <SelectValue placeholder="Организация" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">Организация не указана</SelectItem>
                            {(orgsQ.data ?? []).map((o) => (
                              <SelectItem key={o.id} value={o.id}>{o.shortName || o.name}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    {u.role === 'admin' || u.is_superadmin ? (
                      <Badge variant="outline" className="text-[10px] gap-1"><ShieldCheck className="h-3 w-3" /> Все модули</Badge>
                    ) : (
                      <div className="flex flex-wrap items-center gap-1">
                        {u.role_name ? (
                          <Badge className="text-[10px] gap-1"><KeyRound className="h-3 w-3" />{u.role_name}</Badge>
                        ) : u.modules == null ? (
                          <span className="text-xs text-muted-foreground">Все модули</span>
                        ) : u.modules.length === 0 ? (
                          <span className="text-xs text-destructive/80">Нет доступа</span>
                        ) : (
                          moduleLabels(u.modules).map((l) => (
                            <Badge key={l} variant="secondary" className="text-[10px] font-normal">{l}</Badge>
                          ))
                        )}
                        {canManage && u.id !== selfId && (
                          <AccessDialog member={u} companyId={companyId} roles={roles}
                            onSaved={() => qc.invalidateQueries({ queryKey: ['team-members', companyId] })} />
                        )}
                        {/* Второй слой доступа: по каким объектам видны данные на
                            открытых ролью экранах. У админа не действует — он видит
                            всю сеть, иначе не настроит то, чего не видит. */}
                        {canManage && u.id !== selfId && (
                          <ObjectScopeDialog member={u} companyId={companyId}
                            onSaved={() => qc.invalidateQueries({ queryKey: ['team-members', companyId] })} />
                        )}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    {/* Исключение из компании отбирает доступ ко всем приложениям сразу —
                        спрашиваем, а не выполняем по одному клику мимо. */}
                    {!locked && (
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive"
                            title="Убрать из организации" disabled={remove.isPending}>
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Убрать из организации?</AlertDialogTitle>
                            <AlertDialogDescription>
                              {u.name || u.email} потеряет доступ ко всем приложениям пространства.
                              Учётная запись сохранится — человека можно вернуть приглашением.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Отмена</AlertDialogCancel>
                            <AlertDialogAction onClick={() => remove.mutate(u.id)}>Убрать</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Сотрудников: {members.length}
          {filtered.length !== members.length ? ` · показано ${filtered.length}` : ''}
          {' '}· роль «Администратор» даёт полный доступ
        </p>
      </CardContent>
    </Card>
  )
}

export function InvitationsCard({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['team-invites', companyId],
    queryFn: () => invitationService.listInvitations(companyId),
  })
  // Перевыпуск: единственный способ получить ссылку по существующему
  // приглашению — в базе хранится хеш токена, старую ссылку не достать.
  const [linkFor, setLinkFor] = useState<invitationService.Invitation | null>(null)
  const resend = useMutation({
    mutationFn: (id: string) => invitationService.resendInvitation(id),
    onSuccess: (inv) => {
      setLinkFor(inv)
      qc.invalidateQueries({ queryKey: ['team-invites', companyId] })
    },
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
        <CardDescription>
          Ожидают принятия. Если письмо не дошло — «Отправить снова»: выпустит
          новую ссылку, её можно скопировать и передать мессенджером.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {q.isLoading && <Loading />}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead className="w-[140px]">Роль</TableHead>
              <TableHead className="w-[150px]">Отправлено</TableHead>
              <TableHead className="w-[230px]"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {invites.map((i) => (
              <TableRow key={i.id}>
                <TableCell className="text-sm">
                  {i.email}
                  {i.position && <span className="block text-xs text-muted-foreground">{i.position}</span>}
                </TableCell>
                <TableCell><Badge variant="secondary" className="text-[10px]">{ROLE_LABEL[i.role] ?? i.role}</Badge></TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {new Date(i.created_at).toLocaleDateString('ru')}
                  <span className="block">
                    до {new Date(i.expires_at).toLocaleDateString('ru')}
                  </span>
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-1">
                    {/* Явная кнопка, а не иконка: письмо теряется в спаме, и
                        «отправить заново / взять ссылку» — самое частое действие
                        в этой таблице. Прячась под пиктограммой, оно не находится. */}
                    <Button variant="outline" size="sm" className="h-8"
                      title="Выпустить новую ссылку: письмо уйдёт повторно, ссылку можно скопировать в мессенджер"
                      disabled={resend.isPending} onClick={() => resend.mutate(i.id)}>
                      {resend.isPending && resend.variables === i.id
                        ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                        : <RotateCw className="h-3.5 w-3.5 mr-1.5" />}
                      Отправить снова
                    </Button>
                    <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive"
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

      <Dialog open={linkFor !== null} onOpenChange={(v) => { if (!v) setLinkFor(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Новая ссылка приглашения</DialogTitle></DialogHeader>
          {linkFor && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                {linkFor.email} · выпущена новая ссылка, предыдущая больше не работает.
              </p>
              <InviteLinkPanel invitation={linkFor} />
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setLinkFor(null)}>Готово</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

function InviteDialog({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [position, setPosition] = useState('')
  const [role, setRole] = useState<'user' | 'admin'>('user')
  // Созданное приглашение со ссылкой. Диалог после успеха НЕ закрывается:
  // ссылку отдают один раз, закрыть его до копирования — потерять её.
  const [created, setCreated] = useState<invitationService.Invitation | null>(null)

  const reset = () => { setEmail(''); setPosition(''); setRole('user'); setCreated(null) }

  const invite = useMutation({
    mutationFn: () => invitationService.createInvitation(companyId, email, role, position),
    onSuccess: (inv) => {
      setCreated(inv)
      qc.invalidateQueries({ queryKey: ['team-invites', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) reset() }}>
      <DialogTrigger asChild>
        <Button size="sm"><Send className="h-4 w-4 mr-2" /> Пригласить</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{created ? 'Приглашение создано' : 'Пригласить сотрудника'}</DialogTitle>
        </DialogHeader>

        {created ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {created.email}
              {created.position ? ` · ${created.position}` : ''} · {ROLE_LABEL[created.role] ?? created.role}
            </p>
            <InviteLinkPanel invitation={created} />
          </div>
        ) : (
          <div className="space-y-3">
            <div className="space-y-2">
              <Label>Email сотрудника</Label>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="employee@company.ru" />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>Должность</Label>
                <Input value={position} onChange={(e) => setPosition(e.target.value)}
                  placeholder="напр. Бухгалтер" />
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
            </div>
            <p className="text-xs text-muted-foreground">
              Сотруднику придёт письмо со ссылкой — по ней он задаст ФИО и пароль.
              Ссылку можно скопировать и отправить мессенджером.
            </p>
          </div>
        )}

        <DialogFooter>
          {created ? (
            <>
              <Button variant="outline" onClick={reset}>Пригласить ещё</Button>
              <Button onClick={() => { setOpen(false); reset() }}>Готово</Button>
            </>
          ) : (
            <Button disabled={!email || invite.isPending} onClick={() => invite.mutate()}>
              {invite.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Создать приглашение
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AddUserDialog({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', email: '', password: '', position: '', role: 'user' as 'user' | 'admin' })

  const create = useMutation({
    mutationFn: () => userService.createUser({ companyId, ...form }),
    onSuccess: () => {
      toast.success('Сотрудник добавлен')
      setForm({ name: '', email: '', password: '', position: '', role: 'user' }); setOpen(false)
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
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-2"><Label>ФИО</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Фамилия Имя Отчество" /></div>
            <div className="space-y-2"><Label>Email</Label>
              <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            <div className="space-y-2"><Label>Должность</Label>
              <Input value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })} placeholder="напр. Бухгалтер" /></div>
            <div className="space-y-2"><Label>Роль</Label>
              <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v as 'user' | 'admin' })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">Сотрудник</SelectItem>
                  <SelectItem value="admin">Администратор</SelectItem>
                </SelectContent>
              </Select></div>
            <div className="space-y-2 col-span-2"><Label>Пароль (мин. 6)</Label>
              <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
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

function EditableText({
  value, disabled, placeholder, onSave, className,
}: { value: string; disabled?: boolean; placeholder?: string; onSave: (v: string) => void; className?: string }) {
  const [val, setVal] = useState(value)
  useEffect(() => setVal(value), [value])

  if (disabled) {
    return <span className={`text-sm ${className ?? ''} ${!value ? 'text-muted-foreground' : ''}`}>{value || placeholder}</span>
  }
  return (
    <input
      value={val}
      placeholder={placeholder}
      onChange={(e) => setVal(e.target.value)}
      onBlur={() => { if (val !== value) onSave(val) }}
      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
      className={`h-8 w-full bg-transparent rounded border border-transparent hover:border-border/60 focus:border-primary outline-none text-sm px-1 transition-colors ${className ?? ''}`}
    />
  )
}

function Loading() {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
      <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
    </div>
  )
}

/** Сетка прав роли/доступа по продуктам пространства (app-namespaced). Дерево — то же,
 * что в матрице (`useAccessTree`): каталог подключённых компании продуктов + их разделы
 * из карты меню. Отметка продукта покрывает все его разделы; группы раскрываются по
 * клику — иначе 25 пунктов «Магазина» в диалоге не разобрать. */
function ModuleCheckboxGrid({ companyId, sel, onToggle, disabled }: {
  companyId: string; sel: Set<string>; onToggle: (k: string) => void; disabled?: boolean
}) {
  const { tree, isLoading } = useAccessTree(companyId)
  const [open, setOpen] = useState<Record<string, boolean>>({})

  return (
    <div className={`space-y-2 max-h-80 overflow-y-auto pr-1 ${disabled ? 'opacity-40 pointer-events-none' : ''}`}>
      {isLoading && <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Загрузка каталога…</div>}
      {tree.map((app) => {
        const appOn = sel.has(app.app)
        const picked = app.groups.flatMap((g) => g.modules).filter((m) => sel.has(m.key)).length
        const expanded = !!open[app.app]
        return (
          <div key={app.app}>
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => setOpen((o) => ({ ...o, [app.app]: !o[app.app] }))}
                disabled={!app.count} className="p-1 text-muted-foreground disabled:opacity-0">
                {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              </button>
              <button type="button" onClick={() => onToggle(app.app)}
                className={`flex-1 flex items-center justify-between px-2.5 py-1.5 rounded-md text-sm text-left border font-medium transition-colors ${
                  appOn ? 'bg-primary/10 border-primary/40 text-foreground' : 'border-border hover:bg-accent/40'
                }`}>
                <span>
                  {app.name}
                  <span className="text-[11px] text-muted-foreground/70 ml-1">
                    {appOn ? '· весь продукт' : picked ? `· выбрано: ${picked}` : app.count ? `· разделов: ${app.count}` : ''}
                  </span>
                </span>
                {appOn && <Check className="h-3.5 w-3.5 text-primary shrink-0" />}
              </button>
            </div>
            {expanded && app.groups.map((g) => (
              <div key={g.name} className="ml-6 mt-1 border-l pl-2">
                <div className="px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">{g.name}</div>
                <div className="flex flex-col gap-1">
                  {g.modules.map((m) => {
                    const on = appOn || sel.has(m.key)
                    return (
                      <button key={m.key} type="button" disabled={appOn} onClick={() => onToggle(m.key)}
                        className={`flex items-center justify-between px-2.5 py-1 rounded-md text-[13px] text-left border transition-colors ${
                          on ? 'bg-primary/10 border-primary/40 text-foreground' : 'border-border text-muted-foreground hover:bg-accent/40'
                        } ${appOn ? 'opacity-60' : ''}`}>
                        <span>{m.name}</span>
                        {on && <Check className="h-3.5 w-3.5 text-primary shrink-0" />}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

/** Вкладка «Роли и доступ»: менеджер ролей (CRUD) + каталог модулей. */
export function RolesAccessTab({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const qc = useQueryClient()
  const rolesQ = useQuery({ queryKey: ['company-roles', companyId], queryFn: () => roleService.listRoles(companyId) })
  const roles = rolesQ.data ?? []
  const refetch = () => qc.invalidateQueries({ queryKey: ['company-roles', companyId] })
  const del = useMutation({
    mutationFn: (id: string) => roleService.deleteRole(id, companyId),
    onSuccess: () => { toast.success('Роль удалена'); refetch(); qc.invalidateQueries({ queryKey: ['team-members', companyId] }) },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  return (
    <div className="space-y-4">
      {/* Матрица — главный экран доступа: весь контур прав компании разом. Карточки
          ролей под ней остаются для создания, переименования и удаления. */}
      <AccessMatrix companyId={companyId} roles={roles} canManage={canManage} />
      <div className="grid lg:grid-cols-2 gap-4 items-start">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><KeyRound className="h-5 w-5" /> Роли доступа</CardTitle>
          <CardDescription>Именованные наборы прав на продукты пространства и их разделы. Системные — только чтение; кастомные можно менять.</CardDescription>
          {/* CardHeader — grid: без CardAction кнопка занимает всю ширину карточки. */}
          {canManage && (
            <CardAction><RoleEditDialog companyId={companyId} roles={roles} onSaved={refetch} /></CardAction>
          )}
        </CardHeader>
        <CardContent className="space-y-2.5">
          {rolesQ.isLoading && <Loading />}
          {roles.map((r) => (
            <div key={r.id} className="rounded-md border p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-medium text-sm truncate">{r.name}</span>
                  {r.is_system && <Badge variant="outline" className="text-[10px] shrink-0">системная</Badge>}
                  <span className="text-[11px] text-muted-foreground shrink-0">· {r.members_count} чел.</span>
                </div>
                {canManage && !r.is_system && (
                  <div className="flex items-center gap-0.5 shrink-0">
                    <RoleEditDialog companyId={companyId} roles={roles} editRole={r} onSaved={refetch} />
                    <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-destructive"
                      title="Удалить роль" disabled={del.isPending} onClick={() => del.mutate(r.id)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                )}
              </div>
              {/* Полный список ключей в бейджах перестал читаться, когда у продуктов
                  появились разделы (у роли их бывает под сотню) — здесь сводка, состав
                  виден в матрице выше. */}
              <div className="flex flex-wrap items-center gap-1 mt-2">
                <AccessSummary modules={r.modules} />
                {r.modules != null && r.modules.length > 0 && (
                  <span className="text-[11px] text-muted-foreground/70">
                    · {moduleLabels(r.modules).slice(0, 4).join(', ')}{r.modules.length > 4 ? '…' : ''}
                  </span>
                )}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <MemberAccessCard companyId={companyId} />
      </div>
    </div>
  )
}

/** Кто сейчас чем пользуется: человек → его роль и продукты. Матрица показывает, что
 *  МОЖЕТ дать роль; здесь видно, кому она фактически назначена, включая внешних. */
function MemberAccessCard({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['team-members', companyId],
    queryFn: () => userService.listUsers(companyId),
  })
  const members = q.data ?? []
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Users className="h-5 w-5" /> Кому что назначено</CardTitle>
        <CardDescription>Роль и права каждого участника пространства — свои сотрудники и внешние.</CardDescription>
      </CardHeader>
      <CardContent>
        {q.isLoading && <Loading />}
        <Table>
          <TableHeader><TableRow>
            <TableHead>Участник</TableHead>
            <TableHead className="w-[130px]">Роль</TableHead>
            <TableHead className="w-[150px]">Доступ</TableHead>
            <TableHead className="w-[110px]">Объекты</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {members.map((m) => (
              <TableRow key={m.id}>
                <TableCell className="py-1.5">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-sm truncate">{m.name}</span>
                    <PartyBadge party={{
                      partyType: m.party_type ?? 'internal', role: m.role,
                      orgName: m.organization_name, position: m.position,
                    }} />
                  </div>
                  <div className="text-[11px] text-muted-foreground truncate">{m.email}</div>
                </TableCell>
                <TableCell className="py-1.5 text-xs">{m.role_name ?? (m.role === 'admin' ? 'Администратор' : '—')}</TableCell>
                <TableCell className="py-1.5"><AccessSummary modules={m.role === 'admin' ? null : (m.modules ?? null)} /></TableCell>
                <TableCell className="py-1.5 text-[11px] text-muted-foreground">
                  {m.role === 'admin' || !m.object_scope?.length
                    ? 'вся сеть'
                    : `${m.object_scope.length} объектов`}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

/** Создание (clone-to-create + diff) / правка кастомной роли. */
function RoleEditDialog({ companyId, roles, editRole, onSaved }: {
  companyId: string; roles: CompanyRole[]; editRole?: CompanyRole; onSaved: () => void
}) {
  const isEdit = !!editRole
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(editRole?.name ?? '')
  const [full, setFull] = useState(editRole ? editRole.modules == null : false)
  const [sel, setSel] = useState<Set<string>>(new Set(editRole?.modules ?? []))
  const [cloneId, setCloneId] = useState<string>('')
  useEffect(() => {
    if (open) {
      setName(editRole?.name ?? ''); setFull(editRole ? editRole.modules == null : false)
      setSel(new Set(editRole?.modules ?? [])); setCloneId('')
    }
  }, [open, editRole])
  const applyClone = (id: string) => {
    setCloneId(id)
    const src = roles.find((r) => r.id === id)
    if (src) { setFull(src.modules == null); setSel(new Set(src.modules ?? [])) }
  }
  const save = useMutation({
    mutationFn: () => isEdit
      ? roleService.updateRole(editRole!.id, companyId, name.trim(), full ? null : Array.from(sel))
      : roleService.createRole(companyId, name.trim(), full ? null : Array.from(sel)),
    onSuccess: () => { toast.success(isEdit ? 'Роль сохранена' : 'Роль создана'); onSaved(); setOpen(false) },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const toggle = (k: string) => setSel((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })
  const tmpl = roles.find((r) => r.id === cloneId)
  const tmplSet = tmpl && tmpl.modules ? new Set(tmpl.modules) : null
  const cur = full ? null : sel
  const added = tmplSet && cur ? [...cur].filter((k) => !tmplSet.has(k)) : []
  const removed = tmplSet && cur ? [...tmplSet].filter((k) => !cur.has(k)) : []
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {isEdit
          ? <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-foreground" title="Изменить роль"><Pencil className="h-3.5 w-3.5" /></Button>
          : <Button size="sm" className="gap-1"><Plus className="h-4 w-4" /> Создать роль</Button>}
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>{isEdit ? 'Изменить роль' : 'Новая роль'}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Название</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="напр. Главбух" />
          </div>
          {!isEdit && (
            <div className="space-y-1.5">
              <Label className="flex items-center gap-1"><Copy className="h-3.5 w-3.5" /> Клонировать из</Label>
              <Select value={cloneId} onValueChange={applyClone}>
                <SelectTrigger><SelectValue placeholder="— с нуля —" /></SelectTrigger>
                <SelectContent>{roles.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          )}
          <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
            <input type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} className="h-4 w-4" />
            Полный доступ (все модули)
          </label>
          <ModuleCheckboxGrid companyId={companyId} sel={sel} onToggle={toggle} disabled={full} />
          {tmpl && (added.length > 0 || removed.length > 0) && (
            <div className="text-[11px] rounded-md border bg-muted/30 p-2">
              <span className="text-muted-foreground">Отличия от «{tmpl.name}»: </span>
              {added.map((k) => <span key={k} className="text-emerald-500">+{moduleLabels([k])[0]} </span>)}
              {removed.map((k) => <span key={k} className="text-red-500">−{moduleLabels([k])[0]} </span>)}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Отмена</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !name.trim()}>
            {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />}{isEdit ? 'Сохранить' : 'Создать'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Вкладка «Журнал»: последние изменения доступа/ролей/команды. */
export function AuditTab({ companyId }: { companyId: string }) {
  const q = useQuery({ queryKey: ['audit', companyId], queryFn: () => roleService.listAudit(companyId, 150) })
  const RBAC = /^(role\.|member\.|user\.)/
  const rows = (q.data ?? []).filter((e) => RBAC.test(e.action))
  const ACTION_LABEL: Record<string, string> = {
    'role.create': 'Роль создана', 'role.update': 'Роль изменена', 'role.delete': 'Роль удалена',
    'member.access': 'Доступ изменён', 'member.role': 'Роль сотрудника',
    'user.create': 'Сотрудник добавлен', 'user.remove': 'Сотрудник убран',
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><History className="h-5 w-5" /> Журнал изменений</CardTitle>
        <CardDescription>Кто, когда и что менял в доступе, ролях и команде</CardDescription>
      </CardHeader>
      <CardContent>
        {q.isLoading && <Loading />}
        <Table>
          <TableHeader><TableRow>
            <TableHead className="w-[150px]">Когда</TableHead>
            <TableHead className="w-[170px]">Действие</TableHead>
            <TableHead className="w-[170px]">Кто</TableHead>
            <TableHead>Детали</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {!q.isLoading && rows.length === 0 && (
              <TableRow><TableCell colSpan={4} className="text-center text-sm text-muted-foreground py-6">Нет записей</TableCell></TableRow>
            )}
            {rows.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{new Date(e.timestamp).toLocaleString('ru-RU')}</TableCell>
                <TableCell><Badge variant="secondary" className="text-[10px] font-normal">{ACTION_LABEL[e.action] ?? e.action}</Badge></TableCell>
                <TableCell className="text-xs">{e.user_name ?? '—'}</TableCell>
                <TableCell className="text-xs text-muted-foreground truncate max-w-0">{e.details ?? ''}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

/** Диалог назначения доступа члену: именованная роль ИЛИ ad-hoc набор модулей. */
function AccessDialog({ member, companyId, roles, onSaved }: {
  member: AdminUser; companyId: string; roles: CompanyRole[]; onSaved: () => void
}) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<'role' | 'custom'>(member.role_id ? 'role' : 'custom')
  const [roleId, setRoleId] = useState<string>(member.role_id ?? '')
  const [full, setFull] = useState(member.modules == null && !member.role_id)
  const [sel, setSel] = useState<Set<string>>(new Set(member.modules ?? ALL_ACCESS_KEYS))
  useEffect(() => {
    if (open) {
      setMode(member.role_id ? 'role' : 'custom')
      setRoleId(member.role_id ?? roles[0]?.id ?? '')
      setFull(member.modules == null && !member.role_id)
      setSel(new Set(member.modules ?? ALL_ACCESS_KEYS))
    }
  }, [open, member.role_id, member.modules, roles])
  const save = useMutation({
    mutationFn: () => mode === 'role'
      ? userService.setMemberAccess(member.id, companyId, { mode: 'role', roleId })
      : userService.setMemberAccess(member.id, companyId, { mode: 'custom', modules: full ? null : Array.from(sel) }),
    onSuccess: () => { toast.success('Доступ сохранён'); onSaved(); setOpen(false) },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const toggle = (k: string) => setSel((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })
  const selRole = roles.find((r) => r.id === roleId)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-foreground shrink-0" title="Настроить доступ">
          <SlidersHorizontal className="h-3.5 w-3.5" />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>Доступ: {member.name}</DialogTitle></DialogHeader>
        <div className="flex gap-1">
          <Button variant={mode === 'role' ? 'default' : 'outline'} size="sm" className="h-7 text-xs px-3" onClick={() => setMode('role')}>По роли</Button>
          <Button variant={mode === 'custom' ? 'default' : 'outline'} size="sm" className="h-7 text-xs px-3" onClick={() => setMode('custom')}>Вручную</Button>
        </div>
        {mode === 'role' ? (
          <div className="space-y-3">
            <Select value={roleId} onValueChange={setRoleId}>
              <SelectTrigger><SelectValue placeholder="Выберите роль" /></SelectTrigger>
              <SelectContent>{roles.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
            </Select>
            {selRole && (
              <div className="rounded-md border p-2.5">
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1.5">Модули роли</div>
                <div className="flex flex-wrap gap-1">
                  {selRole.modules == null
                    ? <Badge variant="outline" className="text-[10px] gap-1"><ShieldCheck className="h-3 w-3" /> Все модули</Badge>
                    : moduleLabels(selRole.modules).map((l) => <Badge key={l} variant="secondary" className="text-[10px] font-normal">{l}</Badge>)}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
              <input type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} className="h-4 w-4" />
              Полный доступ (все приложения и модули)
            </label>
            <ModuleCheckboxGrid companyId={companyId} sel={sel} onToggle={toggle} disabled={full} />
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Отмена</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || (mode === 'role' && !roleId)}>
            {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />}Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
