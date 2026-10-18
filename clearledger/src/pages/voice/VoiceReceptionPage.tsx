/**
 * «Правила приёма» — всё, что раньше правили руками в *.reception.json, по вкладкам
 * на языке звонящего (docs/voice-app.html ContactHub, §5).
 *
 * Правка любого поля заводит черновик; действующие правила не меняются до
 * «Проверить» → «Применить» с комментарием. Изменённое поле подписано «было …».
 * Главная подсказка — шкала ожидания на вкладках очереди и обратного звонка:
 * на одной оси цель SLA, объявления позиции, «нажмите 1» и запасной сценарий.
 *
 * Технические ссылки на звуки (sound:…) и строка набора — под «Подробнее»: их
 * трогают редко, а экран «Звуки» с библиотекой записей придёт в волне 2.5.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { Plus, Settings2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { CheckResult, DraftBar, Field, NumberInput } from './DraftParts'
import { записать } from './draftDoc'
import { useDraft, type Черновик } from './useDraft'
import { More, RemoveButton, TextInput } from './FormBits'
import { HoursEditor } from './HoursEditor'
import { Heading, NodeError } from './parts'
import { SimulatePanel } from './Simulate'
import { ПРИЧИНА_ПРОПУСКА } from './format'
import {
  КОМАНДЫ, ПОДПИСИ_ПРАВИЛ, УМОЛЧАНИЯ, звукиВ, звукиИз, кНомеру,
  type ПравилаПриёма, type Цель,
} from './reception'

const ВКЛАДКИ = [
  { key: 'hours', name: 'Часы и линия', поля: ['/lineName', '/slaTargetSec', '/hours', '/greeting', '/mohClass', '/operators'] },
  { key: 'vip', name: 'VIP и повторы', поля: ['/vip', '/repeatWithinMin', '/priority'] },
  { key: 'queue', name: 'Очередь и ожидание', поля: ['/queueAnnounceFirstSec', '/queueAnnounceSec', '/queueAnnounceSound', '/agentLostSound'] },
  { key: 'callback', name: 'Обратный звонок', поля: ['/callbackOfferSec', '/callbackLeadSec', '/callbackOfferSound', '/callbackConfirmSound', '/callbackRetryMin', '/callbackMaxAttempts', '/callbackRingSec', '/callbackDial', '/callbackCallerId', '/missedCallback'] },
  { key: 'fallback', name: 'Вне часов и запасной сценарий', поля: ['/afterHoursTarget', '/targets'] },
  { key: 'topics', name: 'Темы', поля: ['/topics'] },
  { key: 'controls', name: 'Пульт оператора', поля: ['/operatorControls'] },
] as const

type Вкладка = (typeof ВКЛАДКИ)[number]['key']

interface Части {
  т: ПравилаПриёма
  ч: Черновик<ПравилаПриёма>
  поставить: (ключи: string[], значение: unknown) => void
}

export default function VoiceReceptionPage() {
  const { companyId } = useCompany()
  const [params, setParams] = useSearchParams()
  const ч = useDraft<ПравилаПриёма>('reception')
  const паспорт = useQuery({
    queryKey: ['voice-config', companyId, 'passport', 'active'],
    queryFn: async () => (await voice.configActive(companyId, 'passport')).data,
  })
  const вкладка = (ВКЛАДКИ.find(x => x.key === params.get('tab'))?.key ?? 'hours') as Вкладка

  const т = ч.тело
  const поставить = (ключи: string[], значение: unknown) => ч.изменить(b => записать(b, ключи, значение))
  const fb = (паспорт.data?.body as { fallback?: { maxTotalSec?: number; target?: string } } | undefined)?.fallback
  const потолок = fb?.maxTotalSec ?? УМОЛЧАНИЯ.fallbackMaxTotalSec

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Правила приёма"
        подпись="Как узел принимает звонок до оператора: часы, VIP, ожидание, обратный звонок и запасной сценарий." />

      {ч.загрузка && <p role="status" className="text-sm">Читаем правила у узла…</p>}
      {!!ч.ошибка && <NodeError ошибка={ч.ошибка} что="прочитать правила приёма" />}
      {!ч.загрузка && !ч.ошибка && !т && (
        <EmptyBlock иконка={Settings2} текст="У узла нет действующих правил приёма"
          подсказка="Правила появляются при первом запуске узла из файла *.reception.json." />
      )}

      {т && (
        <>
          <DraftBar ч={ч} примечание="контакт-центр правил не видит" />
          <CheckResult ч={ч} подписи={ПОДПИСИ_ПРАВИЛ} последствия={[
            'Применится без перезапуска узла: со следующего звонка. Звонки, которые уже идут, доживут по прежним правилам.',
          ]} />

          <SimulatePanel kind="reception" ч={ч} />

          <Tabs value={вкладка} onValueChange={v => { const n = new URLSearchParams(params); n.set('tab', v); setParams(n, { replace: true }) }}>
            <TabsList>
              {ВКЛАДКИ.map(в => {
                const есть = ч.изменено.some(x => в.поля.some(п => x.path === п || x.path.startsWith(`${п}/`)))
                return (
                  <TabsTrigger key={в.key} value={в.key}>
                    {в.name}{есть && <span className="text-primary" aria-label="есть изменения"> ·</span>}
                  </TabsTrigger>
                )
              })}
            </TabsList>
            <div className="rounded-xl border border-border bg-card px-4">
              <TabsContent value="hours"><HoursTab т={т} ч={ч} поставить={поставить} /></TabsContent>
              <TabsContent value="vip"><VipTab т={т} ч={ч} поставить={поставить} /></TabsContent>
              <TabsContent value="queue"><QueueTab т={т} ч={ч} поставить={поставить} потолок={потолок} /></TabsContent>
              <TabsContent value="callback"><CallbackTab т={т} ч={ч} поставить={поставить} потолок={потолок} /></TabsContent>
              <TabsContent value="fallback"><FallbackTab т={т} ч={ч} поставить={поставить} целиПаспорта={fb?.target} /></TabsContent>
              <TabsContent value="topics"><TopicsTab т={т} ч={ч} поставить={поставить} /></TabsContent>
              <TabsContent value="controls"><ControlsTab т={т} ч={ч} поставить={поставить} /></TabsContent>
            </div>
          </Tabs>
        </>
      )}
    </div>
  )
}

// ——— Общие куски ———

// ——— Часы и линия ———

function HoursTab({ т, ч, поставить }: Части) {
  return (
    <div>
      <Field имя="Линия" подсказка="Код линии меняется только перезапуском узла" было={ч.было('/lineName')}>
        <span className="rounded-md border border-border px-2 py-1 font-mono text-xs">{т.lineId}</span>
        <TextInput значение={т.lineName} onChange={v => поставить(['lineName'], v)} подпись="Название линии"
          placeholder="Название линии для контакт-центра" className="min-w-0 basis-56 flex-1" />
      </Field>

      <Field имя="Часы приёма" было={ч.было('/hours')}
        подсказка="Вне часов звонок не встаёт в очередь и идёт по цели «вне часов». Пусто — круглосуточно.">
        <HoursEditor часы={т.hours} onChange={v => поставить(['hours'], v)} пусто="Часов нет — линия принимает круглосуточно." />
      </Field>

      <Field имя="Цель SLA линии" подсказка="Ответить за столько секунд: по ней считается SL в статистике" было={ч.было('/slaTargetSec')}>
        <NumberInput значение={т.slaTargetSec} onChange={v => поставить(['slaTargetSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ.slaTargetSec} подпись="Цель SLA, секунд" min={1} />
      </Field>

      <More>
        <Field имя="Приветствие" подсказка="Звучит до постановки в очередь: sound:custom/<запись> или стандартный sound:<имя>" было={ч.было('/greeting')}>
          <TextInput значение={т.greeting} onChange={v => поставить(['greeting'], v)} подпись="Приветствие" моно />
        </Field>
        <Field имя="Музыка ожидания" подсказка="Класс музыки Asterisk" было={ч.было('/mohClass')}>
          <TextInput значение={т.mohClass} onChange={v => поставить(['mohClass'], v)} подпись="Музыка ожидания" моно placeholder={УМОЛЧАНИЯ.mohClass} className="w-40" />
        </Field>
        <Field имя="Трубки узла" подсказка="Для работы без контакт-центра, через запятую: PJSIP/op1, PJSIP/op2" было={ч.было('/operators')}>
          <TextInput значение={т.operators.join(', ')} подпись="Трубки узла" моно
            onChange={v => поставить(['operators'], (v ?? '').split(',').map(x => x.trim()).filter(Boolean))} />
        </Field>
      </More>
    </div>
  )
}

// ——— VIP и повторы ———

function VipTab({ т, ч, поставить }: Части) {
  const [набор, setНабор] = useState('')
  const номер = кНомеру(набор)
  const годен = номер.replace(/\D/g, '').length >= 10 && !т.vip.includes(номер)
  return (
    <div>
      <Field имя="Номера VIP" было={ч.было('/vip')}
        подсказка={`Приоритет ${т.priority.vip}. В контакт-центр уходит только приоритет — номер остаётся у узла.`}>
        <div className="w-full space-y-2">
          {!т.vip.length && <p className="text-sm text-muted-foreground">Номеров нет — все звонящие обычные или повторные.</p>}
          {!!т.vip.length && (
            <ul className="flex flex-wrap gap-1.5">
              {т.vip.map(n => (
                <li key={n} className="inline-flex items-center gap-1 rounded-md border border-border py-0.5 pl-2 pr-0.5">
                  <span className="font-mono text-xs">{n}</span>
                  <RemoveButton что={`номер ${n}`} onClick={() => поставить(['vip'], т.vip.filter(x => x !== n))} />
                </li>
              ))}
            </ul>
          )}
          <form className="flex flex-wrap items-center gap-2"
            onSubmit={e => { e.preventDefault(); if (годен) { поставить(['vip'], [...т.vip, номер]); setНабор('') } }}>
            <Input value={набор} onChange={e => setНабор(e.target.value)} inputMode="tel"
              aria-label="Номер VIP" placeholder="+7 900 000-00-00" className="h-9 w-52 font-mono" />
            <Button type="submit" variant="outline" size="sm" disabled={!годен}><Plus />Добавить номер</Button>
            {набор && т.vip.includes(номер) && <span className="text-xs text-muted-foreground">Этот номер уже в списке</span>}
          </form>
        </div>
      </Field>
      <Field имя="Окно повтора" было={ч.было('/repeatWithinMin')}
        подсказка={`Звонок с того же номера в течение окна получает приоритет ${т.priority.repeat}`}>
        <NumberInput значение={т.repeatWithinMin} onChange={v => поставить(['repeatWithinMin'], v ?? 0)} единица="мин" подпись="Окно повтора, минут" />
      </Field>
      <Field имя="Приоритеты" подсказка="Чем больше, тем раньше звонок предлагается оператору" было={ч.было('/priority')}>
        {(['normal', 'repeat', 'vip'] as const).map(k => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className="text-sm text-muted-foreground">{k === 'normal' ? 'обычный' : k === 'repeat' ? 'повтор' : 'VIP'}</span>
            <NumberInput значение={т.priority[k]} onChange={v => поставить(['priority', k], v ?? 0)} подпись={`Приоритет: ${k}`} />
          </span>
        ))}
      </Field>
    </div>
  )
}

// ——— Шкала ожидания ———

/**
 * Что слышит звонящий, пока ждёт: на одной оси цель SLA, объявления позиции,
 * «нажмите 1» и момент запасного сценария. Подписи — списком под полосой, а не
 * на ней: на телефоне полоса сжимается, а текст должен оставаться читаемым.
 */
function WaitScale({ т, потолок }: { т: ПравилаПриёма; потолок: number }) {
  const sla = т.slaTargetSec ?? УМОЛЧАНИЯ.slaTargetSec
  const первое = т.queueAnnounceFirstSec ?? УМОЛЧАНИЯ.queueAnnounceFirstSec
  const повтор = т.queueAnnounceSec ?? УМОЛЧАНИЯ.queueAnnounceSec
  const предложение = т.callbackOfferSec ?? УМОЛЧАНИЯ.callbackOfferSec
  const запас = т.callbackLeadSec ?? УМОЛЧАНИЯ.callbackLeadSec
  const x = (s: number) => `${Math.min(100, Math.max(0, (s / потолок) * 100))}%`

  const объявления: number[] = []
  if (повтор > 0) for (let s = первое; s < потолок && объявления.length < 12; s += повтор) объявления.push(s)
  const прозвучит = предложение > 0 && предложение + запас < потолок

  return (
    <div className="space-y-2 border-b border-border/60 py-4">
      <p className="text-sm font-medium">Что слышит звонящий, пока ждёт</p>
      <div className="relative mx-1 h-6" aria-hidden="true">
        <div className="absolute inset-x-0 top-2.5 h-1.5 rounded-full bg-border" />
        <div className="absolute left-0 top-2.5 h-1.5 rounded-full bg-chart-2" style={{ width: x(sla) }} />
        {объявления.map(s => <div key={s} className="absolute top-1 h-4 w-0.5 bg-chart-1" style={{ left: x(s) }} />)}
        {прозвучит && <div className="absolute top-0 h-6 w-1 rounded bg-chart-4" style={{ left: x(предложение) }} />}
        <div className="absolute right-0 top-0 h-6 w-1 rounded bg-chart-3" />
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <li className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-chart-2" />цель SLA — {sla} с</li>
        <li className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-chart-1" />
          {объявления.length ? `позиция в очереди: ${объявления.map(s => `${s} с`).join(', ')}` : 'позицию не объявляем'}</li>
        <li className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-chart-4" />
          {предложение <= 0 ? 'обратный звонок не предлагаем'
            : прозвучит ? `«нажмите 1» — ${предложение} с`
            : <span className="text-warning">«нажмите 1» не прозвучит: {предложение} с + {запас} с не раньше запасного сценария</span>}</li>
        <li className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-chart-3" />запасной сценарий — {потолок} с</li>
      </ul>
    </div>
  )
}

// ——— Очередь и ожидание ———

function QueueTab({ т, ч, поставить, потолок }: Части & { потолок: number }) {
  return (
    <div>
      <WaitScale т={т} потолок={потолок} />
      <Field имя="Первое объявление позиции" подсказка="Через столько секунд ожидания" было={ч.было('/queueAnnounceFirstSec')}>
        <NumberInput значение={т.queueAnnounceFirstSec} onChange={v => поставить(['queueAnnounceFirstSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ.queueAnnounceFirstSec} подпись="Первое объявление, секунд" />
      </Field>
      <Field имя="Повтор объявления" подсказка="Дальше каждые столько секунд; 0 — не объявлять. Оценка ожидания — по ответам за 10 минут"
        было={ч.было('/queueAnnounceSec')}>
        <NumberInput значение={т.queueAnnounceSec} onChange={v => поставить(['queueAnnounceSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ.queueAnnounceSec} подпись="Повтор объявления, секунд" />
      </Field>
      <Field имя="Потолок ожидания" подсказка="Из паспорта: после него звонок уходит в запасной сценарий. Меняется в «Паспорте для КЦ»">
        <span className="font-mono text-sm">{потолок} с</span>
        <Button asChild variant="outline" size="xs"><Link to="/voice/passport">Открыть паспорт</Link></Button>
      </Field>
      <More>
        <Field имя="Звук перед объявлением позиции" подсказка="Например «все операторы заняты»; через запятую. Пусто — только позиция"
          было={ч.было('/queueAnnounceSound')}>
          <TextInput значение={звукиИз(т.queueAnnounceSound)} onChange={v => поставить(['queueAnnounceSound'], звукиВ(v ?? ''))}
            подпись="Звук перед объявлением" моно />
        </Field>
        <Field имя="Пульт оператора пропал" подсказка="Что услышит звонящий, пока звонок снова ждёт оператора. Пусто — сразу музыка"
          было={ч.было('/agentLostSound')}>
          <TextInput значение={т.agentLostSound} onChange={v => поставить(['agentLostSound'], v)} подпись="Пульт оператора пропал" моно />
        </Field>
      </More>
    </div>
  )
}

// ——— Обратный звонок ———

function CallbackTab({ т, ч, поставить, потолок }: Части & { потолок: number }) {
  return (
    <div>
      <WaitScale т={т} потолок={потолок} />
      <Field имя="Предложить обратный звонок" подсказка="«Нажмите 1» через столько секунд ожидания; 0 — не предлагать"
        было={ч.было('/callbackOfferSec')}>
        <NumberInput значение={т.callbackOfferSec} onChange={v => поставить(['callbackOfferSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ.callbackOfferSec} подпись="Предложить через, секунд" />
      </Field>
      <Field имя="Не позже, чем за" подсказка="До запасного сценария — иначе предложение не успеет прозвучать" было={ч.было('/callbackLeadSec')}>
        <NumberInput значение={т.callbackLeadSec} onChange={v => поставить(['callbackLeadSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ.callbackLeadSec} подпись="Не позже чем за, секунд" />
      </Field>
      <Field имя="Попытки дозвона" подсказка="Повтор через · максимум попыток · сколько звонит набор"
        было={ч.было('/callbackRetryMin') ?? ч.было('/callbackMaxAttempts') ?? ч.было('/callbackRingSec')}>
        <NumberInput значение={т.callbackRetryMin} onChange={v => поставить(['callbackRetryMin'], v)} единица="мин"
          поУмолчанию={УМОЛЧАНИЯ.callbackRetryMin} подпись="Повтор через, минут" целое={false} />
        <NumberInput значение={т.callbackMaxAttempts} onChange={v => поставить(['callbackMaxAttempts'], v)} единица="попыток"
          поУмолчанию={УМОЛЧАНИЯ.callbackMaxAttempts} подпись="Попыток" min={1} />
        <NumberInput значение={т.callbackRingSec} onChange={v => поставить(['callbackRingSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ.callbackRingSec} подпись="Звонит, секунд" целое={false} />
      </Field>
      <MissedCallback т={т} ч={ч} поставить={поставить} />
      <Field имя="Номер, который видит звонящий" подсказка="Когда узел перезванивает" было={ч.было('/callbackCallerId')}>
        <TextInput значение={т.callbackCallerId} onChange={v => поставить(['callbackCallerId'], v)} подпись="Номер для перезвона"
          placeholder="+7 800 000-00-00" className="w-52 font-mono" />
      </Field>
      <More>
        <Field имя="Звук предложения" подсказка="Стандартный звук стенда — английский; через запятую" было={ч.было('/callbackOfferSound')}>
          <TextInput значение={звукиИз(т.callbackOfferSound)} onChange={v => поставить(['callbackOfferSound'], звукиВ(v ?? ''))}
            подпись="Звук предложения" моно placeholder="sound:vm-tocallnum" />
        </Field>
        <Field имя="Звук подтверждения" подсказка="Перед отбоем, через запятую" было={ч.было('/callbackConfirmSound')}>
          <TextInput значение={звукиИз(т.callbackConfirmSound)} onChange={v => поставить(['callbackConfirmSound'], звукиВ(v ?? ''))}
            подпись="Звук подтверждения" моно placeholder="sound:auth-thankyou, sound:goodbye" />
        </Field>
        <Field имя="Строка набора" подсказка="{number} — номер цифрами; по умолчанию через транк оператора связи" было={ч.было('/callbackDial')}>
          <TextInput значение={т.callbackDial} onChange={v => поставить(['callbackDial'], v)} подпись="Строка набора" моно
            placeholder={УМОЛЧАНИЯ.callbackDial} />
        </Field>
      </More>
    </div>
  )
}

/** Причины пропуска, по которым правило заводит долг само, если причин не назвали (node rules.ts MISSED_DUTY_REASONS). */
const ПРИЧИНЫ_ДОЛГА = ['after_hours', 'fallback', 'forward', 'before_queue', 'abandoned', 'interrupted', 'other']
const ВСЕ_ПРИЧИНЫ = ['after_hours', 'fallback', 'forward', 'before_queue', 'abandoned_short', 'abandoned', 'interrupted', 'other']

/**
 * Правило «Перезвонить пропущенным» (волна 7): узел сам заводит долг перезвона по пропущенному звонку.
 * Пропущенный — тот же, что в «Пропущено» статистики. Повтор того же номера присоединяется к открытому долгу.
 */
function MissedCallback({ т, ч, поставить }: Части) {
  const m = т.missedCallback ?? {}
  const вкл = m.enabled === true
  const причины = m.reasons ?? ПРИЧИНЫ_ДОЛГА
  const было = ч.было('/missedCallback') ?? ч.было('/missedCallback/enabled') ?? ч.было('/missedCallback/reasons')
    ?? ч.было('/missedCallback/assignee') ?? ч.было('/missedCallback/delayMin')
  return (
    <Field имя="Перезвонить пропущенным" было={было}
      подсказка="Узел сам заведёт долг перезвона по пропущенному звонку — он появится в «Нужен контакт». Повторный пропуск того же номера присоединится к открытому долгу.">
      <div className="w-full space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={вкл} onCheckedChange={v => поставить(['missedCallback', 'enabled'], v)} aria-label="Перезвонить пропущенным" />
          {вкл ? 'включено' : 'выключено — долг заводят только звонящий, оператор и администратор'}
        </label>
        {вкл && (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">кто звонит</span>
              <select value={m.assignee ?? 'cc'} onChange={e => поставить(['missedCallback', 'assignee'], e.target.value)}
                aria-label="Кто перезванивает пропущенным" className="h-9 rounded-md border border-input bg-card px-2 text-sm">
                <option value="cc">контакт-центр (без подключения — сотрудник)</option>
                <option value="staff">сотрудник заказчика</option>
              </select>
              <span className="text-muted-foreground">через</span>
              <NumberInput значение={m.delayMin} onChange={v => поставить(['missedCallback', 'delayMin'], v)} единица="мин"
                поУмолчанию={0} подпись="Через сколько минут перезванивать" />
            </div>
            <fieldset className="space-y-1">
              <legend className="text-xs text-muted-foreground">По каким пропущенным</legend>
              <div className="flex flex-wrap gap-1.5">
                {ВСЕ_ПРИЧИНЫ.map(r => {
                  const есть = причины.includes(r)
                  return (
                    <button key={r} type="button" aria-pressed={есть}
                      onClick={() => поставить(['missedCallback', 'reasons'], есть ? причины.filter(x => x !== r) : [...причины, r])}
                      className={cn('rounded-md border px-2 py-1 text-xs transition-colors',
                        есть ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-accent/50')}>
                      {ПРИЧИНА_ПРОПУСКА[r] ?? r}
                    </button>
                  )
                })}
              </div>
              {причины.includes('abandoned_short') && (
                <p className="text-xs text-warning">Коротко брошенные обычно ошиблись номером: перезванивать им — лишние звонки.</p>
              )}
            </fieldset>
          </>
        )}
      </div>
    </Field>
  )
}

// ——— Вне часов и запасной сценарий ———

const КОД = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/

function FallbackTab({ т, ч, поставить, целиПаспорта }: Части & { целиПаспорта?: string }) {
  const [новый, setНовый] = useState('')
  const коды = Object.keys(т.targets).sort()
  const вПульте = new Set([...(т.operatorControls?.staff ?? []), ...(т.operatorControls?.external ?? [])].map(x => x.code))
  const занят = (c: string) => c === т.afterHoursTarget ? 'вне часов' : c === целиПаспорта ? 'запасной сценарий паспорта'
    : вПульте.has(c) ? 'перевод оператора' : null
  const годен = КОД.test(новый) && !т.targets[новый]

  return (
    <div>
      <Field имя="Вне часов приёма" подсказка="Куда ведём звонок, пришедший вне часов" было={ч.было('/afterHoursTarget')}>
        <select value={т.afterHoursTarget} onChange={e => поставить(['afterHoursTarget'], e.target.value)}
          aria-label="Цель вне часов" className="h-9 rounded-md border border-input bg-card px-2 text-sm">
          {!т.targets[т.afterHoursTarget] && <option value={т.afterHoursTarget}>{т.afterHoursTarget} — не настроена</option>}
          {коды.map(c => <option key={c} value={c}>{c} — {т.targets[c].action === 'message' ? 'сообщение и отбой' : 'переадресация'}</option>)}
        </select>
      </Field>
      {целиПаспорта && (
        <Field имя="Запасной сценарий" подсказка="Цель задаёт паспорт: звонок дождался потолка ожидания">
          <span className="font-mono text-sm">{целиПаспорта}</span>
          {!т.targets[целиПаспорта] && <span className="text-xs text-destructive">не настроена у узла</span>}
        </Field>
      )}
      <Field имя="Цели" было={ч.было('/targets')}
        подсказка="Код → что делает узел: сообщение и отбой или переадресация. Номер переадресации знает только узел.">
        <div className="w-full space-y-2">
          {коды.map(c => {
            const ц = т.targets[c]
            const где = занят(c)
            return (
              <div key={c} className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2">
                <span className="w-36 truncate font-mono text-xs" title={c}>{c}</span>
                <select value={ц.action} aria-label={`Что делает цель ${c}`}
                  onChange={e => поставить(['targets', c], e.target.value === 'message'
                    ? { action: 'message', sounds: ['sound:vm-nobodyavail', 'sound:goodbye'] } satisfies Цель
                    : { action: 'forward', endpoint: '' } satisfies Цель)}
                  className="h-9 rounded-md border border-input bg-card px-2 text-sm">
                  <option value="message">сообщение и отбой</option>
                  <option value="forward">переадресация</option>
                </select>
                {ц.action === 'message'
                  ? <TextInput значение={звукиИз(ц.sounds)} подпись={`Звуки цели ${c}`} моно className="min-w-0 basis-48 flex-1"
                      onChange={v => поставить(['targets', c], { action: 'message', sounds: звукиВ(v ?? '') ?? [] })} />
                  : <TextInput значение={ц.endpoint} подпись={`Куда звонить, цель ${c}`} моно className="min-w-0 basis-48 flex-1"
                      placeholder="PJSIP/<трубка> или PJSIP/<номер>@<транк>"
                      onChange={v => поставить(['targets', c], { action: 'forward', endpoint: v ?? '' })} />}
                {где
                  ? <span className="text-xs text-muted-foreground">используется: {где}</span>
                  : <RemoveButton что={`цель ${c}`} onClick={() => поставить(['targets'], Object.fromEntries(Object.entries(т.targets).filter(([k]) => k !== c)))} />}
              </div>
            )
          })}
          <form className="flex flex-wrap items-center gap-2"
            onSubmit={e => { e.preventDefault(); if (годен) { поставить(['targets', новый], { action: 'message', sounds: ['sound:vm-nobodyavail', 'sound:goodbye'] }); setНовый('') } }}>
            <Input value={новый} onChange={e => setНовый(e.target.value.trim())} aria-label="Код новой цели"
              placeholder="код, латиницей: holiday_message" className="h-9 w-64 font-mono text-xs" />
            <Button type="submit" variant="outline" size="sm" disabled={!годен}><Plus />Добавить цель</Button>
          </form>
          <p className="text-xs text-muted-foreground">
            Цели перевода сотрудникам удобнее настраивать в «<Link to="/voice/targets" className="underline">Сотрудниках и переводах</Link>»:
            там одна цель сразу попадает в паспорт, правила и пульт оператора.
          </p>
        </div>
      </Field>
    </div>
  )
}

// ——— Темы ———

function TopicsTab({ т, ч, поставить }: Части) {
  const темы = т.topics ?? []
  const править = (i: number, k: 'code' | 'name' | 'category' | 'description', v: string | undefined) =>
    поставить(['topics'], темы.map((x, n) => (n === i ? записать(x, [k], k === 'code' || k === 'name' ? v ?? '' : v) : x)))
  return (
    <Field имя="Темы обращения" было={ч.было('/topics')}
      подсказка="Что окно заказчика предлагает оператору выбрать; код — значение поля «тема» в журнале и статистике">
      <div className="w-full space-y-2">
        {!темы.length && <p className="text-sm text-muted-foreground">Тем нет — оператор итог звонка не классифицирует.</p>}
        {темы.map((x, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2">
            <Input value={x.code} onChange={e => править(i, 'code', e.target.value.trim())} aria-label="Код темы"
              placeholder="код" className="h-9 w-36 font-mono text-xs" />
            <Input value={x.name} onChange={e => править(i, 'name', e.target.value)} aria-label="Название темы"
              placeholder="Название" className="h-9 min-w-0 basis-48 flex-1" />
            <Input value={x.category ?? ''} onChange={e => править(i, 'category', e.target.value || undefined)} aria-label="Категория темы"
              placeholder="Категория" className="h-9 w-40" />
            <RemoveButton что={`тему ${x.name || x.code}`} onClick={() => поставить(['topics'], темы.filter((_, n) => n !== i))} />
          </div>
        ))}
        <Button variant="outline" size="xs" onClick={() => поставить(['topics'], [...темы, { code: '', name: '' }])}>
          <Plus />Добавить тему
        </Button>
      </div>
    </Field>
  )
}

// ——— Пульт оператора ———

function ControlsTab({ т, ч, поставить }: Части) {
  const п = т.operatorControls ?? {}
  const пс = (k: string, v: unknown) => поставить(['operatorControls', k], v)
  const все = Object.keys(КОМАНДЫ)
  const разрешены = new Set(п.commands ?? все)
  const было = (k: string) => ч.было(`/operatorControls/${k}`)

  return (
    <div>
      <Field имя="Что может оператор" подсказка="Команды пульта; снятая галка — команда недоступна оператору" было={было('commands')}>
        <div className="grid w-full gap-1.5 sm:grid-cols-2">
          {все.map(c => (
            <label key={c} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={разрешены.has(c)}
                onChange={e => {
                  const next = new Set(разрешены)
                  if (e.target.checked) next.add(c); else next.delete(c)
                  пс('commands', next.size === все.length ? undefined : все.filter(x => next.has(x)))
                }} />
              {КОМАНДЫ[c]}
            </label>
          ))}
        </div>
      </Field>
      <Field имя="Конференция" подсказка="Оператор может соединить звонящего с сотрудником втроём" было={было('conference')}>
        <Switch checked={п.conference !== false} onCheckedChange={v => пс('conference', v ? undefined : false)} aria-label="Конференция" />
      </Field>
      <Field имя="Парковка" подсказка="Звонок ждёт на парковке и возвращается тому же оператору; дольше предела — в очередь"
        было={было('park')}>
        <Switch checked={п.park !== false} onCheckedChange={v => пс('park', v ? undefined : false)} aria-label="Парковка" />
        {п.park !== false && (
          <NumberInput значение={п.park?.maxSec} onChange={v => пс('park', v === undefined ? undefined : { maxSec: v })}
            единица="с" поУмолчанию={УМОЛЧАНИЯ.parkMaxSec} подпись="Предел парковки, секунд" min={1} />
        )}
      </Field>
      <Field имя="Пауза записи" подсказка="Оператор может приостановить запись разговора (например, при диктовке данных карты)"
        было={было('recording')}>
        <Switch checked={п.recording === 'pause'} onCheckedChange={v => пс('recording', v ? 'pause' : undefined)} aria-label="Пауза записи" />
      </Field>
      <Field имя="Обратный звонок от оператора" подсказка="Оператор может поставить задачу «перезвонить»" было={было('callback')}>
        <Switch checked={п.callback !== false} onCheckedChange={v => пс('callback', v ? undefined : false)} aria-label="Обратный звонок от оператора" />
      </Field>
      <Field имя="Позвать начальника смены" подсказка="Оператор может попросить помощи старшего во время разговора" было={было('escalate')}>
        <Switch checked={п.escalate !== false} onCheckedChange={v => пс('escalate', v ? undefined : false)} aria-label="Позвать начальника смены" />
      </Field>
      <Field имя="Перевод вслепую не удался" подсказка="Сотрудник не ответил — куда вернуть звонок" было={было('blindFailed')}>
        <select value={п.blindFailed ?? 'same_operator'} aria-label="Перевод вслепую не удался"
          onChange={e => пс('blindFailed', e.target.value === 'same_operator' ? undefined : e.target.value)}
          className="h-9 rounded-md border border-input bg-card px-2 text-sm">
          <option value="same_operator">тому же оператору</option>
          <option value="queue">в очередь</option>
        </select>
      </Field>
      <Field имя="Удержание" подсказка="Напомнить оператору через · повторять каждые · предел удержания (пусто — без предела)"
        было={было('holdRemindSec') ?? было('holdRepeatSec') ?? было('maxHoldSec')}>
        <NumberInput значение={п.holdRemindSec} onChange={v => пс('holdRemindSec', v)} единица="с" поУмолчанию={УМОЛЧАНИЯ.holdRemindSec}
          подпись="Напомнить через, секунд" min={1} />
        <NumberInput значение={п.holdRepeatSec} onChange={v => пс('holdRepeatSec', v)} единица="с" поУмолчанию={УМОЛЧАНИЯ.holdRepeatSec}
          подпись="Повторять каждые, секунд" min={1} />
        <NumberInput значение={п.maxHoldSec} onChange={v => пс('maxHoldSec', v)} единица="с" подпись="Предел удержания, секунд" min={1} />
      </Field>
      {п.maxHoldSec !== undefined && (
        <Field имя="На пределе удержания" подсказка="Снять звонок с удержания или позвать начальника смены" было={было('holdAutoResume')}>
          <select value={п.holdAutoResume ? 'resume' : 'escalate'} aria-label="На пределе удержания"
            onChange={e => пс('holdAutoResume', e.target.value === 'resume' ? true : undefined)}
            className="h-9 rounded-md border border-input bg-card px-2 text-sm">
            <option value="escalate">позвать начальника смены</option>
            <option value="resume">снять с удержания</option>
          </select>
        </Field>
      )}
      <Field имя="Кому можно перевести" подсказка="Сотрудники и внешние номера настраиваются одним местом в «Сотрудниках и переводах»">
        <span className="text-sm">
          {[...(п.staff ?? []), ...(п.external ?? [])].map(x => x.label).join(', ') || 'никому'}
        </span>
        <Button asChild variant="outline" size="xs"><Link to="/voice/targets">Сотрудники и переводы</Link></Button>
      </Field>
      <More>
        <Field имя="Объявления паузы записи" подсказка="Что слышит звонящий при паузе и возобновлении записи, если так требует заказчик"
          было={было('recordingAnnounce')}>
          <TextInput значение={п.recordingAnnounce?.pause} подпись="Звук паузы" моно placeholder="пауза: sound:…" className="w-56"
            onChange={v => пс('recordingAnnounce', записать(п.recordingAnnounce ?? {}, ['pause'], v))} />
          <TextInput значение={п.recordingAnnounce?.resume} подпись="Звук возобновления" моно placeholder="возобновление: sound:…" className="w-56"
            onChange={v => пс('recordingAnnounce', записать(п.recordingAnnounce ?? {}, ['resume'], v))} />
        </Field>
      </More>
    </div>
  )
}
