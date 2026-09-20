/**
 * «Заявки» — срез работ «Поддержки» глазами эксплуатации.
 *
 * Инженер живёт в пространстве, а заявки — в соседнем приложении. Вопрос «что
 * сейчас с работами по сети, где сорваны сроки, чьё железо чаще ломается» он
 * задаёт отсюда и не пойдёт за ним в другое окно. Копии заявок в Ядре нет:
 * разрез спрашивается у «Поддержки» в момент показа (docs/PROCESS.md).
 *
 * Разрезы двух происхождений, и это видно в подписях: статус, вид работ, стадия
 * маршрута, источник и сроки считает «Поддержка»; марку станции, регион и
 * владельца добавляет реестр объектов пространства.
 *
 * Плитки работают фильтрами, как на остальных экранах раздела: «865 со срывом
 * срока» — это не число, а список, который надо открыть.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { OpsSnapshotNotice } from './OpsSnapshotNotice'
import {
  AlertTriangle, Clock, ExternalLink, LifeBuoy, Loader2, Timer,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { StationLink } from '@/components/common/StationLink'
import { SortTh } from '@/components/workspace/SortableTh'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ReportPivot } from '@/components/workspace/ReportPivot'
import { useTableSort } from '@/hooks/useTableSort'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { cn } from '@/lib/utils'
import { getOpsTickets, type TicketRow } from '@/services/opsService'

const nf = new Intl.NumberFormat('ru-RU')
const ОКНА = [30, 90, 365] as const

const дата = (iso?: string | null) => iso
  ? new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
  : '—'

/** Срок словами: «11 ч» читается, «11.3» — нет. */
function срок(часов: number | null | undefined): string {
  if (часов == null) return '—'
  if (часов < 24) return `${Math.round(часов)} ч`
  const дней = часов / 24
  return дней < 30 ? `${дней.toFixed(дней < 10 ? 1 : 0)} дн` : `${Math.round(дней / 30)} мес`
}

function Плитка({ icon: Icon, label, value, hint, tone, onClick, active }: {
  icon: typeof LifeBuoy; label: string; value: string; hint?: string; tone?: string
  onClick?: () => void; active?: boolean
}) {
  const внутри = (
    <>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="size-3.5" />{label}
      </div>
      <div className={cn('mt-0.5 text-lg font-semibold tabular-nums', tone)}>{value}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </>
  )
  const вид = cn('rounded-lg border bg-card px-3 py-2 text-left',
    active ? 'border-primary ring-1 ring-primary/40' : 'border-border/60')
  if (!onClick) return <div data-kpi className={вид}>{внутри}</div>
  return (
    <button type="button" data-kpi onClick={onClick} aria-pressed={!!active}
      className={cn(вид, 'transition-colors hover:border-primary/60')}>
      {внутри}
    </button>
  )
}

/** Разрез: имя, сколько всего и сколько открыто. */
function Разрез({ title, rows, source, onPick, active }: {
  title: string
  rows: { key: string; count: number; open?: number; breached?: number }[]
  /** Кто посчитал: «Поддержка» или реестр объектов — подписываем честно. */
  source: string
  onPick?: (key: string) => void
  active?: string
}) {
  if (!rows.length) return null
  const всего = rows.reduce((a, r) => a + r.count, 0) || 1
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline gap-2">
        <div className="text-sm font-medium">{title}</div>
        <span className="text-[11px] text-muted-foreground">{source}</span>
      </div>
      <div className="space-y-1">
        {rows.slice(0, 8).map((r) => (
          <button key={r.key} type="button"
            onClick={() => onPick?.(r.key)}
            className={cn('flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs transition-colors',
              onPick && 'hover:bg-accent/40',
              active === r.key && 'bg-primary/10 text-primary')}>
            <span className="min-w-0 flex-1 truncate">{r.key}</span>
            {!!r.breached && (
              <span className="text-red-600 dark:text-red-400">срыв {r.breached}</span>
            )}
            {r.open != null && r.open > 0 && (
              <span className="text-amber-600 dark:text-amber-400">откр. {r.open}</span>
            )}
            <span className="w-12 text-right tabular-nums">{nf.format(r.count)}</span>
            <span className="h-1 w-10 overflow-hidden rounded-full bg-muted">
              <span className="block h-full bg-primary/60"
                style={{ width: `${Math.max(3, (r.count / всего) * 100)}%` }} />
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

export function OpsTicketsPanel() {
  const { companyId } = useCompany()
  const { regionIds } = useFilters()
  const [наДень, setНаДень] = useState('')
  const экран = useRef<HTMLDivElement>(null)
  const [окно, setОкно] = useState<number>(90)
  const [поиск, setПоиск] = useState('')
  const [статус, setСтатус] = useState('all')
  const [марка, setМарка] = useState('all')
  const [регион, setРегион] = useState('all')
  const [разрез, setРазрез] = useState<'all' | 'open' | 'breached' | 'stale'>('open')
  const [вид, setВид] = useState('list')

  const область = регион !== 'all' ? регион : regionIds.length ? regionIds.join('|') : undefined
  const q = useQuery({
    queryKey: ['ops-tickets', companyId, окно, область, наДень],
    queryFn: () => getOpsTickets(companyId, { days: окно, region: область, asOf: наДень || undefined }),
    enabled: !!companyId,
    staleTime: 60_000,
    retry: false,
  })

  const [маркиСписком, регионыСписком] = useMemo(() => {
    const м = new Set<string>()
    const р = new Set<string>()
    for (const r of q.data?.rows ?? []) { м.add(r.brand); р.add(r.region) }
    const по = (a: string, b: string) => a.localeCompare(b, 'ru')
    return [[...м].sort(по), [...р].sort(по)]
  }, [q.data])

  const строки = useMemo(() => {
    let все = q.data?.rows ?? []
    if (разрез === 'open') все = все.filter((r) => r.isOpen)
    if (разрез === 'breached') все = все.filter((r) => r.slaBreached)
    // Возраст считает сервер: брать время в рендере — нечистая функция, и
    // React это справедливо запрещает.
    if (разрез === 'stale') все = все.filter((r) => r.isOpen && (r.ageDays ?? 0) > 30)
    // Отбор по ПОДПИСИ статуса: в разрезе и в селекте теперь имена стадий, а не
    // коды, и сравнивать надо то же, что человек видит.
    if (статус !== 'all') все = все.filter((r) => (r.statusLabel ?? r.status) === статус)
    if (марка !== 'all') все = все.filter((r) => r.brand === марка)
    if (регион !== 'all') все = все.filter((r) => r.region === регион)
    const текст = поиск.trim().toLowerCase()
    if (!текст) return все
    return все.filter((r) => [r.number, r.title, r.station, r.stationNumber, r.brand, r.city]
      .some((v) => (v ?? '').toLowerCase().includes(текст)))
  }, [q.data, разрез, статус, марка, регион, поиск])

  const сортировка = useMemo(() => ({
    number: (r: TicketRow) => r.number,
    title: (r: TicketRow) => r.title,
    status: (r: TicketRow) => r.statusLabel,
    station: (r: TicketRow) => r.station,
    brand: (r: TicketRow) => r.brand,
    region: (r: TicketRow) => r.region,
    created: (r: TicketRow) => r.createdAt,
    closed: (r: TicketRow) => r.closedAt,
  }), [])
  const таблица = useTableSort(строки, сортировка, { key: 'created', dir: 'desc' })

  if (q.isLoading) {
    return <div className="flex justify-center py-12">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  }
  if (q.error || !q.data) {
    return <div className="p-8 text-center text-sm text-muted-foreground">
      Не удалось получить заявки: «Поддержка» недоступна или пространство с ней не связано.
    </div>
  }

  const d = q.data
  const t = d.totals

  return (
    <div ref={экран} className="space-y-3 p-3">
      <OpsSnapshotNotice data={d} />
      <Card>
        <CardContent className="space-y-3 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold">Заявки по сети</div>
              <div className="text-xs text-muted-foreground">
                окно {d.days} дней · открытые показаны все · строк {nf.format(d.shown)}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-xs" htmlFor="tickets-asof">на день</label>
              <Input id="tickets-asof" type="date" value={наДень} onChange={(e) => setНаДень(e.target.value)} className="w-36" />
              {наДень && <Button variant="ghost" onClick={() => setНаДень('')}>К текущим данным</Button>}
              {ОКНА.map((о) => (
                <Button key={о} size="sm" variant={окно === о ? 'default' : 'outline'}
                  className="h-7 px-2 text-xs" onClick={() => setОкно(о)}>
                  {о} дн
                </Button>
              ))}
              <a href="/support/" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                Открыть Поддержку <ExternalLink className="size-3" />
              </a>
              <ExportButton title="Заявки по сети" subtitle={`за ${d.days} дней`}
                getEl={() => экран.current} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            <Плитка icon={LifeBuoy} label="Заявок в списке" value={nf.format(t.total)}
              hint={`за окно ${nf.format(t.inWindow)}`
                + (t.openBeforeWindow ? ` · ${nf.format(t.openBeforeWindow)} открыты с прошлого` : '')}
              active={разрез === 'all'} onClick={() => setРазрез('all')} />
            <Плитка icon={Clock} label="Открыто сейчас" value={nf.format(t.open)}
              hint={`срочных ${nf.format(t.urgentOpen)} · станций ${nf.format(t.openObjects)}`}
              tone={t.open ? 'text-amber-600 dark:text-amber-400' : undefined}
              active={разрез === 'open'} onClick={() => setРазрез('open')} />
            <Плитка icon={AlertTriangle} label="Срок сорван" value={nf.format(t.breached)}
              tone={t.breached ? 'text-red-600 dark:text-red-400' : undefined}
              active={разрез === 'breached'}
              onClick={() => setРазрез(разрез === 'breached' ? 'all' : 'breached')} />
            <Плитка icon={Timer} label="Висят дольше месяца" value={nf.format(t.staleOpen)}
              hint="созданы более 30 дней назад"
              tone={t.staleOpen ? 'text-red-600 dark:text-red-400' : undefined}
              active={разрез === 'stale'}
              onClick={() => setРазрез(разрез === 'stale' ? 'all' : 'stale')} />
            <Плитка icon={Timer} label="Закрывают в среднем" value={срок(t.avgHours)}
              hint={`станций затронуто ${nf.format(t.objects)}`} />
          </div>

          {/* Чего в данных нет — говорим прямо: пустой разрез хуже честной строки. */}
          {d.gaps.length > 0 && (
            <div className="space-y-0.5 rounded-md border border-amber-500/30 bg-amber-500/5 p-2">
              {d.gaps.map((g, i) => (
                <div key={i} className="text-xs text-muted-foreground">· {g}</div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card><CardContent className="space-y-3 p-3">
          <Разрез title="По состоянию" rows={d.by.status ?? []} source="из «Поддержки»"
            onPick={(k) => setСтатус(статус === k ? 'all' : k)} active={статус} />
          <Разрез title="По виду работ" rows={d.by.kind ?? []} source="из «Поддержки»" />
        </CardContent></Card>
        <Card><CardContent className="space-y-3 p-3">
          <Разрез title="По источнику" rows={d.by.source ?? []} source="из «Поддержки»" />
          <Разрез title="По стадии маршрута" rows={d.by.stage ?? []} source="из «Поддержки»" />
        </CardContent></Card>
        <Card><CardContent className="space-y-3 p-3">
          <Разрез title="По марке станции" rows={d.by.brand ?? []} source="из реестра объектов"
            onPick={(k) => setМарка(марка === k ? 'all' : k)} active={марка} />
          <Разрез title="По региону" rows={d.by.region ?? []} source="из реестра объектов"
            onPick={(k) => setРегион(регион === k ? 'all' : k)} active={регион} />
        </CardContent></Card>
      </div>

      <Card>
        <CardContent className="space-y-2 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Select value={статус} onValueChange={setСтатус}>
              <SelectTrigger className="h-7 w-44 text-xs">
                <SelectValue placeholder="Состояние" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любое состояние</SelectItem>
                {(d.by.status ?? []).map((x) => (
                  <SelectItem key={x.key} value={x.key}>{x.key}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={марка} onValueChange={setМарка}>
              <SelectTrigger className="h-7 w-44 text-xs">
                <SelectValue placeholder="Марка" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все марки</SelectItem>
                {маркиСписком.map((м) => <SelectItem key={м} value={м}>{м}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={регион} onValueChange={setРегион}>
              <SelectTrigger className="h-7 w-52 text-xs">
                <SelectValue placeholder="Регион" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все регионы</SelectItem>
                {регионыСписком.map((р) => <SelectItem key={р} value={р}>{р}</SelectItem>)}
              </SelectContent>
            </Select>
            <Input value={поиск} onChange={(e) => setПоиск(e.target.value)}
              placeholder="Номер, тема, станция…" className="h-7 w-56 text-xs" />
            {(статус !== 'all' || марка !== 'all' || регион !== 'all' || поиск
              || разрез !== 'open') && (
              <Button size="sm" variant="ghost" className="h-7 text-xs"
                onClick={() => {
                  setСтатус('all'); setМарка('all'); setРегион('all')
                  setПоиск(''); setРазрез('open')
                }}>
                Сбросить
              </Button>
            )}
            <span className="text-xs text-muted-foreground">
              строк: {nf.format(таблица.rows.length)}
            </span>
          </div>

          <PanelViewTabs value={вид} onChange={setВид} label={null} tabs={[
            { k: 'list', label: 'Список' },
            { k: 'pivot', label: 'Сводная' },
          ]} />

          {вид === 'pivot' ? (
            /* Разрезов больше, чем на плитках: сводную открывают именно ради
               сочетаний — марка × регион × состояние, источник × вид работ,
               возраст × срыв срока. Меры — только складываемые: среднее время
               по группам суммировать нельзя, поэтому его здесь нет (20.09.2026). */
            <ReportPivot
              fields={['brand', 'region', 'status', 'kind', 'source', 'stage',
                       'priority', 'owner', 'city', 'age', 'sla', 'month',
                       'tickets', 'open', 'closed', 'breached']}
              columns={['Марка', 'Регион', 'Состояние', 'Вид работ', 'Источник',
                        'Стадия', 'Важность', 'Владелец', 'Город', 'Возраст',
                        'Срок', 'Месяц', 'Заявок', 'Открыто', 'Закрыто', 'Срыв срока']}
              rows={таблица.rows.map((r) => ({
                brand: r.brand,
                region: r.region,
                status: r.statusLabel ?? r.status,
                kind: r.kind,
                source: r.source,
                stage: r.stage ?? '— стадия не задана',
                priority: r.priorityLabel ?? r.priority ?? '— важность не указана',
                owner: r.owner,
                city: r.city ?? '— город не указан',
                age: r.closedAt ? 'закрыта'
                  : (r.ageDays ?? 0) > 90 ? 'открыта дольше трёх месяцев'
                    : (r.ageDays ?? 0) > 30 ? 'открыта больше месяца'
                      : (r.ageDays ?? 0) > 7 ? 'открыта больше недели' : 'открыта на этой неделе',
                sla: r.slaBreached ? 'срок сорван' : 'в срок',
                month: (r.createdAt ?? '').slice(0, 7),
                tickets: 1,
                open: r.closedAt ? 0 : 1,
                closed: r.closedAt ? 1 : 0,
                breached: r.slaBreached ? 1 : 0,
              }))} />
          ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm"
              {...exportRows('Заявки',
                ['Номер', 'Тема', 'Состояние', 'Станция', 'Марка', 'Регион',
                 'Заведена', 'Закрыта', 'Срок сорван'],
                таблица.rows.map((r) => [
                  r.number, r.title, r.statusLabel, r.station ?? '', r.brand,
                  r.region, дата(r.createdAt), дата(r.closedAt),
                  r.slaBreached ? 'да' : '',
                ]))}>
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <SortTh sortKey="number" sort={таблица.sort} onSort={таблица.toggle}>Номер</SortTh>
                  <SortTh sortKey="title" sort={таблица.sort} onSort={таблица.toggle}>Тема</SortTh>
                  <SortTh sortKey="status" sort={таблица.sort} onSort={таблица.toggle}>Состояние</SortTh>
                  <SortTh sortKey="station" sort={таблица.sort} onSort={таблица.toggle}>Станция</SortTh>
                  <SortTh sortKey="brand" sort={таблица.sort} onSort={таблица.toggle}>Марка</SortTh>
                  <SortTh sortKey="region" sort={таблица.sort} onSort={таблица.toggle}>Регион</SortTh>
                  <SortTh sortKey="created" sort={таблица.sort} onSort={таблица.toggle} align="right">Заведена</SortTh>
                  <SortTh sortKey="closed" sort={таблица.sort} onSort={таблица.toggle} align="right">Закрыта</SortTh>
                </tr>
              </thead>
              <tbody>
                {таблица.rows.slice(0, 500).map((r) => (
                  <tr key={r.id}
                    className={cn('border-b border-border/40', r.slaBreached && 'bg-red-500/5')}>
                    <td className="p-1.5 font-mono text-xs">
                      <a href={`/support/customer/tickets/${r.id}`}
                        className="text-primary hover:underline">{r.number}</a>
                    </td>
                    <td className="max-w-[280px] truncate p-1.5" title={r.title}>{r.title}</td>
                    <td className="p-1.5">
                      {r.statusLabel}
                      {r.slaBreached && (
                        <span className="ml-1 text-xs text-red-600 dark:text-red-400">срок</span>
                      )}
                    </td>
                    <td className="max-w-[200px] truncate p-1.5">
                      {r.locationId
                        ? <StationLink station={r.locationId}>{r.station ?? r.locationId}</StationLink>
                        : <span className="text-xs text-muted-foreground">не сопоставлена</span>}
                    </td>
                    <td className="p-1.5 text-muted-foreground">{r.brand}</td>
                    <td className="p-1.5 text-muted-foreground">{r.region}</td>
                    <td className="p-1.5 text-right text-xs tabular-nums">{дата(r.createdAt)}</td>
                    <td className="p-1.5 text-right text-xs tabular-nums text-muted-foreground">
                      {дата(r.closedAt)}
                    </td>
                  </tr>
                ))}
                {!таблица.rows.length && (
                  <tr>
                    <td colSpan={8} className="p-6 text-center text-sm text-muted-foreground">
                      Заявок по этому отбору нет
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            {таблица.rows.length > 500 && (
              <p className="p-2 text-center text-xs text-muted-foreground">
                показаны первые 500 из {nf.format(таблица.rows.length)} — сузьте отбор
              </p>
            )}
          </div>
          )}

          <p className="text-xs text-muted-foreground">{d.note}</p>
        </CardContent>
      </Card>
    </div>
  )
}
