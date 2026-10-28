/**
 * «Бухгалтерия» пространства: разделы «Объекты» и «Источники».
 *
 * «Объекты» отвечают на вопрос «чем обоснована площадка»: аренда земли и получение
 * электроэнергии — первый предметный контур. Техприсоединение сюда не приравнивается:
 * это отдельное основание, и текущего снабжения оно не доказывает.
 *
 * «Источники» — журнал того, из чего собраны сведения: файл, партия, период, SHA-256.
 * Дата формирования выгрузки в 1С неизвестна и не выдумывается: «данные на 30.09»
 * говорит о дате данных, а не о дате выгрузки.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Building2, FileSpreadsheet, Fuel, Landmark, Loader2, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  RelatedLink, RelatedReport, ReportTools, RowCard, SheetTable, TILE_ROW, Tile,
  ToolPanel, ToolStrip, qty, useReportKit, type Cell,
} from '@/components/report-kit'
import { ExportButton } from './analytics/ExportButton'
import { exportRows } from './analytics/exportRows'
import { useCompany } from '@/contexts/CompanyContext'
import { MARK_LABEL, MATCHING_LABEL, дата, type MarkState } from '@/lib/accountingMark'
import { AccountingMark } from '@/components/reference/AccountingMark'
import { useAccountingMarks } from '@/hooks/useAccountingMarks'
import {
  getAccountingObjects, getAccountingSources, getAccountingSummary,
  type AccountingObject, type AccountingObjectContract,
} from '@/services/accountingSpaceService'

function Загрузка() {
  return <div className="flex justify-center py-12"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
}
function Ошибка({ text, onRetry, busy }: { text: string; onRetry: () => void; busy: boolean }) {
  return <div role="alert" className="flex flex-col items-center gap-3 p-8 text-sm text-muted-foreground">
    <p>{text}</p>
    <Button variant="outline" onClick={onRetry} disabled={busy}>Повторить загрузку</Button>
  </div>
}

// ── Объекты ──────────────────────────────────────────────────────────────────

const О = { код: 0, площадка: 1, адрес: 2, договоров: 3, аренда: 4, энергия: 5,
  сИсточником: 6, безИсточника: 7, непроверено: 8, сверка: 9, состояние: 10 }
const О_ШАПКА = ['Код', 'Площадка', 'Адрес', 'Договоров', 'Аренда земли',
  'Получение э/э', 'Со сведениями бухгалтерии', 'Без сведений', 'Непроверенных',
  'Сверка с бухгалтерией', 'Состояние']
const О_СКРЫТЫ = [О.состояние]
const О_ШИРИНЫ = { [О.код]: 120, [О.площадка]: 260, [О.адрес]: 300, [О.договоров]: 110,
  [О.аренда]: 120, [О.энергия]: 130, [О.сИсточником]: 200, [О.безИсточника]: 130,
  [О.непроверено]: 130, [О.сверка]: 230 }

export function AccountingObjectsPanel() {
  const { companyId } = useCompany()
  const экран = useRef<HTMLDivElement>(null)
  const [поиск, setПоиск] = useState('')
  const [толькоПробелы, setТолькоПробелы] = useState(false)
  const [карточка, setКарточка] = useState<{ order: number[]; pos: number } | null>(null)
  const [разбор, setРазбор] = useState<'rent' | 'energy' | null>(null)
  const [порядок, setПорядок] = useState<number[]>([])

  const q = useQuery({
    queryKey: ['acct-space-objects', companyId],
    queryFn: () => getAccountingObjects(companyId),
    enabled: !!companyId, staleTime: 60_000,
  })
  const все = q.data?.items ?? []
  const строки = useMemo(() => все.filter((o) => {
    if (толькоПробелы && !o.unchecked && !o.without_source) return false
    const игла = поиск.trim().toLowerCase()
    return !игла || [o.code, o.name, o.address].some((x) => (x || '').toLowerCase().includes(игла))
  }), [все, поиск, толькоПробелы])
  // Общая отметка сверки площадок — одной сводкой на отбор, не запросом на строку.
  const отметки = useAccountingMarks('location', useMemo(() => строки.map((o) => o.id), [строки]))
  const ячейки = useMemo<Cell[][]>(() => строки.map((o) => [
    o.code, o.name, o.address, o.contracts_count,
    o.has_rent ? 'есть' : 'нет', o.has_energy ? 'есть' : 'нет',
    o.with_source, o.without_source, o.unchecked,
    MARK_LABEL[отметки.state(o.id) as MarkState], o.status,
  ]), [строки, отметки])
  const набор = useReportKit({ id: 'acct-objects.v2', title: 'Объекты и основания',
    head: О_ШАПКА, rows: ячейки, hide: О_СКРЫТЫ, ready: !!q.data, help: О_ПОМОЩЬ })
  const видимые = useMemo(() => {
    const { cols, head } = набор.table
    return (cols.order.length === head.length ? cols.order : head.map((_, i) => i))
      .filter((i) => !cols.hidden.includes(i))
  }, [набор.table.cols, набор.table.head])

  if (q.isLoading) return <Загрузка />
  if (q.isError) return <Ошибка text="Не удалось получить основания площадок." onRetry={() => void q.refetch()} busy={q.isFetching} />
  const выбранный = карточка ? строки[карточка.order[карточка.pos]] : null
  const сАрендой = все.filter((o) => o.has_rent).length
  const сЭнергией = все.filter((o) => o.has_energy).length
  // Число плитки обязано совпадать с её отбором: площадка попадает сюда и когда
  // основание осталось без сведений бухгалтерии, и когда сверка не доведена.
  const естьРазобрать = все.filter((o) => o.unchecked > 0 || o.without_source > 0).length
  return <div ref={экран} className="flex flex-col gap-3 p-3">
    <div className={TILE_ROW}>
      <Tile icon={Building2} label="Площадок с договорами" value={qty(все.length)}
        hint="в выборке только площадки со связанными договорами"
        active={!толькоПробелы} onClick={() => setТолькоПробелы(false)} />
      <Tile icon={Landmark} label="С арендой земли" value={qty(сАрендой)} hint="вид договора «аренда»" />
      <Tile icon={Zap} label="С получением э/э" value={qty(сЭнергией)} hint="вид «энергоснабжение»" />
      <Tile icon={Fuel} label="Есть что разобрать" value={qty(естьРазобрать)}
        hint="основания без сведений бухгалтерии или непроверенные"
        active={толькоПробелы} onClick={() => setТолькоПробелы((v) => !v)} />
    </div>
    <Card className="py-0"><CardContent className="flex flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Input value={поиск} onChange={(e) => setПоиск(e.target.value)} aria-label="Код, площадка или адрес"
          placeholder="Код, площадка или адрес…" className="h-9 w-72" />
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">площадок: {qty(строки.length)} из {qty(все.length)}</span>
          <ExportButton title="Объекты и основания" subtitle="аренда земли и получение электроэнергии" getEl={() => экран.current} />
        </div>
      </div>
      <ToolStrip />
      <SheetTable {...набор.table} caption="Объекты и основания"
        lines={['аренда земли и получение электроэнергии', 'техприсоединение — отдельное основание',
          'сверка площадки собрана из её договоров и проверкой самого объекта не является']}
        defaultWidths={О_ШИРИНЫ} onView={setПорядок}
        rowTitle={(i) => строки[i] ? строки[i].code + ' · ' + строки[i].name : ''}
        onRow={(order, pos) => setКарточка({ order, pos })}
        render={(i, c) => {
          const o = строки[i]
          if (!o) return undefined
          if (c === О.сверка) return <AccountingMark state={отметки.state(o.id)}
            summary={отметки.summary(o.id)} />
          if (c === О.аренда || c === О.энергия) {
            const есть = c === О.аренда ? o.has_rent : o.has_energy
            return <span className={есть ? '' : 'text-muted-foreground'}>{есть ? 'есть' : 'нет'}</span>
          }
          if (c === О.адрес) return <span className="block whitespace-normal break-words text-xs">{o.address || '—'}</span>
          return undefined
        }}
        empty="По этому отбору площадок нет. Площадки без связанных договоров в отчёт не попадают."
        tableAttrs={exportRows('Объекты и основания', видимые.map((c) => набор.sheet.head[c]),
          порядок.map((i) => видимые.map((c) => набор.sheet.rows[i]?.[c] ?? '')))} />
    </CardContent></Card>
    <ToolPanel><ReportTools {...набор.tools} searchHint="Код, площадка, адрес или число"
      formulaExample="Например, Непроверенных" compare={null} /></ToolPanel>
    <RowCard report="Объекты и основания" head={набор.sheet.head}
      title={выбранный ? выбранный.code + ' · ' + выбранный.name : undefined}
      row={карточка ? набор.sheet.rows[карточка.order[карточка.pos]] ?? null : null}
      at={карточка?.pos ?? 0} of={карточка?.order.length ?? 0}
      onStep={(dir) => setКарточка((v) => v ? { ...v, pos: Math.max(0, Math.min(v.pos + dir, v.order.length - 1)) } : v)}
      onClose={() => { setКарточка(null); setРазбор(null) }}
      extra={выбранный && <div className="flex flex-col gap-3">
        <Основания title="Аренда земли" items={выбранный.rent} />
        <Основания title="Получение электроэнергии" items={выбранный.energy} />
        {!!выбранный.other.length && <Основания title="Другие договоры площадки" items={выбранный.other} />}
        <div className="divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60">
          <RelatedLink label="Строки бухгалтерии по аренде" hint="источник, статусы и расхождения"
            onClick={() => setРазбор('rent')} />
          <RelatedLink label="Строки бухгалтерии по электроэнергии" hint="источник, статусы и расхождения"
            onClick={() => setРазбор('energy')} />
        </div>
      </div>} />
    <ОбъектРасшифровка kind={карточка ? разбор : null} object={выбранный} onClose={() => setРазбор(null)} />
  </div>
}

function Основания({ title, items }: { title: string; items: AccountingObjectContract[] }) {
  return <section className="rounded-lg border border-border/60 p-3">
    <h3 className="mb-2 text-sm font-semibold">{title}</h3>
    {!items.length
      ? <p className="text-xs text-muted-foreground">Основания этого вида у площадки не заведены.</p>
      : <div className="flex flex-col gap-2">{items.map((i) => <div key={i.contract.id}
          className="rounded-md border border-border/50 bg-muted/20 p-2.5 text-xs">
          <div className="text-sm font-medium">№ {i.contract.number || '—'} от {i.contract.date || '—'}</div>
          <div className="text-muted-foreground">{i.contract.counterparty_name || 'контрагент не указан'}
            {i.contract.basis ? ' · ' + i.contract.basis : ''}</div>
          {i.source.length
            ? <ul className="mt-1.5 flex flex-col gap-1">{i.source.map((s) => <li key={s.record_id}>
                {MATCHING_LABEL[s.status] ?? s.status_label} · {s.file || 'файл не указан'}
                {s.rows ? ' · строки ' + s.rows : ''}
                {s.as_of ? ' · данные на ' + дата(s.as_of) : ''}
              </li>)}</ul>
            : <p className="mt-1.5 text-muted-foreground">Сведений бухгалтерии нет: в периметр выгрузки
                этот договор не попал, сравнивать нечего.</p>}
        </div>)}</div>}
  </section>
}

function ОбъектРасшифровка({ kind, object, onClose }: {
  kind: 'rent' | 'energy' | null; object: AccountingObject | null; onClose: () => void
}) {
  const items = kind === 'rent' ? object?.rent ?? [] : kind === 'energy' ? object?.energy ?? [] : []
  const head = ['Договор', 'Контрагент в бухгалтерии', 'Строка источника', 'Сопряжение', 'Файл', 'Строки', 'Данные на дату']
  const rows: Cell[][] = items.flatMap((i) => i.source.length
    ? i.source.map((s) => ['№ ' + (i.contract.number || '—') + ' от ' + (i.contract.date || '—'),
        s.counterparty, s.contract_label, MATCHING_LABEL[s.status] ?? s.status_label,
        s.file, s.rows, дата(s.as_of)])
    : [['№ ' + (i.contract.number || '—') + ' от ' + (i.contract.date || '—'),
        '', 'нет сведений для сравнения', '', '', '', '']])
  return <RelatedReport open={!!kind && !!object}
    title={kind === 'rent' ? 'Аренда земли: строки бухгалтерии' : 'Электроэнергия: строки бухгалтерии'}
    subtitle={object ? object.code + ' · ' + object.name : ''} head={head} rows={rows} onClose={onClose}
    note={rows.length ? undefined : 'Оснований этого вида у площадки нет.'} />
}

const О_ПОМОЩЬ = <div className="flex flex-col gap-3 text-sm leading-relaxed text-muted-foreground">
  <p>Отчёт отвечает на вопрос «чем обоснована площадка»: аренда земли и получение
    электроэнергии. Техприсоединение — отдельное основание и текущего снабжения не доказывает.</p>
  <p>В отчёт попадают площадки со связанными договорами пространства. «Со сведениями
    бухгалтерии» — у скольких оснований есть строка выгрузки. «Без сведений» — не ошибка:
    выгрузка ограничена периодом, и сравнивать для таких договоров нечего.</p>
  <p>«Непроверенных» считает основания, где сверка не проводилась, устарела или дала
    расхождения. Площадка не наследует проверку своего договора: сопряжён договор —
    это ещё не проверенная площадка.</p>
  <p>«Сверка с бухгалтерией» — та же отметка, что в карточках договоров и контрагентов:
    «Сверенные реквизиты совпадают», «Есть расхождения», «Нужна повторная сверка»,
    «Требует сверки» или «Нет данных для сравнения». Сверено означает конкретные поля
    (номер, дата, контрагент, вид), а не все реквизиты договора. У площадки отметка
    собрана из её договоров и проверкой самого объекта не является.</p>
  <p>Карточка площадки показывает основания по видам и источник каждого.
    Расшифровки открываются окном поверх карточки.</p>
</div>

// ── Источники ────────────────────────────────────────────────────────────────

const И_ШАПКА = ['Файл', 'Лист', 'Партия', 'Период источника', 'Данные на дату', 'Строк',
  'Сопряжено', 'Связанные', 'Не сопряжено', 'Нужна проверка', 'Загружено', 'Выгружено из 1С',
  'SHA-256 файла', 'Тип ключа источника']
const И_ШИРИНЫ = { 0: 320, 1: 100, 2: 330, 3: 180, 4: 140, 5: 90, 6: 110, 7: 110, 8: 130,
  9: 140, 10: 130, 11: 150, 12: 180, 13: 220 }

export function AccountingSourcesPanel() {
  const { companyId } = useCompany()
  const экран = useRef<HTMLDivElement>(null)
  const [порядок, setПорядок] = useState<number[]>([])
  const q = useQuery({
    queryKey: ['acct-space-sources', companyId],
    queryFn: () => getAccountingSources(companyId),
    enabled: !!companyId, staleTime: 60_000,
  })
  const qСводка = useQuery({
    queryKey: ['acct-space-summary', companyId],
    queryFn: () => getAccountingSummary(companyId),
    enabled: !!companyId, staleTime: 60_000,
  })
  const items = q.data?.items ?? []
  const ячейки = useMemo<Cell[][]>(() => items.map((b) => [
    b.file, b.sheet, b.batch_id, b.period, дата(b.as_of), b.rows,
    b.by_status.matched ?? 0, b.by_status.related ?? 0, b.by_status.unmatched ?? 0,
    b.by_status.candidate ?? 0, дата(b.loaded_at), b.exported_at ? дата(b.exported_at) : '',
    b.sha256 ? b.sha256.slice(0, 16) + '…' : '',
    b.key_type === 'text_fingerprint_not_1c_guid' ? 'текстовый отпечаток, не GUID 1С' : b.key_type,
  ]), [items])
  const набор = useReportKit({ id: 'acct-sources.v1', title: 'Источники сведений',
    head: И_ШАПКА, rows: ячейки, ready: !!q.data, help: И_ПОМОЩЬ })
  const видимые = useMemo(() => {
    const { cols, head } = набор.table
    return (cols.order.length === head.length ? cols.order : head.map((_, i) => i))
      .filter((i) => !cols.hidden.includes(i))
  }, [набор.table.cols, набор.table.head])
  if (q.isLoading) return <Загрузка />
  if (q.isError) return <Ошибка text="Не удалось получить журнал источников." onRetry={() => void q.refetch()} busy={q.isFetching} />
  const s = qСводка.data
  return <div ref={экран} className="flex flex-col gap-3 p-3">
    <div className={TILE_ROW}>
      <Tile icon={FileSpreadsheet} label="Партий загружено" value={qty(items.length)}
        hint="файл · лист · период" />
      <Tile icon={FileSpreadsheet} label="Строк в пространстве" value={qty(items.reduce((n, b) => n + b.rows, 0))}
        hint="принятые строки выгрузки" />
      <Tile icon={Building2} label="Договоров пространства" value={qty(s?.space.contracts ?? 0)}
        hint={s ? qty(s.space.contracts_without_source) + ' без строки источника' : 'загружается'}
        disabled={!s} />
      <Tile icon={Landmark} label="Карточек сопряжено" value={qty(s?.linked_contracts ?? 0)}
        hint={s ? qty(s.missing_cards) + ' связей без карточки' : 'загружается'} disabled={!s} />
    </div>
    <Card className="py-0"><CardContent className="flex flex-col gap-3 p-3">
      <p className="text-xs text-muted-foreground">{q.data?.scope}</p>
      <div className="flex justify-end">
        <ExportButton title="Источники сведений" subtitle="партии выгрузок бухгалтерии" getEl={() => экран.current} />
      </div>
      <ToolStrip />
      <SheetTable {...набор.table} caption="Источники сведений" defaultWidths={И_ШИРИНЫ} onView={setПорядок}
        lines={['дата выгрузки из 1С источником не сообщается — столбец пуст намеренно']}
        empty="Партий выгрузок в пространстве нет."
        tableAttrs={exportRows('Источники сведений', видимые.map((c) => набор.sheet.head[c]),
          порядок.map((i) => видимые.map((c) => набор.sheet.rows[i]?.[c] ?? '')))} />
    </CardContent></Card>
    <ToolPanel><ReportTools {...набор.tools} searchHint="Файл, партия или число"
      formulaExample="Например, Строк" compare={null} /></ToolPanel>
  </div>
}

const И_ПОМОЩЬ = <div className="flex flex-col gap-3 text-sm leading-relaxed text-muted-foreground">
  <p>Журнал показывает, из чего собраны сведения бухгалтерии: файл, лист, партия загрузки,
    период данных и SHA-256 исходного файла. Одна партия — один заход загрузки.</p>
  <p>«Данные на дату» — дата, по состоянию на которую собран отчёт. «Выгружено из 1С» пусто:
    файл такой даты не содержит, и подставлять её нельзя.</p>
  <p>Ключ источника — текстовый отпечаток строки, а не GUID 1С. Он устойчив для повторной
    загрузки того же файла, но не является идентификатором объекта учёта.</p>
  <p>«Договоров пространства» и «без строки источника» показаны рядом намеренно: выгрузка
    покрывает только свой период, поэтому отсутствие строки не означает отсутствия договора
    в бухгалтерии.</p>
</div>
