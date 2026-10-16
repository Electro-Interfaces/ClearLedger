/**
 * «Аудит доступа» — кто открывал номер, запись и расшифровку, кто выгружал журнал: когда,
 * какой звонок, по какой причине и с какого адреса.
 *
 * Журнал узла только дописывается: строки не правятся и не удаляются (это держит триггер
 * в базе узла). По умолчанию экран показывает доступ к данным звонящих; «Все действия» —
 * ещё и настройки, подключения и чистки. Выгрузка — то, что загружено на экран, с
 * фильтрами первой строкой.
 */
import { useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Download, FileSpreadsheet, Search, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { скачатьCSV, скачатьExcel, type Лист } from './exportTable'
import { ДЕЙСТВИЕ_АУДИТА, деньФайла, когда, ктоСделал, началоДня } from './format'
import { Heading, NodeError } from './parts'

const ПЕРИОДЫ = [
  { key: 'today', name: 'Сегодня', дней: 0 },
  { key: 'week', name: '7 дней', дней: 6 },
  { key: 'month', name: '30 дней', дней: 29 },
  { key: 'year', name: 'Год', дней: 364 },
] as const

/** Доступ к данным звонящего: то, ради чего экран открывают. */
const ДОСТУП = ['call.number', 'call.search_number', 'recording.ticket', 'recording.play', 'recording.download',
  'transcript.read', 'journal.export', 'recording.delete', 'call.view']

const ВСЕ = Object.keys(ДЕЙСТВИЕ_АУДИТА)

/** Подробность строки без ПДн: сколько строк выгружено, маской ли, сколько удалено. */
function подробность(з: voice.AuditEntry) {
  const d = (з.detail ?? {}) as Record<string, unknown>
  const ч: string[] = []
  if (з.action === 'journal.export') {
    if (typeof d.rows === 'number') ч.push(`${d.rows} строк`)
    if (d.numbers === 'full') ч.push('номера целиком')
    else if (d.numbers) ч.push('номера маской')
  }
  if (з.action === 'purge.run') {
    if (typeof d.recordings === 'number') ч.push(`записей ${d.recordings}`)
    if (typeof d.transcripts === 'number') ч.push(`расшифровок ${d.transcripts}`)
    if (typeof d.numbers === 'number') ч.push(`номеров ${d.numbers}`)
  }
  if (з.action === 'call.search_number') {
    if (typeof d.number === 'string') ч.push(`цифры ${d.number}`)
    if (typeof d.found === 'number') ч.push(`найдено ${d.found}`)
  }
  if (з.action === 'recording.delete') {
    if (typeof d.recordings === 'number') ч.push(`записей ${d.recordings}`)
    if (typeof d.segments === 'number') ч.push(`фраз ${d.segments}`)
  }
  if (з.action === 'retention.hold' && typeof d.until === 'string') ч.push(`до ${d.until}`)
  return ч.join(', ')
}

/** У этих действий объект — № звонка: ведём ссылкой в журнал. У прочих — версия настроек, звук, подключение. */
const ПРО_ЗВОНОК = /^(call\.(view|number)|transcript\.|recording\.|retention\.|callback\.cancel)/
const звонок = (з: voice.AuditEntry) => !!з.object && ПРО_ЗВОНОК.test(з.action)

export default function VoiceAuditPage() {
  const { companyId } = useCompany()
  const [период, setПериод] = useState<(typeof ПЕРИОДЫ)[number]['key']>('week')
  const [действие, setДействие] = useState('')
  const [толькоДоступ, setТолькоДоступ] = useState(true)
  const [кто, setКто] = useState('')
  const [набор, setНабор] = useState('')
  const [номерЗвонка, setНомерЗвонка] = useState('')

  const п = ПЕРИОДЫ.find(x => x.key === период) ?? ПЕРИОДЫ[1]
  const from = началоДня(-п.дней)

  const журнал = useInfiniteQuery({
    queryKey: ['voice-audit', companyId, 'screen', from, действие, кто, номерЗвонка],
    queryFn: ({ pageParam }) => voice.audit(companyId, {
      from, action: действие || undefined, actor: кто || undefined, contactId: номерЗвонка || undefined,
      cursor: pageParam || undefined, limit: 200,
    }),
    initialPageParam: '',
    getNextPageParam: last => last.next ?? undefined,
  })
  const загружено = журнал.data?.pages.flatMap(p => p.items) ?? []
  // Отбор «только доступ к данным» — на экране: узел фильтрует по одному действию.
  const строки = !действие && толькоДоступ ? загружено.filter(з => ДОСТУП.includes(з.action)) : загружено

  // Люди для фильтра — из загруженного: узел сам списка не отдаёт.
  const люди = new Map<string, string>()
  for (const з of загружено) if (з.actor.sub) люди.set(з.actor.sub, ктоСделал(з.actor))
  if (кто && !люди.has(кто)) люди.set(кто, кто)

  function искать(e: React.FormEvent) {
    e.preventDefault()
    setНомерЗвонка(набор.trim())
  }

  function лист(): Лист {
    const фильтры = [`Период: ${п.name}`, действие ? `действие: ${ДЕЙСТВИЕ_АУДИТА[действие] ?? действие}` : толькоДоступ ? 'доступ к данным звонящих' : 'все действия',
      кто ? `кто: ${люди.get(кто) ?? кто}` : '', номерЗвонка ? `звонок: ${номерЗвонка}` : ''].filter(Boolean).join('; ')
    return {
      имя: 'Аудит доступа',
      строки: [
        [фильтры],
        ['Когда', 'Кто', 'Вид входа', 'Действие', 'Объект', 'Причина', 'Подробности', 'Адрес'],
        ...строки.map(з => [new Date(з.at).toLocaleString('ru-RU'), ктоСделал(з.actor), з.actor.kind ?? '',
          ДЕЙСТВИЕ_АУДИТА[з.action] ?? з.action, з.object ?? '', з.reason ?? '', подробность(з), з.ip ?? '']),
      ],
    }
  }
  const файл = () => `телефония-аудит-${деньФайла(from)}_${деньФайла(Date.now())}`

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Аудит доступа" подпись="Кто открывал номер, запись и расшифровку, кто выгружал журнал: когда, какой звонок и почему.">
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={!строки.length} onClick={() => скачатьCSV(файл(), [лист()])}><Download />CSV</Button>
          <Button variant="outline" size="sm" disabled={!строки.length}
            onClick={() => void скачатьExcel(файл(), [лист()]).catch(() => toast.error('Excel не собрался, выгрузите CSV'))}>
            <FileSpreadsheet />Excel
          </Button>
        </div>
      </Heading>

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
          действие
          <select value={действие} onChange={e => setДействие(e.target.value)}
            className="h-9 max-w-56 rounded-md border border-input bg-card px-2 text-sm text-foreground">
            <option value="">{толькоДоступ ? 'доступ к данным звонящих' : 'все действия'}</option>
            <optgroup label="Доступ к данным звонящих">
              {ДОСТУП.map(a => <option key={a} value={a}>{ДЕЙСТВИЕ_АУДИТА[a]}</option>)}
            </optgroup>
            <optgroup label="Настройки и подключения">
              {ВСЕ.filter(a => !ДОСТУП.includes(a)).map(a => <option key={a} value={a}>{ДЕЙСТВИЕ_АУДИТА[a]}</option>)}
            </optgroup>
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          кто
          <select value={кто} onChange={e => setКто(e.target.value)}
            className="h-9 max-w-48 rounded-md border border-input bg-card px-2 text-sm text-foreground">
            <option value="">все</option>
            {[...люди].sort((a, b) => a[1].localeCompare(b[1], 'ru')).map(([sub, имя]) => <option key={sub} value={sub}>{имя}</option>)}
          </select>
        </label>
        <form onSubmit={искать} className="flex items-center gap-1.5">
          <Input value={набор} onChange={e => setНабор(e.target.value)} aria-label="№ звонка" placeholder="№ звонка" className="h-9 w-44 font-mono" />
          <Button type="submit" variant="outline" size="sm"><Search />Найти</Button>
          {номерЗвонка && <Button type="button" variant="ghost" size="sm" onClick={() => { setНабор(''); setНомерЗвонка('') }}>Сбросить</Button>}
        </form>
      </div>
      {!действие && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={!толькоДоступ} onChange={e => setТолькоДоступ(!e.target.checked)} />
          Показать и остальные действия: настройки, подключения, чистку по сроку
        </label>
      )}

      {журнал.isLoading && <p role="status" className="text-sm">Читаем журнал доступа узла…</p>}
      {журнал.isError && <NodeError ошибка={журнал.error} что="прочитать журнал доступа" />}
      {журнал.isSuccess && !строки.length && !журнал.hasNextPage && (
        <EmptyBlock иконка={ShieldCheck} текст="За этот период таких строк нет"
          подсказка="Каждое открытие номера, записи и расшифровки узел пишет сюда вместе с причиной." />
      )}
      {журнал.isSuccess && !строки.length && журнал.hasNextPage && (
        <p className="text-sm text-muted-foreground">В загруженных {загружено.length} строках журнала доступа к данным звонящих нет — загрузите ещё.</p>
      )}

      {!!строки.length && (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[50rem] text-sm">
            <thead className="bg-card text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-normal">Когда</th>
                <th className="px-3 py-2 font-normal">Кто</th>
                <th className="px-3 py-2 font-normal">Действие</th>
                <th className="px-3 py-2 font-normal">Звонок или объект</th>
                <th className="px-3 py-2 font-normal">Причина</th>
                <th className="px-3 py-2 font-normal">Адрес</th>
              </tr>
            </thead>
            <tbody>
              {строки.map(з => (
                <tr key={з.id} className="border-t border-border/60 align-top">
                  <td className="whitespace-nowrap px-3 py-2">{когда(з.at)}</td>
                  <td className="min-w-32 px-3 py-2">{ктоСделал(з.actor)}</td>
                  <td className="min-w-36 px-3 py-2">
                    {ДЕЙСТВИЕ_АУДИТА[з.action] ?? <span className="font-mono text-xs">{з.action}</span>}
                    {подробность(з) && <span className="block text-xs text-muted-foreground">{подробность(з)}</span>}
                  </td>
                  <td className="px-3 py-2">
                    {звонок(з)
                      ? <Link to={`/voice/calls?id=${encodeURIComponent(з.object!)}`} className="font-mono text-xs text-primary hover:underline">{з.object}</Link>
                      : <span className="font-mono text-xs text-muted-foreground">{з.object ?? '—'}</span>}
                  </td>
                  <td className="min-w-48 max-w-80 px-3 py-2">{з.reason ?? <span className="text-muted-foreground">—</span>}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-muted-foreground">{з.ip ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {журнал.hasNextPage && (
          <Button variant="outline" size="sm" onClick={() => журнал.fetchNextPage()} disabled={журнал.isFetchingNextPage}>
            {журнал.isFetchingNextPage ? 'Читаем…' : 'Показать ещё'}
          </Button>
        )}
        {журнал.isSuccess && (
          <p className="text-xs text-muted-foreground">
            Показано {строки.length}{строки.length !== загружено.length && ` из ${загружено.length} загруженных`}. Выгрузка берёт показанное.
            Журнал узла только дописывается: строки нельзя изменить или удалить.
          </p>
        )}
      </div>
    </div>
  )
}
