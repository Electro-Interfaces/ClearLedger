/**
 * «Обратные звонки» — задачи «перезвонить»: от звонящего («нажмите 1») и от
 * оператора. Просроченные сверху: ради них сюда и приходят.
 *
 * Снять можно только задачу, которая ждёт набора: живую задачу снимает приём узла,
 * и контакт-центр получает об этом событие. Номер — маской, как везде.
 * Перенести срок узел пока не умеет — кнопки нет, чтобы не обещать лишнего.
 */
import { useState } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, PhoneForwarded } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { когда } from './format'
import { Heading, NodeError } from './parts'

const СОСТОЯНИЕ: Record<voice.Callback['state'], string> = {
  scheduled: 'ждёт набора',
  dialing: 'набираем',
  reached: 'дозвонились',
  not_reached: 'не дозвонились',
  canceled: 'снята',
}

const ФИЛЬТР: { key: voice.Callback['state'] | ''; name: string }[] = [
  { key: '', name: 'Все' },
  { key: 'scheduled', name: 'Ждут набора' },
  { key: 'dialing', name: 'Набираем' },
  { key: 'reached', name: 'Дозвонились' },
  { key: 'not_reached', name: 'Не дозвонились' },
  { key: 'canceled', name: 'Сняты' },
]

export default function VoiceCallbacksPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [состояние, setСостояние] = useState<voice.Callback['state'] | ''>('')
  const [просрочены, setПросрочены] = useState(false)
  const [снять, setСнять] = useState<string | null>(null)
  const [причина, setПричина] = useState('')

  const задачи = useInfiniteQuery({
    queryKey: ['voice-callbacks', companyId, состояние, просрочены],
    queryFn: ({ pageParam }) => voice.callbacks(companyId, {
      state: состояние, overdue: просрочены || undefined, cursor: pageParam || undefined, limit: 100,
    }),
    initialPageParam: '',
    getNextPageParam: last => last.next ?? undefined,
  })
  // Просроченные сверху, дальше — как отдал узел (новые первыми).
  const строки = (задачи.data?.pages.flatMap(p => p.items) ?? [])
    .map((x, i) => ({ x, i }))
    .sort((a, b) => Number(!!b.x.overdue) - Number(!!a.x.overdue) || a.i - b.i)
    .map(({ x }) => x)

  async function снятьЗадачу(id: string) {
    try {
      await voice.cancelCallback(companyId, id, причина.trim() || undefined)
      toast.success('Задача снята')
      setСнять(null)
      setПричина('')
      await qc.invalidateQueries({ queryKey: ['voice-callbacks', companyId] })
    } catch (e) {
      toast.error(e instanceof voice.VoiceError && e.code === 'callback_busy'
        ? 'Задача уже у оператора: идёт набор или разговор. Снять её сейчас нельзя.'
        : e instanceof Error ? e.message : 'Не снята')
      await qc.invalidateQueries({ queryKey: ['voice-callbacks', companyId] })
    }
  }

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Обратные звонки" подпись="Задачи «перезвонить»: от звонящего и от оператора. Просроченные — сверху." />

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1 rounded-md border border-border p-0.5">
          {ФИЛЬТР.map(x => (
            <button key={x.key || 'all'} type="button" onClick={() => setСостояние(x.key)} aria-pressed={состояние === x.key}
              className={cn('min-h-8 rounded px-3 text-sm transition-colors',
                состояние === x.key ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent/50')}>
              {x.name}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={просрочены} onCheckedChange={setПросрочены} aria-label="Только просроченные" />
          только просроченные
        </label>
      </div>

      {задачи.isLoading && <p role="status" className="text-sm">Читаем задачи у узла…</p>}
      {задачи.isError && <NodeError ошибка={задачи.error} что="прочитать обратные звонки" />}
      {задачи.isSuccess && !строки.length && (
        <EmptyBlock иконка={PhoneForwarded} текст="Задач нет"
          подсказка="Задача появляется, когда звонящий нажал «1» в очереди или оператор пообещал перезвонить." />
      )}

      {!!строки.length && (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-card text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-normal">Поставлена</th>
                <th className="px-3 py-2 font-normal">Кто попросил</th>
                <th className="px-3 py-2 font-normal">Номер</th>
                <th className="px-3 py-2 font-normal">Срок</th>
                <th className="px-3 py-2 font-normal">Попытки</th>
                <th className="px-3 py-2 font-normal">Состояние</th>
                <th className="px-3 py-2 font-normal">Следующая попытка</th>
                <th className="px-3 py-2 font-normal"><span className="sr-only">Действия</span></th>
              </tr>
            </thead>
            <tbody>
              {строки.map(x => (
                <tr key={x.id} className="border-t border-border/60 align-top">
                  <td className="whitespace-nowrap px-3 py-2">
                    {когда(x.createdAt)}
                    {x.originContactId && (
                      <div><Link to={`/voice/calls?id=${encodeURIComponent(x.originContactId)}`} className="text-xs underline">звонок</Link></div>
                    )}
                  </td>
                  <td className="px-3 py-2">{x.source === 'caller' ? 'звонящий' : 'оператор'}</td>
                  <td className="px-3 py-2 font-mono text-xs">{x.number ?? '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    {когда(x.dueAt)}
                    {x.overdue && (
                      <div className="flex items-center gap-1 text-xs text-warning"><AlertTriangle className="h-3.5 w-3.5" />просрочена</div>
                    )}
                  </td>
                  <td className="px-3 py-2 tabular-nums">{x.attempts ?? 0}{x.maxAttempts ? ` из ${x.maxAttempts}` : ''}</td>
                  <td className={cn('px-3 py-2', x.state === 'reached' && 'text-success', x.state === 'not_reached' && 'text-destructive')}>
                    {СОСТОЯНИЕ[x.state]}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">{x.state === 'scheduled' ? когда(x.nextAt) : '—'}</td>
                  <td className="px-3 py-2">
                    {x.state === 'scheduled' && снять !== x.id && (
                      <Button variant="outline" size="xs" onClick={() => { setСнять(x.id); setПричина('') }}>Снять</Button>
                    )}
                    {снять === x.id && (
                      <form className="flex flex-wrap items-center gap-1.5" onSubmit={e => { e.preventDefault(); void снятьЗадачу(x.id) }}>
                        <Input value={причина} onChange={e => setПричина(e.target.value)} maxLength={200} aria-label="Почему снимаем"
                          placeholder="почему (необязательно)" className="h-8 w-44" />
                        <Button type="submit" variant="destructive" size="xs">Снять задачу</Button>
                        <Button type="button" variant="ghost" size="xs" onClick={() => setСнять(null)}>Нет</Button>
                      </form>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {задачи.hasNextPage && (
        <Button variant="outline" size="sm" onClick={() => задачи.fetchNextPage()} disabled={задачи.isFetchingNextPage}>
          {задачи.isFetchingNextPage ? 'Читаем…' : 'Показать ещё'}
        </Button>
      )}
    </div>
  )
}
