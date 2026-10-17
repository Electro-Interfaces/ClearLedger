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
 *
 * ТАБЛИЦА С ИНСТРУМЕНТАМИ (report-kit, 15.10.2026). Список — общий набор
 * `@/components/report-kit`, перенесённый из отчётов КП СДО: меню столбца
 * (сортировка, закрепление, фильтр по значениям, полоски), Σ в шапке, карточка
 * строки, а в правой рельсе — калькулятор, свои столбцы, поиск, столбцы,
 * сравнение и отложенные цифры. Плитки и быстрые отборы сверху остались: они
 * отвечают «что смотреть», набор — «как разобрать увиденное».
 */
import { useCallback, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { OpsSnapshotNotice } from './OpsSnapshotNotice'
import {
  AlertTriangle, ChevronDown, ClipboardCheck, ClipboardX, Gauge, Loader2, Plug,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { StationLink } from '@/components/common/StationLink'
import { IntakeHealthBar } from '@/components/workspace/IntakeHealthBar'
import { BulkTicketDialog } from '@/components/locations/BulkTicketDialog'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ReportPivot } from '@/components/workspace/ReportPivot'
import {
  PageSizeField, RelatedLink, RelatedReport, ReportTools, RowCard, SheetTable, TILE_ROW, Tile as Плитка, ToolPanel, ToolStrip, qty, useReportKit,
  type Cell, type Mark,
} from '@/components/report-kit'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { daysAgoISO } from '@/components/workspace/analytics/periodPresets'
import { cn } from '@/lib/utils'
import { matchesSearch } from '@/lib/textUtils'
import {
  getOpsTickets, getOpsWorklist, getStationHistory, getStationVisits, type OpsWorklist, type WorklistRow,
} from '@/services/opsService'

const nf = new Intl.NumberFormat('ru-RU')

function money(v: number | null | undefined): string {
  if (!v) return '—'
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)} млн ₽`
  if (v >= 1_000) return `${nf.format(Math.round(v / 1_000))} тыс ₽`
  return `${nf.format(Math.round(v))} ₽`
}

const ЦВЕТ_ПРИЧИНЫ: Record<string, string> = {
  silent: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
  dry: 'bg-red-500/15 text-red-700 dark:text-red-400',
  failing: 'bg-red-500/15 text-red-700 dark:text-red-400',
  breached: 'bg-purple-500/15 text-purple-700 dark:text-purple-400',
  // Профилактика — синим: спокойнее отказов, но не серая, иначе её перестают
  // замечать до дня, когда поверка уже истекла.
  meter: 'bg-sky-500/15 text-sky-700 dark:text-sky-400',
  service: 'bg-sky-500/15 text-sky-700 dark:text-sky-400',
  check: 'bg-orange-500/15 text-orange-700 dark:text-orange-400',
  connector: 'bg-rose-500/15 text-rose-700 dark:text-rose-400',
}

/** Слово причины для сводной: самая тяжёлая идёт первой в строке. */
const СЛОВО_ПРИЧИНЫ: Record<string, string> = {
  // «Молчит» читали как «нет связи» и «нет электроснабжения» (РусГидро, 16.10.2026):
  // речь о зарядках с энергией, связь — отдельно, по статусу витрины.
  silent: 'нет зарядок',
  dry: 'попытки без энергии',
  failing: 'отказывает',
  breached: 'срок сорван',
  meter: 'поверка счётчика',
  service: 'просрочено ТО',
  check: 'нарушение по осмотру',
  connector: 'неисправен разъём',
}

/** Профилактика — не отказ: у неё своё «сколько всего». */
const ПРОФИЛАКТИКА = ['meter', 'service', 'check']

/**
 * Столбцы таблицы. Порядок — номер столбца в строке: на него опираются
 * сохранённые настройки вида (`report-kit.v1:cols:ops-today.v1`), поэтому новый
 * столбец дописывается в конец, а смена смысла столбца — новый `ВИД`.
 */
const ВИД = 'ops-today.v1'
const КЛЮЧ_ФИЛЬТРОВ = 'report-kit.v1:filters-open:ops-today'

/**
 * Поле фильтра — своей ширины, а не доли сетки: в сетке на шесть колонок
 * селекты шириной по тексту разъезжались по всему экрану (МАГ, 15.10.2026).
 */
function Поле({ label, w, children }: { label: string; w: string; children: React.ReactNode }) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', w)}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </div>
  )
}
const С = {
  номер: 0, станция: 1, город: 2, регион: 3, что: 4, главная: 5, зарядка: 6,
  молчит: 7, впустую: 8, ушло: 9, приездов: 10, цена: 11, заявок: 12, работа: 13,
} as const
const ШАПКА = ['№', 'Станция', 'Город', 'Регион', 'Что со станцией', 'Главная причина',
  'Последняя зарядка', 'Без зарядок, дн', 'Приездов впустую, %', 'Ушло клиентов',
  'Приездов в сутки', 'Цена ₽/мес', 'Открытых заявок', 'В работе']
/** Скрыты по умолчанию — видны в карточке строки и включаются в «Столбцах». */
const СКРЫТЫ = [С.город, С.главная, С.молчит, С.впустую, С.ушло, С.заявок]
/** Столбцы, по которым шапка предлагает сводную: столбец → поле сводной. */
const СВОДНАЯ_ПО: Record<number, string> = { [С.регион]: 'Регион', [С.главная]: 'Главная причина', [С.работа]: 'В работе', [С.город]: 'Город' }
/**
 * Отчёты-расшифровки карточки строки: каждый раскрывает значения строки и
 * открывается окном поверх (МАГ, 15.10.2026). Переходов на другие экраны из
 * карточки нет — закрыл окно и остался на своей строке.
 */
const РАСШИФРОВКИ = [
  { вид: 'visits', имя: 'Приезды за 90 дней', подсказка: 'откуда «Приездов в сутки», «Ушло клиентов», «Приездов впустую»' },
  { вид: 'breaks', имя: 'Перерывы в работе за 90 дней', подсказка: 'откуда «Без зарядок, дн» и «Последняя зарядка»' },
  { вид: 'days', имя: 'Работа по дням за 90 дней', подсказка: 'сессии, энергия и выручка — основа «Цены ₽/мес»' },
  { вид: 'tickets', имя: 'Заявки станции за год', подсказка: 'откуда «Открытых заявок» и «В работе»' },
] as const
type Расшифровка = (typeof РАСШИФРОВКИ)[number]['вид']

/**
 * Не идут в сводную: номер и станция у каждой строки свои, «Что со станцией» —
 * список причин с пометками (разрез по нему — «Главная причина»). Столбцы в
 * процентах тоже мимо: сводная складывает меры, а сумма процентов — не число.
 */
const ВНЕ_СВОДНОЙ: number[] = [С.номер, С.станция, С.что]

const датаМск = (iso: string, год: boolean) => new Date(iso).toLocaleDateString('ru-RU',
  { day: '2-digit', month: '2-digit', ...(год ? { year: 'numeric' } : {}), timeZone: 'Europe/Moscow' })

function вРаботе(r: WorklistRow, workKnown: boolean) {
  if (!workKnown) return 'неизвестно'
  if (!r.openTickets) return 'не взята'
  return r.lastTicketNumber ?? `${r.openTickets} заявк.`
}

function строкаТаблицы(r: WorklistRow, workKnown: boolean): Cell[] {
  return [
    r.number ?? r.code ?? '', r.name, r.city ?? '', r.region ?? '',
    r.reasons.map((p) => p.label + (p.note ? ` · ${p.note}` : '')).join('; '),
    СЛОВО_ПРИЧИНЫ[r.reasons[0]?.kind ?? ''] ?? 'нет зарядок',
    r.lastSessionAt ? датаМск(r.lastSessionAt, true) : '',
    r.silentDays ?? '', r.failedVisitsPct ?? '', r.clientsLost,
    r.visitsPerDay ?? '', r.lossPerMonth || '',
    workKnown ? r.openTickets : '', вРаботе(r, workKnown),
  ]
}

export function OpsWorklistPanel() {
  const { companyId } = useCompany()
  const { regionIds, period } = useFilters()
  const экран = useRef<HTMLDivElement>(null)
  const [поиск, setПоиск] = useState('')
  const [причина, setПричина] = useState('all')
  const [регионОтбора, setРегионОтбора] = useState('all')
  // «Никем не взято» — положение по умолчанию: остальное уже в работе, и
  // утренний список должен начинаться с того, чего не делает никто.
  const [неВзятые, setНеВзятые] = useState(true)
  const [вид, setВид] = useState('list')
  const [первыйУровень, setПервыйУровень] = useState<number | null>(null)
  const [отмечены, setОтмечены] = useState<Set<string>>(new Set())
  const [пачка, setПачка] = useState<{ id: string; name: string; number: string | null }[] | null>(null)
  const [карточка, setКарточка] = useState<{ order: number[]; pos: number } | null>(null)
  const [порядок, setПорядок] = useState<number[]>([])
  const [возврат, setВозврат] = useState(false)
  const [расшифровка, setРасшифровка] = useState<Расшифровка | null>(null)
  // День, НА который смотрим, — конец общего периода в строке фильтра (МАГ,
  // 15.10.2026: период выбирается там же, где на всех экранах, а не своим полем).
  // Период по вчера или по сегодня — граница данных (последняя загруженная
  // сессия): выгрузка приходит раз в сутки, и «по вчера» — это и есть последние
  // данные, а не срез на вчера с подписью «Работа на 14.10». Разбор «почему
  // 3 сентября встала половина региона» — период, кончающийся 3-м.
  const наДень = period.to >= daysAgoISO(1) ? '' : period.to
  const [фильтрыОткрыты, setФильтрыОткрыты] = useState(() => {
    try { return localStorage.getItem(КЛЮЧ_ФИЛЬТРОВ) === '1' } catch { return false }
  })
  const переключитьФильтры = (v: boolean) => {
    setФильтрыОткрыты(v)
    try { localStorage.setItem(КЛЮЧ_ФИЛЬТРОВ, v ? '1' : '0') } catch { /* хранилище недоступно */ }
  }

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
    if (!поиск.trim()) return все
    return все.filter((r) => matchesSearch(поиск, [r.name, r.number, r.code, r.city, r.region,
      r.lastTicketNumber, ...r.reasons.map((p) => `${p.label} ${p.note ?? ''}`)]))
  }, [q.data, поиск, причина, регионОтбора, неВзятые])

  const workKnown = !!q.data?.workKnown
  const ячейки = useMemo(() => строки.map((r) => строкаТаблицы(r, workKnown)), [строки, workKnown])
  const итог = useMemo<Cell[]>(() => {
    const t: Cell[] = ШАПКА.map(() => '')
    t[С.номер] = 'Итого'
    t[С.станция] = `${qty(строки.length)} станций`
    t[С.ушло] = строки.reduce((s, r) => s + r.clientsLost, 0)
    t[С.цена] = строки.reduce((s, r) => s + (r.lossPerMonth || 0), 0)
    if (workKnown) t[С.заявок] = строки.reduce((s, r) => s + r.openTickets, 0)
    return t
  }, [строки, workKnown])

  const данныеПо = q.data ? new Date(q.data.asOf).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' }) : ''
  const отбор = [
    неВзятые && 'никем не взято',
    причина !== 'all' && (СЛОВО_ПРИЧИНЫ[причина] ?? причина),
    регионОтбора !== 'all' && регионОтбора,
    поиск.trim() && `поиск «${поиск.trim()}»`,
  ].filter(Boolean) as string[]

  const набор = useReportKit({
    id: ВИД,
    title: 'На сегодня',
    head: ШАПКА,
    rows: ячейки,
    total: итог,
    hide: СКРЫТЫ,
    ready: !!q.data,
    pivot: вид === 'pivot',
    help: ПОМОЩЬ,
  })

  const сброс = () => {
    setНеВзятые(true)
    setПричина('all')
    setРегионОтбора('all')
    setПоиск('')
    набор.setFilters({})
  }

  const отметка = useMemo<Mark>(() => ({
    has: (i) => отмечены.has(строки[i]?.locationId),
    set: (rows, on) => setОтмечены((было) => {
      const стало = new Set(было)
      for (const i of rows) {
        const id = строки[i]?.locationId
        if (!id) continue
        if (on) стало.add(id); else стало.delete(id)
      }
      return стало
    }),
    label: (i) => строки[i]?.name ?? '',
  }), [отмечены, строки])

  const ячейка = useCallback((i: number, c: number) => {
    const r = строки[i]
    if (!r) return undefined
    if (c === С.номер) return <span className="font-mono text-xs text-muted-foreground">{r.number ?? r.code ?? '—'}</span>
    if (c === С.станция) return (
      <span className="font-medium">
        <StationLink station={r.locationId}>{r.name}</StationLink>
        {r.city && <span className="ml-1.5 text-xs font-normal text-muted-foreground">{r.city}</span>}
      </span>
    )
    // Причин может быть несколько: станция и молчит, и до этого отправляла людей
    // ни с чем — в наряде это один выезд.
    if (c === С.что) return (
      <div className="flex min-w-[260px] max-w-[420px] flex-wrap gap-1 whitespace-normal">
        {r.reasons.map((p, k) => (
          <span key={`${p.kind}-${k}`} className={cn('rounded px-1.5 py-0.5 text-xs', ЦВЕТ_ПРИЧИНЫ[p.kind])}>
            {p.label}
            {p.note && <span className="ml-1 opacity-70">· {p.note}</span>}
          </span>
        ))}
      </div>
    )
    // Дата, а не «молчит N дн»: по ней инженер сверяется с клиентом и
    // оператором. Год — всегда (МАГ, 15.10.2026): дата без года читается как ошибка.
    if (c === С.зарядка) return r.lastSessionAt
      ? <span className="text-muted-foreground" title={r.clientsLost ? `ушло клиентов за квартал: ${r.clientsLost}` : undefined}>
          {датаМск(r.lastSessionAt, true)}
        </span>
      : undefined
    if (c === С.цена) return r.lossPerMonth ? <span className="font-medium">{money(r.lossPerMonth)}</span> : undefined
    if (c === С.работа) {
      if (!workKnown) return <span className="text-xs">неизвестно</span>
      if (!r.openTickets) return <span className="text-xs text-red-600 dark:text-red-400">не взята</span>
      return (
        <a href={`/support/customer/tickets/${r.lastTicketId}`} className="text-xs text-primary hover:underline">
          {r.lastTicketNumber ?? `${r.openTickets} заявк.`}
          {r.breachedTickets > 0 && <span className="ml-1 text-red-600 dark:text-red-400">срок сорван</span>}
        </a>
      )
    }
    return undefined
  }, [строки, workKnown])

  const видимые = useMemo(() => {
    const cols = набор.table.cols
    const head = набор.sheet.head
    const order = cols.order.length === head.length ? cols.order : head.map((_, i) => i)
    return order.filter((i) => !cols.hidden.includes(i))
  }, [набор.table.cols, набор.sheet.head])

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
  const отфильтрованы = набор.kept.length !== строки.length
  // Сводная — от всех столбцов таблицы набора, включая свои столбцы-формулы:
  // что есть в списке, то можно и свести (МАГ, 15.10.2026). Первым — уровень,
  // выбранный в шапке, затем деньги: по первой мере упорядочены группы и
  // считается доля.
  const шапка = набор.sheet.head
  const колонки = шапка.map((_, c) => c).filter((c) => !ВНЕ_СВОДНОЙ.includes(c) && !шапка[c].includes('%'))
  const впереди = [первыйУровень, С.цена].filter((c): c is number => c !== null && колонки.includes(c))
  const поляСводной = [...new Set([...впереди, ...колонки])].map((c) => `c${c}`)
  const подписиСводной = поляСводной.map((п) => {
    const c = Number(п.slice(1))
    return c === С.зарядка ? 'Последняя зарядка, месяц' : шапка[c]
  })
  const строкиСводной = набор.kept.map((i) => {
    const r = набор.sheet.rows[i]
    return Object.fromEntries(колонки.map((c) => {
      let v = r[c]
      // Дата — разрезом по месяцу: по дню каждая станция своя.
      if (c === С.зарядка && typeof v === 'string') v = v.slice(3)
      // В ячейке номер заявки; для группировки важно только «взята или нет».
      if (c === С.работа) v = v === 'не взята' ? 'никем не взята' : v === 'неизвестно' ? v : 'взята'
      return [`c${c}`, v]
    }))
  })
  const строкаКарточки = карточка ? строки[карточка.order[карточка.pos]] : null
  const пустоСписка = ПРОФИЛАКТИКА.includes(причина)
    ? 'Сроков по этому отбору нет — либо они не заполнены'
    : неВзятые
      ? 'Всё, что видно, уже взято в работу'
      : 'Работы по этому отбору нет'

  return (
    <div ref={экран} className="space-y-3 p-3">
      {/* Срез данных — только когда он отстал: дата среза и так в подписи
          таблицы, а постоянная плашка над плитками — шум (МАГ, 15.10.2026). */}
      {(!d.dataThrough || (d.dataLagHours ?? 0) >= 24) && <OpsSnapshotNotice data={d} />}
      {/* Если выгрузка молчит — сказать это первым, до всяких чисел: список
          работы построен на последнем загруженном дне. */}
      {/* Только «выгрузка не приходила»: платежи без сессии и пропавшие графы —
          вопрос к данным и экономисту, инженер их не исправит (МАГ, 30.09.2026). */}
      <IntakeHealthBar compact />

      {/* Только плитки — они же переключатели списка. Заголовок, «Как собран
          список» и пропуски сроков сняты по замечанию МАГа 15.10.2026: дата
          среза есть в подписи таблицы, пояснение — в «Инфо». */}
          <div className={TILE_ROW}>
            {/* Плитки — это и есть фильтры списка: нажатие показывает ровно те
                строки, про которые число. */}
            <Плитка icon={ClipboardCheck} label="Станций в списке" value={nf.format(t.rows)}
              hint={`без зарядок ${nf.format(t.silent)} · отказывают ${nf.format(t.failing)}`}
              active={!неВзятые && причина === 'all'}
              onClick={() => { setНеВзятые(false); setПричина('all') }} />
            {/* Разрыв между «видно» и «делается» — главное число экрана. */}
            <Плитка icon={ClipboardX} label="Никем не взято" value={t.notTaken == null ? '—' : nf.format(t.notTaken)}
              hint={d.workKnown
                ? `нет открытой заявки${t.lossNotTaken ? ` · ${money(t.lossNotTaken)}/мес` : ''}`
                : наДень ? 'история заявок на день не восстановлена' : 'связь с Поддержкой недоступна'}
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
            {/* Разъём по статусу витрины: станция на связи и продаёт, а один
                разъём две книги подряд в ошибке — клиент с этим типом уезжает. */}
            <Плитка icon={Plug} label="Неисправен разъём" value={nf.format(t.connector ?? 0)}
              hint={d.statusDay ? 'больше суток, станция на связи' : 'статусов витрины нет'}
              tone={t.connector ? 'text-rose-600 dark:text-rose-400' : undefined}
              active={причина === 'connector'}
              onClick={() => { setНеВзятые(false); setПричина(причина === 'connector' ? 'all' : 'connector') }} />
            {/* Цена бездействия и ушедшие клиенты — показатели руководителя: здесь
                они задают порядок строк, отдельная плитка не нужна. Профилактика —
                плиткой, только когда она есть: «0» при незаполненных сроках
                читался как «всё в порядке». Сроки не зависят от того, взята ли
                станция в работу, поэтому отбор «никем не взято» снимается. */}
            {t.meter + t.service + t.check > 0 && (
              <Плитка icon={Gauge} label="Поверка и ТО"
                value={nf.format(t.meter + t.service)}
                hint={`поверка ${nf.format(t.meter)} · ТО ${nf.format(t.service)}`
                  + (t.check ? ` · осмотр ${nf.format(t.check)}` : '')}
                tone={t.meter ? 'text-sky-600 dark:text-sky-400' : undefined}
                active={причина === 'meter'}
                onClick={() => {
                  setНеВзятые(false)
                  setПричина(причина === 'meter' ? 'all' : 'meter')
                }} />
            )}
          </div>

      {/* py-0: свои поля карточки (py-6) плюс p-3 содержимого давали пустую
          полосу над строкой фильтров (МАГ, 15.10.2026). */}
      <Card className="py-0">
        <CardContent className="space-y-3 p-3">
          {/* Фильтры сворачиваются, как в отчётах КП СДО: развёрнуты — подписанные
              поля, свёрнуты — одна строка с тем, что сейчас отобрано. */}
          {фильтрыОткрыты && (
            <div className="flex flex-wrap items-end gap-3">
              <Поле label="В работе" w="w-44">
                <Select value={неВзятые ? 'free' : 'all'} onValueChange={(v) => setНеВзятые(v === 'free')}>
                  <SelectTrigger className="h-9 w-full text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="free">Никем не взято</SelectItem>
                    <SelectItem value="all">Все станции</SelectItem>
                  </SelectContent>
                </Select>
              </Поле>
              <Поле label="Причина" w="w-52">
                <Select value={причина} onValueChange={setПричина}>
                  <SelectTrigger className="h-9 w-full text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Любая причина</SelectItem>
                    <SelectItem value="silent">Нет зарядок</SelectItem>
                    <SelectItem value="dry">Попытки без энергии</SelectItem>
                    <SelectItem value="failing">Отказывает</SelectItem>
                    <SelectItem value="breached">Срок заявки сорван</SelectItem>
                    <SelectItem value="meter">Поверка счётчика</SelectItem>
                    <SelectItem value="service">Просрочено ТО</SelectItem>
                    <SelectItem value="check">Нарушение по осмотру</SelectItem>
                    <SelectItem value="connector">Неисправен разъём</SelectItem>
                  </SelectContent>
                </Select>
              </Поле>
              <Поле label="Регион" w="w-52">
                <Select value={регионОтбора} onValueChange={setРегионОтбора}>
                  <SelectTrigger className="h-9 w-full text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Все регионы</SelectItem>
                    {регионыСписком.map((р) => (
                      <SelectItem key={р} value={р}>{р}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Поле>
              <Поле label="Поиск" w="w-64">
                <Input value={поиск} onChange={(e) => setПоиск(e.target.value)}
                  placeholder="Номер, название, город…" className="h-9 text-sm" />
              </Поле>
              <Поле label="Строк на странице" w="w-32">
                <PageSizeField bare />
              </Поле>
            </div>
          )}
          <div className={cn('flex flex-wrap items-center justify-between gap-2', фильтрыОткрыты && 'border-t border-border/60 pt-3')}>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <button type="button" onClick={() => переключитьФильтры(!фильтрыОткрыты)} aria-expanded={фильтрыОткрыты}
                className="-ml-1 inline-flex h-8 items-center gap-1.5 rounded-md px-1.5 text-sm font-semibold text-primary hover:bg-accent">
                <ChevronDown className={cn('size-4 transition-transform', фильтрыОткрыты && 'rotate-180')} />
                {фильтрыОткрыты ? 'Свернуть фильтры' : 'Фильтры'}
                {/* Свёрнутые фильтры не должны выглядеть пустыми: число установленных
                    — на кнопке, сами они — в подписи таблицы (МАГ, 15.10.2026). */}
                {!фильтрыОткрыты && отбор.length + Object.keys(набор.filters).length > 0 && (
                  <span className="rounded-full bg-primary px-1.5 text-[11px] font-semibold leading-5 text-primary-foreground">
                    {отбор.length + Object.keys(набор.filters).length}
                  </span>
                )}
              </button>
              {/* Чипов отбора здесь нет: тот же отбор — строкой в подписи
                  таблицы, второй раз он только занимал место (МАГ, 15.10.2026). */}
              <PanelViewTabs value={вид} onChange={setВид} label={null} tabs={[
                { k: 'list', label: 'Список' },
                { k: 'pivot', label: 'Сводная' },
              ]} />
              <span className="text-xs text-muted-foreground">
                строк: {nf.format(отфильтрованы ? набор.kept.length : строки.length)}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {отмечены.size > 0 && (
                <Button size="sm" className="h-8 text-xs"
                  onClick={() => setПачка(строки.filter((r) => отмечены.has(r.locationId))
                    .map((r) => ({ id: r.locationId, name: r.name, number: r.number ?? r.code })))}>
                  Завести заявки ({отмечены.size})
                </Button>
              )}
              <ExportButton title="Работа на сегодня" subtitle={`данные по ${данныеПо}`}
                getEl={() => экран.current} />
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={сброс}
                disabled={!отбор.length && !Object.keys(набор.filters).length}>
                Сброс
              </Button>
            </div>
          </div>

          {/* Телефон и планшет: рельсы нет, те же кнопки — полосой над таблицей. */}
          <ToolStrip />

          {вид === 'pivot' ? (
            <div className="space-y-2">
              {/* Фильтры столбцов списка действуют и на сводную: иначе одна и та
                  же цифра на двух вкладках расходилась бы без объяснения. */}
              {отфильтрованы && (
                <div className="rounded-md bg-primary/5 px-3 py-1.5 text-xs text-muted-foreground">
                  Сводная собрана по {nf.format(набор.kept.length)} из {nf.format(строки.length)} станций: фильтр по{' '}
                  {Object.keys(набор.filters).map((k) => `«${набор.sheet.head[Number(k)]}»`).join(', ')}.{' '}
                  <button type="button" className="font-semibold text-primary hover:underline" onClick={() => набор.setFilters({})}>
                    Снять
                  </button>
                </div>
              )}
              <ReportPivot
                key={поляСводной[0]}
                // Первая мера — деньги: по ней упорядочены группы и считается доля.
                // «Станций» убрано: это то же число, что «Строк» сводной. Причина —
                // главная (первая) у станции: сумма по нескольким задвоила бы деньги.
                fields={поляСводной}
                columns={подписиСводной}
                rows={строкиСводной} />
            </div>
          ) : (
            <SheetTable
                {...набор.table}
                caption={<>Работа на {наДень ? наДень.split('-').reverse().join('.') : 'сегодня'}</>}
                lines={[`данные по ${данныеПо} МСК`, ...отбор]}
                groupBy={СВОДНАЯ_ПО}
                onGroup={(c) => { setПервыйУровень(c); setВид('pivot') }}
                onRow={(order, pos) => setКарточка({ order, pos })}
                onView={setПорядок}
                render={ячейка}
                rowTitle={(i) => строки[i]?.name ?? ''}
                mark={отметка}
                empty={пустоСписка}
                // Выгрузка — видимые столбцы в порядке человека, строки в порядке
                // таблицы с фильтрами: Excel получает то, что на экране.
                tableAttrs={exportRows('На сегодня',
                  видимые.map((c) => набор.sheet.head[c]),
                  порядок.map((i) => видимые.map((c) => набор.sheet.rows[i]?.[c] ?? '')))}
              />
          )}
        </CardContent>
      </Card>

      <ToolPanel>
        <ReportTools
          {...набор.tools}
          searchHint="Номер, название, регион, причина или число"
          formulaExample="Например, Цена на клиента"
          compare={<WorklistCompare companyId={companyId} region={регион} base={наДень || d.dataThrough?.slice(0, 10) || ''} now={d} />}
        />
      </ToolPanel>

      <RowCard
        report="На сегодня"
        head={набор.sheet.head}
        // «Завести заявку» открывается поверх, а окно строки прячется и
        // возвращается, когда её закрыли: человек не уходит со своей строки.
        row={карточка && !(возврат && пачка)
          ? набор.sheet.rows[карточка.order[карточка.pos]] ?? null : null}
        title={строкаКарточки?.name}
        at={карточка?.pos ?? 0}
        of={карточка?.order.length ?? 0}
        onStep={(dir) => setКарточка((k) => (k ? { ...k, pos: Math.min(Math.max(k.pos + dir, 0), k.order.length - 1) } : k))}
        onClose={() => { setКарточка(null); setВозврат(false) }}
        extra={строкаКарточки && (
          <div className="space-y-5">
            <div className="divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60">
              {РАСШИФРОВКИ.map((р) => (
                <RelatedLink key={р.вид} label={р.имя} hint={р.подсказка} onClick={() => setРасшифровка(р.вид)} />
              ))}
            </div>
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Действия</div>
              <div className="overflow-hidden rounded-lg border border-border/60">
                <RelatedLink label="Завести заявку" hint="на выезд по этой станции"
                  icon={<ClipboardCheck className="size-4" aria-hidden />}
                  onClick={() => {
                    setВозврат(true)
                    setПачка([{ id: строкаКарточки.locationId, name: строкаКарточки.name, number: строкаКарточки.number ?? строкаКарточки.code }])
                  }} />
              </div>
            </div>
          </div>
        )}
      />
      <WorklistDrill вид={карточка ? расшифровка : null} row={строкаКарточки} onClose={() => setРасшифровка(null)} />

      <BulkTicketDialog open={!!пачка} onClose={() => { setПачка(null); setОтмечены(new Set()) }}
        stations={пачка ?? []} />
    </div>
  )
}

const мск = (iso: string | null) => iso ? new Date(iso).toLocaleString('ru-RU',
  { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' }) : ''

/** Окно-расшифровка строки: данные станции из тех же API, что карточка станции. */
function WorklistDrill({ вид, row, onClose }: { вид: Расшифровка | null; row: WorklistRow | null; onClose: () => void }) {
  const { companyId } = useCompany()
  const id = row?.locationId ?? ''
  const надо = (...в: Расшифровка[]) => !!companyId && !!id && !!вид && в.includes(вид)
  const визиты = useQuery({
    queryKey: ['drill-visits', companyId, id],
    queryFn: () => getStationVisits(companyId, id, { days: 90 }),
    enabled: надо('visits'), staleTime: 60_000,
  })
  const история = useQuery({
    queryKey: ['drill-history', companyId, id],
    queryFn: () => getStationHistory(companyId, id, 90),
    enabled: надо('breaks', 'days'), staleTime: 60_000,
  })
  // Заявки — срез региона станции, отбор по станции здесь: отдельного запроса
  // «заявки одной станции» у сервера нет.
  const заявки = useQuery({
    queryKey: ['drill-tickets', companyId, row?.region ?? ''],
    queryFn: () => getOpsTickets(companyId, { days: 365, region: row?.region ?? undefined, limit: 5000 }),
    enabled: надо('tickets'), staleTime: 60_000,
  })
  const имя = РАСШИФРОВКИ.find((р) => р.вид === вид)?.имя ?? ''
  const подпись = row ? `${row.name}${row.number ? ` · № ${row.number}` : ''}` : ''
  let head: string[] = []
  let rows: Cell[][] = []
  let q: { isLoading: boolean; isError: boolean } = визиты
  let note: string | undefined
  if (вид === 'visits') {
    const d = визиты.data
    const картина = new Map(d?.patterns.map((p) => [p.key, p.label]) ?? [])
    head = ['Начало', 'Минут у станции', 'Попыток', 'Зарядился', 'кВт·ч', 'Выручка, ₽', 'Клиент', 'Карта', 'Как прошло']
    rows = (d?.visits ?? []).map((v) => [мск(v.startedAt), v.minutesAtStation ?? '', v.attempts, v.charged ? 'да' : 'нет',
      v.energyKwh, v.revenue, v.clientName ?? v.client ?? '', v.card ?? '', картина.get(v.pattern) ?? v.pattern])
    note = d?.note
  } else if (вид === 'breaks') {
    q = история
    head = ['С', 'По', 'Дней']
    rows = (история.data?.breaks ?? []).map((b) => [мск(b.from), b.ongoing ? 'идёт сейчас' : мск(b.to), b.days])
    note = история.data?.note
  } else if (вид === 'days') {
    q = история
    head = ['День', 'Сессий', 'Неудачных', 'кВт·ч', 'Выручка, ₽']
    rows = [...(история.data?.days_series ?? [])].reverse()
      .map((s) => [s.day.split('-').reverse().join('.'), s.sessions, s.failed, s.energyKwh, s.revenue])
  } else if (вид === 'tickets') {
    q = заявки
    head = ['№', 'Заявка', 'Статус', 'Заведена', 'Дней', 'Срок', 'Исполнитель']
    rows = (заявки.data?.rows ?? []).filter((t) => t.locationId === id)
      .map((t) => [t.number, t.title, t.statusLabel, мск(t.createdAt), t.ageDays ?? '', t.slaBreached ? 'сорван' : '', t.assignee ?? ''])
  }
  return (
    <RelatedReport open={!!вид && !!row} title={имя} subtitle={подпись} head={head} rows={rows}
      loading={q.isLoading} error={q.isError} note={note} onClose={onClose} />
  )
}

function WorklistHelp() {
  const абзац = 'text-sm leading-relaxed text-di-on-surface-variant'
  return (
    <div className="space-y-3">
      <p className={абзац}>
        «На сегодня» — список станций, по которым есть работа: нет зарядок, попытки без энергии, отказывают, сорван срок заявки, неисправен разъём,
        кончаются поверка и ТО. Сверху — плитки-отборы, ниже — таблица. Порядок по умолчанию — по деньгам, которые станция
        теряет за месяц, потом по ушедшим клиентам и загруженности площадки.
      </p>
      <p className={абзац}>
        <b>Таблица.</b> Наведите на заголовок: стрелка сортирует, Σ считает сумму, среднее, минимум и максимум, ▾ открывает
        меню — закрепить столбцы слева, скрыть, полоски величины и фильтр по значениям («не взята» в «В работе», нужный регион).
        Заголовок можно перетащить, край — потянуть. Щелчок по строке открывает её карточку, ↑ ↓ и Enter работают с клавиатуры.
      </p>
      <p className={абзац}>
        <b>Инструменты справа.</b> «Калькулятор»: пока он открыт, щелчок по ячейке добавляет число. «Формулы» — свой
        столбец из других, например цена на одного ушедшего клиента. «Поиск» подсвечивает совпадения по всем страницам.
        «Столбцы» включают скрытое: город, «без зарядок, дн», долю приездов впустую, число заявок. «Сравнить» показывает, что
        изменилось со вчера или за неделю. «Цифры» — отложенные для сверки числа.
      </p>
      <p className={абзац}>
        <b>Данные.</b> Сессии — на выбранный день (МСК), статусы станций и разъёмов — по выгрузке витрины АСУиМ, она
        приходит раз в сутки; дата среза — в подписи таблицы. Плашка над плитками появляется, только если выгрузка отстала
        больше чем на сутки. Сроки поверки и ТО заполняются в карточке станции → Сервис → Осмотр, блок «Метрология и
        обслуживание».
      </p>
      <p className={абзац}>
        Отметьте строки флажками — появится «Завести заявки». Значок у «Региона», «Главной причины» и «В работе» открывает
        сводную сразу с этим уровнем.
      </p>
    </div>
  )
}

const ПОМОЩЬ = <WorklistHelp />

const сдвигДня = (iso: string, дней: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() - дней)
  return d.toISOString().slice(0, 10)
}

/**
 * «Сравнить» для рабочего листа: тот же список на день раньше или неделю назад.
 * Периода у экрана нет, поэтому сравниваются два среза — что появилось в работе
 * и что из неё ушло. Регион отбора действует на оба среза, быстрые отборы и
 * фильтры столбцов — нет: сравнивается весь список.
 */
function WorklistCompare({ companyId, region, base, now }: { companyId: string; region?: string; base: string; now: OpsWorklist }) {
  const [дней, setДней] = useState<number | null>(null)
  const день = base && дней ? сдвигДня(base, дней) : ''
  const q = useQuery({
    queryKey: ['ops-worklist', companyId, region ?? '', день],
    queryFn: () => getOpsWorklist(companyId, { region, asOf: день }),
    enabled: !!companyId && !!день,
    staleTime: 60_000,
  })
  const было = q.data
  const разница = useMemo(() => {
    if (!было) return null
    const прежние = new Map(было.rows.map((r) => [r.locationId, r]))
    const теперь = new Set(now.rows.map((r) => r.locationId))
    const новые = now.rows.filter((r) => !прежние.has(r.locationId)).sort((a, b) => b.lossPerMonth - a.lossPerMonth)
    const ушли = было.rows.filter((r) => !теперь.has(r.locationId)).sort((a, b) => b.lossPerMonth - a.lossPerMonth)
    return { новые, ушли }
  }, [было, now])
  const ряды: { label: string; cur: number | null; prev: number | null; деньги?: boolean }[] = было ? [
    { label: 'Станций в списке', cur: now.totals.rows, prev: было.totals.rows },
    { label: 'Никем не взято', cur: now.totals.notTaken, prev: было.totals.notTaken },
    { label: 'Срок заявки сорван', cur: now.totals.breached, prev: было.totals.breached },
    { label: 'Неисправен разъём', cur: now.totals.connector ?? 0, prev: было.totals.connector ?? 0 },
    { label: 'Поверка и ТО', cur: now.totals.meter + now.totals.service, prev: было.totals.meter + было.totals.service },
    { label: 'Цена бездействия, ₽/мес', cur: now.totals.lossPerMonth, prev: было.totals.lossPerMonth, деньги: true },
  ] : []
  const список = (title: string, rows: WorklistRow[]) => (
    <div>
      <h3 className="mb-1.5 text-sm font-semibold text-foreground">{title}: {nf.format(rows.length)}</h3>
      {!rows.length ? <p className="text-xs text-muted-foreground">Нет.</p> : (
        <ul className="flex flex-col divide-y divide-di-outline-variant/50">
          {rows.slice(0, 8).map((r) => (
            <li key={r.locationId} className="flex items-baseline justify-between gap-3 py-1.5 text-xs">
              <span className="min-w-0 truncate">
                <StationLink station={r.locationId}>{r.name}</StationLink>
                <span className="ml-1 text-muted-foreground">{СЛОВО_ПРИЧИНЫ[r.reasons[0]?.kind ?? ''] ?? ''}</span>
              </span>
              <span className="shrink-0 tabular-nums text-muted-foreground">{money(r.lossPerMonth)}</span>
            </li>
          ))}
          {rows.length > 8 && <li className="py-1.5 text-xs text-muted-foreground">и ещё {nf.format(rows.length - 8)}</li>}
        </ul>
      )}
    </div>
  )
  return (
    <>
      <p className="text-xs leading-relaxed text-muted-foreground">
        Тот же список на более ранний день: что прибавилось в работе и что из неё ушло. Регион отбора действует на оба среза,
        быстрые отборы и фильтры столбцов — нет.
      </p>
      <div className="flex gap-2">
        {[[1, 'С прошлым днём'], [7, 'С неделей назад']].map(([n, label]) => (
          <Button key={n} size="sm" variant={дней === n ? 'default' : 'outline'} disabled={!base}
            onClick={() => setДней(n as number)}>
            {label}
          </Button>
        ))}
      </div>
      {q.isFetching && <div className="flex justify-center py-4"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>}
      {q.isError && <p role="alert" className="text-sm font-medium text-red-700 dark:text-red-400">Список на {день} собрать не удалось.</p>}
      {было && !q.isFetching && разница && (
        <>
          <p className="text-xs text-di-on-surface-variant">
            Сейчас — {base.split('-').reverse().join('.')}, было — {день.split('-').reverse().join('.')}
          </p>
          <ul className="flex flex-col divide-y divide-di-outline-variant/50">
            {ряды.map((r) => {
              const дельта = r.cur != null && r.prev != null ? r.cur - r.prev : null
              const показ = (v: number | null) => (v == null ? '—' : r.деньги ? money(v) : nf.format(v))
              return (
                <li key={r.label} className="py-2 first:pt-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-sm text-di-on-surface-variant">{r.label}</span>
                    <span className={cn('whitespace-nowrap text-sm font-bold tabular-nums',
                      дельта && дельта > 0 ? 'text-red-700 dark:text-red-400' : дельта && дельта < 0 ? 'text-emerald-700 dark:text-emerald-400' : 'text-foreground')}>
                      {дельта == null ? '—' : `${дельта > 0 ? '+' : дельта < 0 ? '−' : ''}${показ(Math.abs(дельта))}`}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-baseline justify-between gap-3 text-xs text-muted-foreground">
                    <span>сейчас <span className="font-semibold text-foreground">{показ(r.cur)}</span></span>
                    <span>было {показ(r.prev)}</span>
                  </div>
                </li>
              )
            })}
          </ul>
          {было.workKnown === false && (
            <p className="text-xs text-muted-foreground">
              На прошлый день история заявок не восстанавливается, поэтому «никем не взято» там неизвестно.
            </p>
          )}
          {список('Появились в работе', разница.новые)}
          {список('Ушли из работы', разница.ушли)}
        </>
      )}
    </>
  )
}
