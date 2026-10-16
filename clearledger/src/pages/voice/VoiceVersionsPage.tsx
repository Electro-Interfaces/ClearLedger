/**
 * «Версии и изменения» — две вкладки (docs/voice-app.html ContactHub, §6).
 *
 * «Версии настроек»: список версий вида (правила приёма, паспорт, хранение),
 * сравнение «было — стало» с подписями по-русски и откат. Откат ничего не стирает:
 * для правил и паспорта он заводит черновик из выбранной версии и открывает его —
 * дальше та же проверка и «Применить» с комментарием. Хранение — короткий документ
 * без своего экрана до волны 2.5, его возвращаем сразу, тоже с комментарием.
 *
 * «Журнал изменений»: всё, что меняли администраторы — настройки, звуки,
 * подключения КЦ и допуск. Пишет узел сам, править его нельзя.
 */
import { useState } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { History, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCompany } from '@/contexts/CompanyContext'
import { useMaxWidth } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { показать } from './draftDoc'
import { когда } from './format'
import { Heading, NodeError } from './parts'
import { ПОДПИСИ_ПАСПОРТА, ПОДПИСИ_ХРАНЕНИЯ } from './passport'
import { ПОДПИСИ_ПРАВИЛ } from './reception'

const ВИДЫ: { kind: voice.ConfigKind; name: string; экран?: string; подписи: Record<string, string> }[] = [
  { kind: 'reception', name: 'Правила приёма', экран: '/voice/reception', подписи: ПОДПИСИ_ПРАВИЛ },
  { kind: 'passport', name: 'Паспорт для КЦ', экран: '/voice/passport', подписи: ПОДПИСИ_ПАСПОРТА },
  { kind: 'policy', name: 'Сроки хранения', подписи: ПОДПИСИ_ХРАНЕНИЯ },
]

const СОСТОЯНИЕ: Record<voice.ConfigState, string> = {
  draft: 'черновик',
  validated: 'черновик, проверен',
  active: 'действует',
  retired: 'заменена',
}

const ИМЯ_ВИДА: Record<string, string> = { reception: 'Правила приёма', passport: 'Паспорт', policy: 'Хранение' }

/** «reception@15,passport@7» → «Правила приёма r15, Паспорт r7». */
function объект(o?: string | null) {
  if (!o) return '—'
  return o.split(',').map(x => {
    const [k, v] = x.split('@')
    return ИМЯ_ВИДА[k] ? `${ИМЯ_ВИДА[k]} ${v === 'draft' ? 'черновик' : `r${v}`}` : x
  }).join(', ')
}

function кто(a?: voice.Actor | null) {
  return a?.name ?? (a?.kind === 'node' ? 'узел' : a?.kind === 'service' ? 'система' : a?.sub ?? '—')
}

/** Подпись поля по пути: точная или ближайшего раздела с хвостом пути. */
function подпись(подписи: Record<string, string>, path: string) {
  if (подписи[path]) return { имя: подписи[path], хвост: '' }
  const р = Object.keys(подписи).filter(k => path.startsWith(`${k}/`)).sort((a, b) => b.length - a.length)[0]
  return р ? { имя: подписи[р], хвост: path.slice(р.length) } : { имя: null, хвост: path }
}

export default function VoiceVersionsPage() {
  const [params, setParams] = useSearchParams()
  const вкладка = params.get('tab') === 'log' ? 'log' : 'rev'
  return (
    <div className="space-y-4 p-4">
      <Heading имя="Версии и изменения"
        подпись="Одна строка на каждое применение: кто, когда и зачем. Откат заводит новую версию — история не стирается." />
      <Tabs value={вкладка} onValueChange={v => { const n = new URLSearchParams(params); n.set('tab', v); setParams(n, { replace: true }) }}>
        <TabsList>
          <TabsTrigger value="rev">Версии настроек</TabsTrigger>
          <TabsTrigger value="log">Журнал изменений</TabsTrigger>
        </TabsList>
        <TabsContent value="rev"><Versions /></TabsContent>
        <TabsContent value="log"><ChangeLog /></TabsContent>
      </Tabs>
    </div>
  )
}

// ——— Версии ———

function Versions() {
  const { companyId } = useCompany()
  const [params, setParams] = useSearchParams()
  const узкий = useMaxWidth(1024)
  const вид = ВИДЫ.find(x => x.kind === params.get('kind')) ?? ВИДЫ[0]
  const выбрана = Number(params.get('v')) || null

  const версии = useInfiniteQuery({
    queryKey: ['voice-versions', companyId, вид.kind],
    queryFn: ({ pageParam }) => voice.configVersions(companyId, вид.kind, { cursor: pageParam || undefined, limit: 50 }),
    initialPageParam: '',
    getNextPageParam: last => last.next ?? undefined,
  })
  const строки = версии.data?.pages.flatMap(p => p.items) ?? []
  const текущая = строки.find(x => x.version === выбрана) ?? строки[0]

  const поставить = (k: string, v: string | null) => {
    const n = new URLSearchParams(params)
    if (v === null) n.delete(k); else n.set(k, v)
    if (k === 'kind') n.delete('v')
    setParams(n, { replace: true })
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Что сравниваем">
        {ВИДЫ.map(x => (
          <button key={x.kind} type="button" aria-pressed={x.kind === вид.kind} onClick={() => поставить('kind', x.kind)}
            className={cn('min-h-8 rounded-md border px-3 text-sm transition-colors',
              x.kind === вид.kind ? 'border-primary bg-primary/10 font-medium text-primary' : 'border-border hover:bg-accent/50')}>
            {x.name}
          </button>
        ))}
      </div>

      {версии.isLoading && <p role="status" className="text-sm">Читаем версии у узла…</p>}
      {версии.isError && <NodeError ошибка={версии.error} что="прочитать версии" />}
      {версии.isSuccess && !строки.length && (
        <EmptyBlock иконка={History} текст="Версий нет" подсказка="Первая версия появляется при первом запуске узла из файла." />
      )}

      {!!строки.length && (
        <div className={cn('grid gap-4', !узкий && 'grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]')}>
          <div className="space-y-2">
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-card text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-normal">Версия</th>
                    <th className="px-3 py-2 font-normal">Состояние</th>
                    <th className="px-3 py-2 font-normal">Кто · когда</th>
                    <th className="px-3 py-2 font-normal">Зачем</th>
                  </tr>
                </thead>
                <tbody>
                  {строки.map(x => (
                    <tr key={x.version} onClick={() => поставить('v', String(x.version))} aria-selected={x === текущая}
                      className={cn('cursor-pointer border-t border-border/60 hover:bg-accent/40', x === текущая && 'bg-primary/5')}>
                      <td className="px-3 py-2 font-mono text-xs">r{x.version}</td>
                      <td className={cn('px-3 py-2', x.state === 'active' && 'font-medium text-success')}>{СОСТОЯНИЕ[x.state]}</td>
                      <td className="px-3 py-2">
                        {кто(x.appliedBy ?? x.createdBy)}
                        <div className="text-xs text-muted-foreground">{когда(x.appliedAt ?? x.createdAt)}</div>
                      </td>
                      <td className="px-3 py-2">
                        {x.comment || <span className="text-muted-foreground">—</span>}
                        {вид.kind === 'passport' && (x.state === 'active' || x.state === 'retired') && (
                          <span className="ml-1.5 rounded-md border border-border px-1.5 text-xs text-muted-foreground">ушло в КЦ</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {версии.hasNextPage && (
              <Button variant="outline" size="sm" onClick={() => версии.fetchNextPage()} disabled={версии.isFetchingNextPage}>
                {версии.isFetchingNextPage ? 'Читаем…' : 'Показать ещё'}
              </Button>
            )}
          </div>
          {текущая && <VersionCard key={`${вид.kind}-${текущая.version}`} вид={вид} в={текущая} строки={строки} />}
        </div>
      )}
    </div>
  )
}

function VersionCard({ вид, в, строки }: {
  вид: (typeof ВИДЫ)[number]
  в: voice.ConfigVersion
  строки: voice.ConfigVersion[]
}) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [зачем, setЗачем] = useState('')
  const [идёт, setИдёт] = useState(false)

  const действующая = строки.find(x => x.state === 'active')
  const черновик = в.state === 'draft' || в.state === 'validated'
  // С чем сравниваем: черновик — с действующей, прочие — с предыдущей версией вида.
  const индекс = строки.indexOf(в)
  const с = черновик ? действующая?.version : строки[индекс + 1]?.version
  const разница = useQuery({
    queryKey: ['voice-diff', companyId, вид.kind, с ?? 0, в.version],
    queryFn: () => voice.configDiff(companyId, вид.kind, с!, в.version),
    enabled: с !== undefined,
  })

  async function откатить() {
    setИдёт(true)
    try {
      if (вид.экран) {
        await voice.configDraft(companyId, вид.kind, { from: в.version, comment: `Откат к r${в.version}` })
        await qc.invalidateQueries({ queryKey: ['voice-config', companyId, вид.kind] })
        await qc.invalidateQueries({ queryKey: ['voice-versions', companyId, вид.kind] })
        toast.success(`Черновик из r${в.version} заведён — проверьте и примените`)
        navigate(вид.экран)
      } else {
        if (!действующая) return
        await voice.configApply(companyId, вид.kind, в.version, действующая.etag ?? `"${действующая.version}"`, зачем.trim())
        await qc.invalidateQueries({ queryKey: ['voice-config', companyId] })
        await qc.invalidateQueries({ queryKey: ['voice-versions', companyId, вид.kind] })
        await qc.invalidateQueries({ queryKey: ['voice-changes', companyId] })
        toast.success(`Сроки хранения r${в.version} снова действуют`)
        setЗачем('')
      }
    } catch (e) {
      toast.error(e instanceof voice.VoiceError && e.code === 'draft_exists'
        ? 'Уже есть черновик: сначала примените или отмените его'
        : e instanceof Error ? e.message : 'Откат не удался')
    } finally {
      setИдёт(false)
    }
  }

  return (
    <section aria-label={`Версия r${в.version}`} className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-start gap-2">
        <div className="mr-auto min-w-0">
          <h2 className="font-headline text-base font-semibold">r{в.version} · {в.comment || СОСТОЯНИЕ[в.state]}</h2>
          <p className="text-xs text-muted-foreground">
            начата {когда(в.createdAt)} · {кто(в.createdBy)}
            {в.appliedAt && <> · применена {когда(в.appliedAt)} · {кто(в.appliedBy)}</>}
          </p>
        </div>
        {черновик && вид.экран && (
          <Button variant="outline" size="sm" onClick={() => navigate(вид.экран!)}>Открыть черновик</Button>
        )}
        {в.state === 'retired' && вид.экран && (
          <Button variant="outline" size="sm" onClick={откатить} disabled={идёт}><RotateCcw />Откатить к r{в.version}</Button>
        )}
      </div>
      {в.state === 'retired' && !вид.экран && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={e => { e.preventDefault(); if (зачем.trim().length >= 3) void откатить() }}>
          <Input value={зачем} onChange={e => setЗачем(e.target.value)} maxLength={500} aria-label="Зачем возвращаем"
            placeholder="Зачем возвращаем — попадёт в журнал изменений" className="min-w-60 flex-1" />
          <Button type="submit" variant="outline" size="sm" disabled={идёт || зачем.trim().length < 3}>
            <RotateCcw />Вернуть r{в.version}
          </Button>
        </form>
      )}

      {с === undefined && <p className="text-sm text-muted-foreground">Первая версия: с ней нечего сравнивать.</p>}
      {разница.isLoading && <p role="status" className="text-sm">Сравниваем…</p>}
      {разница.isError && <NodeError ошибка={разница.error} что="сравнить версии" />}
      {разница.data && (
        разница.data.changes.length === 0
          ? <p className="text-sm text-muted-foreground">С r{с} ничего не изменилось{в.comment?.startsWith('Откат') ? ' — это откат к прежнему содержимому' : ''}.</p>
          : (
            <div className="overflow-x-auto">
              <p className="pb-1 text-xs text-muted-foreground">Было в r{с} → стало в r{в.version}</p>
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr><th className="py-1 pr-3 font-normal">Поле</th><th className="py-1 pr-3 font-normal">Было</th><th className="py-1 font-normal">Стало</th></tr>
                </thead>
                <tbody>
                  {разница.data.changes.map(ch => {
                    const п = подпись(вид.подписи, ch.path)
                    return (
                      <tr key={ch.path} className="border-t border-border/60 align-top">
                        <td className="py-1.5 pr-3">
                          {п.имя ?? <span className="font-mono text-xs">{п.хвост}</span>}
                          {п.имя && п.хвост && <span className="ml-1 font-mono text-xs text-muted-foreground">{п.хвост}</span>}
                        </td>
                        <td className="max-w-56 break-words py-1.5 pr-3 text-muted-foreground">{ch.op === 'add' ? '—' : показать(ch.from)}</td>
                        <td className="max-w-56 break-words py-1.5">{ch.op === 'remove' ? 'убрано' : показать(ch.to)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )
      )}
    </section>
  )
}

// ——— Журнал изменений ———

const ДЕЙСТВИЯ: Record<string, string> = {
  'config.import': 'Импорт из файла',
  'config.draft': 'Правка черновика',
  'config.draft_delete': 'Черновик удалён',
  'config.apply': 'Применено',
  'config.rollback': 'Откат',
  'config.targets': 'Цели перевода',
  'sound.upload': 'Звук загружен',
  'sound.delete': 'Звук удалён',
  'cc.invite': 'Приглашение контакт-центра',
  'cc.activate': 'Контакт-центр включён',
  'cc.state': 'Состояние контакт-центра',
  'cc.operator': 'Допуск оператора',
}

function подробности(з: voice.AuditEntry) {
  const d = (з.detail ?? {}) as Record<string, unknown>
  const части: string[] = []
  if (з.action === 'config.draft' && d.op === 'create') части.push('черновик заведён')
  if (Array.isArray(d.changed)) части.push(`изменено полей: ${d.changed.length}`)
  if (з.action === 'config.rollback' && d.source) части.push(`содержимое r${d.source}`)
  if (Array.isArray(d.codes)) части.push(`цели: ${d.codes.join(', ')}`)
  if (d.breaking) части.push('ломающее для КЦ')
  if (typeof d.state === 'string') части.push(d.state)
  return части.join(' · ')
}

function ChangeLog() {
  const { companyId } = useCompany()
  const [вид, setВид] = useState<voice.ConfigKind | ''>('')
  const журнал = useInfiniteQuery({
    queryKey: ['voice-changes', companyId, вид],
    queryFn: ({ pageParam }) => voice.configChanges(companyId, { kind: вид || undefined, cursor: pageParam || undefined, limit: 100 }),
    initialPageParam: '',
    getNextPageParam: last => last.next ?? undefined,
  })
  const строки = журнал.data?.pages.flatMap(p => p.items) ?? []

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
        что менялось
        <select value={вид} onChange={e => setВид(e.target.value as voice.ConfigKind | '')}
          className="h-9 rounded-md border border-input bg-card px-2 text-sm text-foreground">
          <option value="">всё: настройки, звуки, контакт-центры</option>
          {ВИДЫ.map(x => <option key={x.kind} value={x.kind}>{x.name}</option>)}
        </select>
      </label>

      {журнал.isLoading && <p role="status" className="text-sm">Читаем журнал изменений…</p>}
      {журнал.isError && <NodeError ошибка={журнал.error} что="прочитать журнал изменений" />}
      {журнал.isSuccess && !строки.length && (
        <EmptyBlock иконка={History} текст="Изменений пока нет" подсказка="Сюда попадает каждое действие администратора с узлом." />
      )}
      {!!строки.length && (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-card text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-normal">Когда</th>
                <th className="px-3 py-2 font-normal">Кто</th>
                <th className="px-3 py-2 font-normal">Что</th>
                <th className="px-3 py-2 font-normal">Подробности</th>
                <th className="px-3 py-2 font-normal">Откуда</th>
              </tr>
            </thead>
            <tbody>
              {строки.map(з => (
                <tr key={з.id} className="border-t border-border/60 align-top">
                  <td className="whitespace-nowrap px-3 py-2">{когда(з.at)}</td>
                  <td className="px-3 py-2">{кто(з.actor)}</td>
                  <td className="px-3 py-2">
                    {ДЕЙСТВИЯ[з.action] ?? <span className="font-mono text-xs">{з.action}</span>}
                    <div className="text-xs text-muted-foreground">{объект(з.object)}</div>
                  </td>
                  <td className="px-3 py-2">
                    {з.reason && <span>«{з.reason}»</span>}
                    {подробности(з) && <div className="text-xs text-muted-foreground">{подробности(з)}</div>}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{з.ip ?? '—'}</td>
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
  )
}
