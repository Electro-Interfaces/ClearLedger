/**
 * Команда компании: сотрудники (роль-на-компанию) + приглашения по email.
 * Используется в админ-разделе (мастер-деталь) для выбранной компании.
 */
import { useState } from 'react'
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
  Mail, UserPlus, Trash2, Loader2, Send, X,
  KeyRound, Plus, Pencil, Copy, Share2, Users,
} from 'lucide-react'
import * as userService from '@/services/userService'
import * as invitationService from '@/services/invitationService'
import { useCompany } from '@/contexts/CompanyContext'
import { InviteLinkPanel } from './InviteLinkPanel'
import * as roleService from '@/services/roleService'
import type { CompanyRole } from '@/services/roleService'
import { moduleLabels } from '@/config/accessModules'
import { AccessMatrix, AccessSummary } from './AccessMatrix'
import { AccessTreeGrid } from './AccessTreeGrid'
import { DepartmentsPanel } from './DepartmentsPanel'
import { MembersBoard } from './MembersBoard'
import { projectSpaceUsers, listSpaceOrganizations } from '@/services/spaceObjectsService'
import { PartyBadge } from '@/components/chat/PartyBadge'
import { StoreBusinessAccess } from './StoreBusinessAccess'

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

/**
 * Состав пространства: свои сотрудники ИЛИ люди компаний-партнёров.
 *
 * `party` делит один список на два раздела «Управления». Это не косметика: у
 * сотрудника организации и у представителя подрядчика разные вопросы («кому что можно
 * внутри» против «какая сторонняя компания допущена и до чего»), и в общем списке
 * партнёр читался как свой — отличить можно было только заглянув в колонку «Кто это».
 * Партнёров показываем сгруппированными по их компании: единица учёта здесь — компания,
 * а не человек.
 *
 * Сам состав рисует `MembersBoard` — карта «человек × продукты». Здесь остаются только
 * действия раздела: завести человека, пригласить, отправить людей в приложения.
 */
export function MembersCard({
  companyId, canManage, selfId, party = 'internal',
}: {
  companyId: string; canManage: boolean; selfId: string
  party?: 'internal' | 'external'
}) {
  // Организации пространства нужны, чтобы указать, КОГО представляет внешний участник.
  const orgsQ = useQuery({
    queryKey: ['space-orgs', companyId],
    queryFn: () => listSpaceOrganizations(companyId),
    enabled: canManage,
    retry: false,
  })
  const projectUsers = useMutation({
    mutationFn: () => projectSpaceUsers(companyId, 'support'),
    onSuccess: (r) => toast.success(
      `Поддержка обновлена: создано ${r.created}, обновлено ${r.updated}`,
      { description: `Отправлено сотрудников: ${r.sent}` },
    ),
    onError: (e) => toast.error('Проекция не выполнена', { description: (e as Error).message }),
  })

  return (
    <Card>
      {/* Название раздела и его смысл — в шапке рабочей области («Управление»),
          здесь только действия и сам состав: заголовок дважды не нужен. */}
      <CardContent className="pt-6">
        <MembersBoard companyId={companyId} canManage={canManage} selfId={selfId} party={party}
          toolbar={canManage ? (
            <>
              {/* Люди пространства должны быть и в приложениях-разрезах: заводим один
                  раз здесь, проекция доносит их до Координатора (docs/SPACE.md).
                  Проекция отправляет весь состав, поэтому кнопка одна — в «Сотрудниках». */}
              {party === 'internal' && (
                <Button variant="outline" size="sm" className="h-8 gap-1.5"
                  disabled={projectUsers.isPending} onClick={() => projectUsers.mutate()}
                  title="Отправить людей пространства в приложения экосистемы">
                  {projectUsers.isPending
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <Share2 className="h-4 w-4" />}
                  В приложения
                </Button>
              )}
              <InviteDialog companyId={companyId} party={party} orgs={orgsQ.data ?? []} />
              <AddUserDialog companyId={companyId} party={party} orgs={orgsQ.data ?? []} />
            </>
          ) : null} />
        {/* Штатная структура — в том же разделе: люди и их подразделения это один
            вопрос «кто где работает и кто кому подчиняется» (решение МАГа 31.07.2026). */}
        {party === 'internal' && (
          <div className="mt-6 border-t pt-4">
            <h3 className="mb-2 text-sm font-semibold">Подразделения</h3>
            <DepartmentsPanel companyId={companyId} canManage={canManage} />
          </div>
        )}
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
    // Ссылку сразу кладём в буфер: за ней сюда и приходят — переслать человеку
    // мессенджером. Раньше её надо было доставать из диалога вторым кликом, а сам
    // диалог открывался кнопкой «Отправить снова», по имени которой не догадаться,
    // что это вообще единственный способ взять ссылку.
    onSuccess: async (inv) => {
      setLinkFor(inv)
      qc.invalidateQueries({ queryKey: ['team-invites', companyId] })
      if (inv.invite_url) {
        try {
          await navigator.clipboard.writeText(inv.invite_url)
          toast.success('Ссылка скопирована — можно вставить в мессенджер')
        } catch {
          // Буфер закрыт политикой браузера — ссылка всё равно видна в диалоге.
          toast.info('Ссылка готова — скопируйте её в открывшемся окне')
        }
      }
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
          Ожидают принятия: человек попадёт в «Сотрудники», когда перейдёт по ссылке и
          задаст пароль. «Скопировать ссылку» выпускает новую, кладёт её в буфер и
          заодно отправляет письмо повторно — прежняя ссылка при этом перестаёт работать.
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
                <TableCell className="space-y-1">
                  <Badge variant="secondary" className="text-[10px]">{ROLE_LABEL[i.role] ?? i.role}</Badge>
                  {/* Охват виден в списке: приглашение в пространство касается всех
                      организаций и показывается в каждой из них — без пометки было бы
                      непонятно, почему чужое приглашение стоит в этом списке. */}
                  {i.scope === 'space' && (
                    <Badge variant="outline"
                      className="block w-fit text-[10px] border-blue-500/40 bg-blue-500/5">
                      всё пространство
                    </Badge>
                  )}
                  {i.company_id && i.company_id !== companyId && i.company_name && (
                    <span className="block text-[10px] text-muted-foreground">
                      выпущено в «{i.company_name}»
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {new Date(i.created_at).toLocaleDateString('ru')}
                  <span className="block">
                    до {new Date(i.expires_at).toLocaleDateString('ru')}
                  </span>
                </TableCell>
                <TableCell>
                  {/* Распоряжаться приглашением вправе админ ТОЙ организации, где оно
                      выпущено. Приглашение в пространство видно из любой, поэтому у
                      чужого действия скрыты: кнопка, дающая 403, хуже её отсутствия. */}
                  {i.company_id && i.company_id !== companyId ? (
                    <div className="text-right text-xs text-muted-foreground">
                      управляется в «{i.company_name ?? 'другой организации'}»
                    </div>
                  ) : (
                  <div className="flex items-center justify-end gap-1">
                    {/* Явная кнопка, а не иконка: письмо теряется в спаме, и
                        «взять ссылку и переслать» — самое частое действие в этой
                        таблице. Прячась под пиктограммой, оно не находится.
                        Названа по результату («Скопировать ссылку»), а не по
                        механике («отправить снова»): письмо при этом тоже уходит
                        повторно, но пришли сюда не за ним. */}
                    <Button variant="outline" size="sm" className="h-8"
                      title="Выпустить новую ссылку, скопировать её в буфер и заодно отправить письмо повторно"
                      disabled={resend.isPending} onClick={() => resend.mutate(i.id)}>
                      {resend.isPending && resend.variables === i.id
                        ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                        : <Copy className="h-3.5 w-3.5 mr-1.5" />}
                      Скопировать ссылку
                    </Button>
                    <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      title="Отозвать" disabled={revoke.isPending} onClick={() => revoke.mutate(i.id)}>
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  )}
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

function InviteDialog({ companyId, party = 'internal', orgs = [] }: {
  companyId: string
  party?: 'internal' | 'external'
  orgs?: { id: string; name: string; shortName?: string | null }[]
}) {
  const qc = useQueryClient()
  const external = party === 'external'
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [position, setPosition] = useState('')
  const [role, setRole] = useState<'user' | 'admin'>('user')
  // Какую компанию представляет приглашаемый. Хранится в приглашении: иначе принявший
  // его партнёр попадает в раздел сотрудников организации и ждёт ручной пометки.
  const [orgId, setOrgId] = useState('')
  // Куда зовём: в эту организацию или в пространство целиком. Пространство и
  // организация — разные вещи: «Аудит» это имя ПРОСТРАНСТВА, внутри которого своя
  // практика и обслуживаемые организации. Выбор показываем только там, где он есть,
  // то есть когда организаций больше одной.
  const [scope, setScope] = useState<invitationService.InviteScope>('company')
  const { companies } = useCompany()
  const multiCompany = companies.length > 1
  // Созданное приглашение со ссылкой. Диалог после успеха НЕ закрывается:
  // ссылку отдают один раз, закрыть его до копирования — потерять её.
  const [created, setCreated] = useState<invitationService.Invitation | null>(null)

  const reset = () => {
    setEmail(''); setPosition(''); setRole('user'); setOrgId('')
    setScope('company'); setCreated(null)
  }

  const invite = useMutation({
    mutationFn: () => invitationService.createInvitation(companyId, email, role, position,
      external
        ? { partyType: 'partner', organizationId: orgId, scope }
        : { scope }),
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
          <DialogTitle>
            {created ? 'Приглашение создано'
              : external ? 'Пригласить человека компании-партнёра' : 'Пригласить сотрудника'}
          </DialogTitle>
        </DialogHeader>

        {created ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {created.email}
              {created.position ? ` · ${created.position}` : ''} · {ROLE_LABEL[created.role] ?? created.role}
              {created.organization_name ? ` · ${created.organization_name}` : ''}
            </p>
            <InviteLinkPanel invitation={created} />
          </div>
        ) : (
          <div className="space-y-3">
            <div className="space-y-2">
              <Label>{external ? 'Email представителя' : 'Email сотрудника'}</Label>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="employee@company.ru" />
            </div>
            {external && (
              <div className="space-y-2">
                <Label>Компания-партнёр</Label>
                <Select value={orgId} onValueChange={setOrgId}>
                  <SelectTrigger><SelectValue placeholder="Выберите компанию из контрагентов" /></SelectTrigger>
                  <SelectContent>
                    {orgs.map((o) => (
                      <SelectItem key={o.id} value={o.id}>{o.shortName || o.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Компании берутся из контрагентов пространства («Справочники»). Ею человек
                  будет подписан в чатах и заявках.
                </p>
              </div>
            )}
            {multiCompany && (
              <div className="space-y-2">
                <Label>Куда приглашаем</Label>
                <Select value={scope}
                  onValueChange={(v) => setScope(v as invitationService.InviteScope)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="company">Только в эту организацию</SelectItem>
                    <SelectItem value="space">
                      Во всё пространство — {companies.length} организации
                    </SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {scope === 'space'
                    ? 'Человек получит доступ ко всем организациям пространства, включая их данные.'
                    : 'Доступ только к данным этой организации. Остальные пространства человек не увидит.'}
                </p>
              </div>
            )}
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
              Приглашённому придёт письмо со ссылкой — по ней он укажет ФИО, при
              необходимости поправит должность и задаст пароль; изменить нельзя только
              email. Ссылка действует 7 дней; повторная отправка выпускает новую ссылку,
              прежняя перестаёт работать. Ссылку можно скопировать и отправить мессенджером.
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
            // Партнёра без компании не приглашаем: он окажется участником без стороны в
            // чатах и заявках, а разобраться потом сложнее, чем выбрать сейчас.
            <Button disabled={!email || (external && !orgId) || invite.isPending} onClick={() => invite.mutate()}>
              {invite.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />} Создать приглашение
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AddUserDialog({ companyId, party = 'internal', orgs = [] }: {
  companyId: string
  party?: 'internal' | 'external'
  orgs?: { id: string; name: string; shortName?: string | null }[]
}) {
  const qc = useQueryClient()
  const external = party === 'external'
  const [open, setOpen] = useState(false)
  const empty = { name: '', email: '', password: '', position: '', role: 'user' as 'user' | 'admin', orgId: '' }
  const [form, setForm] = useState(empty)

  const create = useMutation({
    mutationFn: () => userService.createUser({
      companyId, name: form.name, email: form.email, password: form.password,
      position: form.position, role: form.role,
      // Принадлежность ставится при создании, а не правится потом: заведённый из
      // раздела партнёров человек не должен появляться в сотрудниках организации.
      ...(external ? { partyType: 'partner' as const, organizationId: form.orgId } : {}),
    }),
    onSuccess: () => {
      toast.success(external ? 'Представитель компании добавлен' : 'Сотрудник добавлен')
      setForm(empty); setOpen(false)
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
        <DialogHeader><DialogTitle>
          {external ? 'Добавить представителя компании-партнёра' : 'Добавить сотрудника вручную'}
        </DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-2"><Label>ФИО</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Фамилия Имя Отчество" /></div>
            <div className="space-y-2"><Label>Email</Label>
              <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            {external && (
              <div className="space-y-2 col-span-2"><Label>Компания-партнёр</Label>
                <Select value={form.orgId} onValueChange={(v) => setForm({ ...form, orgId: v })}>
                  <SelectTrigger><SelectValue placeholder="Выберите компанию из контрагентов" /></SelectTrigger>
                  <SelectContent>
                    {orgs.map((o) => (
                      <SelectItem key={o.id} value={o.id}>{o.shortName || o.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select></div>
            )}
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
          <Button disabled={!form.email || !form.name || form.password.length < 6
            || (external && !form.orgId) || create.isPending}
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
      <StoreBusinessAccess companyId={companyId} canManage={canManage} />
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
  const changeOpen = (next: boolean) => {
    if (next) {
      setName(editRole?.name ?? '')
      setFull(editRole ? editRole.modules == null : false)
      setSel(new Set(editRole?.modules ?? []))
      setCloneId('')
    }
    setOpen(next)
  }
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
  const toggle = (k: string) => setSel((s) => {
    const n = new Set(s)
    if (n.has(k)) n.delete(k)
    else n.add(k)
    return n
  })
  // «Разжать» продукт из грида: снять отметку целиком, оставить разделы кроме закрытого.
  const carve = (app: string, keep: string[]) => setSel((s) =>
    new Set([...[...s].filter((k) => k !== app && !k.startsWith(`${app}:`)), ...keep]))
  const tmpl = roles.find((r) => r.id === cloneId)
  const tmplSet = tmpl && tmpl.modules ? new Set(tmpl.modules) : null
  const cur = full ? null : sel
  const added = tmplSet && cur ? [...cur].filter((k) => !tmplSet.has(k)) : []
  const removed = tmplSet && cur ? [...tmplSet].filter((k) => !cur.has(k)) : []
  return (
    <Dialog open={open} onOpenChange={changeOpen}>
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
          <AccessTreeGrid companyId={companyId} sel={sel} onToggle={toggle} onCarve={carve} disabled={full} />
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
