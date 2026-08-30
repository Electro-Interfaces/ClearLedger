/**
 * «Сайт» — рабочее место того, кто ведёт публичную витрину компании.
 *
 * Граница с сайтом проходит по хозяину данных, и пункты рельсы идут по ней же:
 *
 *   Заявки · Обращения · Показы       — рождаются НА САЙТЕ, здесь их читают.
 *   Кабинеты · Пространства · Стенды  — ведутся ЗДЕСЬ, сайт их читает при входе.
 *   Витрина                           — лежит на сайте, правится ЗДЕСЬ.
 *
 * Поэтому у первых есть состояние «связи нет» (и оно называется причиной, а не
 * пустой таблицей: пустая таблица врала бы, будто на сайте ничего не происходит),
 * а вторые правятся прямо в строке — это решения, а не отчёт.
 *
 * Чего здесь нет намеренно: договоров, актов и сверок клиента. Кабинет сайта —
 * прихожая; работает клиент в СВОЁМ пространстве, и бумаги у него там.
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, PlugZap, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import * as siteService from '@/services/siteService'
import {
  LEAD_STATUS_LABELS, LEVEL_LABELS, SPACE_STATUS_LABELS, siteTime,
} from '@/services/siteService'
import { ShowcaseEditor } from './ShowcaseEditor'
import * as referenceService from '@/services/referenceService'
import { cn } from '@/lib/utils'

type Tab = 'leads' | 'requests' | 'showcase' | 'cabinets' | 'spaces' | 'stands' | 'shows'

const TABS: { key: Tab; label: string; hint: string; owner: 'site' | 'space' }[] = [
  { key: 'leads', label: 'Заявки', hint: 'кто оставил контакт на формах витрины', owner: 'site' },
  { key: 'requests', label: 'Обращения', hint: 'что написали из кабинета сайта', owner: 'site' },
  { key: 'showcase', label: 'Витрина', hint: 'тексты, цены и контакты публичного сайта', owner: 'site' },
  { key: 'cabinets', label: 'Кабинеты', hint: 'кому открыт кабинет и что ему видно', owner: 'space' },
  { key: 'spaces', label: 'Пространства', hint: 'у кого развёрнут свой контур и в каком он состоянии', owner: 'space' },
  { key: 'stands', label: 'Стенды', hint: 'что вообще можно показать клиенту', owner: 'space' },
  { key: 'shows', label: 'Показы', hint: 'кому и когда открывали стенд', owner: 'site' },
]

const LEVELS = ['guest', 'client', 'partner', 'admin']

/** Полоса состояния связи — только когда связи нет: молчащее «всё в порядке»
 *  занимает место, где потом не заметят настоящую тревогу. */
function ConnectionNote({ reason }: { reason: string | null }) {
  if (!reason) return null
  return (
    <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/40
                    bg-amber-500/10 px-3 py-2 text-sm">
      <PlugZap className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
      <span>{reason}</span>
    </div>
  )
}

function EmptyRow({ colSpan, text }: { colSpan: number; text: string }) {
  return (
    <TableRow>
      <TableCell colSpan={colSpan} className="py-8 text-center text-muted-foreground">
        {text}
      </TableCell>
    </TableRow>
  )
}

export function SitePage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  // Экран живёт в адресе, а выбирается в рельсе приложения (`AppSidebar`,
  // SITE_SECTIONS): на «Заявки» дают ссылку и ставят закладку, как на любой
  // другой пункт пространства.
  const [params] = useSearchParams()
  const view = params.get('view')
  const tab: Tab = (TABS.some((t) => t.key === view) ? view : 'requests') as Tab

  // Что рождается на сайте.
  const summary = useQuery({
    queryKey: ['site-summary', companyId],
    queryFn: () => siteService.getSummary(companyId),
    enabled: !!companyId,
  })
  const requests = useQuery({
    queryKey: ['site-requests', companyId],
    queryFn: () => siteService.getRequests(companyId),
    enabled: !!companyId && tab === 'requests',
  })
  const shows = useQuery({
    queryKey: ['site-demos', companyId],
    queryFn: () => siteService.getDemos(companyId),
    enabled: !!companyId && tab === 'shows',
  })
  const leads = useQuery({
    queryKey: ['site-leads', companyId],
    queryFn: () => siteService.getLeads(companyId),
    enabled: !!companyId && tab === 'leads',
  })
  const setLeadStatus = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      siteService.setLeadStatus(companyId, id, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['site-leads', companyId] }),
    onError: (e: Error) => toast.error(e.message || 'Состояние не сохранено'),
  })

  // Что ведётся здесь.
  const cabinets = useQuery({
    queryKey: ['site-cabinet-users', companyId],
    queryFn: () => siteService.getCabinetUsers(companyId),
    enabled: !!companyId && tab === 'cabinets',
  })
  // Кто заведён В КАБИНЕТЕ САЙТА. До появления пространства доступы открывали
  // прямо там, и в нашей таблице этих людей нет — а входят они каждый день.
  // Показываем обе стороны: иначе экран уверяет, что кабинет никому не открыт.
  const siteCabinets = useQuery({
    queryKey: ['site-cabinets', companyId],
    queryFn: () => siteService.getCabinets(companyId),
    enabled: !!companyId && tab === 'cabinets',
  })
  const stands = useQuery({
    queryKey: ['site-demo-stands', companyId],
    queryFn: () => siteService.getDemoStands(companyId),
    enabled: !!companyId && (tab === 'stands' || tab === 'cabinets'),
  })
  const clients = useQuery({
    queryKey: ['counterparties', companyId],
    queryFn: () => referenceService.getCounterparties(companyId),
    enabled: !!companyId && (tab === 'cabinets' || tab === 'spaces'),
  })
  const spaces = useQuery({
    queryKey: ['site-client-spaces', companyId],
    queryFn: () => siteService.getClientSpaces(companyId),
    enabled: !!companyId && (tab === 'spaces' || tab === 'cabinets'),
  })

  const saveCabinet = useMutation({
    mutationFn: (input: siteService.CabinetUserInput) =>
      siteService.saveCabinetUser(companyId, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-cabinet-users', companyId] })
      toast.success('Доступ сохранён')
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось сохранить'),
  })
  const dropCabinet = useMutation({
    mutationFn: (id: string) => siteService.dropCabinetUser(companyId, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-cabinet-users', companyId] })
      toast.success('Доступ закрыт')
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось закрыть'),
  })
  const saveSpace = useMutation({
    mutationFn: (input: siteService.ClientSpaceInput) =>
      siteService.saveClientSpace(companyId, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-client-spaces', companyId] })
      toast.success('Пространство записано')
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось записать'),
  })
  const saveStand = useMutation({
    mutationFn: (input: siteService.DemoStandInput) =>
      siteService.saveDemoStand(companyId, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-demo-stands', companyId] })
      toast.success('Стенд сохранён')
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось сохранить'),
  })

  // Форма заведения доступа. Одна строка над таблицей, а не модалка: заводят
  // подряд по несколько человек одного клиента.
  const [newEmail, setNewEmail] = useState('')
  const [newLevel, setNewLevel] = useState('client')
  const [newClient, setNewClient] = useState('')
  const [newStand, setNewStand] = useState({ code: '', title: '', upstream: '' })
  const [newSpace, setNewSpace] = useState({ client: '', slug: '', domain: '', status: 'active' })

  const counts: Record<Tab, number | undefined> = {
    leads: summary.data?.leads,
    requests: summary.data?.requests,
    showcase: undefined,
    cabinets: cabinets.data?.items.length,
    spaces: spaces.data?.items.length,
    stands: stands.data?.items.length,
    shows: summary.data?.demos,
  }
  // Адреса сайта, которых нет в нашей таблице доступов.
  const onSiteOnly = useMemo(() => {
    const ours = new Set((cabinets.data?.items ?? []).map((c) => c.email.toLowerCase()))
    return (siteCabinets.data?.items ?? [])
      .filter((c) => c.email && !ours.has(c.email.toLowerCase()))
  }, [cabinets.data, siteCabinets.data])
  // Клиент → адрес его контура: в кабинетах видно, есть ли человеку куда войти.
  const spaceOf = useMemo(() => {
    const map = new Map<string, string>()
    for (const s of spaces.data?.items ?? []) {
      if (s.status === 'active' && s.domain) map.set(s.counterpartyId, s.domain)
    }
    return map
  }, [spaces.data])
  const standTitle = useMemo(() => {
    const map = new Map<string, string>()
    for (const s of stands.data?.items ?? []) map.set(s.code, s.title)
    return map
  }, [stands.data])

  // Причина связи касается только вкладок, которые читают сайт.
  const active = TABS.find((t) => t.key === tab)
  const siteOwned = active?.owner === 'site'
  const feedReason: Partial<Record<Tab, string | null | undefined>> = {
    leads: leads.data?.reason,
    requests: requests.data?.reason,
    shows: shows.data?.reason,
  }
  // Витрина говорит о связи сама — внутри своего редактора.
  const reason = siteOwned && tab !== 'showcase'
    ? (feedReason[tab] ?? summary.data?.reason ?? null)
    : null

  return (
    <div className="p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        {/* Заголовок экрана равен имени пункта рельсы (канон «Пульса» и «Трека»),
            а строкой ниже — чем этот экран занят: у семи пунктов разный хозяин
            данных, и понимать это надо до клика, а не после. */}
        <div>
          <h1 className="text-lg font-semibold">
            {active?.label}
            {counts[tab] !== undefined && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                {counts[tab]}
              </span>
            )}
          </h1>
          <p className="text-xs text-muted-foreground">{active?.hint}</p>
        </div>
        {summary.data?.url && (
          <a href={summary.data.url} target="_blank" rel="noreferrer"
             className="inline-flex items-center gap-1.5 text-sm text-muted-foreground
                        hover:text-foreground">
            {summary.data.url.replace(/^https?:\/\//, '')}
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </div>

      <ConnectionNote reason={reason} />

      {/* «Витрина» — не таблица, а рабочее место со своей второй колонкой, как у
          «Топлива» и «Эксплуатации». Карточка ей мешает: колонка пунктов должна
          стоять от края панели, а не внутри отступов карточки. */}
      {tab === 'showcase' ? (
        <div className="h-[calc(100vh-13rem)] min-h-[26rem] overflow-hidden rounded-lg border bg-card">
          <ShowcaseEditor companyId={companyId} />
        </div>
      ) : (
      <Card>
        <CardContent className="pt-6">
          {tab === 'leads' && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Когда</TableHead>
                  <TableHead>Кто</TableHead>
                  <TableHead>Контакт</TableHead>
                  <TableHead>Зачем</TableHead>
                  <TableHead className="w-44">Состояние</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(leads.data?.items ?? []).map((l) => (
                  <TableRow key={l.id}>
                    <TableCell className="whitespace-nowrap">{siteTime(l.created_at)}</TableCell>
                    <TableCell>
                      <div>{l.name || 'Без имени'}</div>
                      {l.company && (
                        <div className="text-xs text-muted-foreground">{l.company}</div>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">
                      {l.email && <div>{l.email}</div>}
                      {l.phone && <div className="text-muted-foreground">{l.phone}</div>}
                    </TableCell>
                    <TableCell className="max-w-md">
                      {l.product && <div className="font-medium">{l.product}</div>}
                      <div className="text-sm text-muted-foreground">{l.interest ?? '—'}</div>
                      {l.message && (
                        <div className="mt-0.5 line-clamp-2 text-xs italic text-muted-foreground">
                          {l.message}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <select
                        value={l.status}
                        onChange={(e) =>
                          setLeadStatus.mutate({ id: l.id, status: e.target.value })}
                        className="h-8 w-full rounded-md border bg-background px-2 text-sm"
                      >
                        {Object.entries(LEAD_STATUS_LABELS).map(([code, label]) => (
                          <option key={code} value={code}>{label}</option>
                        ))}
                      </select>
                    </TableCell>
                  </TableRow>
                ))}
                {!leads.isLoading && !(leads.data?.items ?? []).length && (
                  <EmptyRow colSpan={5} text={reason ? 'Данные не прочитаны' : 'Заявок нет'} />
                )}
              </TableBody>
            </Table>
          )}

          {tab === 'requests' && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Когда</TableHead>
                  <TableHead>Кто</TableHead>
                  <TableHead>Компания</TableHead>
                  <TableHead>О чём</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(requests.data?.items ?? []).map((r, i) => (
                  <TableRow key={r.id ?? i}>
                    <TableCell className="whitespace-nowrap">{siteTime(r.created_at)}</TableCell>
                    <TableCell>{r.email ?? '—'}</TableCell>
                    <TableCell>{r.company ?? '—'}</TableCell>
                    <TableCell>{r.product ?? r.kind ?? r.message ?? '—'}</TableCell>
                  </TableRow>
                ))}
                {!requests.isLoading && !(requests.data?.items ?? []).length && (
                  <EmptyRow colSpan={4} text={reason ? 'Данные не прочитаны' : 'Обращений нет'} />
                )}
              </TableBody>
            </Table>
          )}

          {tab === 'cabinets' && (
            <>
              <div className="mb-4 flex flex-wrap items-end gap-2">
                <div className="w-64">
                  <label className="mb-1 block text-xs text-muted-foreground">Почта</label>
                  <Input value={newEmail} placeholder="ivanov@client.ru"
                         onChange={(e) => setNewEmail(e.target.value)} />
                </div>
                <div className="w-44">
                  <label className="mb-1 block text-xs text-muted-foreground">Уровень</label>
                  <select
                    value={newLevel}
                    onChange={(e) => setNewLevel(e.target.value)}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                  >
                    {LEVELS.map((l) => (
                      <option key={l} value={l}>{LEVEL_LABELS[l] ?? l}</option>
                    ))}
                  </select>
                </div>
                <div className="w-72">
                  <label className="mb-1 block text-xs text-muted-foreground">Клиент</label>
                  <select
                    value={newClient}
                    onChange={(e) => setNewClient(e.target.value)}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                  >
                    <option value="">— без клиента (гость с улицы)</option>
                    {(clients.data ?? []).map((c) => (
                      <option key={c.id} value={c.id}>{c.shortName || c.name}</option>
                    ))}
                  </select>
                </div>
                <Button
                  disabled={!newEmail.includes('@') || saveCabinet.isPending}
                  onClick={() => {
                    saveCabinet.mutate({
                      email: newEmail.trim().toLowerCase(),
                      level: newLevel,
                      counterparty_id: newClient || null,
                    })
                    setNewEmail('')
                  }}
                >
                  <Plus className="mr-1 h-4 w-4" /> Открыть доступ
                </Button>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Адрес</TableHead>
                    <TableHead>Уровень</TableHead>
                    <TableHead>Клиент</TableHead>
                    <TableHead>Стенды</TableHead>
                    <TableHead>Пространство</TableHead>
                    <TableHead className="w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(cabinets.data?.items ?? []).map((c) => (
                    <TableRow key={c.id} className={cn(!c.isActive && 'opacity-50')}>
                      <TableCell>{c.email}</TableCell>
                      <TableCell>{LEVEL_LABELS[c.level] ?? c.level}</TableCell>
                      <TableCell>
                        {c.counterpartyName ?? <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {c.demos.length
                          ? c.demos.map((d) => standTitle.get(d) ?? d).join(', ')
                          : 'все'}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {spaceOf.get(c.counterpartyId ?? '') ?? '—'}
                      </TableCell>
                      <TableCell>
                        <Button variant="ghost" size="sm" title="Закрыть доступ"
                                onClick={() => dropCabinet.mutate(c.id)}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!cabinets.isLoading && !(cabinets.data?.items ?? []).length && (
                    <EmptyRow colSpan={6}
                      text="Через пространство доступ пока никому не открывали" />
                  )}
                </TableBody>
              </Table>

              {onSiteOnly.length > 0 && (
                <div className="mt-6">
                  <p className="mb-2 text-sm font-medium">Заведены на самом сайте</p>
                  <p className="mb-3 text-xs text-muted-foreground">
                    Эти адреса открыли в админке сайта, минуя пространство. Они входят
                    в кабинет, но клиента и стенды им отсюда не назначить — заведите
                    доступ формой выше, и запись станет управляемой.
                  </p>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Адрес</TableHead>
                        <TableHead>Уровень</TableHead>
                        <TableHead>Компания</TableHead>
                        <TableHead>Стенды</TableHead>
                        <TableHead>Был на сайте</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {onSiteOnly.map((c) => (
                        <TableRow key={c.email}>
                          <TableCell>{c.email}</TableCell>
                          <TableCell>{LEVEL_LABELS[c.level ?? ''] ?? c.level ?? '—'}</TableCell>
                          <TableCell>{c.company ?? '—'}</TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {!c.demos || c.demos === '*'
                              ? 'все'
                              : (Array.isArray(c.demos) ? c.demos.join(', ') : c.demos)}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {siteTime(c.last_seen) || '—'}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </>
          )}

          {tab === 'spaces' && (
            <>
              <p className="mb-4 max-w-3xl text-sm text-muted-foreground">
                Каждому клиенту разворачивается своё пространство — работает он там.
                Кабинет сайта только открывает в него дверь, и появляется она, лишь
                когда контур перешёл в состояние «работает».
              </p>
              <div className="mb-4 flex flex-wrap items-end gap-2">
                <div className="w-72">
                  <label className="mb-1 block text-xs text-muted-foreground">Клиент</label>
                  <select
                    value={newSpace.client}
                    onChange={(e) => setNewSpace({ ...newSpace, client: e.target.value })}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                  >
                    <option value="">— выберите клиента</option>
                    {(clients.data ?? []).map((c) => (
                      <option key={c.id} value={c.id}>{c.shortName || c.name}</option>
                    ))}
                  </select>
                </div>
                <div className="w-40">
                  <label className="mb-1 block text-xs text-muted-foreground">Код стека</label>
                  <Input value={newSpace.slug} placeholder="gig"
                         onChange={(e) => setNewSpace({ ...newSpace, slug: e.target.value })} />
                </div>
                <div className="w-64">
                  <label className="mb-1 block text-xs text-muted-foreground">Домен</label>
                  <Input value={newSpace.domain} placeholder="gig.dataworker.ru"
                         onChange={(e) => setNewSpace({ ...newSpace, domain: e.target.value })} />
                </div>
                <div className="w-52">
                  <label className="mb-1 block text-xs text-muted-foreground">Состояние</label>
                  <select
                    value={newSpace.status}
                    onChange={(e) => setNewSpace({ ...newSpace, status: e.target.value })}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                  >
                    {Object.entries(SPACE_STATUS_LABELS).map(([k, v]) => (
                      <option key={k} value={k}>{v}</option>
                    ))}
                  </select>
                </div>
                <Button
                  disabled={!newSpace.client || !newSpace.slug || saveSpace.isPending}
                  onClick={() => {
                    saveSpace.mutate({
                      counterparty_id: newSpace.client,
                      slug: newSpace.slug.trim().toLowerCase(),
                      domain: newSpace.domain.trim(),
                      status: newSpace.status,
                    })
                    setNewSpace({ client: '', slug: '', domain: '', status: 'active' })
                  }}
                >
                  <Plus className="mr-1 h-4 w-4" /> Записать
                </Button>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Клиент</TableHead>
                    <TableHead>Код стека</TableHead>
                    <TableHead>Домен</TableHead>
                    <TableHead>Состояние</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(spaces.data?.items ?? []).map((s) => (
                    <TableRow key={s.id}>
                      <TableCell>{s.counterpartyName ?? '—'}</TableCell>
                      <TableCell className="font-mono text-xs">{s.slug}</TableCell>
                      <TableCell>
                        {s.domain
                          ? (
                            <a href={`https://${s.domain}`} target="_blank" rel="noreferrer"
                               className="inline-flex items-center gap-1 hover:underline">
                              {s.domain}
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          )
                          : <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell>{SPACE_STATUS_LABELS[s.status] ?? s.status}</TableCell>
                    </TableRow>
                  ))}
                  {!spaces.isLoading && !(spaces.data?.items ?? []).length && (
                    <EmptyRow colSpan={4}
                              text="Пространств нет: ни одному клиенту контур пока не развёрнут" />
                  )}
                </TableBody>
              </Table>
            </>
          )}

          {tab === 'stands' && (
            <>
              <div className="mb-4 flex flex-wrap items-end gap-2">
                <div className="w-40">
                  <label className="mb-1 block text-xs text-muted-foreground">Код</label>
                  <Input value={newStand.code} placeholder="monitor"
                         onChange={(e) => setNewStand({ ...newStand, code: e.target.value })} />
                </div>
                <div className="w-64">
                  <label className="mb-1 block text-xs text-muted-foreground">Название</label>
                  <Input value={newStand.title} placeholder="Монитор"
                         onChange={(e) => setNewStand({ ...newStand, title: e.target.value })} />
                </div>
                <div className="w-72">
                  <label className="mb-1 block text-xs text-muted-foreground">Адрес стенда</label>
                  <Input value={newStand.upstream} placeholder="http://10.10.70.52:3021"
                         onChange={(e) => setNewStand({ ...newStand, upstream: e.target.value })} />
                </div>
                <Button
                  disabled={!newStand.code || !newStand.title || saveStand.isPending}
                  onClick={() => {
                    saveStand.mutate({
                      code: newStand.code.trim().toLowerCase(),
                      title: newStand.title.trim(),
                      upstream_url: newStand.upstream.trim() || null,
                    })
                    setNewStand({ code: '', title: '', upstream: '' })
                  }}
                >
                  <Plus className="mr-1 h-4 w-4" /> Завести стенд
                </Button>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Код</TableHead>
                    <TableHead>Название</TableHead>
                    <TableHead>Адрес</TableHead>
                    <TableHead className="w-28">Показываем</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(stands.data?.items ?? []).map((s) => (
                    <TableRow key={s.id}>
                      <TableCell className="font-mono text-xs">{s.code}</TableCell>
                      <TableCell>{s.title}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {s.upstreamUrl || s.externalUrl || '—'}
                      </TableCell>
                      <TableCell>
                        <Switch
                          checked={s.isEnabled}
                          onCheckedChange={(on) => saveStand.mutate({
                            code: s.code, title: s.title, description: s.description,
                            upstream_url: s.upstreamUrl, external_url: s.externalUrl,
                            landing: s.landing, is_enabled: on, sort: s.sort,
                          })}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                  {!stands.isLoading && !(stands.data?.items ?? []).length && (
                    <EmptyRow colSpan={4}
                              text="Каталог пуст: стенды пока перечислены в коде сайта
                                    (monitor, processing, link, space). Заведите их здесь —
                                    и кабинет начнёт брать список отсюда, а показы получат
                                    названия вместо кодов." />
                  )}
                </TableBody>
              </Table>
            </>
          )}

          {tab === 'shows' && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Когда</TableHead>
                  <TableHead>Кто</TableHead>
                  <TableHead>Стенд</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(shows.data?.items ?? []).map((d, i) => (
                  <TableRow key={d.id ?? i}>
                    <TableCell className="whitespace-nowrap">{siteTime(d.ts)}</TableCell>
                    <TableCell>{d.email ?? '—'}</TableCell>
                    <TableCell>
                      {standTitle.get(d.demo_id ?? '') ?? d.demo_id ?? '—'}
                    </TableCell>
                  </TableRow>
                ))}
                {!shows.isLoading && !(shows.data?.items ?? []).length && (
                  <EmptyRow colSpan={3} text={reason ? 'Данные не прочитаны' : 'Показов не было'} />
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      )}
    </div>
  )
}

export default SitePage
