/**
 * «Сайт» — рабочее место того, кто ведёт публичную витрину компании.
 *
 * Граница с сайтом проходит по хозяину данных, и вкладки идут по ней же:
 *
 *   Обращения · Показы — рождаются НА САЙТЕ, здесь их читают.
 *   Кабинеты · Стенды  — ведутся ЗДЕСЬ, сайт их читает при входе.
 *
 * Поэтому у первых двух есть состояние «связи нет» (и оно называется причиной, а
 * не пустой таблицей: пустая таблица врала бы, будто на сайте ничего не происходит),
 * а вторые две правятся прямо в строке — это решения, а не отчёт.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Globe, PlugZap, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import * as siteService from '@/services/siteService'
import { LEVEL_LABELS, siteTime } from '@/services/siteService'
import * as referenceService from '@/services/referenceService'
import { cn } from '@/lib/utils'

type Tab = 'requests' | 'cabinets' | 'stands' | 'shows'

const TABS: { key: Tab; label: string; hint: string; owner: 'site' | 'space' }[] = [
  { key: 'requests', label: 'Обращения', hint: 'что написали из кабинета сайта', owner: 'site' },
  { key: 'cabinets', label: 'Кабинеты', hint: 'кому открыт кабинет и что ему видно', owner: 'space' },
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
  const [tab, setTab] = useState<Tab>('requests')

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

  // Что ведётся здесь.
  const cabinets = useQuery({
    queryKey: ['site-cabinet-users', companyId],
    queryFn: () => siteService.getCabinetUsers(companyId),
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
    enabled: !!companyId && tab === 'cabinets',
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

  const counts: Record<Tab, number | undefined> = {
    requests: summary.data?.requests,
    cabinets: cabinets.data?.items.length,
    stands: stands.data?.items.length,
    shows: summary.data?.demos,
  }
  const standTitle = useMemo(() => {
    const map = new Map<string, string>()
    for (const s of stands.data?.items ?? []) map.set(s.code, s.title)
    return map
  }, [stands.data])

  // Причина связи касается только вкладок, которые читают сайт.
  const siteOwned = TABS.find((t) => t.key === tab)?.owner === 'site'
  const reason = siteOwned
    ? (tab === 'requests' ? requests.data?.reason : shows.data?.reason)
      ?? summary.data?.reason ?? null
    : null

  return (
    <div className="p-6">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Globe className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Сайт</h1>
        </div>
        {summary.data?.url && (
          <a href={summary.data.url} target="_blank" rel="noreferrer"
             className="inline-flex items-center gap-1.5 text-sm text-muted-foreground
                        hover:text-foreground">
            {summary.data.url.replace(/^https?:\/\//, '')}
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </header>

      <nav className="mb-4 flex flex-wrap gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            title={t.hint}
            onClick={() => setTab(t.key)}
            className={cn(
              'relative -mb-px border-b-2 px-3 py-2 text-sm transition-colors',
              tab === t.key
                ? 'border-primary font-medium text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
            {counts[t.key] !== undefined && (
              <span className="ml-1.5 text-xs text-muted-foreground">{counts[t.key]}</span>
            )}
          </button>
        ))}
      </nav>

      <ConnectionNote reason={reason} />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {TABS.find((t) => t.key === tab)?.label}
          </CardTitle>
        </CardHeader>
        <CardContent>
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
                      <TableCell>
                        <Button variant="ghost" size="sm" title="Закрыть доступ"
                                onClick={() => dropCabinet.mutate(c.id)}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!cabinets.isLoading && !(cabinets.data?.items ?? []).length && (
                    <EmptyRow colSpan={5} text="Доступов нет: кабинет пока никому не открыт" />
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
                              text="Стендов нет: показывать клиенту пока нечего" />
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
                    <TableCell className="whitespace-nowrap">{siteTime(d.created_at)}</TableCell>
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
    </div>
  )
}

export default SitePage
