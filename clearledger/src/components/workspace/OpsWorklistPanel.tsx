/**
 * «На сегодня» — рабочий лист инженера эксплуатации.
 *
 * Остальные пункты «Мониторинга» — разрезы: состояние, надёжность, марки,
 * деньги. Это правильно для разбора и неудобно для утра: чтобы понять, чем
 * заняться, приходится обойти шесть экранов и сложить их в голове.
 *
 * Здесь обратный порядок — сначала работа, потом разрезы. Строка отвечает на
 * три вопроса сразу: что со станцией, сколько стоит бездействие и взял ли её
 * кто-нибудь. Последнее — главное: на пилоте 291 станция молчит дольше недели, а
 * открытая заявка есть у одиннадцати. Экран, который показывает беду и не
 * показывает, что она никуда не уходит, воспитывает привычку смотреть мимо.
 *
 * Порядок строк — по деньгам, потом по ушедшим клиентам, загруженности площадки
 * и давности. Не по тяжести: «не работает» у станции с двумя приездами в квартал
 * и у станции с полусотней — разные задачи одного дня.
 *
 * ПРОФИЛАКТИКА В ТОЙ ЖЕ ОЧЕРЕДИ. Кончается поверка счётчика, просрочено ТО,
 * инженер отметил нарушение по осмотру — это не отказы, денег они пока не
 * теряют и наверх не всплывают. Но выезд стоит дороже самой работы: раз машина
 * едет на станцию, везти надо всё, что по ней накопилось.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { OpsSnapshotNotice } from './OpsSnapshotNotice'
import {
  AlertTriangle, ClipboardCheck, ClipboardX, Gauge, Loader2, Users, WifiOff,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { StationLink } from '@/components/common/StationLink'
import { IntakeHealthBar } from '@/components/workspace/IntakeHealthBar'
import { BulkTicketDialog } from '@/components/locations/BulkTicketDialog'
import { SortTh } from '@/components/workspace/SortableTh'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ReportPivot } from '@/components/workspace/ReportPivot'
import { useTableSort } from '@/hooks/useTableSort'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { cn } from '@/lib/utils'
import { getOpsWorklist, type WorklistRow } from '@/services/opsService'

const nf = new Intl.NumberFormat('ru-RU')

function money(v: number | null | undefined): string {
  if (!v) return '—'
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)} млн ₽`
  if (v >= 1_000) return `${nf.format(Math.round(v / 1_000))} тыс ₽`
  return `${nf.format(Math.round(v))} ₽`
}

const ЦВЕТ_ПРИЧИНЫ: Record<string, string> = {
  silent: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
  failing: 'bg-red-500/15 text-red-700 dark:text-red-400',
  breached: 'bg-purple-500/15 text-purple-700 dark:text-purple-400',
  // Профилактика — синим: спокойнее отказов, но не серая, иначе её перестают
  // замечать до дня, когда поверка уже истекла.
  meter: 'bg-sky-500/15 text-sky-700 dark:text-sky-400',
  service: 'bg-sky-500/15 text-sky-700 dark:text-sky-400',
  check: 'bg-orange-500/15 text-orange-700 dark:text-orange-400',
}

/** Слово причины для сводной: самая тяжёлая идёт первой в строке. */
const СЛОВО_ПРИЧИНЫ: Record<string, string> = {
  silent: 'молчит',
  failing: 'отказывает',
  breached: 'срок сорван',
  meter: 'поверка счётчика',
  service: 'просрочено ТО',
  check: 'нарушение по осмотру',
}

/** Профилактика — не отказ: у неё своё «сколько всего». */
const ПРОФИЛАКТИКА = ['meter', 'service', 'check']

/**
 * Плитка показателя. С `onClick` она же — фильтр списка снизу: человек смотрит
 * на число «13 просрочено» и хочет увидеть эти тринадцать, а не искать их
 * селектами. Активная подсвечена рамкой, повторное нажатие снимает отбор.
 */
function Плитка({ icon: Icon, label, value, hint, tone, onClick, active }: {
  icon: typeof Users; label: string; value: string; hint?: string; tone?: string
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
    <button type="button" data-kpi onClick={onClick}
      aria-pressed={!!active}
      className={cn(вид, 'transition-colors hover:border-primary/60')}>
      {внутри}
    </button>
  )
}

export function OpsWorklistPanel() {
  const { companyId } = useCompany()
  const { regionIds } = useFilters()
  const экран = useRef<HTMLDivElement>(null)
  const [поиск, setПоиск] = useState('')
  const [причина, setПричина] = useState('all')
  const [регионОтбора, setРегионОтбора] = useState('all')
  // «Никем не взято» — положение по умолчанию: остальное уже в работе, и
  // утренний список должен начинаться с того, чего не делает никто.
  const [неВзятые, setНеВзятые] = useState(true)
  const [вид, setВид] = useState('list')
  const [отмечены, setОтмечены] = useState<Set<string>>(new Set())
  const [пачка, setПачка] = useState(false)
  // День, НА который смотрим. Пусто — граница данных (последняя загруженная
  // сессия). Разбор «почему 3 сентября встала половина региона» по сегодняшнему
  // срезу невозможен: тот день в нём уже не виден.
  const [наДень, setНаДень] = useState('')

  const регион = регионОтбора !== 'all' ? регионОтбора : regionIds.length ? regionIds.join('|') : undefined
  const q = useQuery({
    queryKey: ['ops-worklist', companyId, регион ?? '', наДень],
    queryFn: () => getOpsWorklist(companyId, { region: регион, asOf: наДень || undefined }),
    enabled: !!companyId,
    staleTime: 60_000,
  })

  const регионыСписком = useMemo(() => {
    const набор = new Set<string>()
    for (const r of q.data?.rows ?? []) if (r.region) набор.add(r.region)
    return [...набор].sort((a, b) => a.localeCompare(b, 'ru'))
  }, [q.data])

  const строки = useMemo(() => {
    let все = q.data?.rows ?? []
    if (неВзятые && q.data?.workKnown) все = все.filter((r) => !r.openTickets)
    if (причина !== 'all') все = все.filter((r) => r.reasons.some((p) => p.kind === причина))
    if (регионОтбора !== 'all') все = все.filter((r) => r.region === регионОтбора)
    const текст = поиск.trim().toLowerCase()
    if (!текст) return все
    return все.filter((r) => [r.name, r.number, r.code, r.city, r.region]
      .some((v) => (v ?? '').toLowerCase().includes(текст)))
  }, [q.data, поиск, причина, регионОтбора, неВзятые])

  const сортировка = useMemo(() => ({
    number: (r: WorklistRow) => r.number ?? r.code,
    name: (r: WorklistRow) => r.name,
    region: (r: WorklistRow) => r.region,
    loss: (r: WorklistRow) => r.lossPerMonth,
    silent: (r: WorklistRow) => r.silentDays,
    failed: (r: WorklistRow) => r.failedVisitsPct,
    clients: (r: WorklistRow) => r.clientsLost,
    visits: (r: WorklistRow) => r.visitsPerDay,
    work: (r: WorklistRow) => r.openTickets || null,
  }), [])
  const таблица = useTableSort(строки, сортировка)

  if (q.isLoading) {
    return <div className="flex justify-center py-12">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  }
  if (q.error || !q.data) {
    return <div className="p-8 text-center text-sm text-muted-foreground">
      Не удалось собрать список работы
    </div>
  }

  const d = q.data
  const t = d.totals
  const данныеПо = new Date(d.asOf).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' })

  return (
    <div ref={экран} className="space-y-3 p-3">
      <OpsSnapshotNotice data={d} />
      {/* Если выгрузка молчит — сказать это первым, до всяких чисел: список
          работы построен на последнем загруженном дне. */}
      <IntakeHealthBar />

      <Card>
        <CardContent className="space-y-3 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold">На сегодня</div>
              <div className="text-xs text-muted-foreground">
                данные по {данныеПо}
                 · МСК
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-xs text-muted-foreground" htmlFor="worklist-asof">
                на день
              </label>
              <Input id="worklist-asof" type="date" value={наДень}
                max={d.dataThrough?.slice(0, 10)}
                onChange={(e) => setНаДень(e.target.value)}
                className="h-7 w-36 text-xs" />
              {наДень && (
                <Button size="sm" variant="ghost" className="h-7 text-xs"
                  onClick={() => setНаДень('')}>
                  К последним данным
                </Button>
              )}
              <ExportButton title="Работа на сегодня" subtitle={`данные по ${данныеПо}`}
                getEl={() => экран.current} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {/* Плитки — это и есть фильтры списка: нажатие показывает ровно те
                строки, про которые число. */}
            <Плитка icon={ClipboardCheck} label="Станций в списке" value={nf.format(t.rows)}
              hint={`молчат ${nf.format(t.silent)} · отказывают ${nf.format(t.failing)}`}
              active={!неВзятые && причина === 'all'}
              onClick={() => { setНеВзятые(false); setПричина('all') }} />
            {/* Разрыв между «видно» и «делается» — главное число экрана. */}
            <Плитка icon={ClipboardX} label="Никем не взято" value={t.notTaken == null ? '—' : nf.format(t.notTaken)}
              hint={d.workKnown ? 'нет открытой заявки' : наДень ? 'история заявок на день не восстановлена' : 'связь с Поддержкой недоступна'}
              tone={t.notTaken ? 'text-red-600 dark:text-red-400' : undefined}
              active={неВзятые && причина === 'all'}
              onClick={() => { setНеВзятые(true); setПричина('all') }} />
            <Плитка icon={AlertTriangle} label="Срок заявки сорван" value={nf.format(t.breached)}
              hint="работа заведена, но стоит"
              tone={t.breached ? 'text-purple-600 dark:text-purple-400' : undefined}
              active={причина === 'breached'}
              onClick={() => {
                // Просроченные заявки существуют только у взятых в работу —
                // держать «никем не взято» вместе с ними значит показать пусто.
                setНеВзятые(false)
                setПричина(причина === 'breached' ? 'all' : 'breached')
              }} />
            <Плитка icon={WifiOff} label="Цена бездействия" value={t.lossNotTaken == null ? '—' : money(t.lossNotTaken)}
              hint={`всего по списку ${money(t.lossPerMonth)}`}
              tone="text-red-600 dark:text-red-400"
              active={неВзятые && причина === 'silent'}
              onClick={() => { setНеВзятые(true); setПричина('silent') }} />
            <Плитка icon={Users} label="Ушло клиентов" value={nf.format(t.clientsLost)}
              hint="за квартал, по этим станциям"
              active={причина === 'failing'}
              onClick={() => setПричина(причина === 'failing' ? 'all' : 'failing')} />
            {/* Профилактика висит на тех же станциях: смотреть её отдельно
                бессмысленно, а не видеть — значит поехать дважды. */}
            <Плитка icon={Gauge} label="Поверка и ТО"
              value={nf.format(t.meter + t.service)}
              hint={t.meter + t.service + t.check
                ? `поверка ${nf.format(t.meter)} · ТО ${nf.format(t.service)}`
                  + (t.check ? ` · осмотр ${nf.format(t.check)}` : '')
                // Нулей здесь не бывает от хорошей жизни: у 537 станций пилота
                // сроки просто не заполнены, и молчать об этом — врать нулём.
                : `сроки не заполнены у ${nf.format(t.upkeepUnknown)} станций`}
              tone={t.meter ? 'text-sky-600 dark:text-sky-400' : undefined}
              active={причина === 'meter'}
              onClick={() => {
                // Сроки не зависят от того, взята ли станция в работу: отбор
                // «никем не взято» здесь только прячет половину поверок.
                setНеВзятые(false)
                setПричина(причина === 'meter' ? 'all' : 'meter')
              }} />
          </div>

          <p className="text-xs text-muted-foreground">{d.note}</p>
          {d.dataGaps.length > 0 && <details className="rounded-md border p-2">
            <summary className="cursor-pointer text-sm min-h-11 flex items-center">Заполнить сроки: {d.dataGaps.length} станций</summary>
            <p className="text-xs text-muted-foreground py-2">Откройте карточку станции → Сервис → Осмотр. В блоке «Метрология и обслуживание» нажмите «Править» и заполните сроки. Впереди — площадки с большим числом попыток зарядки.</p>
            <div className="max-h-72 overflow-auto space-y-2">
              {d.dataGaps.map((r) => <div key={r.locationId} className="text-xs flex flex-wrap gap-2">
                <StationLink station={r.locationId}>№{r.number ?? r.code} · {r.name}</StationLink>
                <span>{r.region ?? 'регион не указан'} · без поверки: {r.meterUnknown}, без ТО: {r.serviceUnknown}</span>
              </div>)}
            </div>
          </details>}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-2 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant={неВзятые ? 'default' : 'outline'}
              className="h-7 text-xs" onClick={() => setНеВзятые(!неВзятые)}>
              Никем не взято
            </Button>
            <Select value={причина} onValueChange={setПричина}>
              <SelectTrigger className="h-7 w-48 text-xs">
                <SelectValue placeholder="Причина" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любая причина</SelectItem>
                <SelectItem value="silent">Молчит</SelectItem>
                <SelectItem value="failing">Отказывает</SelectItem>
                <SelectItem value="breached">Срок заявки сорван</SelectItem>
                <SelectItem value="meter">Поверка счётчика</SelectItem>
                <SelectItem value="service">Просрочено ТО</SelectItem>
                <SelectItem value="check">Нарушение по осмотру</SelectItem>
              </SelectContent>
            </Select>
            <Select value={регионОтбора} onValueChange={setРегионОтбора}>
              <SelectTrigger className="h-7 w-52 text-xs">
                <SelectValue placeholder="Регион" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все регионы</SelectItem>
                {регионыСписком.map((р) => (
                  <SelectItem key={р} value={р}>{р}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input value={поиск} onChange={(e) => setПоиск(e.target.value)}
              placeholder="Номер, название, город…" className="h-7 w-52 text-xs" />
            {отмечены.size > 0 && (
              <Button size="sm" className="h-7 text-xs" onClick={() => setПачка(true)}>
                Завести заявки ({отмечены.size})
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
            <ReportPivot
              fields={['region', 'reason', 'taken', 'city', 'stations', 'loss', 'clients']}
              columns={['Регион', 'Причина', 'В работе', 'Город', 'Станций',
                        'Цена ₽/мес', 'Ушло клиентов']}
              rows={таблица.rows.map((r) => ({
                region: r.region ?? '— регион не указан',
                reason: СЛОВО_ПРИЧИНЫ[r.reasons[0]?.kind ?? ''] ?? 'молчит',
                taken: !d.workKnown ? 'неизвестно' : r.openTickets ? 'взята' : 'никем не взята',
                city: r.city ?? '— город не указан',
                stations: 1,
                loss: r.lossPerMonth,
                clients: r.clientsLost,
              }))} />
          ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm"
              {...exportRows('На сегодня',
                ['Номер', 'Станция', 'Регион', 'Что со станцией', 'Молчит',
                 'Приездов впустую %', 'Ушло клиентов', 'Приездов в сутки',
                 'Цена ₽/мес', 'Открытых заявок', 'Заявка'],
                таблица.rows.map((r) => [
                  r.number ?? r.code, r.name, r.region,
                  r.reasons.map((p) => p.label).join('; '),
                  r.silentDays ?? '', r.failedVisitsPct ?? '', r.clientsLost,
                  r.visitsPerDay ?? '',
                  r.lossPerMonth || '', r.openTickets, r.lastTicketNumber ?? '',
                ]))}>
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="w-8 p-1.5">
                    <Checkbox
                      checked={!!таблица.rows.length && таблица.rows.every((r) => отмечены.has(r.locationId))}
                      onCheckedChange={(v) => setОтмечены(v
                        ? new Set(таблица.rows.map((r) => r.locationId))
                        : new Set())}
                      aria-label="Отметить все строки" />
                  </th>
                  <SortTh sortKey="number" sort={таблица.sort} onSort={таблица.toggle}>№</SortTh>
                  <SortTh sortKey="name" sort={таблица.sort} onSort={таблица.toggle}>Станция</SortTh>
                  <SortTh sortKey="region" sort={таблица.sort} onSort={таблица.toggle}>Регион</SortTh>
                  <SortTh>Что со станцией</SortTh>
                  <SortTh sortKey="clients" sort={таблица.sort} onSort={таблица.toggle} align="right">Ушло клиентов</SortTh>
                  <SortTh sortKey="visits" sort={таблица.sort} onSort={таблица.toggle} align="right">Приездов в сутки</SortTh>
                  <SortTh sortKey="loss" sort={таблица.sort} onSort={таблица.toggle} align="right">Цена ₽/мес</SortTh>
                  <SortTh sortKey="work" sort={таблица.sort} onSort={таблица.toggle}>В работе</SortTh>
                </tr>
              </thead>
              <tbody>
                {таблица.rows.map((r) => (
                  <tr key={r.locationId}
                    className={cn('border-b border-border/40',
                      !r.openTickets && 'bg-red-500/5')}>
                    <td className="p-1.5">
                      <Checkbox checked={отмечены.has(r.locationId)}
                        onCheckedChange={(v) => setОтмечены((было) => {
                          const стало = new Set(было)
                          if (v) стало.add(r.locationId); else стало.delete(r.locationId)
                          return стало
                        })}
                        aria-label={`Отметить ${r.name}`} />
                    </td>
                    <td className="p-1.5 font-mono text-xs text-muted-foreground">
                      {r.number ?? r.code ?? '—'}
                    </td>
                    <td className="max-w-[240px] truncate p-1.5 font-medium" title={r.name}>
                      <StationLink station={r.locationId}>{r.name}</StationLink>
                      {r.city && <span className="ml-1.5 text-xs text-muted-foreground">{r.city}</span>}
                    </td>
                    <td className="p-1.5 text-muted-foreground">{r.region ?? '—'}</td>
                    {/* Причин может быть несколько: станция и молчит, и до этого
                        отправляла людей ни с чем — в наряде это один выезд. */}
                    <td className="p-1.5">
                      <div className="flex flex-wrap gap-1">
                        {r.reasons.map((p, i) => (
                          <span key={`${p.kind}-${i}`}
                            className={cn('rounded px-1.5 py-0.5 text-xs', ЦВЕТ_ПРИЧИНЫ[p.kind])}>
                            {p.label}
                            {p.note && <span className="ml-1 opacity-70">· {p.note}</span>}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="p-1.5 text-right tabular-nums text-muted-foreground">
                      {r.clientsLost || '—'}
                    </td>
                    {/* Загруженность площадки: при равных деньгах вперёд идёт
                        та, где больше людей, а у профилактики это вообще
                        единственный разумный порядок. */}
                    <td className="p-1.5 text-right tabular-nums text-muted-foreground">
                      {r.visitsPerDay ? r.visitsPerDay.toLocaleString('ru-RU') : '—'}
                    </td>
                    <td className="p-1.5 text-right font-medium tabular-nums">
                      {r.lossPerMonth ? money(r.lossPerMonth) : '—'}
                    </td>
                    <td className="p-1.5 text-xs">
                      {!d.workKnown ? <span>неизвестно</span> : r.openTickets ? (
                        <a href={`/support/customer/tickets/${r.lastTicketId}`}
                          className="text-primary hover:underline">
                          {r.lastTicketNumber ?? `${r.openTickets} заявк.`}
                          {r.breachedTickets > 0 && (
                            <span className="ml-1 text-red-600 dark:text-red-400">срок сорван</span>
                          )}
                        </a>
                      ) : (
                        <span className="text-red-600 dark:text-red-400">не взята</span>
                      )}
                    </td>
                  </tr>
                ))}
                {!таблица.rows.length && (
                  <tr>
                    <td colSpan={9} className="p-6 text-center text-sm text-muted-foreground">
                      {ПРОФИЛАКТИКА.includes(причина)
                        ? 'Сроков по этому отбору нет — либо они не заполнены'
                        : неВзятые
                          ? 'Всё, что видно, уже взято в работу'
                          : 'Работы по этому отбору нет'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          )}
        </CardContent>
      </Card>

      <BulkTicketDialog open={пачка} onClose={() => { setПачка(false); setОтмечены(new Set()) }}
        stations={таблица.rows.filter((r) => отмечены.has(r.locationId)).map((r) => ({
          id: r.locationId, name: r.name, number: r.number ?? r.code,
        }))} />
    </div>
  )
}
