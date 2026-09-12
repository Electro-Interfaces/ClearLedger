/**
 * «История» — что было. Сюда приходят с вопросом «когда мы это обсуждали и чем
 * кончилось», поэтому первое на экране — поиск по теме, а в строке видно, кто
 * пришёл и что записали итогом.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { History } from 'lucide-react'

import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import * as conf from '@/services/confService'
import { TalkRow } from './parts'
import { EmptyBlock } from './EmptyBlock'

export default function ConfHistoryPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [поиск, setПоиск] = useState('')
  const [только, setТолько] = useState<'all' | 'mine'>('all')

  const список = useQuery({
    queryKey: ['conf-meetings', companyId, только === 'mine' ? 'mine' : 'past', поиск],
    queryFn: () => conf.listMeetings(companyId, только === 'mine' ? 'mine' : 'past', поиск),
  })
  const обновить = () => void qc.invalidateQueries({ queryKey: ['conf-meetings'] })

  // Что прошло, решает сервер: он делит по факту (конференция закрыта), а не по
  // часам календаря. Клиентский фильтр по `ends_at` прятал только что
  // завершённую конференцию до конца её планового окна (CONF-04).
  const прошедшие = (список.data?.meetings ?? []).filter(
    в => только === 'all' || new Date(в.ends_at) < new Date() || в.session?.ended_at)

  return (
    <div className="space-y-4 p-4">
      <h1 className="font-headline text-lg font-semibold">История</h1>

      <div className="flex flex-wrap items-center gap-2">
        <Input value={поиск} onChange={e => setПоиск(e.target.value)}
          placeholder="Найти по теме" aria-label="Найти конференцию"
          className="h-9 max-w-xs text-base sm:text-sm" />
        <div className="flex gap-1 rounded-md border border-border p-0.5">
          {([['all', 'Все'], ['mine', 'Со мной']] as const).map(([код, имя]) => (
            <button key={код} type="button" onClick={() => setТолько(код)}
              aria-pressed={только === код}
              className={`min-h-8 rounded px-3 text-sm transition-colors ${
                только === код ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent/50'}`}>
              {имя}
            </button>
          ))}
        </div>
      </div>

      {список.isLoading && <p role="status" className="text-sm">Загружаем…</p>}
      {!список.isLoading && !прошедшие.length && (
        <EmptyBlock иконка={History}
          текст={поиск ? 'По этой теме конференций не нашлось' : 'Прошедших конференций пока нет'}
          подсказка="После конференции здесь остаётся строка: кто пришёл, сколько она шла и что записали итогом." />
      )}
      {прошедшие.map(в => (
        <TalkRow key={в.id} meeting={в} companyId={companyId} onChanged={обновить} />
      ))}
    </div>
  )
}
