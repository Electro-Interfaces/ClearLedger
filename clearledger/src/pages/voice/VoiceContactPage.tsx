/**
 * «Нужен контакт» (волна 7, Р2): кому из звонивших мы должны перезвонить, у кого это
 * поручение и что с ним стало. Долг перезвона — задача обратного звонка узла
 * (`GET /callbacks?state=open`): одна на номер и линию, повторные пропуски того же
 * номера присоединяются к ней (столбец «Обращений»), номер и склейка — только у узла.
 *
 * Экран-отчёт на наборе report-kit: над таблицей только плитки-отборы, фильтры свёрнуты,
 * карточка строки — поля долга | обращения долга (расшифровка) и действия: передать
 * КЦ ↔ сотруднику, отметить попытку сотрудника, закрыть с результатом и причиной.
 * Завести долг можно из карточки звонка в журнале (кнопка «Завести перезвон»).
 * `?id=<долг>` открывает карточку сразу — на неё ведёт ссылка из карточки звонка.
 */
import { useCallback, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { AlarmClock, ChevronDown, Headset, Loader2, PhoneForwarded, Repeat, UserRound, UserX } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  PageSizeField, RelatedLink, RelatedReport, ReportTools, RowCard, SheetTable,
  TILE_ROW, Tile, ToolPanel, ToolStrip, qty, useReportKit, type Cell,
} from '@/components/report-kit'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { AssigneePicker } from './debt'
import { ИСПОЛНИТЕЛЬ, ИСХОД, ИТОГ_ДОЛГА, КТО_ЗАВЁЛ } from './format'
import { NodeError } from './parts'

const С = { заведён: 0, завёл: 1, номер: 2, линия: 3, исполнитель: 4, обращений: 5, попыток: 6, срок: 7, просрочен: 8, состояние: 9, следующая: 10 }
const ШАПКА = ['Заведён', 'Кто завёл', 'Номер', 'Линия', 'Исполнитель', 'Обращений', 'Попыток', 'Срок', 'Просрочен', 'Состояние', 'Следующая попытка']
const СКРЫТЫ = [С.линия, С.следующая]
const ШИРИНЫ = { [С.заведён]: 150, [С.номер]: 110, [С.исполнитель]: 180, [С.срок]: 150 }
const КЛЮЧ_ФИЛЬТРОВ = 'report-kit.v1:filters-open:voice-contact'

const СОСТОЯНИЕ: Record<string, string> = { scheduled: 'ждёт', dialing: 'КЦ набирает' }
const ВИД_ОБРАЩЕНИЯ: Record<string, string> = {
  origin: 'исходный пропуск', repeat: 'повторный пропуск', task: 'исполнение КЦ', reached: 'дозвонился сам',
}

type Отбор = 'all' | 'overdue' | 'cc' | 'staff' | 'none' | 'repeat'

/** «2026-10-17 14:30»: так столбец сортируется по времени, а на экране — «17.10.2026 14:30». */
const момент = (iso?: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  const п = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${п(d.getMonth() + 1)}-${п(d.getDate())} ${п(d.getHours())}:${п(d.getMinutes())}`
}
const показатьМомент = (s: string) => s.replace(/^(\d{4})-(\d{2})-(\d{2})/, '$3.$2.$1')

function строка(x: voice.Callback): Cell[] {
  return [момент(x.createdAt), КТО_ЗАВЁЛ[x.source] ?? x.source, x.number || 'удалён', x.lineId ?? '', ИСПОЛНИТЕЛЬ(x.assignee),
    x.missedCalls ?? 1, x.attempts ?? 0, момент(x.dueAt), x.overdue ? 'да' : '', СОСТОЯНИЕ[x.state] ?? x.state, момент(x.nextAt)]
}

/** Все открытые долги: узел отдаёт страницами, долгов обычно десятки. */
async function всеОткрытые(cid: string) {
  const все: voice.Callback[] = []
  let cursor: string | undefined
  for (let i = 0; i < 20; i++) {
    const p = await voice.callbacks(cid, { state: 'open', cursor, limit: 100 })
    все.push(...p.items)
    if (!p.next) break
    cursor = p.next
  }
  return все
}

export default function VoiceContactPage() {
  const { companyId } = useCompany()
  const [params, setParams] = useSearchParams()
  const экран = useRef<HTMLDivElement>(null)
  const [отбор, setОтбор] = useState<Отбор>('all')
  const [поиск, setПоиск] = useState('')
  const [карточка, setКарточка] = useState<{ order: number[]; pos: number } | null>(null)
  const [порядок, setПорядок] = useState<number[]>([])
  const [обращения, setОбращения] = useState(false)
  const [фильтрыОткрыты, setФильтрыОткрыты] = useState(() => {
    try { return localStorage.getItem(КЛЮЧ_ФИЛЬТРОВ) === '1' } catch { return false }
  })

  const q = useQuery({ queryKey: ['voice-callbacks', companyId, 'open-all'], queryFn: () => всеОткрытые(companyId) })
  const все = useMemo(() => q.data ?? [], [q.data])
  const строки = useMemo(() => все.filter(x => {
    if (отбор === 'overdue' && !x.overdue) return false
    if (отбор === 'cc' && x.assignee?.kind !== 'cc') return false
    if (отбор === 'staff' && x.assignee?.kind !== 'staff') return false
    if (отбор === 'none' && x.assignee) return false
    if (отбор === 'repeat' && (x.missedCalls ?? 1) < 2) return false
    const п = поиск.trim().toLowerCase()
    return !п || [x.number, ИСПОЛНИТЕЛЬ(x.assignee)].some(v => v?.toLowerCase().includes(п))
  }), [все, отбор, поиск])
  const ячейки = useMemo(() => строки.map(строка), [строки])
  const набор = useReportKit({ id: 'voice-contact.v1', title: 'Нужен контакт', head: ШАПКА, rows: ячейки, hide: СКРЫТЫ, ready: !!q.data, help: ПОМОЩЬ })

  // `?id=` из карточки звонка: карточка долга открыта, пока id в адресе (закрытый долг в списке не найдётся — не откроется).
  const изАдреса = params.get('id')
  const поАдресу = useMemo(() => {
    const i = изАдреса ? строки.findIndex(x => x.id === изАдреса) : -1
    return i >= 0 ? { order: строки.map((_, k) => k), pos: i } : null
  }, [изАдреса, строки])
  const открыта = карточка ?? поАдресу
  const закрыть = () => {
    setКарточка(null)
    setОбращения(false)
    if (изАдреса) { const n = new URLSearchParams(params); n.delete('id'); setParams(n, { replace: true }) }
  }

  const ячейка = useCallback((i: number, c: number) => {
    const r = строки[i]
    if (!r) return undefined
    if (c === С.заведён || c === С.срок || c === С.следующая) {
      const v = String(ячейки[i]?.[c] ?? '')
      return v ? <span className="tabular-nums">{показатьМомент(v)}</span> : undefined
    }
    if (c === С.номер) return <span className="font-mono text-xs">{r.number || 'удалён'}</span>
    if (c === С.просрочен && r.overdue) return <span className="font-medium text-destructive">просрочен</span>
    if (c === С.исполнитель && !r.assignee) return <span className="text-muted-foreground">не назначен</span>
    return undefined
  }, [строки, ячейки])

  const выбранный = открыта ? строки[открыта.order[открыта.pos]] : null
  const переключить = (v: Отбор) => { setОтбор(v === отбор ? 'all' : v); набор.setFilters({}) }
  const отборов = (отбор !== 'all' ? 1 : 0) + (поиск.trim() ? 1 : 0) + Object.keys(набор.filters).length
  const видимые = useMemo(() => {
    const { cols, head } = набор.table
    return (cols.order.length === head.length ? cols.order : head.map((_, i) => i)).filter(i => !cols.hidden.includes(i))
  }, [набор.table])

  if (q.isLoading) return <div className="flex justify-center py-12"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
  if (q.isError) return <div className="p-4"><NodeError ошибка={q.error} что="прочитать долги перезвона" /></div>

  const сколько = (f: (x: voice.Callback) => boolean) => qty(все.filter(f).length)
  return (
    <div ref={экран} className="flex flex-col gap-3 p-3">
      <div className={TILE_ROW}>
        <Tile icon={PhoneForwarded} label="Ждут контакта" value={qty(все.length)} hint="номеров с открытым долгом"
          active={отбор === 'all'} onClick={() => переключить('all')} />
        <Tile icon={AlarmClock} label="Просрочено" value={сколько(x => !!x.overdue)} hint="срок звонка прошёл"
          tone={все.some(x => x.overdue) ? 'text-destructive' : undefined}
          active={отбор === 'overdue'} onClick={() => переключить('overdue')} />
        <Tile icon={Headset} label="У контакт-центра" value={сколько(x => x.assignee?.kind === 'cc')} hint="набирает узел"
          active={отбор === 'cc'} onClick={() => переключить('cc')} />
        <Tile icon={UserRound} label="У сотрудников" value={сколько(x => x.assignee?.kind === 'staff')} hint="звонят сами, отмечают попытки"
          active={отбор === 'staff'} onClick={() => переключить('staff')} />
        <Tile icon={UserX} label="Не назначено" value={сколько(x => !x.assignee)} hint="Исполнитель ещё не назначен"
          tone={все.some(x => !x.assignee) ? 'text-warning' : undefined}
          active={отбор === 'none'} onClick={() => переключить('none')} />
        <Tile icon={Repeat} label="Звонили повторно" value={сколько(x => (x.missedCalls ?? 1) > 1)} hint="пропусков больше одного"
          active={отбор === 'repeat'} onClick={() => переключить('repeat')} />
      </div>

      <Card className="py-0"><CardContent className="flex flex-col gap-3 p-3">
        {фильтрыОткрыты && (
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex w-64 flex-col gap-1">
              <label htmlFor="contact-search" className="text-xs font-medium text-muted-foreground">Номер или исполнитель</label>
              <Input id="contact-search" value={поиск} onChange={e => setПоиск(e.target.value)} placeholder="•••0001 или имя" className="h-9" />
            </div>
            <div className="flex w-32 flex-col gap-1">
              <label htmlFor="contact-page" className="text-xs font-medium text-muted-foreground">Строк на странице</label>
              <PageSizeField bare id="contact-page" />
            </div>
          </div>
        )}
        <div className={cn('flex flex-wrap items-center justify-between gap-2', фильтрыОткрыты && 'border-t border-border/60 pt-3')}>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" aria-expanded={фильтрыОткрыты} onClick={() => {
              const next = !фильтрыОткрыты
              setФильтрыОткрыты(next)
              try { localStorage.setItem(КЛЮЧ_ФИЛЬТРОВ, next ? '1' : '0') } catch { /* хранилище недоступно */ }
            }} className="inline-flex h-8 items-center gap-1.5 rounded-md px-1.5 text-sm font-semibold text-primary hover:bg-accent">
              <ChevronDown className={cn('size-4 transition-transform', фильтрыОткрыты && 'rotate-180')} />
              {фильтрыОткрыты ? 'Свернуть фильтры' : 'Фильтры'}
              {!фильтрыОткрыты && отборов > 0 && <span className="rounded-full bg-primary px-1.5 text-xs leading-5 text-primary-foreground">{отборов}</span>}
            </button>
            <span className="text-xs text-muted-foreground">долгов: {qty(набор.kept.length)}</span>
          </div>
          <Button size="sm" variant="outline" disabled={!отборов}
            onClick={() => { setОтбор('all'); setПоиск(''); набор.setFilters({}) }}>Сбросить фильтры</Button>
        </div>
        <ToolStrip />
        {!все.length ? (
          <EmptyBlock иконка={PhoneForwarded} текст="Перезванивать некому"
            подсказка="Долг появляется, когда звонящий выбрал обратный звонок, оператор пообещал перезвонить, администратор завёл перезвон из карточки звонка или сработало правило «Перезвонить пропущенным» в правилах приёма." />
        ) : (
          <SheetTable {...набор.table} caption="Нужен контакт" lines={['открытые долги перезвона']} defaultWidths={ШИРИНЫ}
            render={ячейка} rowTitle={i => строки[i]?.number ?? ''} onView={setПорядок}
            onRow={(order, pos) => setКарточка({ order, pos })}
            rowClass={i => (строки[i]?.overdue ? 'font-medium' : '')}
            empty="По этому отбору долгов нет. Сбросьте фильтры."
            tableAttrs={exportRows('Нужен контакт', видимые.map(c => набор.sheet.head[c]),
              порядок.map(i => видимые.map(c => набор.sheet.rows[i]?.[c] ?? '')))} />
        )}
      </CardContent></Card>

      <ToolPanel><ReportTools {...набор.tools} searchHint="Номер, исполнитель или число" formulaExample="Например, Попыток / Обращений"
        compare={<DebtCompare открыто={все.length} />} /></ToolPanel>

      <RowCard report="Нужен контакт" head={набор.sheet.head}
        title={выбранный ? `${выбранный.number || 'номер удалён'} · ${ИСПОЛНИТЕЛЬ(выбранный.assignee)}` : undefined}
        row={открыта ? набор.sheet.rows[открыта.order[открыта.pos]] ?? null : null}
        at={открыта?.pos ?? 0} of={открыта?.order.length ?? 0}
        onStep={dir => { if (открыта) setКарточка({ ...открыта, pos: Math.max(0, Math.min(открыта.pos + dir, открыта.order.length - 1)) }) }}
        onClose={закрыть}
        extra={выбранный && <DebtActions key={выбранный.id} долг={выбранный} onContacts={() => setОбращения(true)}
          onClosed={закрыть} />} />
      <DebtContacts id={открыта && обращения ? выбранный?.id ?? null : null} номер={выбранный?.number} onClose={() => setОбращения(false)} />
    </div>
  )
}

/** Правая колонка карточки: обращения долга и действия по нему. */
function DebtActions({ долг, onContacts, onClosed }: { долг: voice.Callback; onContacts: () => void; onClosed: () => void }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const карточка = useQuery({ queryKey: ['voice-callback', companyId, долг.id], queryFn: () => voice.callbackCard(companyId, долг.id) })
  const [кому, setКому] = useState<voice.Assignee>(долг.assignee?.kind === 'cc' ? { kind: 'staff', id: null, name: null } : { kind: 'cc' })
  const [почемуПередать, setПочемуПередать] = useState('')
  const [итог, setИтог] = useState<'reached' | 'not_reached' | 'refused' | 'resolved'>('reached')
  const [причина, setПричина] = useState('')
  const [заметка, setЗаметка] = useState('')
  const [идёт, setИдёт] = useState<string | null>(null)
  const уСотрудника = долг.assignee?.kind === 'staff'
  const уОператора = долг.state === 'dialing'

  async function сделать(что: string, f: () => Promise<voice.CallbackCard>, готово: (c: voice.CallbackCard) => string) {
    setИдёт(что)
    try {
      const c = await f()
      toast.success(готово(c))
      await qc.invalidateQueries({ queryKey: ['voice-callbacks', companyId] })
      qc.setQueryData(['voice-callback', companyId, долг.id], c)
      if (c.result) onClosed()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Узел не ответил')
    } finally {
      setИдёт(null)
    }
  }

  const блок = 'space-y-2 rounded-lg border border-border/60 p-3'
  const подпись = 'text-xs font-semibold text-muted-foreground'
  return (
    <div className="space-y-4">
      <div className="divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60">
        <RelatedLink label="Обращения долга"
          hint={`исходный пропуск, повторные звонки этого номера, исполнение КЦ${(долг.missedCalls ?? 1) > 1 ? ` · ${долг.missedCalls}` : ''}`}
          onClick={onContacts} />
      </div>
      {карточка.data?.note && <p className="text-sm"><span className="text-muted-foreground">Заметка: </span>{карточка.data.note}</p>}

      <div>
        <div className="mb-2 text-xs font-semibold text-muted-foreground">Действия</div>
        {уОператора && (
          <p className="mb-2 text-xs text-muted-foreground">Контакт-центр сейчас набирает номер: передать или закрыть долг можно после попытки.</p>
        )}
        <div className="space-y-3">
          <form className={блок} onSubmit={e => {
            e.preventDefault()
            if (кому.kind === 'staff' && !кому.name?.trim()) return
            void сделать('assign', () => voice.assignCallback(companyId, долг.id, кому, почемуПередать.trim() || undefined),
              c => `Долг передан: ${ИСПОЛНИТЕЛЬ(c.assignee)}`)
          }}>
            <p className={подпись}>Передать · сейчас: {ИСПОЛНИТЕЛЬ(долг.assignee)}</p>
            <AssigneePicker value={кому} onChange={setКому} />
            <Input value={почемуПередать} onChange={e => setПочемуПередать(e.target.value)} maxLength={500}
              aria-label="Почему передаём" placeholder="Почему (необязательно)" className="h-9" />
            <Button type="submit" size="sm" variant="outline" disabled={!!идёт || уОператора || (кому.kind === 'staff' && !кому.name?.trim())}>
              {идёт === 'assign' ? 'Передаём…' : 'Передать'}
            </Button>
          </form>

          {уСотрудника && (
            <div className={блок}>
              <p className={подпись}>Попытка сотрудника · {долг.attempts ?? 0} из {долг.maxAttempts ?? 3}</p>
              <Input value={заметка} onChange={e => setЗаметка(e.target.value)} maxLength={500}
                aria-label="Заметка к попытке" placeholder="Заметка (необязательно)" className="h-9" />
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={!!идёт}
                  onClick={() => void сделать('reached', () => voice.callbackAttempt(companyId, долг.id, 'reached', заметка.trim() || undefined),
                    () => 'Дозвонились: долг закрыт')}>Дозвонились</Button>
                <Button size="sm" variant="outline" disabled={!!идёт}
                  onClick={() => void сделать('not_reached', () => voice.callbackAttempt(companyId, долг.id, 'not_reached', заметка.trim() || undefined),
                    c => c.result ? 'Попытки кончились: долг закрыт «не дозвонились»' : `Попытка отмечена, долг открыт (${c.attempts} из ${c.maxAttempts})`)}>
                  Не дозвонились
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">Неудачная попытка долг не закрывает, пока попыток меньше предела правил приёма.</p>
            </div>
          )}

          <form className={блок} onSubmit={e => {
            e.preventDefault()
            if (причина.trim().length < 3) return
            void сделать('close', () => voice.closeCallback(companyId, долг.id, итог, причина.trim()),
              c => `Долг закрыт: ${ИТОГ_ДОЛГА[c.result ?? итог] ?? итог}`)
          }}>
            <p className={подпись}>Закрыть долг</p>
            <label className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              результат
              <select value={итог} onChange={e => setИтог(e.target.value as typeof итог)}
                className="h-9 rounded-md border border-input bg-card px-2 text-sm text-foreground">
                {(['reached', 'not_reached', 'refused', 'resolved'] as const).map(k => <option key={k} value={k}>{ИТОГ_ДОЛГА[k]}</option>)}
              </select>
            </label>
            <Input value={причина} onChange={e => setПричина(e.target.value)} maxLength={500} required minLength={3}
              aria-label="Причина закрытия" placeholder="Причина — обязательно: что было и почему закрываем" className="h-9" />
            <Button type="submit" size="sm" disabled={!!идёт || уОператора || причина.trim().length < 3}>
              {идёт === 'close' ? 'Закрываем…' : 'Закрыть долг'}
            </Button>
            {долг.assignee?.kind === 'cc' && <p className="text-xs text-muted-foreground">Закрытие снимет задачу у контакт-центра.</p>}
          </form>
        </div>
      </div>
    </div>
  )
}

/** Расшифровка: обращения долга — исходное, склеенные повторы, исполнение КЦ, «дозвонился сам». */
function DebtContacts({ id, номер, onClose }: { id: string | null; номер?: string; onClose: () => void }) {
  const { companyId } = useCompany()
  const q = useQuery({ queryKey: ['voice-callback', companyId, id], queryFn: () => voice.callbackCard(companyId, id!), enabled: !!id })
  const head = ['Когда', 'Обращение', 'Исход', 'Номер звонка']
  const rows: Cell[][] = (q.data?.contacts ?? []).map(x => [момент(x.startedAt), ВИД_ОБРАЩЕНИЯ[x.kind] ?? x.kind,
    x.outcome ? ИСХОД[x.outcome as voice.Outcome] ?? x.outcome : 'идёт', x.contactId])
  return (
    <RelatedReport open={!!id} title="Обращения долга" subtitle={номер} head={head} rows={rows}
      loading={q.isLoading} error={q.isError} onClose={onClose}>
      <SheetTable head={head} rows={rows} caption={номер ?? 'Обращения долга'} lines={[]} defaultWidths={{ 0: 150, 1: 170, 3: 300 }}
        render={(i, c) => c === 0 ? <span className="tabular-nums">{показатьМомент(String(rows[i][0]))}</span>
          : c === 3 ? <span className="font-mono text-xs">{String(rows[i][3])}</span> : undefined}
        empty="Обращений нет" />
    </RelatedReport>
  )
}

/** «Сравнить»: сколько долгов открыто сейчас и чем кончились заведённые за 7 дней. */
function DebtCompare({ открыто }: { открыто: number }) {
  const { companyId } = useCompany()
  const from = useMemo(() => { const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - 6); return d.toISOString() }, [])
  const q = useQuery({
    queryKey: ['voice-callbacks', companyId, 'week', from],
    queryFn: () => voice.callbacks(companyId, { from, limit: 500 }),
  })
  const по = new Map<string, number>()
  for (const x of q.data?.items ?? []) по.set(x.result ?? 'open', (по.get(x.result ?? 'open') ?? 0) + 1)
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p className="text-xs text-muted-foreground">Открыто сейчас — {qty(открыто)}. Ниже — долги, заведённые за 7 дней, по тому, чем кончились.</p>
      {q.isLoading ? <Loader2 className="size-5 animate-spin" /> : q.isError ? <p role="alert">Не удалось прочитать долги за неделю.</p> : (
        <dl className="divide-y divide-border/60">
          {[['open', 'ещё открыты'], ...Object.entries(ИТОГ_ДОЛГА)].map(([k, т]) => (
            <div key={k} className="flex justify-between gap-4 py-1.5"><dt>{т}</dt><dd className="tabular-nums">{qty(по.get(k) ?? 0)}</dd></div>
          ))}
        </dl>
      )}
      {q.data?.next && <p className="text-xs text-muted-foreground">Показаны первые 500 долгов недели.</p>}
    </div>
  )
}

const ПОМОЩЬ = (
  <div className="flex flex-col gap-3 text-sm leading-relaxed text-muted-foreground">
    <p>«Нужен контакт» — кому мы должны перезвонить. Долг — задача обратного звонка узла: одна на номер и линию. Повторный
      пропуск того же номера новой задачи не заводит, а присоединяется к открытой — это столбец «Обращений».</p>
    <p>Долг заводят: звонящий («нажмите 1»), оператор в разговоре, администратор из карточки звонка в журнале
      («Завести перезвон») и правило «Перезвонить пропущенным» в правилах приёма.</p>
    <p>Исполнитель — контакт-центр (узел набирает номер, КЦ видит задачу без номера) или сотрудник заказчика: он звонит
      сам и отмечает попытку здесь. Закрывается долг только с результатом и причиной; если звонящий сам дозвонился
      и с ним поговорили, узел закрывает долг сам.</p>
    <p>Плитки — отборы, повторное нажатие снимает отбор. Строка открывает карточку: поля долга, его обращения и действия.</p>
  </div>
)
