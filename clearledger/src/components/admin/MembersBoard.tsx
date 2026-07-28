/**
 * Состав пространства как карта доступа: строка — человек, столбцы — продукты.
 *
 * Списком с диалогами это не читалось: чтобы понять, кто куда допущен, приходилось
 * открывать по диалогу на каждого, а продуктов уже больше десятка. Здесь одним
 * взглядом видно всех и все их подключения, стрелка раскрывает человека до разделов
 * внутри продуктов, а карточка рядом отвечает на вопрос «кто это» — должность,
 * реквизиты, чью сторону представляет.
 *
 * Три слоя доступа, которые здесь настраиваются, разные и не подменяют друг друга:
 *  • уровень членства (сотрудник / администратор) — в карточке;
 *  • права: продукт целиком или его разделы — галочки матрицы и разворота;
 *  • объекты: по каким из них видны данные на открытых экранах — отдельной кнопкой.
 *
 * Правки копятся черновиком и уходят на сервер одной кнопкой: доступ правят пачкой
 * («этим двоим — Проекты, этому — только обзор»), и запрос на каждую галочку означал
 * бы полсотни запросов и невозможность передумать.
 */
import { Fragment, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Building2, Check, ChevronDown, ChevronRight, Circle, KeyRound, LifeBuoy, Loader2,
  Minus, Search, ShieldCheck, SlidersHorizontal, Trash2, Undo2, X,
} from 'lucide-react'
import * as userService from '@/services/userService'
import type { AdminUser } from '@/services/userService'
import * as roleService from '@/services/roleService'
import type { CompanyRole } from '@/services/roleService'
import { listSpaceOrganizations } from '@/services/spaceObjectsService'
import { useAccessTree, type AccessApp } from '@/hooks/useAccessTree'
import { appIcon } from '@/config/appIcons'
import { appState, toggleAccessKey, sameAccess, type AppAccess } from '@/lib/accessKeys'
import { AccessTreeGrid } from './AccessTreeGrid'
import { ObjectScopeDialog } from './ObjectScopeDialog'
import { PartyBadge } from '@/components/chat/PartyBadge'

export function MembersBoard({
  companyId, canManage, selfId, party = 'internal', toolbar,
}: {
  companyId: string
  canManage: boolean
  selfId: string
  party?: 'internal' | 'external'
  /** Кнопки раздела (пригласить, добавить, проекция) — они разные у своих и внешних. */
  toolbar?: React.ReactNode
}) {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [cardFor, setCardFor] = useState<string | null>(null)
  const [draft, setDraft] = useState<Record<string, string[] | null>>({})
  const [saving, setSaving] = useState(false)

  const q = useQuery({
    queryKey: ['team-members', companyId],
    queryFn: () => userService.listUsers(companyId),
  })
  const rolesQ = useQuery({
    queryKey: ['company-roles', companyId],
    queryFn: () => roleService.listRoles(companyId),
    enabled: canManage,
  })
  const orgsQ = useQuery({
    queryKey: ['space-orgs', companyId],
    queryFn: () => listSpaceOrganizations(companyId),
    enabled: canManage,
    retry: false,
  })
  const { tree, isLoading: treeLoading } = useAccessTree(companyId)
  const roles = rolesQ.data ?? []

  const refresh = () => qc.invalidateQueries({ queryKey: ['team-members', companyId] })

  // Принадлежность не задана — свой сотрудник: так было до появления партнёров, и
  // перенесённые люди заказчика идут без явной пометки.
  const isExternal = (m: AdminUser) => m.party_type === 'partner' || m.party_type === 'vendor'
  const members = (q.data ?? []).filter((m) => (party === 'external' ? isExternal(m) : !isExternal(m)))
  const filtered = search.trim()
    ? members.filter((m) => `${m.name} ${m.email} ${m.position ?? ''} ${m.organization_name ?? ''}`
        .toLowerCase().includes(search.trim().toLowerCase()))
    : members

  /** Внешние — группами по компаниям: единица учёта здесь компания, а не человек. */
  const groups = useMemo(() => {
    if (party !== 'external') return null
    const byOrg = new Map<string, { label: string; kind: 'partner' | 'vendor' | 'none'; rows: AdminUser[] }>()
    for (const m of filtered) {
      const vendor = m.party_type === 'vendor'
      const key = vendor ? '￿vendor' : (m.organization_id ?? '￾none')
      const label = vendor ? 'Поддержка платформы' : (m.organization_name || 'Компания не указана')
      const kind = vendor ? 'vendor' as const : (m.organization_id ? 'partner' as const : 'none' as const)
      if (!byOrg.has(key)) byOrg.set(key, { label, kind, rows: [] })
      byOrg.get(key)!.rows.push(m)
    }
    return [...byOrg.entries()].sort(([a], [b]) => a.localeCompare(b, 'ru')).map(([key, g]) => ({ key, ...g }))
  }, [party, filtered])

  /** Полный доступ — у администратора и суперадмина: галочки им не нужны. */
  const isFullByRole = (u: AdminUser) => u.is_superadmin || u.role === 'admin'
  const effective = (u: AdminUser): string[] | null =>
    isFullByRole(u) ? null : (u.id in draft ? draft[u.id] : (u.modules ?? null))
  const locked = (u: AdminUser) => !canManage || u.is_superadmin || u.id === selfId

  const dirty = Object.keys(draft).filter((id) => {
    const u = members.find((m) => m.id === id)
    return u ? !sameAccess(draft[id], u.modules ?? null) : false
  })

  const setKeys = (u: AdminUser, next: string[] | null) =>
    setDraft((d) => ({ ...d, [u.id]: next }))

  const toggle = (u: AdminUser, key: string, app: string) => {
    if (locked(u) || isFullByRole(u)) return
    const cur = effective(u)
    // От «всех продуктов» первая же снятая галочка уводит к явному списку — иначе
    // непонятно, что осталось: показываем полный набор минус снятое.
    const base = cur === null ? tree.map((a) => a.app) : cur
    setKeys(u, toggleAccessKey(base, key, app))
  }

  const save = async () => {
    setSaving(true)
    try {
      for (const id of dirty) {
        await userService.setMemberAccess(id, companyId, { mode: 'custom', modules: draft[id] })
      }
      toast.success(`Доступ сохранён: ${dirty.length} чел.`)
      setDraft({})
      refresh()
    } catch (e) {
      toast.error('Не сохранено', { description: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  const card = members.find((m) => m.id === cardFor) ?? null

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder={party === 'external' ? 'Поиск: ФИО, email, компания…' : 'Поиск: ФИО, email, должность…'}
            className="h-8 pl-8 text-sm" />
        </div>
        <div className="flex items-center gap-2">
          {dirty.length > 0 && (
            <>
              <Button variant="ghost" size="sm" className="h-8 gap-1 text-muted-foreground"
                onClick={() => setDraft({})} disabled={saving}>
                <Undo2 className="h-3.5 w-3.5" /> Отменить
              </Button>
              <Button size="sm" className="h-8" onClick={save} disabled={saving}>
                {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />}
                Сохранить ({dirty.length})
              </Button>
            </>
          )}
          {toolbar}
        </div>
      </div>

      <div className="rounded-xl border border-border">
        <HeaderRow apps={tree} loading={treeLoading} />
        <div className="divide-y divide-border/60">
          {q.isLoading && (
            <div className="flex items-center gap-2 px-3 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
            </div>
          )}
          {!q.isLoading && filtered.length === 0 && (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              {members.length > 0 ? 'Ничего не найдено'
                : party === 'external'
                  ? 'Внешних участников нет. Пригласите человека компании-партнёра — он появится здесь, а не в сотрудниках организации.'
                  : 'Нет сотрудников'}
            </div>
          )}
          {(groups
            ? groups.flatMap((g) => [{ group: g }, ...g.rows.map((u) => ({ u }))] as Array<{ group?: typeof g; u?: AdminUser }>)
            : filtered.map((u) => ({ u } as { group?: never; u?: AdminUser }))
          ).map((item) => {
            if (item.group) {
              const g = item.group
              return (
                <div key={`g-${g.key}`} className="flex items-center gap-2 bg-muted/40 px-3 py-1.5 text-sm font-medium">
                  {g.kind === 'vendor'
                    ? <LifeBuoy className="h-3.5 w-3.5 text-primary" />
                    : <Building2 className="h-3.5 w-3.5 text-muted-foreground" />}
                  {g.label}
                  <span className="text-xs font-normal text-muted-foreground">· {g.rows.length} чел.</span>
                  {g.kind === 'none' && (
                    <span className="text-xs font-normal text-amber-500/90">
                      — укажите компанию, иначе в чатах и заявках человек без стороны
                    </span>
                  )}
                </div>
              )
            }
            const u = item.u!
            return (
              <Fragment key={u.id}>
                <MemberRow
                  u={u} apps={tree} keys={effective(u)} full={isFullByRole(u)}
                  locked={locked(u)} changed={dirty.includes(u.id)}
                  expanded={!!expanded[u.id]} party={party}
                  onExpand={() => setExpanded((e) => ({ ...e, [u.id]: !e[u.id] }))}
                  onToggleApp={(app) => toggle(u, app, app)}
                  onCard={() => setCardFor(u.id)}
                  companyId={companyId} onSaved={refresh}
                />
                {expanded[u.id] && (
                  <MemberAccessPanel
                    u={u} companyId={companyId} keys={effective(u)} full={isFullByRole(u)}
                    locked={locked(u)} apps={tree}
                    onToggle={(key, app) => toggle(u, key, app)}
                    onSetAll={() => setKeys(u, null)}
                    onSetNone={() => setKeys(u, [])}
                    onReset={() => setDraft((d) => { const n = { ...d }; delete n[u.id]; return n })}
                    changed={dirty.includes(u.id)}
                  />
                )}
              </Fragment>
            )
          })}
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        {party === 'external'
          ? `Внешних участников: ${members.length} из ${groups?.length ?? 0} компаний`
          : `Сотрудников: ${members.length}`}
        {filtered.length !== members.length ? ` · показано ${filtered.length}` : ''}
        {' · '}<Check className="inline h-3 w-3 text-primary" /> продукт целиком
        {' · '}<Circle className="inline h-2.5 w-2.5 fill-primary/60 text-primary/60" /> отдельные разделы
        {' · '}<Minus className="inline h-3 w-3" /> нет доступа
        {' · администратор организации видит всё'}
      </p>

      <Sheet open={!!card} onOpenChange={(o) => { if (!o) setCardFor(null) }}>
        <SheetContent side="right" className="w-full sm:max-w-md p-0">
          <SheetTitle className="sr-only">Карточка участника</SheetTitle>
          <SheetDescription className="sr-only">Реквизиты, уровень доступа и принадлежность</SheetDescription>
          {card && (
            <MemberCard
              u={card} companyId={companyId} canManage={canManage} isSelf={card.id === selfId}
              roles={roles} orgs={orgsQ.data ?? []} onSaved={refresh}
              onClose={() => setCardFor(null)}
            />
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

/** Шапка матрицы: продукты значками — имена в заголовках столбцов не помещаются. */
function HeaderRow({ apps, loading }: { apps: AccessApp[]; loading: boolean }) {
  return (
    <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-3 py-2 text-[11px] uppercase tracking-wide text-muted-foreground">
      <span className="w-5 shrink-0" />
      <span className="min-w-0 flex-1">Участник</span>
      <span className="hidden w-[150px] shrink-0 xl:block">Кто это</span>
      <span className="flex shrink-0 items-center">
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {apps.map((a) => {
          const Icon = appIcon(a.icon)
          return (
            <span key={a.app} className="flex w-8 justify-center" title={a.name}>
              <Icon className="h-3.5 w-3.5" />
            </span>
          )
        })}
      </span>
      <span className="hidden w-[132px] shrink-0 lg:block">Права</span>
      <span className="w-[92px] shrink-0 text-right">Объекты</span>
      <span className="w-[68px] shrink-0" />
    </div>
  )
}

function MemberRow({
  u, apps, keys, full, locked, changed, expanded, party, onExpand, onToggleApp, onCard,
  companyId, onSaved,
}: {
  u: AdminUser; apps: AccessApp[]; keys: string[] | null; full: boolean; locked: boolean
  changed: boolean; expanded: boolean; party: 'internal' | 'external'
  onExpand: () => void; onToggleApp: (app: string) => void; onCard: () => void
  companyId: string; onSaved: () => void
}) {
  return (
    <div className={`flex items-center gap-2 px-3 py-2 transition-colors ${
      changed ? 'bg-primary/5' : 'hover:bg-accent/30'
    }`}>
      <button type="button" onClick={onExpand} className="w-5 shrink-0 text-muted-foreground hover:text-foreground"
        title="Разделы продуктов">
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>

      <button type="button" onClick={onCard} className="min-w-0 flex-1 text-left">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium">{u.name || u.email}</span>
          {u.is_superadmin && (
            <Badge variant="outline" className="shrink-0 gap-1 text-[10px]"><ShieldCheck className="h-3 w-3" /> супер</Badge>
          )}
          {u.role === 'admin' && !u.is_superadmin && (
            <Badge variant="secondary" className="shrink-0 text-[10px]">админ</Badge>
          )}
        </span>
        <span className="block truncate text-xs text-muted-foreground">
          {u.email}{u.position ? ` · ${u.position}` : ''}
        </span>
      </button>

      <span className="hidden w-[150px] shrink-0 xl:block">
        {party === 'external'
          ? <PartyBadge party={{
              partyType: u.party_type ?? 'internal', role: u.role,
              orgName: u.organization_name, position: u.position,
            }} />
          : <span className="truncate text-xs text-muted-foreground">{u.position || '— должность —'}</span>}
      </span>

      <span className="flex shrink-0 items-center">
        {apps.map((a) => (
          <AppCell key={a.app} state={appState(keys, a.app)} name={a.name}
            locked={locked || full} onClick={() => onToggleApp(a.app)} />
        ))}
      </span>

      <span className="hidden w-[132px] shrink-0 lg:block">
        {full
          ? <span className="text-[11px] text-muted-foreground">все продукты</span>
          : u.role_name
            ? <Badge className="gap-1 text-[10px]"><KeyRound className="h-3 w-3" />{u.role_name}</Badge>
            : keys === null
              ? <span className="text-[11px] text-muted-foreground">все продукты</span>
              : keys.length === 0
                ? <span className="text-[11px] text-destructive/80">нет доступа</span>
                : <span className="text-[11px] text-muted-foreground">
                    свой набор · {keys.filter((k) => !k.includes(':')).length}/{keys.filter((k) => k.includes(':')).length}
                  </span>}
      </span>

      <span className="w-[92px] shrink-0 text-right">
        {u.role === 'admin' || u.is_superadmin
          ? <span className="text-[11px] text-muted-foreground">вся сеть</span>
          : <ObjectScopeDialog member={u} companyId={companyId} onSaved={onSaved} />}
      </span>

      <span className="flex w-[68px] shrink-0 items-center justify-end gap-0.5">
        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-foreground"
          title="Карточка участника" onClick={onCard}>
          <SlidersHorizontal className="h-3.5 w-3.5" />
        </Button>
      </span>
    </div>
  )
}

function AppCell({ state, name, locked, onClick }: {
  state: AppAccess; name: string; locked: boolean; onClick: () => void
}) {
  const title = locked
    ? `${name} — правится в карточке`
    : state === 'full' ? `${name}: продукт целиком — снять`
      : state === 'part' ? `${name}: отдельные разделы — открыть весь продукт`
        : `${name}: нет доступа — открыть`
  return (
    <span className="flex w-8 justify-center">
      <button type="button" onClick={onClick} disabled={locked} title={title}
        className={`inline-flex h-6 w-6 items-center justify-center rounded border transition-colors ${
          state === 'none' ? 'border-border' : 'border-primary/50 bg-primary/15'
        } ${locked ? 'cursor-default opacity-60' : 'cursor-pointer hover:border-primary/60'}`}>
        {state === 'full' && <Check className="h-3.5 w-3.5 text-primary" />}
        {state === 'part' && <Circle className="h-2.5 w-2.5 fill-primary/70 text-primary/70" />}
        {state === 'none' && <Minus className="h-3 w-3 text-muted-foreground/40" />}
      </button>
    </span>
  )
}

/** Разворот строки: разделы внутри продуктов — то, чего не помещается в матрицу. */
function MemberAccessPanel({
  u, companyId, keys, full, locked, apps, onToggle, onSetAll, onSetNone, onReset, changed,
}: {
  u: AdminUser; companyId: string; keys: string[] | null; full: boolean; locked: boolean
  apps: AccessApp[]; onToggle: (key: string, app: string) => void
  onSetAll: () => void; onSetNone: () => void; onReset: () => void; changed: boolean
}) {
  const sel = useMemo(() => new Set(keys ?? apps.map((a) => a.app)), [keys, apps])
  return (
    <div className="border-t border-dashed border-border/60 bg-muted/20 px-4 py-3">
      {full ? (
        <p className="text-xs text-muted-foreground">
          {u.is_superadmin
            ? 'Владелец контейнера видит всё пространство — ограничить его нельзя.'
            : 'Администратор организации видит все продукты и разделы. Чтобы раздать доступ точечно, переведите его в «Сотрудники» в карточке участника.'}
        </p>
      ) : (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            {u.role_name && !changed && (
              <span className="text-muted-foreground">
                Права от роли <span className="font-medium text-foreground">«{u.role_name}»</span> — правка галочек сделает личный набор.
              </span>
            )}
            {changed && (
              <span className="flex items-center gap-1 text-primary">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" /> изменено, не сохранено
              </span>
            )}
            <span className="ml-auto flex items-center gap-1">
              <Button variant="ghost" size="sm" className="h-6 px-2 text-[11px]" disabled={locked} onClick={onSetAll}>
                Все продукты
              </Button>
              <Button variant="ghost" size="sm" className="h-6 px-2 text-[11px]" disabled={locked} onClick={onSetNone}>
                Снять всё
              </Button>
              {changed && (
                <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-[11px] text-muted-foreground"
                  onClick={onReset}>
                  <X className="h-3 w-3" /> вернуть
                </Button>
              )}
            </span>
          </div>
          <AccessTreeGrid companyId={companyId} sel={sel} disabled={locked} wide
            onToggle={(k) => onToggle(k, k.includes(':') ? k.split(':')[0] : k)} />
        </>
      )}
    </div>
  )
}

/** Карточка участника: кто он и на каком основании здесь. Права — в матрице. */
function MemberCard({
  u, companyId, canManage, isSelf, roles, orgs, onSaved, onClose,
}: {
  u: AdminUser; companyId: string; canManage: boolean; isSelf: boolean
  roles: CompanyRole[]; orgs: { id: string; name: string; shortName?: string | null }[]
  onSaved: () => void; onClose: () => void
}) {
  const [name, setName] = useState(u.name)
  const [position, setPosition] = useState(u.position ?? '')
  const editable = canManage && !u.is_superadmin && !isSelf

  const update = useMutation({
    mutationFn: (data: Parameters<typeof userService.updateUser>[1]) => userService.updateUser(u.id, data),
    onSuccess: () => { toast.success('Сохранено'); onSaved() },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const setAccess = useMutation({
    mutationFn: (roleId: string) => userService.setMemberAccess(u.id, companyId, { mode: 'role', roleId }),
    onSuccess: () => { toast.success('Роль назначена'); onSaved() },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const remove = useMutation({
    mutationFn: () => userService.removeUser(u.id, companyId),
    onSuccess: () => { toast.success('Участник убран из организации'); onSaved(); onClose() },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  const dirty = name !== u.name || position !== (u.position ?? '')

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="text-base font-semibold">{u.name || u.email}</span>
          {u.is_superadmin && (
            <Badge variant="outline" className="gap-1 text-[10px]"><ShieldCheck className="h-3 w-3" /> супер</Badge>
          )}
        </div>
        <div className="text-xs text-muted-foreground">{u.email}</div>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
        <section className="space-y-3">
          <SectionTitle>Реквизиты</SectionTitle>
          <div className="space-y-1.5">
            <Label className="text-xs">ФИО</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} disabled={!editable}
              placeholder="Фамилия Имя Отчество" className="h-8 text-sm" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Должность</Label>
            <Input value={position} onChange={(e) => setPosition(e.target.value)} disabled={!editable}
              placeholder="напр. Инженер эксплуатации" className="h-8 text-sm" />
          </div>
          {dirty && editable && (
            <Button size="sm" className="h-8" disabled={update.isPending}
              onClick={() => update.mutate({ companyId, name, position })}>
              {update.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />} Сохранить
            </Button>
          )}
        </section>

        <section className="space-y-3">
          <SectionTitle>Уровень в организации</SectionTitle>
          <Select value={u.role} disabled={!editable}
            onValueChange={(v) => update.mutate({ companyId, role: v as 'user' | 'admin' })}>
            <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="user">Сотрудник — доступ по правам</SelectItem>
              <SelectItem value="admin">Администратор — полный доступ</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-[11px] text-muted-foreground">
            Администратор видит все продукты организации и настраивает доступ остальным.
          </p>
        </section>

        <section className="space-y-3">
          <SectionTitle>Кто это</SectionTitle>
          <Select value={u.party_type ?? 'internal'} disabled={!editable}
            onValueChange={(v) => update.mutate({ companyId, partyType: v as 'internal' | 'partner' | 'vendor' })}>
            <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="internal">Сотрудник организации</SelectItem>
              <SelectItem value="partner">Компания-партнёр</SelectItem>
              <SelectItem value="vendor">Поддержка платформы</SelectItem>
            </SelectContent>
          </Select>
          {(u.party_type === 'partner' || u.party_type === 'vendor') && (
            <Select value={u.organization_id ?? 'none'} disabled={!editable}
              onValueChange={(v) => update.mutate({ companyId, organizationId: v === 'none' ? '' : v })}>
              <SelectTrigger className="h-8 text-sm"><SelectValue placeholder="Компания" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Компания не указана</SelectItem>
                {orgs.map((o) => <SelectItem key={o.id} value={o.id}>{o.shortName || o.name}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          <p className="text-[11px] text-muted-foreground">
            Принадлежность — не права: она отвечает, с кем говорят в чатах и заявках.
          </p>
        </section>

        {u.role !== 'admin' && !u.is_superadmin && (
          <section className="space-y-3">
            <SectionTitle>Права</SectionTitle>
            <Select value={u.role_id ?? ''} disabled={!editable || !roles.length}
              onValueChange={(v) => setAccess.mutate(v)}>
              <SelectTrigger className="h-8 text-sm">
                <SelectValue placeholder={u.modules == null ? 'Все продукты' : 'Личный набор'} />
              </SelectTrigger>
              <SelectContent>
                {roles.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <p className="text-[11px] text-muted-foreground">
              Роль — готовый набор прав. Галочки в строке настраивают доступ поштучно и
              отменяют роль: у человека остаётся личный набор.
            </p>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Объекты:</span>
              <ObjectScopeDialog member={u} companyId={companyId} onSaved={onSaved} />
            </div>
          </section>
        )}

        {editable && (
          <section className="space-y-2 border-t pt-4">
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 gap-1.5 text-destructive hover:text-destructive">
                  <Trash2 className="h-3.5 w-3.5" /> Убрать из организации
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
                  <AlertDialogAction onClick={() => remove.mutate()}>Убрать</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </section>
        )}
      </div>
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{children}</div>
}
