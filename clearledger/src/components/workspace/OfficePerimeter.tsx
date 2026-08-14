/**
 * «Периметр» — всё, чем компания владеет и что должна помимо баланса.
 *
 * Три слоя, и различать их обязано само устройство экранов:
 *
 * 1. **Забалансовый учёт** (001–012, МЦ.\*) — официально, просто вне баланса;
 * 2. **Невидимое в балансе** — самортизированное, малоценка, просроченный долг;
 * 3. **Договорённости** — устное, обещанное, решённое: в учёте этого нет вовсе.
 *
 * Первые два раздел «Официально» показывает теми же витринами, что и «Бухгалтерия»:
 * компоненты переиспользуются, второй реализации цифры нет. Третий живёт только здесь.
 *
 * Почему слои не сведены в один список: доверие к ним разное. Строка «арендовано на
 * 2 млн» подтверждена договором и проводкой, строка «обещали не поднимать цену до
 * весны» — памятью человека. Сложить их в одну сумму значит соврать обеим.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { useWorkspace, useWorkspaceSubView } from '@/contexts/WorkspaceContext'
import { QueryError } from '@/components/common/QueryError'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { exportTable } from '@/services/booksExport'
import {
  createPerimeterRecord, deletePerimeterRecord, getPerimeterDicts, getPerimeterOverview,
  getPerimeterParties, getPerimeterRecords, updatePerimeterRecord,
  type PerimeterRecord, type PerimeterRecordIn,
} from '@/services/perimeterService'
import { Loading, NoCompany, TableCard, Th } from './OfficePanels'
import { OffBalanceAccounts, OffBalanceHiddenScreen } from './OfficeOffBalance'
import { ExportButton, SearchInput, Tabs, money, num } from './officeShared'
import { ProductHelpPanel } from './ProductHelpPanel'
import { PERIMETER_HELP_SLICES } from './helpSlices'
import {
  PER_PICTURE_MENU, PER_OFFICIAL_MENU, PER_RECORDS_MENU, PER_CASH_MENU,
  PER_PEOPLE_MENU,
} from '@/config/workspaceMenus'
import {
  CashJournalScreen, CashLoansScreen, CashPapersScreen, CashPeopleScreen,
} from './OfficeCash'
import { PerimeterPeopleScreen } from './OfficePeople'
import { CommitmentsScreen } from './OfficeCommitments'
import { useWorkspaceSections } from './workspaceSections'

const PER_MENU_FOR_HELP = [...PER_PICTURE_MENU, ...PER_OFFICIAL_MENU,
  ...PER_RECORDS_MENU, ...PER_CASH_MENU, ...PER_PEOPLE_MENU]

const modeForHelpKey = (key: string): string =>
  PER_OFFICIAL_MENU.some((m) => m.key === key) ? 'per_official'
  : PER_RECORDS_MENU.some((m) => m.key === key) ? 'per_records'
  : PER_CASH_MENU.some((m) => m.key === key) ? 'per_cash'
  : PER_PEOPLE_MENU.some((m) => m.key === key) ? 'per_people'
  : 'per_picture'

function Td({ children, right, muted }: {
  children: React.ReactNode; right?: boolean; muted?: boolean
}) {
  return (
    <td className={cn('px-3 py-2 align-top', right && 'text-right tabular-nums whitespace-nowrap',
      muted && 'text-muted-foreground')}>{children}</td>
  )
}

/** Сумма записи: её может не быть, и это законно, а не ноль. */
const amountText = (v: number | null) => (v === null ? '—' : `${money.format(v)} ₽`)

/** Насколько твёрдо: цвет полосы подсказывает, чему можно верить без проверки. */
const CONF_TONE: Record<string, string> = {
  spoken: 'bg-amber-500/70',
  correspondence: 'bg-sky-500/70',
  signed: 'bg-emerald-500/70',
}

export function PerimeterPanel() {
  const { coreMode } = useWorkspace()
  const sections = useWorkspaceSections()
  const items = sections.find((s) => s.mode === coreMode)?.items ?? []
  const [sub] = useWorkspaceSubView(items[0]?.key ?? '', items.map((i) => i.key))
  const { companyId } = useCompany()

  if (!companyId) return <NoCompany />
  if (!items.length) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        В этом разделе нет доступных вам экранов. Права выдаются в «Управлении».
      </div>
    )
  }

  if (coreMode === 'per_help') {
    return (
      <ProductHelpPanel companyId={companyId} section={sub} appCode="perimeter"
        slices={PERIMETER_HELP_SLICES} menu={PER_MENU_FOR_HELP} modeForKey={modeForHelpKey} />
    )
  }

  const view = (() => {
    switch (sub) {
      case 'pr_layers':   return <PerimeterLayers companyId={companyId} />
      case 'pr_due':      return <PerimeterDue companyId={companyId} />
      case 'pr_accounts': return <OffBalanceAccounts companyId={companyId} />
      case 'pr_hidden':   return <OffBalanceHiddenScreen companyId={companyId} />
      case 'pr_registry': return <PerimeterRegistry companyId={companyId} />
      case 'pr_regular':  return <CommitmentsScreen companyId={companyId} />
      case 'pr_parties':  return <PerimeterParties companyId={companyId} />
      case 'pr_cash':        return <CashJournalScreen companyId={companyId} />
      case 'pr_cash_people': return <CashPeopleScreen companyId={companyId} />
      case 'pr_cash_loans':  return <CashLoansScreen companyId={companyId} />
      case 'pr_cash_papers': return <CashPapersScreen companyId={companyId} />
      case 'pr_people':      return <PerimeterPeopleScreen companyId={companyId} />
      default:            return <PerimeterLayers companyId={companyId} />
    }
  })()

  return (
    <div className="h-full flex flex-col">
      <ScrollArea className="flex-1 min-h-0">{view}</ScrollArea>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                          Три слоя                              */
/* ────────────────────────────────────────────────────────────── */

function PerimeterLayers({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['perimeter', 'overview', companyId],
    queryFn: () => getPerimeterOverview(companyId),
    enabled: !!companyId,
  })
  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось собрать картину периметра" onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  const d = q.data

  return (
    <div className="p-4 space-y-4">
      <Card>
        <CardContent className="p-4 space-y-2 text-sm">
          <div className="font-medium">Что показывает этот экран</div>
          <p className="text-muted-foreground">
            Баланс отвечает, чем компания владеет и кому должна по документам. Рядом с ним
            всегда есть три слоя, которых в нём нет: имущество и обязательства на
            забалансовых счетах, невидимое в балансе из-за амортизации и списаний, и то,
            о чём договорились словами. Первые два приходят из бухгалтерии, третий
            записывают люди. Суммы по слоям намеренно не складываются в одну: доверие к
            ним разное.
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-3">
        {d.layers.map((l) => (
          <Card key={l.key}>
            <CardContent className="p-4 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    Слой {l.no}
                  </div>
                  <div className="text-base font-medium">{l.title}</div>
                </div>
                <span className={cn('text-[11px] px-1.5 py-0.5 rounded border whitespace-nowrap',
                  l.official ? 'text-muted-foreground' : 'border-amber-500/50 text-amber-600')}>
                  {l.official ? 'из учёта' : 'со слов'}
                </span>
              </div>
              <div className="text-xl tabular-nums">{money.format(l.amount)} ₽</div>
              <div className="text-[11px] text-muted-foreground">{l.hint}</div>
              <div className="text-[11px] text-muted-foreground tabular-nums">
                {l.empty ? 'записей нет' : `${num.format(l.count)} · ${l.note}`}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Действующих договорённостей" value={num.format(d.activeCount)}
          hint={`всего заведено ${num.format(d.totalCount)}`} />
        <MetricTile label="Просрочено" value={num.format(d.overdue.length)}
          hint="срок прошёл, запись не закрыта"
          tone={d.overdue.length ? 'danger' : undefined} />
        <MetricTile label="Срок в ближайший месяц" value={num.format(d.soon.length)}
          hint="о чём напомнить заранее"
          tone={d.soon.length ? 'warning' : undefined} />
        <MetricTile label="Пора оформлять" value={num.format(d.toFormalize.length)}
          hint="счёт указан, движения по нему нет"
          tone={d.toFormalize.length ? 'warning' : undefined} />
      </div>

      {!!d.byConfidence.length && (
        <TableCard note="Чем подтверждён третий слой. Записанное со слов проверяют первым: спорить с памятью нечем"
          head={<><Th>Подтверждение</Th><Th right>Записей</Th><Th right>Сумма</Th></>}>
          {d.byConfidence.map((c) => (
            <tr key={c.key} className="border-b last:border-0">
              <Td>
                <span className={cn('inline-block w-1.5 h-1.5 rounded-full mr-2',
                  CONF_TONE[c.key] ?? 'bg-muted-foreground')} />
                {c.label}
              </Td>
              <Td right muted>{num.format(c.count)}</Td>
              <Td right>{c.amount ? `${money.format(c.amount)} ₽` : '—'}</Td>
            </tr>
          ))}
        </TableCard>
      )}

      {!!d.byKind.length && (
        <TableCard note="О чём договорились"
          head={<><Th>Вид</Th><Th right>Записей</Th><Th right>Сумма</Th></>}>
          {d.byKind.map((k) => (
            <tr key={k.key} className="border-b last:border-0">
              <Td>{k.label}</Td>
              <Td right muted>{num.format(k.count)}</Td>
              <Td right>{k.amount ? `${money.format(k.amount)} ₽` : '—'}</Td>
            </tr>
          ))}
        </TableCard>
      )}

      {!!d.withoutAmount && (
        <p className="text-[11px] text-muted-foreground">
          У {num.format(d.withoutAmount)} действующих записей суммы нет. Это нормально:
          обещание починить бесплатно деньгами не меряется до поломки, и ставить туда
          ноль значило бы занизить обязательства компании.
        </p>
      )}

      {!!d.toFormalize.length && (
        <TableCard note="Записи, которым место в учёте: забалансовый счёт указан, а движения по нему нет"
          head={<><Th>Счёт</Th><Th>Что записано</Th><Th>Вторая сторона</Th><Th right>Сумма</Th></>}>
          {d.toFormalize.map((r) => (
            <tr key={r.id} className="border-b last:border-0">
              <Td><span className="tabular-nums">{r.account}</span></Td>
              <Td>{r.title}</Td>
              <Td muted>{r.counterparty ?? '—'}</Td>
              <Td right>{amountText(r.amount)}</Td>
            </tr>
          ))}
        </TableCard>
      )}
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                            Сроки                               */
/* ────────────────────────────────────────────────────────────── */

function PerimeterDue({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['perimeter', 'overview', companyId],
    queryFn: () => getPerimeterOverview(companyId),
    enabled: !!companyId,
  })
  if (q.isError) {
    return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <Loading />
  const d = q.data
  const rows = [...d.overdue, ...d.soon]

  if (!rows.length) {
    return (
      <div className="p-4">
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            Ближайших сроков нет: ни одна действующая запись не просрочена и не наступает
            в течение месяца. Срок ставится не у всех записей — «пока работаем, скидка
            сохраняется» бессрочно по своей природе.
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
          Просроченное и ближайшее
        </div>
        <ExportButton onClick={() => exportTable('Сроки периметра', [
          { header: 'Срок', key: 'dueOn', width: 14 },
          { header: 'Дней', key: 'daysLeft', width: 8 },
          { header: 'Что записано', key: 'title', width: 46 },
          { header: 'Вторая сторона', key: 'counterparty', width: 30 },
          { header: 'Вид', key: 'kindLabel', width: 24 },
          { header: 'Сумма', key: 'amount', width: 16, money: true },
        ], rows)} />
      </div>
      <TableCard note="Отрицательные дни — просрочка. Запись не исчезает по сроку: её закрывают руками, отметив, чем закончилось"
        head={<><Th>Срок</Th><Th>Что записано</Th><Th>Вторая сторона</Th>
          <Th>Подтверждение</Th><Th right>Сумма</Th></>}>
        {rows.map((r) => (
          <tr key={r.id} className={cn('border-b last:border-0', r.overdue && 'bg-destructive/5')}>
            <Td>
              <div className="tabular-nums">{r.dueOn}</div>
              <div className={cn('text-[11px] tabular-nums',
                r.overdue ? 'text-destructive' : 'text-muted-foreground')}>
                {r.daysLeft === null ? '' : r.daysLeft < 0
                  ? `просрочено на ${Math.abs(r.daysLeft)} дн.`
                  : `через ${r.daysLeft} дн.`}
              </div>
            </Td>
            <Td>
              <div>{r.title}</div>
              <div className="text-[11px] text-muted-foreground">{r.kindLabel} · {r.directionLabel}</div>
            </Td>
            <Td muted>{r.counterparty ?? '—'}</Td>
            <Td muted>
              <span className={cn('inline-block w-1.5 h-1.5 rounded-full mr-1.5',
                CONF_TONE[r.confidence] ?? 'bg-muted-foreground')} />
              {r.confidenceLabel}
            </Td>
            <Td right>{amountText(r.amount)}</Td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                            Реестр                              */
/* ────────────────────────────────────────────────────────────── */

const EMPTY: PerimeterRecordIn = {
  title: '', kind: 'agreement', direction: 'we_owe', status: 'active', confidence: 'spoken',
}

function PerimeterRegistry({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [status, setStatus] = useState('active')
  const [search, setSearch] = useState('')
  const [edit, setEdit] = useState<{ id: string | null; body: PerimeterRecordIn } | null>(null)

  const dicts = useQuery({
    queryKey: ['perimeter', 'dicts', companyId],
    queryFn: () => getPerimeterDicts(companyId),
    enabled: !!companyId,
  })
  const q = useQuery({
    queryKey: ['perimeter', 'records', companyId, status],
    queryFn: () => getPerimeterRecords(companyId, { status: status || undefined }),
    enabled: !!companyId,
  })

  const save = useMutation({
    mutationFn: (v: { id: string | null; body: PerimeterRecordIn }) =>
      v.id ? updatePerimeterRecord(companyId, v.id, v.body)
           : createPerimeterRecord(companyId, v.body),
    onSuccess: () => {
      setEdit(null)
      qc.invalidateQueries({ queryKey: ['perimeter'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => deletePerimeterRecord(companyId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['perimeter'] }),
  })

  const rows = useMemo(() => {
    const all = q.data?.rows ?? []
    const s = search.trim().toLowerCase()
    if (!s) return all
    return all.filter((r) => `${r.title} ${r.details ?? ''} ${r.counterparty ?? ''}`
      .toLowerCase().includes(s))
  }, [q.data, search])

  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось загрузить реестр" onRetry={() => q.refetch()} />
    </div>
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <Tabs value={status} onChange={setStatus} items={[
          { key: 'active', label: 'Действующие' },
          { key: '', label: 'Все' },
          { key: 'done', label: 'Исполненные' },
          { key: 'formalized', label: 'Оформленные' },
          { key: 'cancelled', label: 'Снятые' },
        ]} />
        <div className="flex items-center gap-2">
          <SearchInput value={search} onChange={setSearch} placeholder="Поиск по записям" />
          <ExportButton onClick={() => exportTable('Договорённости', [
            { header: 'Что записано', key: 'title', width: 46 },
            { header: 'Вид', key: 'kindLabel', width: 24 },
            { header: 'Сторона', key: 'directionLabel', width: 16 },
            { header: 'Вторая сторона', key: 'counterparty', width: 30 },
            { header: 'Сумма', key: 'amount', width: 16, money: true },
            { header: 'Возникло', key: 'startedOn', width: 13 },
            { header: 'Срок', key: 'dueOn', width: 13 },
            { header: 'Подтверждение', key: 'confidenceLabel', width: 18 },
            { header: 'Статус', key: 'statusLabel', width: 20 },
            { header: 'Счёт', key: 'account', width: 10 },
          ], rows)} />
          <Button size="sm" onClick={() => setEdit({ id: null, body: { ...EMPTY } })}>
            <Plus className="w-4 h-4 mr-1" />Записать
          </Button>
        </div>
      </div>

      {!q.data ? <Loading /> : !rows.length ? (
        <Card>
          <CardContent className="p-4 text-sm space-y-2">
            <div className="font-medium">Записей пока нет</div>
            <p className="text-muted-foreground">
              Сюда заносят то, чего нет в документах: устные договорённости с клиентами и
              поставщиками, обещания сроков, решения собственника, поручительства «под
              честное слово», чужое имущество, оставленное на площадке. У каждой записи
              видно, чем она подтверждена, — со слов, перепиской или подписью.
            </p>
            <p className="text-muted-foreground">
              Такие обязательства теряются первыми при передаче дел и всплывают самым
              неудобным образом. Записанная договорённость стоит минуты, невыясненная —
              переговоров заново.
            </p>
          </CardContent>
        </Card>
      ) : (
        <TableCard note={`${num.format(rows.length)} записей. Полоса слева — чем подтверждено`}
          head={<><Th>Что записано</Th><Th>Вторая сторона</Th><Th>Срок</Th>
            <Th right>Сумма</Th><Th>Статус</Th><Th right> </Th></>}>
          {rows.map((r) => (
            <tr key={r.id} className="border-b last:border-0 hover:bg-muted/40">
              <Td>
                <div className="flex items-start gap-2">
                  <span className={cn('mt-1.5 w-1 h-8 rounded-full shrink-0',
                    CONF_TONE[r.confidence] ?? 'bg-muted-foreground')}
                    title={r.confidenceLabel} />
                  <div>
                    <button className="text-left hover:underline"
                      onClick={() => setEdit({ id: r.id, body: toForm(r) })}>
                      {r.title}
                    </button>
                    <div className="text-[11px] text-muted-foreground">
                      {r.kindLabel} · {r.directionLabel}
                      {r.account ? ` · счёт ${r.account}` : ''}
                    </div>
                  </div>
                </div>
              </Td>
              <Td muted>{r.counterparty ?? '—'}</Td>
              <Td>
                {r.dueOn ? (
                  <>
                    <div className="tabular-nums">{r.dueOn}</div>
                    {r.overdue && (
                      <div className="text-[11px] text-destructive">просрочено</div>
                    )}
                  </>
                ) : <span className="text-muted-foreground">без срока</span>}
              </Td>
              <Td right>{amountText(r.amount)}</Td>
              <Td muted>{r.statusLabel}</Td>
              <Td right>
                <button className="text-muted-foreground hover:text-destructive"
                  title="Удалить запись"
                  onClick={() => remove.mutate(r.id)}>
                  <Trash2 className="w-4 h-4" />
                </button>
              </Td>
            </tr>
          ))}
        </TableCard>
      )}

      {edit && dicts.data && (
        <RecordDialog
          value={edit.body}
          isNew={!edit.id}
          dicts={dicts.data}
          saving={save.isPending}
          error={save.error ? String((save.error as Error).message) : null}
          onChange={(body) => setEdit({ ...edit, body })}
          onClose={() => setEdit(null)}
          onSave={() => save.mutate(edit)}
        />
      )}
    </div>
  )
}

const toForm = (r: PerimeterRecord): PerimeterRecordIn => ({
  title: r.title, kind: r.kind, direction: r.direction, details: r.details,
  counterpartyId: r.counterpartyId, counterpartyName: r.counterparty,
  amount: r.amount, startedOn: r.startedOn, dueOn: r.dueOn,
  status: r.status, confidence: r.confidence, source: r.source, evidence: r.evidence,
  consequence: r.consequence, account: r.account, closedNote: r.closedNote,
})

function Field({ label, hint, children }: {
  label: string; hint?: string; children: React.ReactNode
}) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  )
}

const inputCls = 'w-full rounded-md border bg-background px-2.5 py-1.5 text-sm'

/**
 * Форма записи. Обязательно только название: договорённость фиксируют на ходу, и
 * форма из шести обязательных полей приводит к тому, что не фиксируют вовсе.
 */
function RecordDialog({ value, isNew, dicts, saving, error, onChange, onClose, onSave }: {
  value: PerimeterRecordIn
  isNew: boolean
  dicts: { kinds: { key: string; label: string }[]; directions: { key: string; label: string }[]
    statuses: { key: string; label: string }[]; confidence: { key: string; label: string }[] }
  saving: boolean
  error: string | null
  onChange: (v: PerimeterRecordIn) => void
  onClose: () => void
  onSave: () => void
}) {
  const set = (patch: Partial<PerimeterRecordIn>) => onChange({ ...value, ...patch })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isNew ? 'Новая запись периметра' : 'Запись периметра'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
          <Field label="Что записано" hint="Одной фразой, как сказали бы коллеге">
            <input className={inputCls} value={value.title} autoFocus
              onChange={(e) => set({ title: e.target.value })} />
          </Field>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Вид">
              <select className={inputCls} value={value.kind}
                onChange={(e) => set({ kind: e.target.value })}>
                {dicts.kinds.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
              </select>
            </Field>
            <Field label="Сторона">
              <select className={inputCls} value={value.direction}
                onChange={(e) => set({ direction: e.target.value })}>
                {dicts.directions.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
              </select>
            </Field>
          </div>

          <Field label="Вторая сторона" hint="Имя как есть: карточки контрагента может ещё не быть">
            <input className={inputCls} value={value.counterpartyName ?? ''}
              onChange={(e) => set({ counterpartyName: e.target.value })} />
          </Field>

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Сумма, ₽" hint="Пусто, если не меряется деньгами">
              <input className={inputCls} type="number" step="0.01"
                value={value.amount ?? ''}
                onChange={(e) => set({ amount: e.target.value === '' ? null : Number(e.target.value) })} />
            </Field>
            <Field label="Возникло">
              <input className={inputCls} type="date" value={value.startedOn ?? ''}
                onChange={(e) => set({ startedOn: e.target.value || null })} />
            </Field>
            <Field label="Срок">
              <input className={inputCls} type="date" value={value.dueOn ?? ''}
                onChange={(e) => set({ dueOn: e.target.value || null })} />
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Чем подтверждено" hint="От этого зависит, чему верить без проверки">
              <select className={inputCls} value={value.confidence}
                onChange={(e) => set({ confidence: e.target.value })}>
                {dicts.confidence.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
              </select>
            </Field>
            <Field label="Статус">
              <select className={inputCls} value={value.status}
                onChange={(e) => set({ status: e.target.value })}>
                {dicts.statuses.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
              </select>
            </Field>
          </div>

          <Field label="Подробности">
            <textarea className={inputCls} rows={3} value={value.details ?? ''}
              onChange={(e) => set({ details: e.target.value })} />
          </Field>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Где зафиксировано" hint="Встреча, звонок, письмо, чат">
              <input className={inputCls} value={value.source ?? ''}
                onChange={(e) => set({ source: e.target.value })} />
            </Field>
            <Field label="Ссылка на подтверждение" hint="Письмо, сообщение, файл">
              <input className={inputCls} value={value.evidence ?? ''}
                onChange={(e) => set({ evidence: e.target.value })} />
            </Field>
          </div>

          <Field label="Что будет, если сработает"
            hint="Словами: «вернём предоплату 300 тыс.», «встанет отгрузка на неделю»">
            <textarea className={inputCls} rows={2} value={value.consequence ?? ''}
              onChange={(e) => set({ consequence: e.target.value })} />
          </Field>

          <Field label="Забалансовый счёт при оформлении"
            hint="001 аренда, 002 хранение, 008 и 009 обеспечения. Заполните, если запись должна дозреть до учёта">
            <input className={inputCls} value={value.account ?? ''} placeholder="например, 009"
              onChange={(e) => set({ account: e.target.value || null })} />
          </Field>

          {value.status !== 'active' && (
            <Field label="Чем закончилось">
              <textarea className={inputCls} rows={2} value={value.closedNote ?? ''}
                onChange={(e) => set({ closedNote: e.target.value })} />
            </Field>
          )}

          {error && <div className="text-sm text-destructive">{error}</div>}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose}>Отмена</Button>
          <Button size="sm" disabled={!value.title.trim() || saving} onClick={onSave}>
            {saving ? 'Сохраняем…' : 'Сохранить'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                      По второй стороне                         */
/* ────────────────────────────────────────────────────────────── */

function PerimeterParties({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['perimeter', 'parties', companyId],
    queryFn: () => getPerimeterParties(companyId),
    enabled: !!companyId,
  })
  if (q.isError) {
    return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <Loading />
  if (!q.data.rows.length) {
    return (
      <div className="p-4">
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            Пока не с кем: реестр договорённостей пуст.
          </CardContent>
        </Card>
      </div>
    )
  }
  return (
    <div className="p-4 space-y-4">
      <TableCard note="С кем и о чём договорились. Перед разговором с контрагентом полезнее всего именно этот срез"
        head={<><Th>Вторая сторона</Th><Th>О чём</Th><Th right>Действует</Th>
          <Th right>Просрочено</Th><Th right>Ближайший срок</Th><Th right>Сумма</Th></>}>
        {q.data.rows.map((c) => (
          <tr key={c.counterparty} className="border-b last:border-0">
            <Td>{c.counterparty}</Td>
            <Td muted>{c.kinds.join(', ')}</Td>
            <Td right muted>{num.format(c.active)}</Td>
            <Td right>{c.overdue ? (
              <span className="text-destructive">{num.format(c.overdue)}</span>
            ) : '—'}</Td>
            <Td right muted><span className="tabular-nums">{c.nearest ?? '—'}</span></Td>
            <Td right>{c.amount ? `${money.format(c.amount)} ₽` : '—'}</Td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}
