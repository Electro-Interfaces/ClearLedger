/**
 * «Бухгалтерия» → «Разбор»: обе стороны сопоставления в одной таблице.
 *
 * Строка — запись бухгалтерской выгрузки. Слева от карточки видно, что знает
 * бухгалтерия, справа — чем это легло в пространство и что именно сверено.
 *
 * Три признака держатся раздельно (канон сверки 28.10.2026): сопряжение опознаёт
 * запись, проверка касается перечня реквизитов, устаревание — следствие правки
 * карточки после сверки. Одной галочки «проверено» здесь нет и быть не должно.
 */
import { useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, ChevronDown, FileSpreadsheet, FileText, GitCompare, HelpCircle,
  Link2, Loader2, RefreshCcw, Unlink,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  PageSizeField, RelatedLink, RelatedReport, ReportTools, RowCard, SheetTable,
  TILE_ROW, Tile, ToolPanel, ToolStrip, qty, useReportKit, type Cell,
} from '@/components/report-kit'
import { ExportButton } from './analytics/ExportButton'
import { exportRows } from './analytics/exportRows'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import {
  MATCHING_LABEL, VERIFICATION_LABEL, recheckLine, полеRU, сравнение,
} from '@/lib/accountingMark'
import {
  getAccountingRecord, getAccountingSummary, getAllAccountingRecords,
  type AccountingLink, type AccountingRecord, type LinkStatus, type VerificationStatus,
} from '@/services/accountingSpaceService'

const С = {
  контрагент: 0, договор: 1, тип: 2, сопряжение: 3, проверка: 4, карточки: 5,
  расхождений: 6, площадок: 7, строки: 8, основание: 9, наДату: 10,
  станции: 11, кандидаты: 12, период: 13, файл: 14, лист: 15, партия: 16, обработка: 17,
}
const ШАПКА = ['Контрагент в бухгалтерии', 'Договор или основание', 'Тип по бухгалтерии',
  'Сопряжение', 'Проверка', 'Карточки в пространстве', 'Расхождений', 'Площадок',
  'Строки источника', 'Основание', 'Данные на дату', 'Номера ЭЗС из бухгалтерии',
  'Кандидаты в пространстве', 'Период источника', 'Файл источника', 'Лист', 'Партия',
  'Обработка']
const СКРЫТЫ = [С.станции, С.кандидаты, С.период, С.файл, С.лист, С.партия, С.обработка]
const ШИРИНЫ = { [С.контрагент]: 240, [С.договор]: 200, [С.тип]: 230, [С.сопряжение]: 150,
  [С.проверка]: 190, [С.карточки]: 240, [С.расхождений]: 110, [С.площадок]: 100,
  [С.строки]: 130, [С.основание]: 280 }
const КЛЮЧ_ФИЛЬТРОВ = 'report-kit.v1:filters-open:acct-review'

/** Отборы плиток: статус сопряжения или состояние проверки — разные оси. */
type Отбор = 'all' | LinkStatus | 'differences' | 'stale'
const ПОДПИСЬ: Record<Отбор, string> = {
  all: 'Все строки источника', ...MATCHING_LABEL,
  differences: 'Есть расхождения', stale: 'Нужна повторная сверка',
}
const СТАТУСЫ: LinkStatus[] = ['matched', 'related', 'unmatched', 'candidate']
const ПРОВЕРКИ: VerificationStatus[] = ['verified', 'partial', 'differences', 'not_checked', 'stale']
// Словарь подписей общий с отметкой в карточках и списках: расходиться им нельзя.
const ПРОВЕРКА_ПОДПИСЬ = VERIFICATION_LABEL

/** Подписи осей — из общего словаря; текст сервера остаётся запасным. */
const сопр = (r: { status: LinkStatus; status_label: string }) => MATCHING_LABEL[r.status] ?? r.status_label
const пров = (r: { verification: VerificationStatus; verification_label: string }) =>
  VERIFICATION_LABEL[r.verification] ?? r.verification_label

function строка(r: AccountingRecord): Cell[] {
  return [r.counterparty_name, r.contract_label, r.kind, сопр(r), пров(r),
    r.card_labels.join('; '), r.differences_count, r.location_ids.length, r.source_rows,
    r.reason, r.source_as_of ? дата(r.source_as_of) : '', r.station_hint, r.candidates,
    r.source_period, r.source_file, r.source_sheet, r.batch_id,
    r.entry_status + ' · ' + r.layer]
}
const дата = (iso: string) => {
  const d = new Date(iso.slice(0, 10) + 'T12:00:00Z')
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' })
}
function Поле({ id, label, children, className }: {
  id: string; label: string; children: ReactNode; className: string
}) {
  return <div className={cn('flex min-w-0 flex-col gap-1', className)}>
    <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{label}</label>{children}
  </div>
}

export function AccountingReviewPanel() {
  const { companyId } = useCompany()
  const экран = useRef<HTMLDivElement>(null)
  const [отбор, setОтбор] = useState<Отбор>('all')
  const [поиск, setПоиск] = useState('')
  const [проверка, setПроверка] = useState<'all' | VerificationStatus>('all')
  const [карточка, setКарточка] = useState<{ order: number[]; pos: number } | null>(null)
  const [разбор, setРазбор] = useState<'cards' | 'counterparty' | null>(null)
  const [порядок, setПорядок] = useState<number[]>([])
  const [фильтрыОткрыты, setФильтрыОткрыты] = useState(() => {
    try { return localStorage.getItem(КЛЮЧ_ФИЛЬТРОВ) === '1' } catch { return false }
  })

  const qСводка = useQuery({
    queryKey: ['acct-space-summary', companyId],
    queryFn: () => getAccountingSummary(companyId),
    enabled: !!companyId, staleTime: 60_000,
  })
  // Весь отбор целиком: плитки и таблица обязаны показывать одни и те же строки.
  const qСтроки = useQuery({
    queryKey: ['acct-space-records', companyId],
    queryFn: () => getAllAccountingRecords(companyId),
    enabled: !!companyId, staleTime: 60_000,
  })

  const все = qСтроки.data?.items ?? []
  const строки = useMemo(() => все.filter((r) => {
    if (СТАТУСЫ.includes(отбор as LinkStatus) && r.status !== отбор) return false
    if (отбор === 'differences' && !r.differences_count) return false
    if (отбор === 'stale' && !r.stale_count) return false
    if (проверка !== 'all' && r.verification !== проверка) return false
    if (!поиск.trim()) return true
    const игла = поиск.trim().toLowerCase()
    return [r.counterparty_name, r.contract_label, r.kind, r.reason, r.station_hint,
      ...r.card_labels].some((x) => (x || '').toLowerCase().includes(игла))
  }), [все, отбор, проверка, поиск])

  const ячейки = useMemo(() => строки.map(строка), [строки])
  const набор = useReportKit({
    id: 'acct-review.v1', title: 'Разбор бухгалтерии', head: ШАПКА, rows: ячейки,
    hide: СКРЫТЫ, ready: !!qСтроки.data, help: ПОМОЩЬ,
  })
  const видимые = useMemo(() => {
    const { cols, head } = набор.table
    return (cols.order.length === head.length ? cols.order : head.map((_, i) => i))
      .filter((i) => !cols.hidden.includes(i))
  }, [набор.table.cols, набор.table.head])

  const выбранная = карточка ? строки[карточка.order[карточка.pos]] : null
  const qКарточка = useQuery({
    queryKey: ['acct-space-record', companyId, выбранная?.id],
    queryFn: () => getAccountingRecord(companyId, выбранная!.id),
    enabled: !!companyId && !!выбранная, staleTime: 60_000,
  })

  if (qСтроки.isLoading || qСводка.isLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
  }
  if (qСтроки.isError || qСводка.isError) {
    return <div role="alert" className="flex flex-col items-center gap-3 p-8 text-sm text-muted-foreground">
      <p>Не удалось получить сведения бухгалтерии. Это ошибка получения данных, а не отсутствие записей.</p>
      <Button variant="outline" onClick={() => { void qСтроки.refetch(); void qСводка.refetch() }}
        disabled={qСтроки.isFetching}>Повторить загрузку</Button>
    </div>
  }
  const s = qСводка.data!
  const срез = s.as_of.length ? s.as_of.map(дата).join(', ') : 'дата данных не указана'
  const период = s.periods.length ? s.periods.join(', ') : 'период источника не указан'
  const подпись = 'Данные на ' + срез + ' · ' + период
  const отборов = (отбор !== 'all' ? 1 : 0) + (проверка !== 'all' ? 1 : 0)
    + (поиск.trim() ? 1 : 0) + Object.keys(набор.filters).length
  const переключить = (v: Отбор) => { setОтбор((было) => было === v ? 'all' : v); набор.setFilters({}) }
  const сброс = () => { setОтбор('all'); setПроверка('all'); setПоиск(''); набор.setFilters({}) }
  const фильтры = [отбор !== 'all' && ПОДПИСЬ[отбор],
    проверка !== 'all' && ПРОВЕРКА_ПОДПИСЬ[проверка],
    поиск.trim() && 'поиск «' + поиск.trim() + '»'].filter(Boolean) as string[]

  return <div ref={экран} className="flex flex-col gap-3 p-3">
    <div className={TILE_ROW}>
      <Tile icon={FileSpreadsheet} label="Строк источника" value={qty(s.source_rows)}
        hint={qty(s.counterparties_in_source) + ' контрагентов выгрузки'}
        active={отбор === 'all'} onClick={() => setОтбор('all')} />
      <Tile icon={Link2} label="Сопряжено" value={qty(s.by_status.matched ?? 0)}
        hint={qty(s.linked_contracts) + ' карточек договоров'}
        active={отбор === 'matched'} onClick={() => переключить('matched')} />
      <Tile icon={FileText} label="Связанные документы" value={qty(s.by_status.related ?? 0)}
        hint="соглашение к основному договору"
        active={отбор === 'related'} onClick={() => переключить('related')} />
      <Tile icon={Unlink} label="Не сопряжено" value={qty(s.by_status.unmatched ?? 0)}
        hint="очередь разбора" tone={(s.by_status.unmatched ?? 0) ? 'text-amber-600 dark:text-amber-400' : undefined}
        active={отбор === 'unmatched'} onClick={() => переключить('unmatched')} />
      <Tile icon={HelpCircle} label="Нужна проверка" value={qty(s.by_status.candidate ?? 0)}
        hint="кандидаты и неоднозначности"
        active={отбор === 'candidate'} onClick={() => переключить('candidate')} />
      <Tile icon={AlertTriangle} label="Есть расхождения" value={qty(s.differences)}
        hint="номер или дата расходятся с карточкой"
        tone={s.differences ? 'text-destructive' : undefined}
        active={отбор === 'differences'} onClick={() => переключить('differences')} />
      <Tile icon={RefreshCcw} label="Нужна повторная сверка" value={qty(s.stale)}
        hint="карточка менялась после проверки"
        active={отбор === 'stale'} onClick={() => переключить('stale')} />
    </div>
    <Card className="py-0"><CardContent className="flex flex-col gap-3 p-3">
      {фильтрыОткрыты && <div className="flex flex-wrap items-end gap-3">
        <Поле id="acct-search" label="Контрагент, договор или основание" className="w-72">
          <Input id="acct-search" value={поиск} onChange={(e) => setПоиск(e.target.value)}
            placeholder="Название, номер, предмет…" className="h-9" />
        </Поле>
        <Поле id="acct-verify" label="Проверка" className="w-56">
          <Select value={проверка} onValueChange={(v) => setПроверка(v as 'all' | VerificationStatus)}>
            <SelectTrigger id="acct-verify" className="h-9 w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Любая</SelectItem>
              {ПРОВЕРКИ.map((v) => <SelectItem key={v} value={v}>{ПРОВЕРКА_ПОДПИСЬ[v]}</SelectItem>)}
            </SelectContent>
          </Select>
        </Поле>
        <Поле id="acct-page" label="Строк на странице" className="w-32"><PageSizeField bare id="acct-page" /></Поле>
      </div>}
      <div className={cn('flex flex-wrap items-center justify-between gap-2', фильтрыОткрыты && 'border-t border-border/60 pt-3')}>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" aria-expanded={фильтрыОткрыты} onClick={() => {
            const next = !фильтрыОткрыты; setФильтрыОткрыты(next)
            try { localStorage.setItem(КЛЮЧ_ФИЛЬТРОВ, next ? '1' : '0') } catch { /* хранилище недоступно */ }
          }} className="inline-flex h-8 items-center gap-1.5 rounded-md px-1.5 text-sm font-semibold text-primary hover:bg-accent">
            <ChevronDown className={cn('size-4 transition-transform', фильтрыОткрыты && 'rotate-180')} />
            {фильтрыОткрыты ? 'Свернуть фильтры' : 'Фильтры'}
            {!фильтрыОткрыты && отборов > 0 && <span className="rounded-full bg-primary px-1.5 text-xs leading-5 text-primary-foreground">{отборов}</span>}
          </button>
          <span className="text-xs text-muted-foreground">строк: {qty(строки.length)} из {qty(все.length)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ExportButton title="Разбор бухгалтерии" subtitle={подпись} getEl={() => экран.current} />
          <Button size="sm" variant="outline" onClick={сброс} disabled={!отборов}>Сбросить фильтры</Button>
        </div>
      </div>
      <ToolStrip />
      <SheetTable {...набор.table} caption="Разбор бухгалтерии" lines={[подпись, ...фильтры]}
        defaultWidths={ШИРИНЫ} onView={setПорядок}
        rowTitle={(i) => строки[i] ? строки[i].counterparty_name + ' · ' + строки[i].contract_label : ''}
        onRow={(order, pos) => setКарточка({ order, pos })}
        render={(i, c) => {
          const r = строки[i]
          if (!r) return undefined
          if (c === С.сопряжение) return <span className={cn('whitespace-normal',
            r.status === 'unmatched' && 'text-amber-600 dark:text-amber-400',
            r.status === 'candidate' && 'font-medium')}>{сопр(r)}</span>
          if (c === С.проверка) return <span className={cn('whitespace-normal text-xs',
            r.verification === 'differences' && 'font-semibold text-destructive',
            r.verification === 'stale' && 'font-medium text-amber-600 dark:text-amber-400',
          )}>{пров(r)}</span>
          if (c === С.карточки) return <span className="block whitespace-normal break-words text-xs">
            {r.card_labels.length ? r.card_labels.join('; ') : '—'}</span>
          if (c === С.основание) return <span className="block whitespace-normal break-words text-xs">{r.reason || '—'}</span>
          if (c === С.станции && r.station_hint) return <span className="block whitespace-normal text-xs">
            {r.station_hint}<span className="ml-1 text-muted-foreground">(подсказка ВПР)</span></span>
          return undefined
        }}
        empty="По этому отбору строк нет. Это пустой отбор, а не отсутствие выгрузки — сбросьте фильтры."
        tableAttrs={exportRows('Разбор бухгалтерии', видимые.map((c) => набор.sheet.head[c]),
          порядок.map((i) => видимые.map((c) => набор.sheet.rows[i]?.[c] ?? '')))} />
    </CardContent></Card>
    <ToolPanel><ReportTools {...набор.tools} searchHint="Контрагент, договор, предмет или число"
      formulaExample="Например, Расхождений" compare={null} /></ToolPanel>
    <RowCard report="Разбор бухгалтерии" head={набор.sheet.head}
      title={выбранная ? выбранная.counterparty_name + ' · ' + выбранная.contract_label : undefined}
      row={карточка ? набор.sheet.rows[карточка.order[карточка.pos]] ?? null : null}
      at={карточка?.pos ?? 0} of={карточка?.order.length ?? 0}
      onStep={(dir) => setКарточка((v) => v ? { ...v, pos: Math.max(0, Math.min(v.pos + dir, v.order.length - 1)) } : v)}
      onClose={() => { setКарточка(null); setРазбор(null) }}
      extra={выбранная && <div className="flex flex-col gap-3">
        <Стороны card={qКарточка.data} loading={qКарточка.isLoading} error={qКарточка.isError}
          onRetry={() => void qКарточка.refetch()} />
        <div className="divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60">
          <RelatedLink label="Сопряжённые карточки пространства" icon={<Link2 className="size-4" />}
            hint="договор, контрагент, площадки и что сверено" onClick={() => setРазбор('cards')} />
          <RelatedLink label="Другие строки этого контрагента" icon={<GitCompare className="size-4" />}
            hint="вся выгрузка по тому же названию" onClick={() => setРазбор('counterparty')} />
        </div>
      </div>} />
    <RecordDrill kind={карточка ? разбор : null} record={выбранная} companyId={companyId}
      links={qКарточка.data?.links ?? []} onClose={() => setРазбор(null)} />
  </div>
}

/** Две стороны сопоставления: что знает бухгалтерия и что знаем мы. */
function Стороны({ card, loading, error, onRetry }: {
  card: Awaited<ReturnType<typeof getAccountingRecord>> | undefined
  loading: boolean; error: boolean; onRetry: () => void
}) {
  if (loading) return <div className="flex items-center gap-2 rounded-lg border border-border/60 p-3 text-sm text-muted-foreground">
    <Loader2 className="size-4 animate-spin" />Загружается сопоставление</div>
  if (error || !card) return <div role="alert" className="flex items-center gap-3 rounded-lg border border-border/60 p-3 text-sm">
    Не удалось получить сопоставление.<Button size="sm" variant="outline" onClick={onRetry}>Повторить</Button></div>
  const src = card.source_side
  return <div className="flex flex-col gap-3">
    {/* Контрагент, договор, период и файл уже стоят слева, в полях строки: здесь —
        только происхождение записи, которого в таблице нет. */}
    <section className="rounded-lg border border-border/60 p-3">
      <h3 className="mb-2 text-sm font-semibold">Происхождение записи</h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <Строчка label="Вид записи" value={src.record_kind === 'export_row'
          ? 'строка бухгалтерской выгрузки' : src.record_kind} />
        <Строчка label="SHA-256 файла" value={src.sha256 ? src.sha256.slice(0, 16) + '…' : ''} />
        <Строчка label="Ключ источника" value={src.key ? src.key.slice(0, 16) + '… · текстовый отпечаток, не GUID 1С' : ''} />
        <Строчка label="Проведён в 1С" value="неизвестно: выгрузка не содержит признака" />
        <Строчка label="Первичный документ" value="не предоставлен — наличие и подписание неизвестны" />
      </dl>
    </section>
    <section className="rounded-lg border border-border/60 p-3">
      <h3 className="mb-2 text-sm font-semibold">В пространстве</h3>
      {!card.links.length
        ? <p className="text-xs text-muted-foreground">
            Карточка пространства не назначена. {card.candidates && card.candidates !== 'Не найдены'
              ? 'Кандидаты: ' + card.candidates : 'Кандидаты не найдены.'}
          </p>
        : <div className="flex flex-col gap-3">{card.links.map((l) => <Связь key={l.entity_id + l.relation} link={l} />)}</div>}
    </section>
  </div>
}

function Строчка({ label, value }: { label: string; value: string | null | undefined }) {
  return <>
    <dt className="text-muted-foreground">{label}</dt>
    <dd className="min-w-0 break-words">{value || '—'}</dd>
  </>
}

/** Одна связь: карточка, тип связи, что сверено, где расходится. */
function Связь({ link }: { link: AccountingLink }) {
  const c = link.card
  return <div className="rounded-md border border-border/50 bg-muted/20 p-2.5">
    <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
      {c.exists ? <>№ {c.number || '—'} от {c.date || '—'}</> : <span className="text-destructive">карточка не найдена</span>}
      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-normal text-primary">{сопр(link)}</span>
      <span className={cn('rounded-full px-2 py-0.5 text-xs font-normal',
        link.verification === 'differences' ? 'bg-destructive/10 text-destructive'
          : link.stale ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
            : 'bg-muted text-muted-foreground')}>{пров(link)}</span>
    </div>
    <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      <Строчка label="Вид" value={c.type || c.type_code} />
      <Строчка label="Основание" value={c.basis} />
      <Строчка label="Контрагент" value={[c.counterparty_name, c.counterparty_inn && 'ИНН ' + c.counterparty_inn,
        c.counterparty_kpp && 'КПП ' + c.counterparty_kpp].filter(Boolean).join(' · ')} />
      <Строчка label="Площадки" value={(c.locations ?? []).map((l) => l.code || l.id).join(', ')} />
      <Строчка label="Тип связи" value={link.relation === 'same_contract' ? 'тот же договор' : link.relation} />
      <Строчка label="Предмет" value={link.subject_status} />
    </dl>
    {/* Доказательства сверки, а не снимок наших полей: снимок отвечает за
        устаревание, но сам по себе ничего не подтверждает. Сырые имена полей
        человеку не показываем — только русские подписи сервера. */}
    <div className="mt-1.5 text-xs">
      <span className="text-muted-foreground">Сверено с выгрузкой: </span>
      {(link.compared_fields ?? []).length
        ? <ul className="mt-0.5 flex flex-col gap-0.5">
            {link.compared_fields.map((f) => {
              const и = сравнение(f)
              return <li key={f.field} className={и.tone === 'bad' ? 'text-destructive' : undefined}>
                {полеRU(f)} — {и.text}
              </li>
            })}
          </ul>
        : <span>ничего — реквизиты не сверялись</span>}
    </div>
    {!!(link.unchecked_fields ?? []).length && <div className="mt-1 text-xs">
      <span className="text-muted-foreground">Не сверялись: </span>
      {link.unchecked_fields.map((f) => полеRU(f) + (f.reason ? ' (' + f.reason + ')' : '')).join('; ')}
    </div>}
    {!!recheckLine(link.recheck) && <p className="mt-1 text-xs text-muted-foreground">{recheckLine(link.recheck)}</p>}
    {link.stale && <p className="mt-1.5 text-xs text-amber-700 dark:text-amber-400">
      Карточка менялась после сверки — проверку нужно повторить
      (хеш сверенных значений {link.checked_hash.slice(0, 8)}… → {link.current_hash.slice(0, 8)}…).
    </p>}
    {!!link.differences.length && <ul className="mt-1.5 flex flex-col gap-1 text-xs">
      {link.differences.map((d) => <li key={d.field} className="text-destructive">
        {d.label}: в бухгалтерии «{d.source}», в пространстве «{d.space || '—'}»
      </li>)}
    </ul>}
  </div>
}

/** Расшифровка значений строки окном поверх карточки. */
function RecordDrill({ kind, record, companyId, links, onClose }: {
  kind: 'cards' | 'counterparty' | null
  record: AccountingRecord | null
  companyId: string
  links: AccountingLink[]
  onClose: () => void
}) {
  const q = useQuery({
    queryKey: ['acct-space-records', companyId, 'cp', record?.counterparty_name],
    queryFn: () => getAllAccountingRecords(companyId, { search: record!.counterparty_name }),
    enabled: kind === 'counterparty' && !!companyId && !!record?.counterparty_name, staleTime: 60_000,
  })
  if (kind === 'cards') {
    const head = ['Номер', 'Дата', 'Вид', 'Контрагент', 'ИНН', 'Площадки', 'Связь', 'Проверка', 'Расхождения']
    const rows: Cell[][] = links.map((l) => [
      l.card.number ?? '', l.card.date ?? '', l.card.type ?? l.card.type_code ?? '',
      l.card.counterparty_name ?? '', l.card.counterparty_inn ?? '',
      (l.card.locations ?? []).map((x) => x.code || x.id).join(', '),
      сопр(l), пров(l),
      l.differences.map((d) => d.label + ': ' + d.source + ' / ' + (d.space || '—')).join('; '),
    ])
    return <RelatedReport open={!!kind} title="Сопряжённые карточки пространства"
      subtitle={record ? record.counterparty_name + ' · ' + record.contract_label : ''}
      head={head} rows={rows} onClose={onClose}
      note={rows.length ? undefined : 'Карточки не назначены: эта строка источника пока не сопряжена.'} />
  }
  const head = ['Договор или основание', 'Предмет / тип', 'Сопряжение', 'Проверка',
    'Карточки', 'Строки источника', 'Файл']
  const items = q.data?.items.filter((r) => r.counterparty_name === record?.counterparty_name) ?? []
  const rows: Cell[][] = items.map((r) => [r.contract_label, r.kind, сопр(r),
    пров(r), r.card_labels.join('; '), r.source_rows, r.source_file])
  return <RelatedReport open={kind === 'counterparty'} title="Другие строки этого контрагента"
    subtitle={record?.counterparty_name} head={head} rows={rows}
    loading={q.isLoading} error={q.isError} onClose={onClose} />
}

const ПОМОЩЬ = <div className="flex flex-col gap-3 text-sm leading-relaxed text-muted-foreground">
  <p>«Разбор» показывает строки бухгалтерской выгрузки и то, чем они легли в пространство.
    Строка источника — не карточка договора: она остаётся сведением из отчёта бухгалтерии
    со своим файлом, листом и номерами строк.</p>
  <p>Плитки отбирают список и считаются из того же набора, что таблица. Первые пять — ось
    сопряжения: опознана запись или нет. Последние две — ось проверки: расхождения
    реквизитов и устаревшая сверка. Это разные признаки: сопряжение не означает,
    что реквизиты сверены.</p>
  <p>«Нужна повторная сверка» появляется сама: при сверке запоминается хеш проверенных
    значений карточки (номер, дата, контрагент, вид), и если карточку позже правили,
    проверка считается устаревшей. Правка непроверявшегося поля сверку не сбрасывает.</p>
  <p>«Есть расхождения» — номер или дата источника отличаются от карточки. Мелкая разница
    в записи номера расхождением не считается: сравниваются значимые знаки. Пустое значение
    в выгрузке — отсутствие сведений, а не конфликт.</p>
  <p>«Номера ЭЗС из бухгалтерии» — подсказка ВПР с листа «База», а не доказанная область
    договора. Площадки в карточке — связи пространства.</p>
  <p>Выгрузка охватывает расчёты за указанный период. Договор пространства без строки
    источника не значит, что его нет в бухгалтерии: вне периметра выгрузки сведений
    для сравнения нет.</p>
  <p>Карточка строки открывает обе стороны: слева поля строки, справа «В бухгалтерии» и
    «В пространстве» со сверенными полями и расхождениями. Расшифровки открываются окном
    поверх карточки, закрыл — остался на той же строке. Признака проведения документа
    в 1С выгрузка не содержит, поэтому он показан неизвестным.</p>
  <p>Правок здесь нет: срез только читает. Решения менеджера (связать, подтвердить поля,
    отметить неприменимость) — следующий этап приложения.</p>
</div>
