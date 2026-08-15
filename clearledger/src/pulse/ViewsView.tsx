/**
 * Витрины «Пульса»: что и кому показываем наружу.
 *
 * «Пульс» отвечает на вопрос своего руководителя. Витрина — тот же продукт,
 * повёрнутый наружу: заказчику, владельцу сети, куратору со стороны холдинга нужна
 * проверенная картина по своей теме без погружения в приложения.
 *
 * Экран делает две вещи и обе просты: слева список витрин, справа конструктор —
 * блоки из каталога, порядок, заголовки словами получателя, кому назначено. Показ
 * витрины живёт отдельно (`ShowcaseView`): собирать и смотреть — разные занятия,
 * и мешать их в одном экране значит мешать администратору видеть то, что увидит
 * получатель.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Check, Copy, Eye, GripVertical, Link2, Plus, Send, X } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import * as userService from '@/services/userService'
import * as roleService from '@/services/roleService'
import {
  createPulseView, createPulseViewLink, getPulseView, getPulseViewLinks, getPulseViews,
  revokePulseViewLink, setPulseViewBlocks, setPulseViewGrants, setPulseViewRoles,
  updatePulseView,
} from './pulseService'
import { PulseError, PulseLoading } from './parts'
import { ShowcaseBody } from './ShowcaseView'

export function ViewsView() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [openId, setOpenId] = useState<string | null>(null)
  const [preview, setPreview] = useState(false)
  const [newName, setNewName] = useState('')

  const listQ = useQuery({
    queryKey: ['pulse-views', companyId],
    queryFn: () => getPulseViews(companyId),
  })

  const create = useMutation({
    mutationFn: () => createPulseView(companyId, newName.trim()),
    onSuccess: (r) => {
      setNewName('')
      qc.invalidateQueries({ queryKey: ['pulse-views', companyId] })
      setOpenId(r.id)
      toast.success('Витрина создана — соберите состав')
    },
    onError: (e) => toast.error('Не создано', { description: (e as Error).message }),
  })

  if (listQ.isError) return <PulseError what="витрины" onRetry={() => listQ.refetch()} />
  if (!listQ.data) return <PulseLoading what="витрин" />
  const { views, catalog } = listQ.data

  return (
    // Внешний отступ даёт оболочка «Пульса» (`PulseLayout`), как у соседних
    // разделов: свой `p-4` сдвигал конструктор относительно заголовка экрана.
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Input value={newName} onChange={(e) => setNewName(e.target.value)}
          placeholder="Название витрины: «Кабинет клиента»"
          className="h-8 max-w-xs text-[13px]" />
        <Button size="sm" className="h-8 gap-1" disabled={!newName.trim() || create.isPending}
          onClick={() => create.mutate()}>
          <Plus className="h-3.5 w-3.5" /> Завести
        </Button>
        <span className="text-[11px] text-muted-foreground">
          Витрина создаётся черновиком: пока в ней нет блоков, показывать её нельзя.
        </span>
      </div>

      {views.length === 0 && (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
          Витрин пока нет. Витрина — это набор блоков «Пульса» под конкретного
          получателя: заказчика, владельца, куратора со стороны.
        </CardContent></Card>
      )}

      <div className="grid gap-3 lg:grid-cols-[320px_1fr]">
        <div className="space-y-2">
          {views.map((v) => (
            <button key={v.id} onClick={() => { setOpenId(v.id); setPreview(false) }}
              className={cn('w-full rounded-lg border px-3 py-2 text-left transition-colors',
                openId === v.id ? 'border-primary/50 bg-primary/5' : 'border-border hover:bg-accent/40')}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{v.name}</span>
                <Badge variant={v.status === 'published' ? 'default' : 'secondary'}
                  className="text-[10px]">
                  {v.status === 'published' ? 'показывается' : 'черновик'}
                </Badge>
              </div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                {v.audience || 'получатель не указан'} · блоков {v.blocks} · людей {v.people}
              </div>
            </button>
          ))}
        </div>

        <div>
          {!openId && (
            <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
              Выберите витрину слева или заведите новую.
            </CardContent></Card>
          )}
          {openId && (
            preview
              ? <ShowcaseBody viewId={openId} onBack={() => setPreview(false)} />
              : <ViewEditor viewId={openId} catalog={catalog} periods={listQ.data.periods}
                  onPreview={() => setPreview(true)}
                  onChanged={() => qc.invalidateQueries({ queryKey: ['pulse-views', companyId] })} />
          )}
        </div>
      </div>
    </div>
  )
}

type CatalogItem = { key: string; title: string; group: string }
type Draft = { key: string; title: string }

function ViewEditor({ viewId, catalog, periods, onPreview, onChanged }: {
  viewId: string; catalog: CatalogItem[]
  periods: { key: string; title: string }[]
  onPreview: () => void; onChanged: () => void
}) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [blocks, setBlocks] = useState<Draft[]>([])
  const [name, setName] = useState('')
  const [audience, setAudience] = useState('')
  const [owner, setOwner] = useState('')
  const [note, setNote] = useState('')
  const [period, setPeriod] = useState('month')
  const [people, setPeople] = useState<Set<string>>(new Set())
  const [roles, setRoles] = useState<Set<string>>(new Set())

  const q = useQuery({
    queryKey: ['pulse-view', companyId, viewId],
    queryFn: () => getPulseView(companyId, viewId),
  })
  const teamQ = useQuery({
    queryKey: ['team-members', companyId],
    queryFn: () => userService.listUsers(companyId),
    staleTime: 5 * 60_000,
  })
  const rolesQ = useQuery({
    queryKey: ['company-roles', companyId],
    queryFn: () => roleService.listRoles(companyId),
    staleTime: 5 * 60_000,
  })

  useEffect(() => {
    if (!q.data) return
    setBlocks(q.data.blocks.map((b) => ({ key: b.key, title: b.title })))
    setName(q.data.name)
    setAudience(q.data.audience ?? '')
    setOwner(q.data.owner ?? '')
    setNote(q.data.note ?? '')
    setPeriod(q.data.period ?? 'month')
    setPeople(new Set(q.data.people.map((p) => p.id)))
    setRoles(new Set((q.data.roles ?? []).map((r) => r.id)))
  }, [q.data])

  const save = useMutation({
    mutationFn: async () => {
      await updatePulseView(companyId, viewId,
        { name, audience, owner_name: owner, note, period })
      await setPulseViewBlocks(companyId, viewId, blocks)
      await setPulseViewGrants(companyId, viewId, [...people])
      await setPulseViewRoles(companyId, viewId, [...roles])
    },
    onSuccess: () => {
      toast.success('Витрина сохранена')
      qc.invalidateQueries({ queryKey: ['pulse-view', companyId, viewId] })
      onChanged()
    },
    onError: (e) => toast.error('Не сохранено', { description: (e as Error).message }),
  })

  const publish = useMutation({
    mutationFn: (status: string) => updatePulseView(companyId, viewId, { status }),
    onSuccess: (_r, status) => {
      toast.success(status === 'published' ? 'Витрина показывается получателям'
                                           : 'Витрина снята с показа')
      qc.invalidateQueries({ queryKey: ['pulse-view', companyId, viewId] })
      onChanged()
    },
    onError: (e) => toast.error('Не вышло', { description: (e as Error).message }),
  })

  if (q.isError) return <PulseError what="витрину" onRetry={() => q.refetch()} />
  if (!q.data) return <PulseLoading what="витрины" />

  const used = new Set(blocks.map((b) => b.key))
  const groups = [...new Set(catalog.map((c) => c.group))]
  const move = (i: number, d: -1 | 1) => setBlocks((bs) => {
    const n = [...bs]
    const j = i + d
    if (j < 0 || j >= n.length) return bs
    ;[n[i], n[j]] = [n[j], n[i]]
    return n
  })

  return (
    <Card>
      <CardContent className="p-4 space-y-4">
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-[12px] text-muted-foreground">
            Название
            <Input value={name} onChange={(e) => setName(e.target.value)}
              className="mt-1 h-8 text-[13px]" />
          </label>
          <label className="text-[12px] text-muted-foreground">
            Для кого
            <Input value={audience} onChange={(e) => setAudience(e.target.value)}
              placeholder="Руководитель компании-клиента"
              className="mt-1 h-8 text-[13px]" />
          </label>
          <label className="text-[12px] text-muted-foreground">
            Период цифр
            <select value={period} onChange={(e) => setPeriod(e.target.value)}
              className="mt-1 h-8 w-full rounded-md border border-border bg-background
                         px-2 text-[13px]">
              {(periods ?? []).map((x) => (
                <option key={x.key} value={x.key}>{x.title}</option>
              ))}
            </select>
          </label>
          <label className="text-[12px] text-muted-foreground">
            За цифры отвечает
            <Input value={owner} onChange={(e) => setOwner(e.target.value)}
              placeholder="Кто отвечает за цифры" className="mt-1 h-8 text-[13px]" />
          </label>
          <label className="text-[12px] text-muted-foreground">
            Оговорка под витриной
            <Input value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="Данные на дату выгрузки из 1С" className="mt-1 h-8 text-[13px]" />
          </label>
        </div>

        <div>
          <div className="mb-1.5 text-[12px] font-medium">Состав витрины</div>
          {blocks.length === 0 && (
            <div className="rounded-md border border-dashed border-border px-3 py-4
                            text-center text-[12px] text-muted-foreground">
              Пока пусто. Добавьте блоки из каталога ниже.
            </div>
          )}
          <div className="space-y-1">
            {blocks.map((b, i) => {
              const orig = catalog.find((c) => c.key === b.key)?.title ?? b.key
              return (
                <div key={b.key} className="flex items-center gap-2 rounded-md border
                                            border-border px-2 py-1.5">
                  <GripVertical className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <div className="flex shrink-0 flex-col">
                    <button onClick={() => move(i, -1)} className="text-[10px] leading-none
                      text-muted-foreground hover:text-foreground">▲</button>
                    <button onClick={() => move(i, 1)} className="text-[10px] leading-none
                      text-muted-foreground hover:text-foreground">▼</button>
                  </div>
                  {/* Заголовок словами получателя: на витрине заказчика «Продажи»
                      называются «Отпуск энергии». */}
                  <Input value={b.title ?? ''} placeholder={orig}
                    onChange={(e) => setBlocks((bs) => bs.map((x, j) =>
                      j === i ? { ...x, title: e.target.value } : x))}
                    className="h-7 text-[13px]" />
                  {/* На телефоне исходное имя блока прячем: оно уже стоит
                      подсказкой в поле, а второй копией отнимало у поля
                      переименования половину и без того узкой строки. */}
                  <span className="hidden shrink-0 text-[11px] text-muted-foreground sm:inline">
                    {orig}
                  </span>
                  <button onClick={() => setBlocks((bs) => bs.filter((_, j) => j !== i))}
                    className="shrink-0 text-muted-foreground hover:text-foreground">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              )
            })}
          </div>
        </div>

        <div>
          <div className="mb-1.5 text-[12px] font-medium">Каталог блоков</div>
          {groups.map((g) => (
            <div key={g} className="mb-2">
              <div className="mb-1 text-[11px] uppercase tracking-wider text-muted-foreground">{g}</div>
              <div className="flex flex-wrap gap-1.5">
                {catalog.filter((c) => c.group === g).map((c) => (
                  <button key={c.key} disabled={used.has(c.key)}
                    onClick={() => setBlocks((bs) => [...bs, { key: c.key, title: '' }])}
                    className={cn('rounded-md border px-2 py-1 text-[12px]',
                      used.has(c.key) ? 'border-border/50 text-muted-foreground/50'
                                      : 'border-border hover:bg-accent')}>
                    {used.has(c.key) ? <Check className="mr-1 inline h-3 w-3" /> : null}
                    {c.title}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div>
          {/* Роль — главный способ раздачи: новый сотрудник с этой ролью получает
              картину сам. Поимённо — для исключений. */}
          <div className="mb-1.5 text-[12px] font-medium">Каким ролям</div>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {(rolesQ.data ?? []).map((r) => {
              const on = roles.has(r.id)
              return (
                <button key={r.id} onClick={() => setRoles((s) => {
                  const n = new Set(s)
                  if (n.has(r.id)) n.delete(r.id); else n.add(r.id)
                  return n
                })}
                  className={cn('rounded-md border px-2 py-1 text-[12px]',
                    on ? 'border-primary/50 bg-primary/10' : 'border-border hover:bg-accent')}>
                  {r.name}
                </button>
              )
            })}
            {(rolesQ.data ?? []).length === 0 && (
              <span className="text-[11px] text-muted-foreground">
                Ролей в компании нет — назначьте людей поимённо ниже.
              </span>
            )}
          </div>

          <div className="mb-1.5 text-[12px] font-medium">Кому персонально</div>
          <div className="flex flex-wrap gap-1.5">
            {(teamQ.data ?? []).map((u) => {
              const on = people.has(u.id)
              return (
                <button key={u.id} onClick={() => setPeople((s) => {
                  const n = new Set(s)
                  if (n.has(u.id)) n.delete(u.id); else n.add(u.id)
                  return n
                })}
                  className={cn('rounded-md border px-2 py-1 text-[12px]',
                    on ? 'border-primary/50 bg-primary/10' : 'border-border hover:bg-accent')}>
                  {u.name || u.email}
                </button>
              )
            })}
          </div>
        </div>

        <LinksBlock viewId={viewId} published={q.data.status === 'published'} />

        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <Button size="sm" className="h-8" disabled={save.isPending}
            onClick={() => save.mutate()}>Сохранить</Button>
          <Button size="sm" variant="outline" className="h-8 gap-1" onClick={onPreview}>
            <Eye className="h-3.5 w-3.5" /> Как увидит получатель
          </Button>
          {q.data.status === 'published' ? (
            <Button size="sm" variant="ghost" className="h-8"
              onClick={() => publish.mutate('draft')}>Снять с показа</Button>
          ) : (
            <Button size="sm" variant="secondary" className="h-8 gap-1"
              onClick={() => publish.mutate('published')}>
              <Send className="h-3.5 w-3.5" /> Показать получателям
            </Button>
          )}
          <span className="text-[11px] text-muted-foreground">
            Публикуется то, что сохранено.
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

/**
 * Ссылки на витрину: показ тому, у кого нет учётки.
 *
 * Самый опасный элемент концепции — по ссылке уходят финансовые данные. Поэтому у
 * неё срок, отзыв и счётчик открытий, а отозванная ссылка не удаляется: след того,
 * что она была и сколько раз её открывали, важнее чистоты списка.
 */
function LinksBlock({ viewId, published }: { viewId: string; published: boolean }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [label, setLabel] = useState('')
  const [days, setDays] = useState(30)

  const q = useQuery({
    queryKey: ['pulse-view-links', companyId, viewId],
    queryFn: () => getPulseViewLinks(companyId, viewId),
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['pulse-view-links', companyId, viewId] })

  const create = useMutation({
    mutationFn: () => createPulseViewLink(companyId, viewId, { label: label.trim(), days }),
    onSuccess: (r) => {
      setLabel('')
      refresh()
      const url = `${window.location.origin}${r.url}`
      navigator.clipboard?.writeText(url)
      toast.success('Ссылка выдана и скопирована', { description: url })
    },
    onError: (e) => toast.error('Не вышло', { description: (e as Error).message }),
  })
  const revoke = useMutation({
    mutationFn: (id: string) => revokePulseViewLink(companyId, viewId, id),
    onSuccess: () => { toast.success('Ссылка отозвана'); refresh() },
  })

  const links = q.data?.links ?? []

  return (
    <div className="border-t pt-3">
      <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-medium">
        <Link2 className="h-3.5 w-3.5" /> Ссылка без учётки
      </div>
      {!published && (
        <div className="mb-2 text-[11px] text-muted-foreground">
          Ссылку можно выдать только у опубликованной витрины.
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Input value={label} onChange={(e) => setLabel(e.target.value)}
          placeholder="Кому: «Директору компании-клиента»"
          className="h-8 max-w-[240px] text-[13px]" />
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}
          className="h-8 rounded-md border border-border bg-background px-2 text-[13px]">
          <option value={7}>на 7 дней</option>
          <option value={30}>на 30 дней</option>
          <option value={90}>на 90 дней</option>
        </select>
        <Button size="sm" className="h-8" disabled={!published || create.isPending}
          onClick={() => {
            // Ссылка открывается без пароля у любого, кто её получит. Один клик на
            // такое действие — слишком дёшево для цифр, которые уходят наружу.
            const until = new Date(Date.now() + days * 864e5).toLocaleDateString('ru-RU')
            if (window.confirm(
              `Ссылку сможет открыть любой, у кого она окажется, без пароля.
`
              + `Она будет действовать до ${until}. Выдать?`)) create.mutate()
          }}>Выдать</Button>
        <span className="text-[11px] text-muted-foreground">
          Срок обязателен: вечная ссылка на цифры — отложенная утечка.
        </span>
      </div>

      {links.length > 0 && (
        <div className="mt-2 space-y-1">
          {links.map((l) => {
            const dead = l.revoked || l.expired
            return (
              <div key={l.id} className={cn('flex flex-wrap items-center gap-2 rounded-md',
                'border border-border px-2 py-1 text-[12px]', dead && 'opacity-50')}>
                <span className="font-medium">{l.label || 'без пометки'}</span>
                <span className="text-muted-foreground">
                  {l.revoked ? 'отозвана' : l.expired ? 'истекла'
                    : `до ${(l.expiresAt ?? '').slice(0, 10)}`}
                  {' · открывали '}{l.opened}
                </span>
                {!dead && (
                  <>
                    <button onClick={() => {
                      navigator.clipboard?.writeText(`${window.location.origin}${l.url}`)
                      toast.success('Ссылка скопирована')
                    }} className="inline-flex items-center gap-1 text-muted-foreground
                                  hover:text-foreground">
                      <Copy className="h-3 w-3" /> скопировать
                    </button>
                    <button onClick={() => {
                      if (window.confirm('Отозвать ссылку? У получателя витрина'
                        + ' перестанет открываться сразу.')) revoke.mutate(l.id)
                    }} className="text-muted-foreground hover:text-foreground">отозвать</button>
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
