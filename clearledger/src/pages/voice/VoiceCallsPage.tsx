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
 */
import { useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { PhoneCall, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { useMaxWidth } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { CallCard } from './CallCard'
import { ИСХОД, ФЛАГ, когда, началоДня, оператор, плохойИсход, сек } from './format'
import { Heading, Flags, NodeError } from './parts'

const ПЕРИОДЫ = [
  { key: 'today', name: 'Сегодня', from: () => началоДня(0), to: () => undefined },
  { key: 'yesterday', name: 'Вчера', from: () => началоДня(-1), to: () => началоДня(0) },
  { key: 'week', name: '7 дней', from: () => началоДня(-6), to: () => undefined },
  { key: 'month', name: '30 дней', from: () => началоДня(-29), to: () => undefined },
] as const

const ФИЛЬТР_ФЛАГОВ = ['vip', 'repeat', 'after_hours', 'transferred', 'recorded']

export default function VoiceCallsPage() {
  const { companyId } = useCompany()
  const [params, setParams] = useSearchParams()
  const узкий = useMaxWidth(1024)
  const выбран = params.get('id')

  const [период, setПериод] = useState<(typeof ПЕРИОДЫ)[number]['key']>('today')
  const [исход, setИсход] = useState<voice.Outcome | ''>('')
  const [флаги, setФлаги] = useState<string[]>([])
  const [набор, setНабор] = useState('')
  const [номер, setНомер] = useState('')

  const п = ПЕРИОДЫ.find(x => x.key === период) ?? ПЕРИОДЫ[0]
  const from = п.from()
  const to = п.to()
  const flags = флаги.join(',')

  const журнал = useInfiniteQuery({
    queryKey: ['voice-calls', companyId, from, to ?? '', исход, номер, flags],
    queryFn: ({ pageParam }) => voice.calls(companyId, {
      from, to, outcome: исход, number: номер || undefined, flags: flags || undefined,
      cursor: pageParam || undefined, limit: 100,
    }),
    initialPageParam: '',
    getNextPageParam: last => last.next ?? undefined,
  })
  const строки = журнал.data?.pages.flatMap(p => p.items) ?? []

  const цифр = набор.replace(/\D/g, '').length
  function искать(e: React.FormEvent) {
    e.preventDefault()
    if (набор && цифр < 4) return
    setНомер(набор.trim())
  }

  function открыть(id: string | null) {
    const next = new URLSearchParams(params)
    if (id) next.set('id', id); else next.delete('id')
    setParams(next, { replace: !id })
  }

  if (узкий && выбран) return <CallCard contactId={выбран} onBack={() => открыть(null)} />

  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 space-y-4 overflow-y-auto p-4">
        <Heading имя="Журнал звонков" подпись="Все звонки линии, новые сверху. Номер — маской." />

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1 rounded-md border border-border p-0.5">
            {ПЕРИОДЫ.map(x => (
              <button key={x.key} type="button" onClick={() => setПериод(x.key)} aria-pressed={период === x.key}
                className={cn('min-h-8 rounded px-3 text-sm transition-colors',
                  период === x.key ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent/50')}>
                {x.name}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            исход
            <select value={исход} onChange={e => setИсход(e.target.value as voice.Outcome | '')}
              className="h-9 rounded-md border border-input bg-card px-2 text-sm text-foreground">
              <option value="">любой</option>
              {(Object.keys(ИСХОД) as voice.Outcome[]).map(o => <option key={o} value={o}>{ИСХОД[o]}</option>)}
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
        </div>

        {журнал.isLoading && <p role="status" className="text-sm">Читаем журнал узла…</p>}
        {журнал.isError && <NodeError ошибка={журнал.error} что="прочитать журнал" />}
        {журнал.isSuccess && строки.length === 0 && (
          <EmptyBlock иконка={PhoneCall} текст="За этот период звонков нет"
            подсказка="Журнал узла пишет каждый звонок линии: и отвеченные, и брошенные, и пришедшие вне часов." />
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
                подсказка="Карточка покажет ход звонка по этапам, запись и расшифровку и то, кто их уже открывал." />}
        </aside>
      )}
    </div>
  )
}
