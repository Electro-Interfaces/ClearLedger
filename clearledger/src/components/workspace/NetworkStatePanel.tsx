/**
 * «Состояние сети» — рабочее место инженера эксплуатации.
 *
 * Экран отвечает на один вопрос: что со станциями прямо сейчас и куда ехать
 * первым делом. Строится на пересечении двух источников, потому что порознь оба
 * врут: витрина зовёт станцию активной, когда та молчит месяцами, и наоборот —
 * «нет связи» у станции, которая исправно заряжает. Правду говорит только пара
 * «статус + дни без зарядок».
 *
 * Порядок строк — по деньгам, а не по алфавиту: «молчит 16 дней» — повод
 * посмотреть, «молчит 16 дней и это 22 тыс. ₽ в месяц» — повод ехать.
 *
 * Данные приходят суточной выгрузкой, поэтому отсчёт ведётся от последней
 * загруженной сессии, а не от текущего часа — иначе каждое утро вся сеть
 * выглядела бы молчащей.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { OpsSnapshotNotice } from './OpsSnapshotNotice'
import { Activity, AlertTriangle, ClipboardX, Loader2, PlugZap, WifiOff } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ReportPivot } from '@/components/workspace/ReportPivot'
import { Checkbox } from '@/components/ui/checkbox'
import { StationLink } from '@/components/common/StationLink'
import { BulkTicketDialog } from '@/components/locations/BulkTicketDialog'
import { IntakeHealthBar } from '@/components/workspace/IntakeHealthBar'
import { SortTh } from '@/components/workspace/SortableTh'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { useTableSort } from '@/hooks/useTableSort'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { cn } from '@/lib/utils'
import { getNetworkState, type NetworkState, type NetworkStationRow } from '@/services/opsService'
import { getNetworkOpenWork } from '@/services/spaceObjectsService'

const nf = new Intl.NumberFormat('ru-RU')

function money(v: number | null | undefined): string {
  if (!v) return '—'
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)} млн ₽`
  if (v >= 1_000) return `${nf.format(Math.round(v / 1_000))} тыс ₽`
  return `${nf.format(Math.round(v))} ₽`
}

/** Дни без зарядок словами: «никогда» — это не ноль, а отдельный случай. */
function тишина(дней: number | null): string {
  if (дней === null) return 'ни разу'
  if (дней === 0) return 'сегодня'
  if (дней === 1) return 'вчера'
  return `${дней} дн`
}

const ЦВЕТ_СОСТОЯНИЯ: Record<string, string> = {
  working: 'text-emerald-600 dark:text-emerald-400',
  no_link: 'text-amber-600 dark:text-amber-400',
  disabled: 'text-muted-foreground',
  decommissioned: 'text-muted-foreground',
  not_working: 'text-red-600 dark:text-red-400',
  on_repair: 'text-blue-600 dark:text-blue-400',
  unknown: 'text-muted-foreground',
}

/** Плитка показателя; с `onClick` — ещё и фильтр списка снизу. */
function Плитка({ icon: Icon, label, value, hint, tone, onClick, active }: {
  icon: typeof Activity; label: string; value: string; hint?: string; tone?: string
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

export function NetworkStatePanel() {
  const { companyId } = useCompany()
  const { regionIds } = useFilters()
  const экран = useRef<HTMLDivElement>(null)
  // Экран открывают ради проблем, поэтому «только требующие внимания» —
  // положение по умолчанию. Полный список сети рядом, одним переключателем.
  const [толькоПроблемы, setТолькоПроблемы] = useState(true)
  const [поиск, setПоиск] = useState('')
  // Разрезы отбора: состояние из выгрузки и регион. Область учёта из шапки
  // сужает выборку на сервере, а это — ручная донастройка поверх неё.
  const [состояние, setСостояние] = useState<string>('all')
  const [регионОтбора, setРегионОтбора] = useState<string>('all')
  const [вид, setВид] = useState<string>('list')
  // «Беда видна, и никто её не взял» — главный отбор экрана: на пилоте таких
  // 280 станций из 291 молчащей.
  const [безЗаявки, setБезЗаявки] = useState(false)
  // Разрез по факту работы: он не совпадает с состоянием из выгрузки, и это
  // главный вопрос экрана — «числится рабочей, а энергии нет».
  const [факт, setФакт] = useState<'all' | 'fresh' | 'silent' | 'loss' | 'mismatch'>('all')
  // День, НА который смотрим: пусто — граница данных.
  const [наДень, setНаДень] = useState('')
  const [отмечены, setОтмечены] = useState<Set<string>>(new Set())
  const [пачка, setПачка] = useState(false)

  const регион = регионОтбора !== 'all' ? регионОтбора : regionIds.length ? regionIds.join('|') : undefined
  const q = useQuery({
    queryKey: ['ops-network-state', companyId, регион ?? '', толькоПроблемы, наДень],
    queryFn: () => getNetworkState(companyId, {
      region: регион, onlyProblems: толькоПроблемы, asOf: наДень || undefined }),
    enabled: !!companyId,
    staleTime: 60_000,
  })

  // По каким станциям работа уже идёт. Отдельный запрос, а не поле витрины:
  // ход работы ведёт «Поддержка», и копия его состояния в Ядре была бы второй
  // правдой (docs/PROCESS.md).
  const работа = useQuery({
    queryKey: ['network-open-work', companyId, наДень],
    queryFn: () => getNetworkOpenWork(companyId),
    enabled: !!companyId && !наДень,
    staleTime: 60_000,
    retry: false,
  })
  const поЗаявкам = useMemo(() => {
    const m = new Map<string, { open: number; lastNumber: string | null; lastId: string | null; breached: number }>()
    for (const r of работа.data?.objects ?? []) {
      m.set(r.ecoObjectId, {
        open: r.open, lastNumber: r.lastNumber, lastId: r.lastId, breached: r.breached,
      })
    }
    return m
  }, [работа.data])

  const сортировка = useMemo(() => ({
    name: (r: NetworkStationRow) => r.name,
    number: (r: NetworkStationRow) => r.number ?? r.code,
    region: (r: NetworkStationRow) => r.region,
    status: (r: NetworkStationRow) => r.statusLabel,
    // «Ни разу не заряжала» — самый тяжёлый случай, поэтому в сортировке он
    // тяжелее любого числа дней, а не пустое место.
    silent: (r: NetworkStationRow) => (r.silentDays === null ? 100_000 : r.silentDays),
    sessions: (r: NetworkStationRow) => r.sessions7d,
    loss: (r: NetworkStationRow) => r.loss,
    work: (r: NetworkStationRow) => поЗаявкам.get(r.locationId)?.open ?? null,
  }), [поЗаявкам])

  // Значения фильтров берём из самих данных: захардкоженный перечень регионов
  // разошёлся бы с сетью на первой же новой области.
  const регионыСписком = useMemo(() => {
    const набор = new Set<string>()
    for (const r of q.data?.stations ?? []) if (r.region) набор.add(r.region)
    return [...набор].sort((a, b) => a.localeCompare(b, 'ru'))
  }, [q.data])

  const строки = useMemo(() => {
    let все = q.data?.stations ?? []
    if (состояние !== 'all') все = все.filter((r) => r.status === состояние)
    if (регионОтбора !== 'all') все = все.filter((r) => r.region === регионОтбора)
    if (безЗаявки && работа.data && !наДень) все = все.filter((r) => !поЗаявкам.get(r.locationId)?.open)
    if (факт === 'fresh') все = все.filter((r) => r.silentDays !== null && r.silentDays <= 2)
    if (факт === 'silent') все = все.filter((r) => r.silentDays === null || r.silentDays > 7)
    if (факт === 'loss') все = все.filter((r) => r.loss > 0)
    if (факт === 'mismatch') все = все.filter((r) => r.mismatch)
    const текст = поиск.trim().toLowerCase()
    if (!текст) return все
    return все.filter((r) => [r.name, r.number, r.code, r.city, r.region]
      .some((v) => (v ?? '').toLowerCase().includes(текст)))
  }, [q.data, поиск, состояние, регионОтбора, безЗаявки, поЗаявкам, факт])

  const таблица = useTableSort(строки, сортировка)

  // Регионы — такая же рабочая таблица, как список станций: по ней решают,
  // куда ехать бригадой. Сортировка столбцов нужна ей ровно так же.
  const сортРегионов = useMemo(() => ({
    region: (g: NetworkState['regions'][number]) => g.region,
    stations: (g: NetworkState['regions'][number]) => g.stations,
    working: (g: NetworkState['regions'][number]) => g.working,
    noLink: (g: NetworkState['regions'][number]) => g.noLink,
    silent: (g: NetworkState['regions'][number]) => g.silentWeek,
    money: (g: NetworkState['regions'][number]) => g.revenuePerMonth,
  }), [])
  const регионы = useTableSort(q.data?.regions ?? [], сортРегионов,
    { key: 'money', dir: 'desc' })

  if (q.isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }
  if (q.error || !q.data) {
    return <div className="p-8 text-center text-sm text-muted-foreground">
      Не удалось получить состояние сети
    </div>
  }

  const d = q.data
  const t = d.totals
  // Счёт ведём по станциям, требующим внимания, а не по всей сети: «не взята в
  // работу» исправная станция — не беда, а норма.
  const требуютВнимания = (d.stations ?? []).filter((r) => r.attention)
  const вРаботе = требуютВнимания.filter((r) => поЗаявкам.get(r.locationId)?.open).length
  const безЗаявкиВсего = требуютВнимания.length - вРаботе
  const данныеПо = new Date(d.asOf).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' })

  return (
    <div ref={экран} className="space-y-3 p-3">
      <OpsSnapshotNotice data={d} />
      <IntakeHealthBar compact />

      <Card>
        <CardContent className="space-y-3 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold">Состояние сети</div>
              {/* Честность про возраст данных: экран показывает не «сейчас», а
                  последний загруженный час — иначе по нему принимают решения,
                  которых данные не подтверждают. */}
              <div className="text-xs text-muted-foreground">
                данные по {данныеПо}
                 · МСК
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-xs text-muted-foreground" htmlFor="state-asof">
                на день
              </label>
              <Input id="state-asof" type="date" value={наДень}
                max={d.dataThrough?.slice(0, 10)}
                onChange={(e) => setНаДень(e.target.value)}
                className="h-7 w-36 text-xs" />
              {наДень && (
                <Button size="sm" variant="ghost" className="h-7 text-xs"
                  onClick={() => setНаДень('')}>
                  К последним данным
                </Button>
              )}
              <ExportButton title="Состояние сети" subtitle={`данные по ${данныеПо}`}
                getEl={() => экран.current} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {/* Плитки — фильтры списка: человек смотрит на «молчат 204» и хочет
                увидеть эти двести четыре, а не собирать их селектами. */}
            <Плитка icon={Activity} label="Станций в сети" value={nf.format(t.stations)}
              hint={`действующих ${nf.format(t.active)}`}
              active={факт === 'all' && !безЗаявки}
              onClick={() => { setФакт('all'); setБезЗаявки(false); setТолькоПроблемы(false) }} />
            <Плитка icon={PlugZap} label="Заряжали за 2 суток" value={nf.format(t.charging2d)}
              hint={`за неделю ${nf.format(t.chargingWeek)}`}
              tone="text-emerald-600 dark:text-emerald-400"
              active={факт === 'fresh'}
              onClick={() => {
                // Заряжающие станции в «требующих внимания» не лежат — иначе
                // плитка показала бы пусто.
                setТолькоПроблемы(false)
                setФакт(факт === 'fresh' ? 'all' : 'fresh')
              }} />
            <Плитка icon={WifiOff} label="Молчат больше недели" value={nf.format(t.silentWeek)}
              hint={`ни разу не заряжали ${nf.format(t.neverCharged)}`}
              tone="text-amber-600 dark:text-amber-400"
              active={факт === 'silent'}
              onClick={() => {
                setТолькоПроблемы(false)
                setФакт(факт === 'silent' ? 'all' : 'silent')
              }} />
            <Плитка icon={AlertTriangle} label="Требуют внимания" value={nf.format(t.attention)}
              hint={`расхождений статуса ${nf.format(t.mismatch)}`}
              tone="text-red-600 dark:text-red-400"
              active={факт === 'mismatch'}
              onClick={() => {
                setТолькоПроблемы(false)
                setФакт(факт === 'mismatch' ? 'all' : 'mismatch')
              }} />
            <Плитка icon={AlertTriangle} label="Недобираем в месяц" value={money(t.lossPerMonth)}
              hint="по выручке молчащих станций"
              tone="text-red-600 dark:text-red-400"
              active={факт === 'loss'}
              onClick={() => {
                setТолькоПроблемы(false)
                setФакт(факт === 'loss' ? 'all' : 'loss')
              }} />
            {/* Разрыв между «видно» и «делается»: беда без заявки не уходит
                сама. На пилоте молчат 291 станция, взяты в работу 11. */}
            <Плитка icon={ClipboardX} label="Не взяты в работу"
              value={работа.data && !наДень ? nf.format(безЗаявкиВсего) : '—'}
              hint={работа.isError ? 'связь с Поддержкой недоступна'
                : `в работе ${nf.format(вРаботе)}`}
              tone={безЗаявкиВсего ? 'text-red-600 dark:text-red-400' : undefined}
              active={безЗаявки}
              onClick={() => { setТолькоПроблемы(true); setБезЗаявки(!безЗаявки) }} />
          </div>

          <p className="text-xs text-muted-foreground">{d.note}</p>
        </CardContent>
      </Card>

      {d.regions.length > 1 && (
        <Card>
          <CardContent className="p-3">
            <div className="mb-2 text-sm font-semibold">Где сеть проседает</div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-export-name="Регионы">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <SortTh sortKey="region" sort={регионы.sort} onSort={регионы.toggle}>Регион</SortTh>
                    <SortTh sortKey="stations" sort={регионы.sort} onSort={регионы.toggle} align="right">Станций</SortTh>
                    <SortTh sortKey="working" sort={регионы.sort} onSort={регионы.toggle} align="right">Работает</SortTh>
                    <SortTh sortKey="noLink" sort={регионы.sort} onSort={регионы.toggle} align="right">Нет связи</SortTh>
                    <SortTh sortKey="silent" sort={регионы.sort} onSort={регионы.toggle} align="right">Молчат &gt; недели</SortTh>
                    <SortTh sortKey="money" sort={регионы.sort} onSort={регионы.toggle} align="right">Недобираем, ₽/мес</SortTh>
                  </tr>
                </thead>
                <tbody>
                  {регионы.rows.map((g) => (
                    <tr key={g.region} className="border-b border-border/40">
                      <td className="p-1.5">{g.region}</td>
                      <td className="p-1.5 text-right tabular-nums">{nf.format(g.stations)}</td>
                      <td className="p-1.5 text-right tabular-nums">{nf.format(g.working)}</td>
                      <td className="p-1.5 text-right tabular-nums">{nf.format(g.noLink)}</td>
                      <td className="p-1.5 text-right tabular-nums">{nf.format(g.silentWeek)}</td>
                      <td className="p-1.5 text-right tabular-nums font-medium">
                        {money(g.revenuePerMonth)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-2 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant={толькоПроблемы ? 'default' : 'outline'}
              className="h-7 text-xs" onClick={() => setТолькоПроблемы(true)}>
              Требуют внимания
            </Button>
            <Button size="sm" variant={толькоПроблемы ? 'outline' : 'default'}
              className="h-7 text-xs" onClick={() => setТолькоПроблемы(false)}>
              Вся сеть
            </Button>
            <Select value={состояние} onValueChange={setСостояние}>
              <SelectTrigger className="h-7 w-44 text-xs">
                <SelectValue placeholder="Состояние" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любое состояние</SelectItem>
                {Object.entries(d.statusLabels).map(([код, имя]) => (
                  <SelectItem key={код} value={код}>{имя}</SelectItem>
                ))}
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
              placeholder="Номер, название, город…" className="h-7 w-56 text-xs" />
            <Button size="sm" variant={безЗаявки ? 'default' : 'outline'}
              className="h-7 text-xs" onClick={() => setБезЗаявки(!безЗаявки)}>
              Без заявки
            </Button>
            {(состояние !== 'all' || регионОтбора !== 'all' || поиск || безЗаявки
              || факт !== 'all') && (
              <Button size="sm" variant="ghost" className="h-7 text-xs"
                onClick={() => {
                  setСостояние('all'); setРегионОтбора('all')
                  setПоиск(''); setБезЗаявки(false); setФакт('all')
                }}>
                Сбросить
              </Button>
            )}
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
            /* Сводная по тем же строкам: «сколько молчащих по регионам и
               состояниям» одним разрезом, а не пересчётом глазами. */
            <ReportPivot
              fields={['region', 'status', 'city', 'silence', 'stations', 'loss', 'sessions7d']}
              columns={['Регион', 'Состояние', 'Город', 'Давность', 'Станций',
                        'Недобираем ₽/мес', 'Сессий за 7 дней']}
              rows={таблица.rows.map((r) => ({
                region: r.region ?? '— регион не указан',
                status: r.statusLabel,
                city: r.city ?? '— город не указан',
                silence: r.silentDays === null ? 'ни разу не заряжала'
                  : r.silentDays <= 2 ? 'работает (до 2 дней)'
                    : r.silentDays <= 7 ? 'молчит до недели'
                      : r.silentDays <= 30 ? 'молчит до месяца' : 'молчит больше месяца',
                stations: 1,
                loss: r.loss,
                sessions7d: r.sessions7d,
              }))} />
          ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm"
              {...exportRows('Станции',
                ['Номер', 'Станция', 'Регион', 'Город', 'Состояние', 'Молчит',
                 'Последняя зарядка', 'Сессий за 7 дней', 'Недобираем ₽/мес',
                 'Открытых заявок', 'Последняя заявка'],
                таблица.rows.map((r) => [
                  r.number ?? r.code, r.name, r.region, r.city, r.statusLabel,
                  тишина(r.silentDays),
                  r.lastSessionAt ? r.lastSessionAt.slice(0, 10) : '',
                  r.sessions7d, r.loss || '',
                  поЗаявкам.get(r.locationId)?.open ?? 0,
                  поЗаявкам.get(r.locationId)?.lastNumber ?? '',
                ]))}>
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="w-8 p-1.5">
                    {/* Отметить всё видимое: отбор уже сделан фильтрами, и
                        «выделить страницу» — единственный осмысленный смысл. */}
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
                  <SortTh sortKey="status" sort={таблица.sort} onSort={таблица.toggle}>Состояние</SortTh>
                  <SortTh sortKey="silent" sort={таблица.sort} onSort={таблица.toggle} align="right">Молчит</SortTh>
                  <SortTh sortKey="sessions" sort={таблица.sort} onSort={таблица.toggle} align="right">Сессий за 7 дн</SortTh>
                  <SortTh sortKey="loss" sort={таблица.sort} onSort={таблица.toggle} align="right">Недобираем</SortTh>
                  <SortTh sortKey="work" sort={таблица.sort} onSort={таблица.toggle}>В работе</SortTh>
                </tr>
              </thead>
              <tbody>
                {таблица.rows.map((r) => (
                  <tr key={r.locationId}
                    className={cn('border-b border-border/40',
                      r.mismatch && 'bg-amber-500/5')}>
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
                    <td className={cn('p-1.5', ЦВЕТ_СОСТОЯНИЯ[r.status] ?? '')}
                      title={r.statusRaw ?? undefined}>
                      {r.statusLabel}
                      {/* Расхождение подписано словами: инженеру важно не «жёлтая
                          строка», а что именно не сходится. */}
                      {r.mismatch && (
                        <span className="ml-1 text-xs text-amber-600 dark:text-amber-400">
                          · числится рабочей
                        </span>
                      )}
                    </td>
                    <td className="p-1.5 text-right tabular-nums">{тишина(r.silentDays)}</td>
                    <td className="p-1.5 text-right tabular-nums text-muted-foreground">
                      {nf.format(r.sessions7d)}
                    </td>
                    <td className="p-1.5 text-right font-medium tabular-nums">
                      {r.loss ? money(r.loss) : '—'}
                    </td>
                    {/* Ссылка ведёт прямо в заявку: «в работе» без возможности
                        посмотреть, в какой именно, — просто успокоительная метка. */}
                    <td className="p-1.5 text-xs">
                      {(() => {
                        const w = поЗаявкам.get(r.locationId)
                        if (!w?.open) {
                          return r.attention
                            ? <span className="text-red-600 dark:text-red-400">{работа.data && !наДень ? "не взята" : "неизвестно"}</span>
                            : <span className="text-muted-foreground">—</span>
                        }
                        return (
                          <a href={`/support/customer/tickets/${w.lastId}`}
                            className="text-primary hover:underline">
                            {w.lastNumber ?? `${w.open} заявк.`}
                            {w.open > 1 && <span className="ml-1 text-muted-foreground">+{w.open - 1}</span>}
                            {w.breached > 0 && (
                              <span className="ml-1 text-red-600 dark:text-red-400">срок сорван</span>
                            )}
                          </a>
                        )
                      })()}
                    </td>
                  </tr>
                ))}
                {!таблица.rows.length && (
                  <tr>
                    <td colSpan={9} className="p-6 text-center text-sm text-muted-foreground">
                      {толькоПроблемы
                        ? 'Станций, требующих внимания, нет — сеть работает'
                        : 'Станций не найдено'}
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
