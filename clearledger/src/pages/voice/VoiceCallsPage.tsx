/**
 * «Журнал звонков» — все звонки линии, включая не дошедшие до контакт-центра.
 *
 * Главный вопрос сюда приходит словами «почему не дозвонились»: звонок ищут по
 * последним цифрам номера (не меньше четырёх — поиск по номеру узел пишет в
 * журнал доступа) и открывают карточку справа. На телефоне карточка ложится
 * поверх списка с кнопкой «К журналу».
 *
 * Выбранный звонок живёт в адресе (`?id=`): ссылку на него можно переслать
 * коллеге, а с экрана «Сейчас» сюда ведёт «Карточка».
 *
 * Волна 7 (Р1): плитки «Статистики» и «Отчёта за месяц» открывают журнал с
 * `metric=<показатель>[:причина]` и тем же периодом и линией — узел отбирает ровно
 * обращения, из которых сложилось число, тем же расчётом. Отбор целиком в адресе:
 * ссылку можно переслать, `back` возвращает к плитке. Участник (`operator`) —
 * оператор КЦ или сотрудник, который отвечал или консультировал.
 */
import { useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, PhoneCall, Search, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { useMaxWidth } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { CallCard } from './CallCard'
import { ЕДИНИЦА, ИСХОД, ОБСЛУЖИЛ, ПРИЧИНА_ЗАПАСНОГО, ПРИЧИНА_ПРОПУСКА, ФЛАГ, когда, началоДня, оператор, плохойИсход, сек, число } from './format'
import { Heading, Flags, NodeError } from './parts'

const ПЕРИОДЫ = [
  { key: 'today', name: 'Сегодня', from: () => началоДня(0), to: () => undefined },
  { key: 'yesterday', name: 'Вчера', from: () => началоДня(-1), to: () => началоДня(0) },
  { key: 'week', name: '7 дней', from: () => началоДня(-6), to: () => undefined },
  { key: 'month', name: '30 дней', from: () => началоДня(-29), to: () => undefined },
] as const

const ФИЛЬТР_ФЛАГОВ = ['vip', 'repeat', 'after_hours', 'transferred', 'recorded']

/** Узел режет период показателя по 15 минутам: «по сейчас» — вверх до четверти часа, ключ запроса не дрожит. */
const ЧЕТВЕРТЬ = 15 * 60_000
const сейчасДо15 = () => new Date(Math.ceil(Date.now() / ЧЕТВЕРТЬ) * ЧЕТВЕРТЬ).toISOString()

/** «с 1 окт., 00:00 по 17 окт., 15:00» — период, пришедший ссылкой с плитки. */
function отрезок(from: string, to?: string) {
  const ф = (iso: string) => new Date(iso).toLocaleString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  return to ? `с ${ф(from)} по ${ф(to)}` : `с ${ф(from)}`
}

export default function VoiceCallsPage() {
  const { companyId } = useCompany()
  const [params, setParams] = useSearchParams()
  const узкий = useMaxWidth(1024)
  const выбран = params.get('id')

  const metric = params.get('metric') ?? ''
  const участник = params.get('operator') ?? ''
  const line = params.get('line') ?? ''
  const servedBy = (params.get('servedBy') ?? '') as voice.ServedBy | ''
  const topic = params.get('topic') ?? ''
  const назад = params.get('back')
  // Период: свой (from/to из ссылки плитки) или кнопкой. Показатель без конца периода считаем «по сейчас».
  const свой = params.get('from')
  const п = ПЕРИОДЫ.find(x => x.key === params.get('period')) ?? ПЕРИОДЫ[0]
  const from = свой ?? п.from()
  const to = свой ? params.get('to') ?? undefined : п.to() ?? (metric ? сейчасДо15() : undefined)

  const [исход, setИсход] = useState<voice.Outcome | ''>('')
  const [флаги, setФлаги] = useState<string[]>([])
  const [набор, setНабор] = useState('')
  const [номер, setНомер] = useState('')
  const flags = флаги.join(',')

  function поставить(изм: Record<string, string | null>, replace = true) {
    const n = new URLSearchParams(params)
    for (const [k, v] of Object.entries(изм)) { if (v) n.set(k, v); else n.delete(k) }
    setParams(n, { replace })
  }

  const журнал = useInfiniteQuery({
    queryKey: ['voice-calls', companyId, from, to ?? '', исход, номер, flags, metric, участник, line, servedBy, topic],
    queryFn: ({ pageParam }) => voice.calls(companyId, {
      from, to, outcome: исход, number: номер || undefined, flags: flags || undefined,
      metric: metric || undefined, operator: участник || undefined, line: line || undefined,
      servedBy: metric ? servedBy : undefined, topic: topic || undefined,
      cursor: pageParam || undefined, limit: 100,
    }),
    initialPageParam: '',
    getNextPageParam: last => last.next ?? undefined,
  })
  const строки = журнал.data?.pages.flatMap(p => p.items) ?? []
  const мета = журнал.data?.pages[0]?.metric

  // Участники за период — те, кто отвечал (статистика по операторам); выбранный из ссылки остаётся в списке.
  const операторы = useQuery({
    queryKey: ['voice-stats', companyId, 'operators', from, to ?? '', line || undefined],
    queryFn: () => voice.statsOperators(companyId, { from, to: to ?? сейчасДо15(), line: line || undefined }),
    staleTime: 60_000,
  })
  const участники = (операторы.data ?? []).map(r => ({ key: `${r.operator.kind}:${r.operator.id}`, имя: оператор(r.operator) }))
  if (участник && !участники.some(x => x.key === участник)) {
    const [kind, ...id] = участник.split(':')
    участники.unshift({ key: участник, имя: оператор({ kind: kind === 'cc' ? 'cc' : 'staff', id: id.join(':') }) })
  }

  const цифр = набор.replace(/\D/g, '').length
  function искать(e: React.FormEvent) {
    e.preventDefault()
    if (набор && цифр < 4) return
    setНомер(набор.trim())
  }

  function открыть(id: string | null) {
    поставить({ id }, !id)
  }

  if (узкий && выбран) return <CallCard contactId={выбран} onBack={() => открыть(null)} />

  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 space-y-4 overflow-y-auto p-4">
        <Heading имя="Журнал звонков" подпись="Все звонки линии, новые сверху. Номер — маской." />

        {metric && <MetricBar metric={metric} мета={мета} from={from} to={to} line={line} servedBy={servedBy} назад={назад}
          ошибка={журнал.isError} onReset={() => поставить({ metric: null, servedBy: null, back: null })} />}

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1 rounded-md border border-border p-0.5">
            {ПЕРИОДЫ.map(x => {
              const вкл = !свой && п.key === x.key
              return (
                <button key={x.key} type="button" aria-pressed={вкл}
                  onClick={() => поставить({ period: x.key === 'today' ? null : x.key, from: null, to: null })}
                  className={cn('min-h-8 rounded px-3 text-sm transition-colors',
                    вкл ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent/50')}>
                  {x.name}
                </button>
              )
            })}
          </div>
          {свой && !metric && (
            <span className="inline-flex min-h-8 items-center gap-1 rounded-md border border-primary/40 bg-primary/5 pl-2.5 text-sm text-primary">
              {отрезок(from, to)}
              <button type="button" aria-label="Снять свой период" onClick={() => поставить({ from: null, to: null })}
                className="grid size-8 place-items-center rounded-md hover:bg-accent/50"><X className="size-4" /></button>
            </span>
          )}
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            исход
            <select value={исход} onChange={e => setИсход(e.target.value as voice.Outcome | '')}
              className="h-9 rounded-md border border-input bg-card px-2 text-sm text-foreground">
              <option value="">любой</option>
              {(Object.keys(ИСХОД) as voice.Outcome[]).map(o => <option key={o} value={o}>{ИСХОД[o]}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            участник
            <select value={участник} onChange={e => поставить({ operator: e.target.value || null })}
              className="h-9 max-w-56 rounded-md border border-input bg-card px-2 text-sm text-foreground">
              <option value="">любой</option>
              {участники.map(x => <option key={x.key} value={x.key}>{x.имя}</option>)}
            </select>
          </label>
          <form onSubmit={искать} className="flex items-center gap-1.5">
            <Input value={набор} onChange={e => setНабор(e.target.value)} inputMode="tel"
              aria-label="Последние цифры номера" placeholder="последние цифры номера" className="h-9 w-48" />
            <Button type="submit" variant="outline" size="sm" disabled={!!набор && цифр < 4}>
              <Search />Найти
            </Button>
            {номер && <Button type="button" variant="ghost" size="sm" onClick={() => { setНабор(''); setНомер('') }}>Сбросить</Button>}
          </form>
        </div>
        {!!набор && цифр < 4 && (
          <p className="text-xs text-muted-foreground">Нужно не меньше четырёх последних цифр. Поиск по номеру попадёт в журнал доступа.</p>
        )}

        <div className="flex flex-wrap gap-1.5">
          {ФИЛЬТР_ФЛАГОВ.map(ф => {
            const вкл = флаги.includes(ф)
            return (
              <button key={ф} type="button" aria-pressed={вкл}
                onClick={() => setФлаги(вкл ? флаги.filter(x => x !== ф) : [...флаги, ф])}
                className={cn('rounded-md border px-2 py-1 text-xs transition-colors',
                  вкл ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-accent/50')}>
                {ФЛАГ[ф]}
              </button>
            )
          })}
          {topic && (
            <span className="inline-flex items-center gap-1 rounded-md border border-primary bg-primary/10 pl-2 text-xs text-primary">
              тема <span className="font-mono">{topic}</span>
              <button type="button" aria-label="Снять отбор по теме" onClick={() => поставить({ topic: null })}
                className="grid size-6 place-items-center rounded hover:bg-accent/50"><X className="size-3.5" /></button>
            </span>
          )}
        </div>

        {журнал.isLoading && <p role="status" className="text-sm">Читаем журнал узла…</p>}
        {журнал.isError && <NodeError ошибка={журнал.error} что="прочитать журнал" />}
        {журнал.isSuccess && строки.length === 0 && (
          <EmptyBlock иконка={PhoneCall} текст={metric ? 'Звонков по этому показателю нет' : 'За этот период звонков нет'}
            подсказка={metric ? 'Число плитки за этот период — ноль, или его сузили отборы исхода, номера и меток.'
              : 'Журнал узла пишет каждый звонок линии: и отвеченные, и брошенные, и пришедшие вне часов.'} />
        )}

        {строки.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="bg-card text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-normal">Когда</th>
                  <th className="px-3 py-2 font-normal">Номер</th>
                  <th className="px-3 py-2 font-normal">Исход</th>
                  <th className="px-3 py-2 font-normal">Ожидание</th>
                  <th className="px-3 py-2 font-normal">Разговор</th>
                  <th className="px-3 py-2 font-normal">Оператор</th>
                  {metric && <th className="whitespace-nowrap px-3 py-2 text-right font-normal" title="Сколько раз обращение вошло в число плитки">В числе</th>}
                </tr>
              </thead>
              <tbody>
                {строки.map(r => (
                  <tr key={r.contactId} onClick={() => открыть(r.contactId)}
                    aria-selected={выбран === r.contactId}
                    className={cn('cursor-pointer border-t border-border/60 hover:bg-accent/40',
                      выбран === r.contactId && 'bg-primary/5')}>
                    <td className="whitespace-nowrap px-3 py-2">{когда(r.startedAt)}</td>
                    <td className="px-3 py-2">
                      <span className="font-mono text-xs">{r.numberPurged ? 'удалён' : r.number || '—'}</span>
                      <span className="ml-2"><Flags флаги={r.flags?.filter(f => f !== 'recorded')} /></span>
                    </td>
                    <td className={cn('px-3 py-2', плохойИсход(r.outcome) && 'text-destructive')}>
                      {r.outcome ? ИСХОД[r.outcome] ?? r.outcome : 'идёт'}
                    </td>
                    <td className="px-3 py-2 tabular-nums">{сек(r.waitSec)}</td>
                    <td className="px-3 py-2 tabular-nums">{сек(r.talkSec)}</td>
                    <td className="px-3 py-2 text-muted-foreground">{оператор(r.operator)}</td>
                    {metric && (
                      <td className={cn('px-3 py-2 text-right tabular-nums', (r.count ?? 1) > 1 && 'font-medium')}>
                        {r.count ?? 1}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {журнал.hasNextPage && (
          <Button variant="outline" size="sm" onClick={() => журнал.fetchNextPage()} disabled={журнал.isFetchingNextPage}>
            {журнал.isFetchingNextPage ? 'Читаем…' : 'Показать ещё'}
          </Button>
        )}
      </div>

      {!узкий && (
        <aside className="w-[420px] shrink-0 overflow-y-auto border-l border-border bg-card" aria-label="Карточка звонка">
          {выбран
            ? <CallCard key={выбран} contactId={выбран} />
            : <EmptyBlock иконка={PhoneCall} текст="Выберите звонок"
                подсказка="Карточка покажет, кто говорил со звонящим и сколько, записи участков и расшифровку, и кто их уже открывал." />}
        </aside>
      )}
    </div>
  )
}

/**
 * Плашка показателя: какое число открыто, сколько в нём единиц и сколько это обращений.
 * У показателей по отрезкам и задачам строк меньше числа плитки — перевод на свою же линию
 * и повтор не удваивают строку журнала; разница видна здесь и в столбце «В числе».
 */
function MetricBar({ metric, мета, from, to, line, servedBy, назад, ошибка, onReset }: {
  metric: string
  мета?: voice.DrillMeta
  from: string
  to?: string
  line: string
  servedBy: string
  назад: string | null
  ошибка: boolean
  onReset: () => void
}) {
  const [ключ, причина] = metric.split(':')
  const название = мета?.title ?? ключ
  const уточнение = причина ? (ключ === 'fallback' ? ПРИЧИНА_ЗАПАСНОГО : ПРИЧИНА_ПРОПУСКА)[причина] ?? причина : null
  const единица = мета ? ЕДИНИЦА[мета.unit] ?? мета.unitTitle ?? '' : ''
  return (
    <section aria-label="Отбор по показателю"
      className="flex flex-wrap items-start gap-x-4 gap-y-2 rounded-xl border border-primary/35 bg-card p-3">
      <div className="min-w-0 flex-1 basis-64 space-y-0.5">
        <p className="text-sm">
          <span className="font-medium">{название}</span>
          {уточнение && <span> · {уточнение}</span>}
          {мета && <span className="ml-2 font-headline text-base font-semibold tabular-nums">{число(мета.total)}</span>}
          {мета && <span className="text-muted-foreground"> {единица}</span>}
        </p>
        <p className="text-xs text-muted-foreground">
          {мета && (мета.unit !== 'call' || мета.total !== мета.calls) && <>обращений в списке: {число(мета.calls)} · </>}
          {отрезок(мета?.from ?? from, мета?.to ?? to)}
          {line && <> · линия <span className="font-mono">{line}</span></>}
          {servedBy && <> · {ОБСЛУЖИЛ[servedBy] ?? servedBy}</>}
        </p>
        {мета?.unitTitle && мета.unit !== 'call' && <p className="text-xs text-muted-foreground">Единица счёта: {мета.unitTitle}.</p>}
        {ошибка && <p className="text-xs text-destructive">Узел не отдал список по показателю: возможно, узел старше волны 7.</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        {назад?.startsWith('/voice/') && (
          <Button asChild variant="outline" size="sm"><Link to={назад}><ArrowLeft />Вернуться</Link></Button>
        )}
        <Button variant="ghost" size="sm" onClick={onReset}>Снять отбор</Button>
      </div>
    </section>
  )
}
