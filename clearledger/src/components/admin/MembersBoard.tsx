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
import { Link } from 'react-router-dom'
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
  Building2, Check, ChevronDown, ChevronRight, History, KeyRound, LifeBuoy, Loader2,
  Search, ShieldCheck, SlidersHorizontal, Trash2, Undo2, X,
} from 'lucide-react'
import * as userService from '@/services/userService'
import type { AdminUser } from '@/services/userService'
import * as roleService from '@/services/roleService'
import type { CompanyRole } from '@/services/roleService'
import { listSpaceContracts, listSpaceOrganizations, type SpaceContract } from '@/services/spaceObjectsService'
import { useAccessTree, type AccessApp } from '@/hooks/useAccessTree'
import { appIcon } from '@/config/appIcons'
import { appState, toggleAccessKey, sameAccess, type AppAccess } from '@/lib/accessKeys'
import { AccessTreeGrid } from './AccessTreeGrid'
import { ACTION_LABEL } from './AuditLog'
import { copyText } from './InviteLinkPanel'
import { ObjectScopeDialog } from './ObjectScopeDialog'
import { PartyBadge } from '@/components/chat/PartyBadge'

/** «31.07, 14:02» — компактная отметка последнего входа для строки состава. */
const seenShort = (iso?: string | null) => iso
  ? new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  : null

/** Столбцы одного слоя: значки продуктов, отделённые от соседнего слоя чертой. */
interface ColumnGroup { key: string; label: string; apps: AccessApp[] }

/** Ширина блока клеток: клетка 32px + по 4px отступа с каждой стороны группы. */
const colsWidth = (groups: ColumnGroup[]) =>
  groups.reduce((w, g) => w + g.apps.length * 32 + 8, 0)

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
  const [sort, setSort] = useState<'name' | 'seen'>('name')
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
  // Договоры — основание допуска внешних участников: у своих сотрудников оснований
  // не спрашивают, поэтому реестр тянем только в разделе компаний.
  const contractsQ = useQuery({
    queryKey: ['space-contracts', companyId],
    queryFn: () => listSpaceContracts(companyId),
    enabled: canManage && party === 'external',
    staleTime: 5 * 60_000,
    retry: false,
  })
  const { tree, isLoading: treeLoading } = useAccessTree(companyId)
  const roles = rolesQ.data ?? []
  const contracts = contractsQ.data ?? []
  /** Договоры конкретной компании-партнёра — её основание работать в пространстве. */
  const contractsOf = (orgId?: string | null) =>
    orgId ? contracts.filter((c) => c.counterpartyId === orgId) : []

  const refresh = () => qc.invalidateQueries({ queryKey: ['team-members', companyId] })

  // Принадлежность не задана — свой сотрудник: так было до появления партнёров, и
  // перенесённые люди заказчика идут без явной пометки.
  const isExternal = (m: AdminUser) => m.party_type === 'partner' || m.party_type === 'vendor'
  const members = (q.data ?? []).filter((m) => (party === 'external' ? isExternal(m) : !isExternal(m)))
  // Люди платформы (vendor) из списка сотрудников НЕ прячутся: заказчик должен видеть,
  // кто ещё имеет доступ в его пространство. Отдельной группой, со статусом — не в общем
  // ряду сотрудников (решение МАГа 31.07.2026). На их статус лягут отдельные права.
  const platform = party === 'internal' ? (q.data ?? []).filter((m) => m.party_type === 'vendor') : []
  const bySearch = (list: AdminUser[]) => search.trim()
    ? list.filter((m) => `${m.name} ${m.email} ${m.position ?? ''} ${m.organization_name ?? ''}`
        .toLowerCase().includes(search.trim().toLowerCase()))
    : list
  // «Недавно заходили» — админский вопрос «кто вообще пользуется»: не заходившие в конец.
  const bySort = (list: AdminUser[]) => sort === 'seen'
    ? [...list].sort((a, b) =>
        (b.last_seen_at ? Date.parse(b.last_seen_at) : 0) - (a.last_seen_at ? Date.parse(a.last_seen_at) : 0))
    : [...list].sort((a, b) => (a.name || a.email).localeCompare(b.name || b.email, 'ru'))
  const filtered = bySort(bySearch(members))
  const filteredPlatform = bySort(bySearch(platform))

  /** Внешние — группами по компаниям: единица учёта здесь компания, а не человек. */
  const groups = useMemo(() => {
    if (party !== 'external') {
      // Сотрудники + люди платформы: группы появляются, только когда есть кого отделять.
      if (filteredPlatform.length === 0) return null
      return [
        { key: 'staff', label: 'Сотрудники', kind: 'staff' as const, rows: filtered },
        { key: 'vendor', label: 'Поддержка платформы', kind: 'vendor' as const, rows: filteredPlatform },
      ]
    }
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
  }, [party, filtered, filteredPlatform])

  /**
   * Столбцы группами по слою: приложения-разрезы, сервисы контейнера (чат, заявки,
   * конференции) и управление пространством — разные вещи, и «может ли подрядчик
   * писать в чат» не должно теряться в общем ряду значков.
   */
  const columnGroups = useMemo(() => ([
    { key: 'app', label: 'Приложения' },
    { key: 'service', label: 'Сервисы' },
    { key: 'admin', label: 'Управление' },
  ] as const).map((g) => ({ ...g, apps: tree.filter((a) => (a.layer ?? 'app') === g.key) }))
    .filter((g) => g.apps.length), [tree])

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

  // «Разжать» продукт: снять отметку целиком, оставить все разделы кроме закрытого.
  // Жест из грида: человеку с «весь продукт» закрывают один пункт одним кликом.
  const carve = (u: AdminUser, app: string, keep: string[]) => {
    if (locked(u) || isFullByRole(u)) return
    const cur = effective(u)
    const base = cur === null ? tree.map((a) => a.app) : cur
    setKeys(u, [...base.filter((k) => k !== app && !k.startsWith(`${app}:`)), ...keep])
  }

  // Роль назначается сразу, без черновика: это готовый набор целиком, а не правка
  // отдельных клеток — копить тут нечего.
  const setRole = useMutation({
    mutationFn: ({ id, roleId }: { id: string; roleId: string }) =>
      userService.setMemberAccess(id, companyId, { mode: 'role', roleId }),
    onSuccess: (_data, v) => {
      toast.success('Роль назначена')
      setDraft((d) => { const n = { ...d }; delete n[v.id]; return n })
      refresh()
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

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
        <div className="flex items-center gap-2">
          <div className="relative w-full max-w-xs">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder={party === 'external' ? 'Поиск: ФИО, email, компания…' : 'Поиск: ФИО, email, должность…'}
              className="h-8 pl-8 text-sm" />
          </div>
          <Select value={sort} onValueChange={(v) => setSort(v as 'name' | 'seen')}>
            <SelectTrigger className="h-8 w-[168px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="name">По имени</SelectItem>
              <SelectItem value="seen">Недавно заходили</SelectItem>
            </SelectContent>
          </Select>
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

      {/* Без этой строки матрица читается как отчёт: клетки выглядят одинаково
          «нарисованными», и неочевидно, что они кликаются, а разделы лежат глубже. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-dashed border-border/70 bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-flex h-4 w-4 items-center justify-center rounded-[4px] border border-primary bg-primary text-primary-foreground">
            <Check className="h-2.5 w-2.5" strokeWidth={3} />
          </span>
          продукт целиком
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-flex h-4 w-4 items-center justify-center rounded-[4px] border border-primary/70 bg-primary/20">
            <span className="h-1 w-1 rounded-full bg-primary" />
          </span>
          часть разделов
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-4 w-4 rounded-[4px] border border-dashed border-muted-foreground/40" />
          нет доступа
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-flex h-4 w-4 items-center justify-center rounded-[4px] border border-primary/30 bg-primary/10 text-primary/50">
            <Check className="h-2.5 w-2.5" />
          </span>
          доступ не настроен — открыто всё
        </span>
        <span className="text-muted-foreground/80">
          Клетка переключается нажатием. Разделы внутри продукта — стрелка слева или колонка «Права».
        </span>
      </div>

      <div className="rounded-xl border border-border">
        <HeaderRow groups={columnGroups} loading={treeLoading} />
        <div className="divide-y divide-border/60">
          {q.isLoading && (
            <div className="flex items-center gap-2 px-3 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
            </div>
          )}
          {!q.isLoading && filtered.length === 0 && filteredPlatform.length === 0 && (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              {members.length + platform.length > 0 ? 'Ничего не найдено'
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
                    : g.kind === 'staff'
                      ? <Users2 className="h-3.5 w-3.5 text-muted-foreground" />
                      : <Building2 className="h-3.5 w-3.5 text-muted-foreground" />}
                  {g.label}
                  <span className="text-xs font-normal text-muted-foreground">· {g.rows.length} чел.</span>
                  {g.kind === 'vendor' && party === 'internal' && (
                    <span className="text-xs font-normal text-muted-foreground">
                      — не сотрудники компании: разработчик и сопровождение платформы с доступом в пространство
                    </span>
                  )}
                  {g.kind === 'none' && (
                    <span className="text-xs font-normal text-amber-500/90">
                      — укажите компанию, иначе в чатах и заявках человек без стороны
                    </span>
                  )}
                  {/* Договоры компании — то, на каком основании её люди здесь вообще
                      появились. Сам допуск даёт роль, договор объясняет «почему». */}
                  {g.kind === 'partner' && (
                    <ContractsHint items={contractsOf(g.rows[0]?.organization_id)} />
                  )}
                </div>
              )
            }
            const u = item.u!
            return (
              <Fragment key={u.id}>
                <MemberRow
                  u={u} groups={columnGroups} keys={effective(u)} full={isFullByRole(u)}
                  locked={locked(u)} changed={dirty.includes(u.id)}
                  expanded={!!expanded[u.id]} party={party}
                  onExpand={() => setExpanded((e) => ({ ...e, [u.id]: !e[u.id] }))}
                  onToggleApp={(app) => toggle(u, app, app)}
                  onCard={() => setCardFor(u.id)}
                  companyId={companyId} onSaved={refresh}
                  contracts={contractsOf(u.organization_id)}
                />
                {expanded[u.id] && (
                  <MemberAccessPanel
                    u={u} companyId={companyId} keys={effective(u)} full={isFullByRole(u)}
                    locked={locked(u)} apps={tree} roles={roles}
                    onRole={(roleId) => setRole.mutate({ id: u.id, roleId })}
                    onToggle={(key, app) => toggle(u, key, app)}
                    onCarve={(app, keep) => carve(u, app, keep)}
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
          : `Сотрудников: ${members.length}${platform.length ? ` · поддержка платформы: ${platform.length}` : ''}`}
        {filtered.length !== members.length ? ` · показано ${filtered.length}` : ''}
        {' · администратор организации видит все продукты — ограничить его можно, переведя в «Сотрудники» в карточке'}
      </p>

      <Sheet open={!!card} onOpenChange={(o) => { if (!o) setCardFor(null) }}>
        <SheetContent side="right" className="w-full sm:max-w-md p-0">
          <SheetTitle className="sr-only">Карточка участника</SheetTitle>
          <SheetDescription className="sr-only">Реквизиты, уровень доступа и принадлежность</SheetDescription>
          {card && (
            <MemberCard
              u={card} companyId={companyId} canManage={canManage} isSelf={card.id === selfId}
              roles={roles} orgs={orgsQ.data ?? []} contracts={contractsOf(card.organization_id)}
              onSaved={refresh}
              onClose={() => setCardFor(null)}
            />
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

/** Шапка матрицы: продукты значками — имена в заголовках столбцов не помещаются. */
function HeaderRow({ groups, loading }: { groups: ColumnGroup[]; loading: boolean }) {
  return (
    <div className="flex items-end gap-2 border-b border-border bg-muted/40 px-3 py-2 text-[11px] uppercase tracking-wide text-muted-foreground">
      <span className="w-5 shrink-0" />
      <span className="min-w-0 flex-1 pb-0.5">Участник</span>
      <span className="hidden w-[150px] shrink-0 pb-0.5 xl:block">Кто это</span>
      <span className="flex shrink-0 items-end">
        {loading && <Loader2 className="mb-0.5 h-3.5 w-3.5 animate-spin" />}
        {groups.map((g) => (
          <span key={g.key} className="flex flex-col items-center border-l border-border/50 px-1 first:border-l-0">
            <span className="text-[9px] leading-tight tracking-normal text-muted-foreground/70">{g.label}</span>
            <span className="flex">
              {g.apps.map((a) => {
                const Icon = appIcon(a.icon)
                return (
                  <span key={a.app} className="flex w-8 justify-center pt-0.5" title={a.name}>
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                )
              })}
            </span>
          </span>
        ))}
      </span>
      <span className="hidden w-[132px] shrink-0 lg:block">Права</span>
      <span className="w-[92px] shrink-0 text-right">Объекты</span>
      <span className="w-[68px] shrink-0" />
    </div>
  )
}

function MemberRow({
  u, groups, keys, full, locked, changed, expanded, party, onExpand, onToggleApp, onCard,
  companyId, onSaved, contracts,
}: {
  u: AdminUser; groups: ColumnGroup[]; keys: string[] | null; full: boolean; locked: boolean
  changed: boolean; expanded: boolean; party: 'internal' | 'external'
  onExpand: () => void; onToggleApp: (app: string) => void; onCard: () => void
  companyId: string; onSaved: () => void; contracts: SpaceContract[]
}) {
  const basis = contracts.filter((c) => u.contract_ids?.includes(c.id))
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
        {party === 'external' || u.party_type === 'vendor' ? (
          <>
            <PartyBadge party={{
              partyType: u.party_type ?? 'internal', role: u.role,
              orgName: u.organization_name, position: u.position,
            }} />
            {/* Основание допуска: по какому договору человек здесь. Пусто — не запрет,
                а вопрос к администратору: почему у подрядчика нет основания. */}
            {u.party_type === 'partner' && (
              <span className="mt-0.5 block truncate text-[11px] text-muted-foreground"
                title={basis.map((c) => `№${c.number} от ${c.date}`).join(', ')}>
                {basis.length
                  ? `${basis.map((c) => `№${c.number}`).slice(0, 2).join(', ')}${basis.length > 2 ? ` +${basis.length - 2}` : ''}`
                  : <span className="text-amber-500/90">без основания</span>}
              </span>
            )}
          </>
        ) : (
          <>
            <span className="block truncate text-xs text-muted-foreground">{u.position || '— должность —'}</span>
            <span className="block truncate text-[11px] text-muted-foreground/80">
              {seenShort(u.last_seen_at) ? `вход: ${seenShort(u.last_seen_at)}` : 'не заходил(а)'}
            </span>
          </>
        )}
      </span>

      {/* У администратора все клетки всегда отмечены — ряд одинаковых галочек выглядел
          так, будто ему что-то раздали вручную, и путался с настраиваемым доступом.
          Вместо ряда — одна плашка на ту же ширину. */}
      {full ? (
        <span className="flex shrink-0 items-center justify-center gap-1.5 rounded-md border border-dashed border-primary/25 bg-primary/5 py-1 text-[11px] text-muted-foreground"
          style={{ width: colsWidth(groups) }}>
          <ShieldCheck className="h-3.5 w-3.5 text-primary/70" />
          {u.is_superadmin ? 'владелец контейнера — полный доступ' : 'администратор — полный доступ'}
        </span>
      ) : (
        <span className="flex shrink-0 items-center">
          {groups.map((g) => (
            <span key={g.key} className="flex border-l border-border/40 px-1 first:border-l-0">
              {g.apps.map((a) => (
                <AppCell key={a.app} state={appState(keys, a.app)} name={a.name}
                  locked={locked} implicit={keys === null} onClick={() => onToggleApp(a.app)} />
              ))}
            </span>
          ))}
        </span>
      )}

      {/* Права — не подпись, а вход в настройку: сам текст раскрывает разделы, потому
          что стрелку слева в строке из полутора десятков клеток никто не замечает. */}
      <span className="hidden w-[150px] shrink-0 lg:block">
        {full ? (
          <span className="text-[11px] text-muted-foreground">все продукты и разделы</span>
        ) : (
          <button type="button" onClick={onExpand}
            className="flex items-center gap-1 rounded px-1 py-0.5 text-left text-[11px] text-muted-foreground hover:bg-accent/50 hover:text-foreground"
            title="Открыть разделы внутри продуктов">
            {u.role_name
              ? <Badge className="gap-1 text-[10px]"><KeyRound className="h-3 w-3" />{u.role_name}</Badge>
              : keys === null
                ? <span className="text-amber-500/90">не настроен</span>
                : keys.length === 0
                  ? <span className="text-destructive/80">нет доступа</span>
                  : <span>
                      продуктов: {keys.filter((k) => !k.includes(':')).length}
                      {keys.some((k) => k.includes(':')) ? ` · разделов: ${keys.filter((k) => k.includes(':')).length}` : ''}
                    </span>}
            {expanded ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
          </button>
        )}
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

/**
 * Клетка доступа. Состояния должны различаться ИЗДАЛЕКА, иначе строка из полутора
 * десятков клеток читается как один узор: залитый квадрат — весь продукт, точка на
 * бледном фоне — часть разделов, пустой пунктир — доступа нет.
 */
function AppCell({ state, name, locked, implicit, onClick }: {
  state: AppAccess; name: string; locked: boolean; onClick: () => void
  /** Доступ никто не настраивал: прав нет — значит открыто всё. Не то же, что выдали. */
  implicit?: boolean
}) {
  const title = locked
    ? `${name} — полный доступ администратора`
    : implicit ? `${name}: доступ не настроен, поэтому открыт. Нажмите, чтобы оставить только нужные продукты`
      : state === 'full' ? `${name}: открыт весь продукт. Нажмите, чтобы закрыть`
        : state === 'part' ? `${name}: открыты отдельные разделы. Нажмите, чтобы открыть продукт целиком`
          : `${name}: доступа нет. Нажмите, чтобы открыть`
  return (
    <span className="flex w-8 justify-center">
      <button type="button" onClick={onClick} disabled={locked} title={title}
        className={`inline-flex h-6 w-6 items-center justify-center rounded-[5px] border transition-all ${
          implicit ? 'border-primary/30 bg-primary/10 text-primary/50'
            : state === 'full' ? 'border-primary bg-primary text-primary-foreground'
              : state === 'part' ? 'border-primary/70 bg-primary/20'
                : 'border-dashed border-muted-foreground/40 bg-transparent'
        } ${locked ? 'cursor-default opacity-45' : 'cursor-pointer hover:ring-2 hover:ring-primary/30'}`}>
        {(state === 'full' || implicit) && <Check className="h-3.5 w-3.5" strokeWidth={implicit ? 2 : 3} />}
        {state === 'part' && !implicit && <span className="h-1.5 w-1.5 rounded-full bg-primary" />}
      </button>
    </span>
  )
}

/** Разворот строки: разделы внутри продуктов — то, чего не помещается в матрицу. */
function MemberAccessPanel({
  u, companyId, keys, full, locked, apps, roles, onRole, onToggle, onCarve, onSetAll,
  onSetNone, onReset, changed,
}: {
  u: AdminUser; companyId: string; keys: string[] | null; full: boolean; locked: boolean
  apps: AccessApp[]; roles: CompanyRole[]; onRole: (roleId: string) => void
  onToggle: (key: string, app: string) => void
  onCarve: (app: string, keep: string[]) => void
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
            {/* Готовая роль — самый быстрый способ настроить нового человека; галочки
                ниже нужны, когда типовой набор не подходит. */}
            <span className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Роль:</span>
              <Select value={u.role_id ?? ''} disabled={locked || !roles.length} onValueChange={onRole}>
                <SelectTrigger className="h-7 w-[190px] text-xs">
                  <SelectValue placeholder={u.modules == null ? 'все продукты' : 'личный набор'} />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </span>
            {u.role_name && !changed && (
              <span className="text-muted-foreground">
                правка галочек сделает личный набор
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
            onToggle={(k) => onToggle(k, k.includes(':') ? k.split(':')[0] : k)}
            onCarve={onCarve} />
        </>
      )}
    </div>
  )
}

/** Карточка участника: кто он и на каком основании здесь. Права — в матрице. */
function MemberCard({
  u, companyId, canManage, isSelf, roles, orgs, contracts, onSaved, onClose,
}: {
  u: AdminUser; companyId: string; canManage: boolean; isSelf: boolean
  roles: CompanyRole[]; orgs: { id: string; name: string; shortName?: string | null }[]
  contracts: SpaceContract[]; onSaved: () => void; onClose: () => void
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
  const setContracts = useMutation({
    mutationFn: (ids: string[]) => userService.setMemberContracts(u.id, companyId, ids),
    onSuccess: () => onSaved(),
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const remove = useMutation({
    mutationFn: () => userService.removeUser(u.id, companyId),
    onSuccess: () => { toast.success('Участник убран из организации'); onSaved(); onClose() },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  // Последние события человека — входы и действия из журнала пространства.
  const activityQ = useQuery({
    queryKey: ['audit', companyId, 'member', u.id],
    queryFn: () => roleService.listAudit(companyId, 10, { userId: u.id }),
    enabled: canManage,
    retry: false,
  })
  // Ссылка для входа: одноразовый сброс пароля, который передают мессенджером.
  // Единственный путь внутрь для человека, до которого не доходят письма.
  const [resetUrl, setResetUrl] = useState('')
  const resetLink = useMutation({
    mutationFn: () => userService.issueResetLink(u.id, companyId),
    onSuccess: async (r) => {
      setResetUrl(r.reset_url)
      if (await copyText(r.reset_url)) toast.success('Ссылка скопирована — действует 24 часа')
      else toast.error('Не удалось скопировать — выделите ссылку вручную')
    },
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

        <section className="space-y-2">
          <SectionTitle>Активность</SectionTitle>
          <p className="text-xs text-muted-foreground">
            Последний вход:{' '}
            <span className="text-foreground">
              {u.last_seen_at ? new Date(u.last_seen_at).toLocaleString('ru-RU') : 'ещё не заходил(а)'}
            </span>
          </p>
          {canManage && (
            <div className="space-y-1.5">
              <Button variant="outline" size="sm" className="h-7 gap-1 text-xs"
                disabled={resetLink.isPending} onClick={() => resetLink.mutate()}>
                {resetLink.isPending
                  ? <Loader2 className="h-3 w-3 animate-spin" />
                  : <KeyRound className="h-3 w-3" />}
                Ссылка для входа
              </Button>
              {resetUrl && (
                <div className="rounded-md border border-border bg-background px-2 py-1.5">
                  <code className="block break-all font-mono text-[10px] leading-relaxed">{resetUrl}</code>
                </div>
              )}
              <p className="text-[11px] text-muted-foreground">
                Когда письма не доходят: одноразовая ссылка сброса пароля, действует 24 часа.
                Передайте её человеку мессенджером — по ней он сам задаст новый пароль.
              </p>
            </div>
          )}
          {canManage && (
            <>
              {(activityQ.data ?? []).length > 0 && (
                <div className="space-y-1">
                  {(activityQ.data ?? []).map((e) => (
                    <div key={e.id} className="flex items-baseline gap-2 text-[11px]">
                      <span className="shrink-0 tabular-nums text-muted-foreground">
                        {new Date(e.timestamp).toLocaleString('ru-RU',
                          { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <span className="truncate" title={e.details ?? undefined}>
                        {ACTION_LABEL[e.action] ?? e.action}{e.details ? ` — ${e.details}` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {activityQ.data?.length === 0 && (
                <p className="text-[11px] text-muted-foreground">Событий в журнале пока нет.</p>
              )}
              {/* Десять строк — витрина; полная история с фильтрами живёт в «Журнале». */}
              <Link to={`/admin/company/audit?user=${u.id}`} onClick={onClose}
                className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline">
                <History className="h-3 w-3" /> Весь журнал человека
              </Link>
            </>
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

        {/* Основание — только у людей компаний-партнёров: свой сотрудник работает здесь
            по трудовому договору, и спрашивать его основание незачем. */}
        {u.party_type === 'partner' && (
          <section className="space-y-2">
            <SectionTitle>Основание</SectionTitle>
            {!u.organization_id ? (
              <p className="text-[11px] text-amber-500/90">
                Сначала укажите компанию — договоры берутся из её карточки.
              </p>
            ) : contracts.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">
                У компании нет договоров в реестре пространства («Управление → Договоры и оборудование»).
              </p>
            ) : (
              <div className="flex max-h-56 flex-col gap-1 overflow-y-auto pr-1">
                {contracts.map((c) => {
                  const on = !!u.contract_ids?.includes(c.id)
                  return (
                    <button key={c.id} type="button" disabled={!editable || setContracts.isPending}
                      onClick={() => setContracts.mutate(on
                        ? (u.contract_ids ?? []).filter((x) => x !== c.id)
                        : [...(u.contract_ids ?? []), c.id])}
                      className={`flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-left text-[13px] transition-colors ${
                        on ? 'border-primary/40 bg-primary/10' : 'border-border hover:bg-accent/40'
                      } ${c.isClosed ? 'opacity-60' : ''}`}>
                      <span className="min-w-0">
                        <span className="font-medium">№{c.number}</span>
                        <span className="text-muted-foreground"> от {c.date}</span>
                        {c.type && <span className="block truncate text-[11px] text-muted-foreground">{c.type}</span>}
                      </span>
                      {on && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                    </button>
                  )
                })}
              </div>
            )}
            <p className="text-[11px] text-muted-foreground">
              Договор ничего не открывает и не закрывает — он объясняет, почему человек
              допущен в пространство. Оснований может быть несколько.
            </p>
          </section>
        )}

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

/** Договоры компании-партнёра в шапке её группы: на чём держится присутствие людей. */
function ContractsHint({ items }: { items: SpaceContract[] }) {
  if (!items.length) return null
  const open = items.filter((c) => !c.isClosed)
  const shown = (open.length ? open : items).slice(0, 3)
  return (
    <span className="truncate text-xs font-normal text-muted-foreground"
      title={items.map((c) => `№${c.number} от ${c.date}${c.isClosed ? ' (закрыт)' : ''}`).join('\n')}>
      · договоры: {shown.map((c) => `№${c.number}`).join(', ')}
      {items.length > shown.length ? ` +${items.length - shown.length}` : ''}
    </span>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{children}</div>
}
