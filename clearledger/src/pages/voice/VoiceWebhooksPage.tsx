/**
 * «Системы и вебхуки» — как системы заказчика (учёт, CRM, заявочная) получают данные узла.
 *
 * Два пути. Получатели событий — узел сам шлёт события на адрес системы (`/webhooks`):
 * подпись по Standard Webhooks, повторы до 7 суток, журнал доставок. Адрес — только из
 * белого списка узла. Ключи систем — система сама спрашивает статистику и журнал доступа:
 * ключ выдаёт Ядро пространства (Я-10), система меняет его на короткий служебный токен
 * и ходит в API узла через кромку стека. Секрет и ключ показываются один раз.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Check, Copy, KeyRound, Plus, Trash2, Webhook } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { когда } from './format'
import { Heading, NodeError } from './parts'

const СОБЫТИЕ: Record<voice.EventType, string> = {
  'call.completed': 'звонок закончился',
  'call.recording_ready': 'запись готова',
  'call.transcript_ready': 'расшифровка готова',
  'callback.closed': 'задача «перезвонить» закрыта',
  'alert.raised': 'тревога поднята',
  'alert.cleared': 'тревога снята',
  'config.applied': 'применены настройки',
  'audit.recorded': 'строка журнала доступа',
}

const ПО_УМОЛЧАНИЮ: voice.EventType[] = ['call.completed', 'callback.closed', 'alert.raised', 'alert.cleared']

const ДОСТАВКА: Record<voice.Delivery['state'], string> = { pending: 'ждёт повтора', delivered: 'доставлено', failed: 'прекращено' }

function ошибкаДоставки(e?: string | null) {
  if (!e) return null
  if (e.startsWith('http_')) return `получатель ответил ${e.slice(5)}`
  return ({ timeout: 'получатель не ответил вовремя', network: 'не удалось соединиться', host_not_allowed: 'адрес вне белого списка' } as Record<string, string>)[e] ?? e
}

const ОБЛАСТЬ: Record<voice.KeyScope, { имя: string; что: string }> = {
  'voice.stats': { имя: 'Статистика и состояние узла', что: 'показатели линии, ряды и состояние частей узла; номеров и звука нет' },
  'voice.audit': { имя: 'Журнал доступа', что: 'кто открывал номера, записи и расшифровки — для службы безопасности' },
}

/** Секрет или ключ — один раз: после закрытия его не увидеть, только выпустить новый. */
function ShownOnce({ заголовок, текст, значение, onClose }: { заголовок: string; текст: string; значение: string; onClose: () => void }) {
  const [скопирован, setСкопирован] = useState(false)
  return (
    <section aria-label={заголовок} className="space-y-2 rounded-xl border border-primary/35 bg-card p-4">
      <h3 className="font-headline text-base font-semibold">{заголовок}</h3>
      <p className="text-sm">{текст}</p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="max-w-full break-all rounded-md border border-border bg-background px-3 py-2 font-mono text-sm">{значение}</code>
        <Button variant="outline" size="sm" onClick={async () => {
          try { await navigator.clipboard.writeText(значение); setСкопирован(true) } catch { toast.error('Не удалось скопировать — выделите вручную') }
        }}>{скопирован ? <Check /> : <Copy />}{скопирован ? 'Скопирован' : 'Скопировать'}</Button>
        <Button variant="ghost" size="sm" onClick={onClose}>Я сохранил</Button>
      </div>
    </section>
  )
}

export default function VoiceWebhooksPage() {
  const [params, setParams] = useSearchParams()
  const вкладка = params.get('tab') === 'keys' ? 'keys' : 'hooks'
  return (
    <div className="space-y-4 p-4">
      <Heading имя="Системы и вебхуки"
        подпись="Как учёт, CRM или заявочная система заказчика получают данные узла: события на свой адрес или запросы по ключу." />
      <Tabs value={вкладка} onValueChange={v => { const n = new URLSearchParams(params); n.set('tab', v); setParams(n, { replace: true }) }}>
        <TabsList>
          <TabsTrigger value="hooks">Получатели событий</TabsTrigger>
          <TabsTrigger value="keys">Ключи систем</TabsTrigger>
        </TabsList>
        <TabsContent value="hooks"><Hooks /></TabsContent>
        <TabsContent value="keys"><Keys /></TabsContent>
      </Tabs>
    </div>
  )
}

// ——— Получатели событий ———

function Hooks() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const список = useQuery({ queryKey: ['voice-webhooks', companyId], queryFn: () => voice.webhooks(companyId) })
  // Без WEBHOOK_ALLOWED_HOSTS узел вебхуки не шлёт и получателя не примет: говорим это до попытки.
  const узел = useQuery({ queryKey: ['voice-node', companyId], queryFn: () => voice.nodeInfo(companyId), refetchInterval: 5 * 60_000 })
  const выключены = узел.data?.features?.webhooks === false
  const [адрес, setАдрес] = useState('')
  const [типы, setТипы] = useState<voice.EventType[]>(ПО_УМОЛЧАНИЮ)
  const [секрет, setСекрет] = useState<{ url: string; secret: string } | null>(null)
  const [идёт, setИдёт] = useState(false)
  const все = список.data?.items ?? []

  let годен = false
  try { const u = new URL(адрес.trim()); годен = (u.protocol === 'https:' || u.protocol === 'http:') && !u.username && !u.password } catch { годен = false }

  async function добавить(e: React.FormEvent) {
    e.preventDefault()
    if (!годен || !типы.length || выключены) return
    setИдёт(true)
    try {
      const w = await voice.addWebhook(companyId, адрес.trim(), типы)
      setСекрет({ url: w.url, secret: w.secret })
      setАдрес('')
      await qc.invalidateQueries({ queryKey: ['voice-webhooks', companyId] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Получатель не добавлен')
    } finally {
      setИдёт(false)
    }
  }

  return (
    <div className="space-y-4 pt-2">
      {секрет && (
        <ShownOnce заголовок="Секрет подписи" значение={секрет.secret} onClose={() => setСекрет(null)}
          текст={`Передайте секрет тем, кто настраивает приём на ${секрет.url}. Им система проверяет подпись каждого события. Секрет показывается один раз.`} />
      )}

      {выключены && (
        <div role="status" className="flex gap-2 rounded-xl border border-warning/50 bg-warning/5 p-4 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <div className="space-y-1">
            <p className="font-medium">Вебхуки на узле выключены: WEBHOOK_ALLOWED_HOSTS не задан</p>
            <p className="text-muted-foreground">
              Получателя добавить нельзя, и события никуда не уходят. Белый список хостов задаёт тот, кто ставит узел: после него и перезапуска узла можно добавлять получателей.
            </p>
          </div>
        </div>
      )}

      <form onSubmit={добавить} className="space-y-3 rounded-xl border border-border bg-card p-4">
        <h3 className="font-headline text-base font-semibold">Добавить получателя</h3>
        <label className="block space-y-1 text-xs text-muted-foreground">
          <span className="block">Адрес приёма событий</span>
          <Input value={адрес} onChange={e => setАдрес(e.target.value)} inputMode="url" placeholder="https://crm.example.ru/hooks/voice"
            className="font-mono" aria-invalid={!!адрес && !годен} />
        </label>
        <p className="text-xs text-muted-foreground">
          Только https и только хосты из белого списка узла: его задаёт тот, кто ставит узел. Перенаправления узел не выполняет.
        </p>
        <fieldset className="space-y-1.5">
          <legend className="text-xs text-muted-foreground">Какие события слать</legend>
          <div className="flex flex-wrap gap-1.5">
            {(Object.keys(СОБЫТИЕ) as voice.EventType[]).map(t => {
              const вкл = типы.includes(t)
              return (
                <button key={t} type="button" aria-pressed={вкл} onClick={() => setТипы(вкл ? типы.filter(x => x !== t) : [...типы, t])}
                  className={cn('rounded-md border px-2 py-1 text-xs transition-colors',
                    вкл ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-accent/50')}>
                  {СОБЫТИЕ[t]}
                </button>
              )
            })}
          </div>
        </fieldset>
        <Button type="submit" size="sm" disabled={!годен || !типы.length || идёт || выключены}><Plus />{идёт ? 'Добавляем…' : 'Добавить'}</Button>
      </form>

      {список.isLoading && <p role="status" className="text-sm">Читаем получателей у узла…</p>}
      {список.isError && <NodeError ошибка={список.error} что="прочитать получателей событий" />}
      {список.isSuccess && !все.length && (
        <EmptyBlock иконка={Webhook} текст="Получателей событий нет"
          подсказка="События узла заводятся только после того, как добавлен получатель: прежние звонки задним числом не придут." />
      )}
      {!!все.length && <ul className="space-y-2">{все.map(w => <HookRow key={w.id} w={w} />)}</ul>}

      <details className="rounded-xl border border-border bg-card p-4 text-sm">
        <summary className="cursor-pointer font-medium">Как система проверяет события</summary>
        <div className="space-y-1.5 pt-2 text-muted-foreground">
          <p>Узел шлёт POST с телом CloudEvents 1.0 и заголовками Standard Webhooks: webhook-id, webhook-timestamp и webhook-signature.</p>
          <p>Подпись — v1 и base64 HMAC-SHA256 над строкой «id.timestamp.тело» ключом из секрета (часть после whsec_, в base64).</p>
          <p>Успех — любой ответ 2xx. Иначе узел повторяет через 1, 2, 5, 10 и 30 минут, затем раз в час, и через 7 суток прекращает.
            Одно событие может прийти дважды: система отсеивает повторы по webhook-id.</p>
        </div>
      </details>
    </div>
  )
}

function HookRow({ w }: { w: voice.Webhook }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [открыт, setОткрыт] = useState(false)
  const [удалить, setУдалить] = useState(false)
  const доставки = useQuery({
    queryKey: ['voice-webhook-deliveries', companyId, w.id],
    queryFn: () => voice.webhookDeliveries(companyId, w.id, 100),
    enabled: открыт,
  })
  const плохо = w.lastStatus != null && (w.lastStatus < 200 || w.lastStatus >= 300)

  async function убрать() {
    try {
      await voice.deleteWebhook(companyId, w.id)
      toast.success('Получатель удалён')
      await qc.invalidateQueries({ queryKey: ['voice-webhooks', companyId] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Получатель не удалён')
    }
  }

  return (
    <li className="space-y-2 rounded-xl border border-border bg-card p-3 text-sm">
      <div className="flex flex-wrap items-start gap-2">
        <div className="mr-auto min-w-0">
          <p className="break-all font-mono text-xs">{w.url}</p>
          <p className="text-xs text-muted-foreground">{w.types.map(t => СОБЫТИЕ[t] ?? t).join(', ')}</p>
          <p className={cn('text-xs', плохо ? 'text-warning' : 'text-muted-foreground')}>
            {w.lastDeliveredAt ? `доставлено ${когда(w.lastDeliveredAt)}` : 'ещё ничего не доставлено'}
            {w.lastStatus != null && ` · последний ответ ${w.lastStatus}`}
            {!!w.pending && ` · ждут доставки ${w.pending}`}
            {` · добавлен ${когда(w.createdAt)}`}
          </p>
        </div>
        <Button variant="outline" size="sm" aria-expanded={открыт} onClick={() => setОткрыт(!открыт)}>{открыт ? 'Скрыть доставки' : 'Доставки'}</Button>
        {!удалить && <Button variant="outline" size="sm" aria-label="Удалить получателя" onClick={() => setУдалить(true)}><Trash2 /></Button>}
      </div>
      {удалить && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2">
          <span>Удалить получателя? Недоставленные ему события удалятся вместе с ним.</span>
          <Button size="sm" variant="destructive" onClick={() => void убрать()}>Удалить</Button>
          <Button size="sm" variant="ghost" onClick={() => setУдалить(false)}>Нет</Button>
        </div>
      )}
      {открыт && (
        <div className="space-y-1">
          {доставки.isLoading && <p role="status" className="text-xs">Читаем доставки…</p>}
          {доставки.isError && <NodeError ошибка={доставки.error} что="прочитать доставки" />}
          {доставки.data && !доставки.data.items.length && <p className="text-xs text-muted-foreground">Событий этому получателю ещё не было.</p>}
          {!!доставки.data?.items.length && (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-xs">
                <thead className="bg-background text-left text-muted-foreground">
                  <tr>
                    <th className="px-2 py-1.5 font-normal">Событие</th>
                    <th className="px-2 py-1.5 font-normal">Заведено</th>
                    <th className="px-2 py-1.5 font-normal">Итог</th>
                    <th className="px-2 py-1.5 text-right font-normal">Попыток</th>
                    <th className="px-2 py-1.5 font-normal">Что дальше</th>
                  </tr>
                </thead>
                <tbody>
                  {доставки.data.items.map(д => (
                    <tr key={д.eventId} className="border-t border-border/60 align-top">
                      <td className="px-2 py-1.5">{СОБЫТИЕ[д.type] ?? д.type}</td>
                      <td className="whitespace-nowrap px-2 py-1.5">{когда(д.at)}</td>
                      <td className={cn('px-2 py-1.5', д.state === 'failed' && 'text-destructive', д.state === 'pending' && 'text-warning')}>
                        {ДОСТАВКА[д.state]}{ошибкаДоставки(д.error) && `: ${ошибкаДоставки(д.error)}`}
                      </td>
                      <td className="px-2 py-1.5 text-right tabular-nums">{д.attempts}</td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-muted-foreground">
                        {д.state === 'delivered' && д.deliveredAt ? когда(д.deliveredAt)
                          : д.state === 'pending' && д.nextAt ? `повтор ${когда(д.nextAt)}` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-muted-foreground">Тела событий узел здесь не показывает: только тип, время и итог.</p>
        </div>
      )}
    </li>
  )
}

// ——— Ключи систем (Ядро, Я-10) ———

function Keys() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const ключи = useQuery({ queryKey: ['voice-system-keys', companyId], queryFn: () => voice.systemKeys(companyId), retry: false })
  const [кому, setКому] = useState('')
  const [области, setОбласти] = useState<voice.KeyScope[]>(['voice.stats'])
  const [выдан, setВыдан] = useState<{ consumer: string; key: string } | null>(null)
  const [отозвать, setОтозвать] = useState<string | null>(null)
  const [идёт, setИдёт] = useState(false)
  const нет = ключи.isSuccess && ключи.data === null
  const все = ключи.data ?? []
  const обновить = () => qc.invalidateQueries({ queryKey: ['voice-system-keys', companyId] })

  async function выдать(e: React.FormEvent) {
    e.preventDefault()
    if (кому.trim().length < 2 || !области.length) return
    setИдёт(true)
    try {
      const r = await voice.createSystemKey(companyId, кому.trim(), области)
      setВыдан({ consumer: r.consumer, key: r.key })
      setКому('')
      await обновить()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ключ не выдан')
    } finally {
      setИдёт(false)
    }
  }

  async function отозватьКлюч(id: string) {
    try {
      await voice.revokeSystemKey(companyId, id)
      toast.success('Ключ отозван: система больше не получит по нему токен')
      setОтозвать(null)
      await обновить()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ключ не отозван')
    }
  }

  return (
    <div className="space-y-4 pt-2">
      {нет && (
        <div className="space-y-1 rounded-xl border border-border bg-card p-4 text-sm">
          <p className="font-medium">Ключи систем выдаёт Ядро пространства, а в этом пространстве их выдача ещё не включена.</p>
          <p className="text-muted-foreground">
            Она появится с доработкой Ядра для «Телефонии» (Я-10). Пока систему заказчика можно подключить к событиям узла на вкладке «Получатели событий».
          </p>
        </div>
      )}
      {ключи.isError && <NodeError ошибка={ключи.error} что="прочитать ключи систем" />}
      {выдан && (
        <ShownOnce заголовок={`Ключ для «${выдан.consumer}»`} значение={выдан.key} onClose={() => setВыдан(null)}
          текст="Передайте ключ тем, кто настраивает систему. Ключ показывается один раз; потерян — отзовите и выдайте новый." />
      )}

      {!нет && ключи.isSuccess && (
        <form onSubmit={выдать} className="space-y-3 rounded-xl border border-border bg-card p-4">
          <h3 className="font-headline text-base font-semibold">Выдать ключ</h3>
          <label className="block space-y-1 text-xs text-muted-foreground">
            <span className="block">Для какой системы</span>
            <Input value={кому} onChange={e => setКому(e.target.value)} maxLength={200} placeholder="CRM отдела продаж" />
          </label>
          <fieldset className="space-y-1.5">
            <legend className="text-xs text-muted-foreground">Что система сможет читать</legend>
            {(Object.keys(ОБЛАСТЬ) as voice.KeyScope[]).map(o => (
              <label key={o} className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={области.includes(o)}
                  onChange={e => setОбласти(e.target.checked ? [...области, o] : области.filter(x => x !== o))} />
                <span><span className="font-medium">{ОБЛАСТЬ[o].имя}</span> <span className="text-muted-foreground">— {ОБЛАСТЬ[o].что}</span></span>
              </label>
            ))}
          </fieldset>
          <Button type="submit" size="sm" disabled={кому.trim().length < 2 || !области.length || идёт}><KeyRound />{идёт ? 'Выдаём…' : 'Выдать ключ'}</Button>
        </form>
      )}

      {ключи.isLoading && <p role="status" className="text-sm">Читаем ключи у Ядра…</p>}
      {ключи.isSuccess && !нет && !все.length && (
        <EmptyBlock иконка={KeyRound} текст="Ключей пока нет" подсказка="Каждой системе — свой ключ: видно, кто и когда ходил, и любой можно отозвать, не задев остальные." />
      )}
      {!!все.length && (
        <ul className="space-y-2">
          {все.map(k => (
            <li key={k.id} className={cn('space-y-1 rounded-xl border border-border bg-card p-3 text-sm', k.revoked_at && 'opacity-60')}>
              <div className="flex flex-wrap items-start gap-2">
                <div className="mr-auto min-w-0">
                  <p className="font-medium">{k.consumer} <span className="font-mono text-xs font-normal text-muted-foreground">{k.prefix}…</span></p>
                  <p className="text-xs text-muted-foreground">{k.scopes.map(o => ОБЛАСТЬ[o]?.имя ?? o).join(', ')}</p>
                  <p className="text-xs text-muted-foreground">
                    {k.revoked_at ? `отозван ${когда(k.revoked_at)}` : k.last_used_at ? `последний раз ходила ${когда(k.last_used_at)}` : 'ещё не ходила'}
                    {k.created_at && ` · выдан ${когда(k.created_at)}`}
                  </p>
                </div>
                {!k.revoked_at && отозвать !== k.id && <Button variant="outline" size="sm" onClick={() => setОтозвать(k.id)}>Отозвать</Button>}
              </div>
              {отозвать === k.id && (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2">
                  <span>Отозвать ключ? Система сразу перестанет получать данные.</span>
                  <Button size="sm" variant="destructive" onClick={() => void отозватьКлюч(k.id)}>Отозвать</Button>
                  <Button size="sm" variant="ghost" onClick={() => setОтозвать(null)}>Нет</Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <details className="rounded-xl border border-border bg-card p-4 text-sm">
        <summary className="cursor-pointer font-medium">Как система пользуется ключом</summary>
        <div className="space-y-1.5 pt-2 text-muted-foreground">
          <p>Система меняет ключ на служебный токен Ядра — он живёт не дольше двух минут — и с ним спрашивает узел через пространство:
            /voice/api/v1/stats/summary, /stats/series, /health или /audit, смотря что разрешено ключу.</p>
          <p>Номеров звонящих, записей и расшифровок по ключу не получить: их открывает только администратор, по причине и с записью в журнал доступа.</p>
        </div>
      </details>
    </div>
  )
}
