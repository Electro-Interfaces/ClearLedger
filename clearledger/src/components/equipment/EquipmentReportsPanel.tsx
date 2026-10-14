/**
 * «Отчёты» складского учёта оборудования: остатки на дату, оборотная ведомость,
 * что числится за контрагентом, единицы в ремонте.
 *
 * Всё считается сервером из журнала движений, поэтому отвечает и на вопросы
 * задним числом («что лежало у хранителя на 30 сентября»). Единицы без истории
 * движений показываются по текущему состоянию и помечены — их на любую дату
 * видно там, где они числятся сегодня.
 *
 * Раздел ведёт складские предметы: станция, введённая в эксплуатацию, со
 * складского учёта выбыла и в остатки не входит — она показана одним числом.
 */
import { useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ViewParamsBar } from '@/components/workspace/ViewParamsBar'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { loadLocations } from '@/services/locationService'
import {
  getHoldersReport, getRepairsReport, getStockReport, getTurnoverReport,
  type ReportUnitRow, type TurnoverFigures,
} from '@/services/equipmentService'
import { formatDate } from '@/lib/formatDate'
import { eqName } from './equipmentDocPrint'

const REPORTS = [
  { k: 'stock', label: 'Остатки на дату' },
  { k: 'turnover', label: 'Оборотная ведомость' },
  { k: 'holders', label: 'За контрагентом' },
  { k: 'repairs', label: 'В ремонте' },
] as const

type Cell = string | number | null
const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const today = () => new Date().toISOString().slice(0, 10)
const day = (iso: string | null) => (iso ? formatDate(iso) : null)
const selectClass = 'h-8 max-w-[240px] rounded-md border bg-background px-2 text-xs max-sm:h-10'
const sum = <T,>(rows: T[], f: (r: T) => number) => rows.reduce((n, r) => n + f(r), 0)
const byOp = (ops: TurnoverFigures['incomeByOp']) => ops.map((o) => `${o.label} ${nf.format(o.qty)}`).join(', ') || null

/** Таблица отчёта: то, что на экране, тем же составом уходит в Excel. */
function Table({ name, cols, rows, foot, warn, empty = 'Нет данных' }: {
  name: string; cols: string[]; rows: Cell[][]; foot?: Cell[]; warn?: boolean[]; empty?: string
}) {
  const cell = (v: Cell, i: number, bold?: boolean) => (
    <td key={i} className={`p-2 ${typeof v === 'number' ? 'text-right tabular-nums whitespace-nowrap' : ''} ${bold ? 'font-semibold' : ''}`}>
      {v === null || v === '' ? <span className="text-muted-foreground/40">—</span> : typeof v === 'number' ? nf.format(v) : v}
    </td>
  )
  return (
    <Card>
      <CardContent className="p-0">
        <h3 className="px-3 py-2 text-sm font-semibold">{name} <span className="font-normal text-muted-foreground">· {nf.format(rows.length)}</span></h3>
        {rows.length === 0 ? <p className="px-3 pb-3 text-sm text-muted-foreground">{empty}</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs" {...exportRows(name, cols, foot ? [...rows, foot] : rows)}>
              <thead>
                <tr className="border-y bg-muted/40 text-left text-muted-foreground">
                  {cols.map((c, i) => <th key={c} className={`p-2 font-medium ${typeof rows[0][i] === 'number' ? 'text-right' : ''}`}>{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, n) => (
                  <tr key={n} className={`border-b border-border/30 ${warn?.[n] ? 'text-amber-700 dark:text-amber-400' : ''}`}>{r.map((v, i) => cell(v, i))}</tr>
                ))}
              </tbody>
              {foot && <tfoot><tr className="bg-muted/30">{foot.map((v, i) => cell(v, i, true))}</tr></tfoot>}
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{label}:{children}</label>
}

function DateField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <Field label={label}>
      <Input type="date" value={value} onChange={(e) => e.target.value && onChange(e.target.value)} className="h-8 w-[140px] text-xs max-sm:h-10" />
    </Field>
  )
}

function Pick({ label, all, value, onChange, opts }: {
  label: string; all: string; value: string; onChange: (v: string) => void; opts: { id: string; name: string }[]
}) {
  return (
    <Field label={label}>
      <select aria-label={label} className={selectClass} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{all}</option>
        {opts.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
      </select>
    </Field>
  )
}

/** Загрузка и ошибка отчёта: ошибка — это ошибка, а не пустой список. */
function Pending({ q }: { q: { isError: boolean; error: unknown } }) {
  return q.isError
    ? <p role="alert" className="text-sm text-destructive">Отчёт не загрузился{q.error instanceof Error ? `: ${q.error.message}` : ''}</p>
    : <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}

function Note({ children }: { children: ReactNode }) {
  return <p className="text-xs text-muted-foreground">{children}</p>
}

const SPARE_NOTE = 'Есть корректировки ЗИП без величины изменения — в расчёт они не вошли, остаток может отличаться от карточки склада.'
const UNIT_COLS = ['Серийный №', 'Инв. №', 'Оборудование', 'Состояние', 'Где', 'С даты', 'Документ', 'Контрагент', 'История движений']
const unitCells = (u: ReportUnitRow): Cell[] => [
  u.serialNumber, u.inventoryNumber, eqName(u.vendor, u.model) || null, u.stateLabel, u.place, day(u.since),
  u.docNumber ?? u.basis, u.counterpartyName, u.noHistory ? 'нет' : null,
]

type Params = { date: string; dateFrom: string; dateTo: string; locationId: string; counterpartyId: string }
type ReportProps = { companyId: string; f: Params; patch: (p: Partial<Params>) => void; warehouses: { id: string; name: string }[]; bar: (params: ReactNode, subtitle: string) => ReactNode }

function StockReportView({ companyId, f, patch, warehouses, bar }: ReportProps) {
  const q = useQuery({
    queryKey: ['eq-report-stock', companyId, f.date, f.locationId, f.counterpartyId],
    queryFn: () => getStockReport({ companyId, date: f.date, locationId: f.locationId || undefined, counterpartyId: f.counterpartyId || undefined }),
  })
  const d = q.data
  // Остаток — то, что на складском учёте: на складах, в монтаже, в ремонте.
  // Возвращённое производителю и списанное выбыло — показано справочно.
  const kept = (d?.groups ?? []).filter((g) => g.section !== 'gone')
  const gone = (d?.groups ?? []).filter((g) => g.section === 'gone')
  const isGone = (u: ReportUnitRow) => u.placeKind === 'vendor' || u.placeKind === 'written_off'
  return <>
    {bar(<>
      <DateField label="На дату" value={f.date} onChange={(v) => patch({ date: v })} />
      <Pick label="Склад" all="Все" value={f.locationId} onChange={(v) => patch({ locationId: v })} opts={warehouses} />
      <Pick label="Контрагент" all="Все" value={f.counterpartyId} onChange={(v) => patch({ counterpartyId: v })} opts={d?.counterparties ?? []} />
    </>, `на ${formatDate(f.date)}`)}
    {!d ? <Pending q={q} /> : <>
      <Table name="Остатки"
        cols={['Где', ...d.states.map((s) => s.label), 'Всего', 'Без истории движений']}
        rows={kept.map((g) => [g.name, ...d.states.map((s) => g.byState[s.key] ?? 0), g.total, g.noHistory])}
        foot={['Итого', ...d.states.map((s) => sum(kept, (g) => g.byState[s.key] ?? 0)), d.total, d.noHistory]}
        empty="На эту дату единиц по отбору нет" />
      {d.noHistory > 0 && <Note>Без истории движений: {nf.format(d.noHistory)} из {nf.format(d.total)}. Такие единицы показаны там, где числятся сегодня, — где они были на выбранную дату, учёт не знает.</Note>}
      <Table name="Единицы" cols={UNIT_COLS} rows={d.units.filter((u) => !isGone(u)).map(unitCells)} empty="На эту дату единиц по отбору нет" />
      <Table name="Справочно: выбыло со складского учёта" cols={['Куда', 'Единиц']}
        rows={[['Передано в эксплуатацию', d.inOperation], ...gone.map((g): Cell[] => [g.name, g.total])]} />
      <Table name="Возвращено производителю и списано" cols={UNIT_COLS} rows={d.units.filter(isGone).map(unitCells)} empty="Таких единиц нет" />
      <Table name="ЗИП" cols={['Склад', 'Номенклатура', 'Артикул', 'Остаток', 'Ед.']}
        rows={d.spares.map((s) => [s.location, s.name, s.article, s.qty, s.unitLabel])} empty="Остатков ЗИП на эту дату нет" />
      {d.spareCorrectionsUnknown > 0 && <Note>{SPARE_NOTE}</Note>}
    </>}
  </>
}

function TurnoverReportView({ companyId, f, patch, warehouses, bar }: ReportProps) {
  const q = useQuery({
    queryKey: ['eq-report-turnover', companyId, f.dateFrom, f.dateTo, f.locationId],
    queryFn: () => getTurnoverReport({ companyId, dateFrom: f.dateFrom, dateTo: f.dateTo, locationId: f.locationId || undefined }),
  })
  const d = q.data
  const figures = (t: TurnoverFigures): Cell[] => [t.opening, t.income, t.outcome, t.closing, byOp(t.incomeByOp), byOp(t.outcomeByOp)]
  const cols = ['Начальный остаток', 'Приход', 'Расход', 'Конечный остаток', 'Приход по операциям', 'Расход по операциям']
  return <>
    {bar(<>
      <DateField label="Период с" value={f.dateFrom} onChange={(v) => patch({ dateFrom: v })} />
      <DateField label="по" value={f.dateTo} onChange={(v) => patch({ dateTo: v })} />
      <Pick label="Склад" all="Все склады" value={f.locationId} onChange={(v) => patch({ locationId: v })} opts={warehouses} />
    </>, `${formatDate(f.dateFrom)} — ${formatDate(f.dateTo)}`)}
    {!d ? <Pending q={q} /> : <>
      <Table name="Оборудование по складам, шт." cols={['Склад', ...cols]}
        rows={d.warehouses.map((w) => [w.location, ...figures(w)])}
        foot={['Итого', sum(d.warehouses, (w) => w.opening), sum(d.warehouses, (w) => w.income),
          sum(d.warehouses, (w) => w.outcome), sum(d.warehouses, (w) => w.closing), null, null]}
        empty="Складов нет" />
      {sum(d.warehouses, (w) => w.noHistory) > 0 && <Note>В остатках есть единицы без истории движений ({nf.format(sum(d.warehouses, (w) => w.noHistory))}): они дают только остаток, без прихода и расхода.</Note>}
      <Table name="ЗИП по складам" cols={['Склад', 'Номенклатура', 'Ед.', ...cols]}
        rows={d.spares.map((s) => [s.location, s.name, s.unitLabel, ...figures(s)])} empty="Движений и остатков ЗИП за период нет" />
      {d.spareCorrectionsUnknown > 0 && <Note>{SPARE_NOTE}</Note>}
    </>}
  </>
}

function HoldersReportView({ companyId, f, patch, bar }: ReportProps) {
  const q = useQuery({ queryKey: ['eq-report-holders', companyId, f.date], queryFn: () => getHoldersReport(companyId, f.date) })
  const all = q.data?.holders ?? []
  // Выбор держателя — сужение уже загруженного отчёта: ключ группы, а не справочника,
  // чтобы выбирались и держатели, записанные текстом.
  const shown = all.filter((h) => !f.counterpartyId || h.key === f.counterpartyId)
  const linked = (h: { linked: boolean }) => (h.linked ? 'да' : 'не привязан')
  return <>
    {bar(<>
      <DateField label="На дату" value={f.date} onChange={(v) => patch({ date: v })} />
      <Pick label="Контрагент" all="Все" value={all.some((h) => h.key === f.counterpartyId) ? f.counterpartyId : ''}
        onChange={(v) => patch({ counterpartyId: v })} opts={all.map((h) => ({ id: h.key, name: h.linked ? h.name : `${h.name} (не привязан к справочнику)` }))} />
    </>, `на ${formatDate(f.date)}`)}
    {!q.data ? <Pending q={q} /> : <>
      <Table name="Контрагенты" cols={['Контрагент', 'В справочнике', 'Складов', 'Единиц на складах', 'В ремонте, возвращено, хранитель в карточке', 'Всего']}
        rows={shown.map((h) => [h.name, linked(h), h.warehouses.length, h.total - h.units.length, h.units.length, h.total])}
        foot={['Итого', null, sum(shown, (h) => h.warehouses.length), sum(shown, (h) => h.total - h.units.length),
          sum(shown, (h) => h.units.length), sum(shown, (h) => h.total)]}
        empty="На эту дату за контрагентами ничего не числится" />
      <Table name="Склады контрагентов" cols={['Контрагент', 'Склад', 'Вид владения', 'Договор', 'Действует до', 'Статус договора', 'Ответственный', 'Единиц']}
        rows={shown.flatMap((h) => h.warehouses.map((w): Cell[] => [h.name, w.name, w.ownershipLabel || null,
          w.contract.number ? `№ ${w.contract.number} от ${w.contract.date ?? ''}` : null, day(w.contract.validUntil),
          w.contract.statusLabel, w.responsible, w.units.length]))}
        warn={shown.flatMap((h) => h.warehouses.map((w) => w.contract.status !== 'active'))}
        empty="Складов у контрагентов нет" />
      <Table name="Единицы за контрагентами" cols={['Контрагент', 'В справочнике', ...UNIT_COLS.slice(0, 7), 'Договор документа', 'История движений']}
        rows={shown.flatMap((h) => [...h.warehouses.flatMap((w) => w.units), ...h.units].map((u): Cell[] => [
          h.name, linked(h), ...unitCells(u).slice(0, 7), u.contractLabel, u.noHistory ? 'нет' : null]))}
        empty="Единиц нет" />
    </>}
  </>
}

function RepairsReportView({ companyId, bar }: ReportProps) {
  const q = useQuery({ queryKey: ['eq-report-repairs', companyId], queryFn: () => getRepairsReport(companyId) })
  const d = q.data
  return <>
    {bar(d ? <span className="text-xs text-muted-foreground">В ремонте: {nf.format(d.items.length)} · дольше планового срока: {nf.format(d.overdue)}</span> : null,
      `на ${formatDate(today())}`)}
    {!d ? <Pending q={q} /> : (
      <Table name="В ремонте"
        cols={['Серийный №', 'Инв. №', 'Оборудование', 'Кому передана', 'Документ', 'Передана', 'Плановый возврат', 'Дней в ремонте', 'Просрочка, дней', 'Вид ремонта', 'Заявка']}
        rows={d.items.map((r) => [r.serialNumber, r.inventoryNumber, eqName(r.vendor, r.model) || null, r.holder, r.docNumber,
          day(r.sentOn), day(r.plannedReturn), r.days, r.overdueDays || null, r.repairKind, r.ticketRef])}
        warn={d.items.map((r) => r.overdueDays > 0)} empty="В ремонте ничего нет" />
    )}
  </>
}

const VIEWS = { stock: StockReportView, turnover: TurnoverReportView, holders: HoldersReportView, repairs: RepairsReportView }

export function EquipmentReportsPanel({ companyId }: { companyId: string }) {
  const [report, setReport] = useState<keyof typeof VIEWS>('stock')
  const [f, setF] = useState<Params>(() => ({ date: today(), dateFrom: `${today().slice(0, 8)}01`, dateTo: today(), locationId: '', counterpartyId: '' }))
  const root = useRef<HTMLDivElement>(null)
  const locs = useQuery({ queryKey: ['eq-locations', companyId], queryFn: () => loadLocations(companyId), staleTime: 60_000 })
  const warehouses = (locs.data ?? []).filter((l) => l.type === 'warehouse').sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  const title = REPORTS.find((r) => r.k === report)?.label ?? ''
  const View = VIEWS[report]
  return (
    <div className="space-y-3 p-4" ref={root}>
      <div data-export-ignore>
        <PanelViewTabs tabs={REPORTS} value={report} label="Отчёт" ariaLabel="Отчёты складского учёта"
          // Контрагент у отчётов выбирается из разных списков — при смене отчёта сбрасывается.
          onChange={(k) => { setReport(k as keyof typeof VIEWS); setF((s) => ({ ...s, counterpartyId: '' })) }} />
      </div>
      <View companyId={companyId} f={f} patch={(p) => setF((s) => ({ ...s, ...p }))} warehouses={warehouses}
        bar={(params, subtitle) => (
          <ViewParamsBar>
            {params}
            <div className="ml-auto"><ExportButton title={`Оборудование · ${title}`} subtitle={subtitle} getEl={() => root.current} /></div>
          </ViewParamsBar>
        )} />
    </div>
  )
}
