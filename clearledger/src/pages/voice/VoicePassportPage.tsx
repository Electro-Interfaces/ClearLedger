/**
 * «Паспорт для КЦ» — что контакт-центр знает о линии и что ему разрешено.
 *
 * Те же приёмы, что в «Правилах приёма»: черновик, «было …», проверка, применение
 * с комментарием. Разница одна и важная: применённый паспорт сразу уходит в
 * контакт-центр новой версией (событие passport.changed), поэтому на плашке и в
 * итоге проверки это сказано словами. Ломающее изменение (старшая принимаемая
 * версия выше действующей) — только с галкой «понимаю».
 *
 * Скачивание записи в КЦ и облачный запасной вариант распознавания протокол
 * запрещает (`const: false`) — показываем их как факт, а не как переключатель.
 */
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, FileText, Plus } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCompany } from '@/contexts/CompanyContext'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { CheckResult, DraftBar, Field, NumberInput } from './DraftParts'
import { записать } from './draftDoc'
import { More, RemoveButton, TextInput } from './FormBits'
import { HoursEditor } from './HoursEditor'
import { Heading, NodeError } from './parts'
import {
  ИМЯ_ОПЕРАТОРА, МАСКА, ПОДПИСИ_ПАСПОРТА, ПОЛЯ_КАРТОЧКИ, УМОЛЧАНИЯ_ПАСПОРТА, type Паспорт,
} from './passport'
import type { ПравилаПриёма } from './reception'
import { useDraft, type Черновик } from './useDraft'

const ВКЛАДКИ = [
  { key: 'presentation', name: 'Представление', поля: ['/presentation'] },
  { key: 'disposition', name: 'Итоги', поля: ['/disposition'] },
  { key: 'privacy', name: 'Приватность', поля: ['/privacy'] },
  { key: 'access', name: 'Допуск операторов', поля: ['/access'] },
  { key: 'actions', name: 'Действия', поля: ['/actions'] },
  { key: 'fallback', name: 'Ожидание и предложение', поля: ['/fallback', '/offer', '/minAcceptedVersion'] },
  { key: 'retention', name: 'Что КЦ хранит', поля: ['/kcRetention'] },
  { key: 'enrichment', name: 'Подсказки', поля: ['/liveEnrichment'] },
] as const

export interface Части {
  п: Паспорт
  ч: Черновик<Паспорт>
  поставить: (ключи: string[], значение: unknown) => void
}

const списокИз = (v?: string[]) => (v ?? []).join(', ')
const списокВ = (t?: string) => (t ?? '').split(',').map(x => x.trim()).filter(Boolean)

export default function VoicePassportPage() {
  const { companyId } = useCompany()
  const [params, setParams] = useSearchParams()
  const ч = useDraft<Паспорт>('passport')
  const правила = useQuery({
    queryKey: ['voice-config', companyId, 'reception', 'active'],
    queryFn: async () => (await voice.configActive(companyId, 'reception')).data as unknown as voice.ConfigVersion<ПравилаПриёма>,
  })
  const вкладка = ВКЛАДКИ.find(x => x.key === params.get('tab'))?.key ?? 'presentation'
  const п = ч.тело
  const поставить = (ключи: string[], значение: unknown) => ч.изменить(b => записать(b, ключи, значение))
  const действует = ч.действующая?.body.version

  const ломает = !!ч.проверка?.breaking
  return (
    <div className="space-y-4 p-4">
      <Heading имя="Паспорт для КЦ"
        подпись="Что контакт-центр знает о линии: приветствие, итоги, приватность, допуск операторов и действия. Каждое применение уходит в КЦ." />

      {ч.загрузка && <p role="status" className="text-sm">Читаем паспорт у узла…</p>}
      {!!ч.ошибка && <NodeError ошибка={ч.ошибка} что="прочитать паспорт" />}
      {!ч.загрузка && !ч.ошибка && !п && (
        <EmptyBlock иконка={FileText} текст="У узла нет действующего паспорта"
          подсказка="Паспорт появляется при первом запуске узла из файла passport.json." />
      )}

      {п && (
        <>
          <DraftBar ч={ч} примечание="после применения уйдёт в контакт-центр" />
          <CheckResult ч={ч} подписи={ПОДПИСИ_ПАСПОРТА}
            последствия={[
              `Паспорт r${ч.черновик?.version} сразу уйдёт в контакт-центр и начнёт действовать с момента применения; перезапуск не нужен.`,
              ...(ломает ? [<span key="b" className="text-warning">Изменение ломающее: старшая принимаемая версия станет выше r{действует}. Операторы КЦ, у которых ещё прежний паспорт, получат отказ на свои команды, пока КЦ не обновится.</span>] : []),
            ]}
            подтверждение={ломает ? 'Понимаю: контакт-центр должен принять новую версию, иначе его команды будут отклонены' : undefined} />

          <Tabs value={вкладка} onValueChange={v => { const n = new URLSearchParams(params); n.set('tab', v); setParams(n, { replace: true }) }}>
            <TabsList>
              {ВКЛАДКИ.map(в => {
                const есть = ч.изменено.some(x => в.поля.some(пп => x.path === пп || x.path.startsWith(`${пп}/`)))
                return (
                  <TabsTrigger key={в.key} value={в.key}>
                    {в.name}{есть && <span className="text-primary" aria-label="есть изменения"> ·</span>}
                  </TabsTrigger>
                )
              })}
            </TabsList>
            <div className="rounded-xl border border-border bg-card px-4">
              <TabsContent value="presentation"><PresentationTab п={п} ч={ч} поставить={поставить} /></TabsContent>
              <TabsContent value="disposition"><DispositionTab п={п} ч={ч} поставить={поставить} /></TabsContent>
              <TabsContent value="privacy"><PrivacyTab п={п} ч={ч} поставить={поставить} /></TabsContent>
              <TabsContent value="access"><AccessTab п={п} ч={ч} поставить={поставить} /></TabsContent>
              <TabsContent value="actions"><ActionsTab п={п} ч={ч} поставить={поставить} /></TabsContent>
              <TabsContent value="fallback">
                <WaitTab п={п} ч={ч} поставить={поставить} цели={Object.keys(правила.data?.body.targets ?? {}).sort()} действует={действует} />
              </TabsContent>
              <TabsContent value="retention"><RetentionTab п={п} ч={ч} поставить={поставить} /></TabsContent>
              <TabsContent value="enrichment"><EnrichmentTab п={п} ч={ч} поставить={поставить} /></TabsContent>
            </div>
          </Tabs>
        </>
      )}
    </div>
  )
}

function Select({ значение, onChange, варианты, подпись }: {
  значение: string
  onChange: (v: string) => void
  варианты: Record<string, string>
  подпись: string
}) {
  return (
    <select value={значение} onChange={e => onChange(e.target.value)} aria-label={подпись}
      className="h-9 rounded-md border border-input bg-card px-2 text-sm">
      {Object.entries(варианты).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
    </select>
  )
}

function Fact({ children }: { children: string }) {
  return <span className="text-sm text-muted-foreground">{children}</span>
}

// ——— Представление ———

function PresentationTab({ п, ч, поставить }: Части) {
  return (
    <div>
      <Field имя="Приветствие оператора" подсказка="Что оператор говорит, взяв трубку" было={ч.было('/presentation/greeting')}>
        <TextInput значение={п.presentation.greeting} onChange={v => поставить(['presentation', 'greeting'], v)}
          подпись="Приветствие оператора" className="min-w-0 basis-72 flex-1" />
      </Field>
      <Field имя="Название для оператора" подсказка="Как оператор называет компанию" было={ч.было('/presentation/brandName')}>
        <TextInput значение={п.presentation.brandName} onChange={v => поставить(['presentation', 'brandName'], v)} подпись="Название" />
      </Field>
      <Field имя="Как называть оператора" подсказка="Что звонящий слышит об операторе" было={ч.было('/presentation/operatorNameMode')}>
        <Select значение={п.presentation.operatorNameMode ?? 'first_name'} варианты={ИМЯ_ОПЕРАТОРА} подпись="Как называть оператора"
          onChange={v => поставить(['presentation', 'operatorNameMode'], v)} />
      </Field>
    </div>
  )
}

// ——— Итоги ———

function DispositionTab({ п, ч, поставить }: Части) {
  const [новый, setНовый] = useState('')
  const коды = п.disposition?.codes ?? []
  const обязательные = п.disposition?.requiredFields ?? {}
  return (
    <div>
      <Field имя="Коды итога" подсказка="Что оператор выбирает после разговора; no_disposition — «итог не записан»" было={ч.было('/disposition/codes')}>
        <div className="w-full space-y-2">
          <ul className="flex flex-wrap gap-1.5">
            {коды.map(к => (
              <li key={к} className="inline-flex items-center gap-1 rounded-md border border-border py-0.5 pl-2 pr-0.5">
                <span className="font-mono text-xs">{к}</span>
                <RemoveButton что={`код ${к}`} onClick={() => поставить(['disposition', 'codes'], коды.filter(x => x !== к))} />
              </li>
            ))}
          </ul>
          <form className="flex flex-wrap items-center gap-2"
            onSubmit={e => { e.preventDefault(); if (новый && !коды.includes(новый)) { поставить(['disposition', 'codes'], [...коды, новый]); setНовый('') } }}>
            <Input value={новый} onChange={e => setНовый(e.target.value.trim())} aria-label="Новый код итога"
              placeholder="refund" className="h-9 w-48 font-mono text-xs" />
            <Button type="submit" variant="outline" size="sm" disabled={!новый || коды.includes(новый)}><Plus />Добавить код</Button>
          </form>
        </div>
      </Field>
      <Field имя="Обязательные поля итога" подсказка="Для кода — какие поля оператор обязан заполнить, через запятую" было={ч.было('/disposition/requiredFields')}>
        <div className="w-full space-y-1.5">
          {коды.filter(к => к !== 'no_disposition').map(к => (
            <div key={к} className="flex flex-wrap items-center gap-2">
              <span className="w-36 truncate font-mono text-xs" title={к}>{к}</span>
              <TextInput значение={списокИз(обязательные[к])} подпись={`Обязательные поля для ${к}`} моно className="min-w-0 basis-48 flex-1"
                onChange={v => {
                  const list = списокВ(v)
                  const next = { ...обязательные }
                  if (list.length) next[к] = list; else delete next[к]
                  поставить(['disposition', 'requiredFields'], Object.keys(next).length ? next : undefined)
                }} />
            </div>
          ))}
        </div>
      </Field>
      <Field имя="Время на итог после разговора" подсказка="Не больше 10 минут; дольше — «итог не записан»" было={ч.было('/disposition/wrapupSec')}>
        <NumberInput значение={п.disposition?.wrapupSec} onChange={v => поставить(['disposition', 'wrapupSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ_ПАСПОРТА.wrapupSec} подпись="Время на итог, секунд" />
      </Field>
    </div>
  )
}

// ——— Приватность ———

function PrivacyTab({ п, ч, поставить }: Части) {
  const поля = п.privacy.cardFields
  const все = [...new Set([...Object.keys(ПОЛЯ_КАРТОЧКИ), ...поля])]
  return (
    <div>
      <Field имя="Номер звонящего у оператора" подсказка="Как оператор КЦ видит номер" было={ч.было('/privacy/phoneMask')}>
        <Select значение={п.privacy.phoneMask} варианты={МАСКА} подпись="Номер у оператора" onChange={v => поставить(['privacy', 'phoneMask'], v)} />
      </Field>
      <Field имя="Поля карточки звонящего" подсказка="Что оператор видит о звонящем" было={ч.было('/privacy/cardFields')}>
        <div className="grid w-full gap-1.5 sm:grid-cols-2">
          {все.map(f => (
            <label key={f} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={поля.includes(f)}
                onChange={e => поставить(['privacy', 'cardFields'], e.target.checked ? [...поля, f] : поля.filter(x => x !== f))} />
              {ПОЛЯ_КАРТОЧКИ[f] ?? <span className="font-mono text-xs">{f}</span>}
            </label>
          ))}
        </div>
      </Field>
      <Field имя="Доступ к звонку после разговора" подсказка="Сколько часов оператор ещё видит карточку; 0 — сразу закрывается"
        было={ч.было('/privacy/postContactAccessHours')}>
        <NumberInput значение={п.privacy.postContactAccessHours} onChange={v => поставить(['privacy', 'postContactAccessHours'], v)}
          единица="ч" поУмолчанию={УМОЛЧАНИЯ_ПАСПОРТА.postContactAccessHours} подпись="Доступ после разговора, часов" />
      </Field>
      <Field имя="Скачивание записи в КЦ" подсказка="Записи остаются у узла заказчика">
        <Fact>запрещено протоколом</Fact>
      </Field>
    </div>
  )
}

// ——— Допуск операторов ———

function AccessTab({ п, ч, поставить }: Части) {
  const a = п.access
  return (
    <div>
      <Field имя="Как допускать операторов" подсказка="Вручную — каждого нового оператора допускает администратор в «Контакт-центрах»"
        было={ч.было('/access/admission')}>
        <Select значение={a.admission ?? 'manual'} варианты={{ manual: 'вручную', auto: 'автоматически' }} подпись="Как допускать"
          onChange={v => поставить(['access', 'admission'], v)} />
      </Field>
      <Field имя="Часы работы операторов" подсказка="Вне часов операторы КЦ не получают звонков линии" было={ч.было('/access/hours')}>
        <HoursEditor часы={a.hours ?? []} onChange={v => поставить(['access', 'hours'], v.length ? v : undefined)} пусто="Часов нет — без ограничения." />
      </Field>
      <Field имя="Сети, из которых можно работать" подсказка="Адреса через запятую: 10.0.0.0/8, 192.168.1.0/24. Пусто — откуда угодно"
        было={ч.было('/access/cidr')}>
        <TextInput значение={списокИз(a.cidr)} подпись="Сети" моно onChange={v => { const l = списокВ(v); поставить(['access', 'cidr'], l.length ? l : undefined) }} />
      </Field>
      <Field имя="Вторая проверка входа" подсказка="Оператор входит с кодом из приложения или СМС, а не только по паролю" было={ч.было('/access/requireMfa')}>
        <Switch checked={!!a.requireMfa} onCheckedChange={v => поставить(['access', 'requireMfa'], v)} aria-label="Вторая проверка входа" />
        {!a.requireMfa && (
          <span className="flex items-center gap-1 text-xs text-warning"><AlertTriangle className="h-3.5 w-3.5" />
            без неё рабочий узел не запустится: установка требует второй проверки</span>
        )}
      </Field>
    </div>
  )
}

// ——— Действия ———

function ActionsTab({ п, ч, поставить }: Части) {
  const act = п.actions
  return (
    <div>
      <Field имя="Цели перевода" подсказка="Кому оператор может перевести звонок; настраиваются одним местом">
        <span className="text-sm">{(act.transferTargets ?? []).map(x => x.label).join(', ') || 'никому'}</span>
        <Button asChild variant="outline" size="xs"><Link to="/voice/targets">Сотрудники и переводы</Link></Button>
      </Field>
      <Field имя="Перевод между операторами КЦ" было={ч.было('/actions/ccOperatorTransfer')}>
        <Switch checked={!!act.ccOperatorTransfer} onCheckedChange={v => поставить(['actions', 'ccOperatorTransfer'], v)} aria-label="Перевод между операторами" />
      </Field>
      <Field имя="Перехват разговора старшим" подсказка="Начальник смены КЦ может забрать разговор у оператора" было={ч.было('/actions/takeover')}>
        <Switch checked={!!act.takeover} onCheckedChange={v => поставить(['actions', 'takeover'], v)} aria-label="Перехват разговора" />
      </Field>
      <Field имя="Создание заявки" подсказка="Оператор может завести заявку по итогам разговора" было={ч.было('/actions/createTicket')}>
        <Switch checked={!!act.createTicket} onCheckedChange={v => поставить(['actions', 'createTicket'], v)} aria-label="Создание заявки" />
      </Field>
    </div>
  )
}

// ——— Ожидание и предложение ———

function WaitTab({ п, ч, поставить, цели, действует }: Части & { цели: string[]; действует?: number }) {
  const fb = п.fallback
  return (
    <div>
      <Field имя="Потолок ожидания" подсказка="После него звонок уходит в запасной сценарий; эту же отметку видно на шкале в «Правилах приёма»"
        было={ч.было('/fallback/maxTotalSec')}>
        <NumberInput значение={fb.maxTotalSec} onChange={v => поставить(['fallback', 'maxTotalSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ_ПАСПОРТА.maxTotalSec} подпись="Потолок ожидания, секунд" min={1} />
      </Field>
      <Field имя="Цель запасного сценария" подсказка="Код цели из правил приёма: сообщение или переадресация" было={ч.было('/fallback/target')}>
        <select value={fb.target ?? ''} onChange={e => поставить(['fallback', 'target'], e.target.value || undefined)} aria-label="Цель запасного сценария"
          className="h-9 rounded-md border border-input bg-card px-2 text-sm">
          <option value="">не задана</option>
          {fb.target && !цели.includes(fb.target) && <option value={fb.target}>{fb.target} — нет в правилах</option>}
          {цели.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </Field>
      <Field имя="Нет готовых операторов — ждём" подсказка="Сколько КЦ ищет оператора, прежде чем узел повторит предложение; 5–120 с"
        было={ч.было('/fallback/afterSec')}>
        <NumberInput значение={fb.afterSec} onChange={v => поставить(['fallback', 'afterSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ_ПАСПОРТА.afterSec} подпись="Ждём оператора, секунд" min={5} />
      </Field>
      <Field имя="Повторно предлагаем через" подсказка="5–120 с" было={ч.было('/fallback/retryAfterSec')}>
        <NumberInput значение={fb.retryAfterSec} onChange={v => поставить(['fallback', 'retryAfterSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ_ПАСПОРТА.retryAfterSec} подпись="Повтор предложения, секунд" min={5} />
      </Field>
      <Field имя="Сколько ждём ответа оператора" подсказка="Оператор не взял звонок — предложение снимается" было={ч.было('/offer/maxTtlSec')}>
        <NumberInput значение={п.offer?.maxTtlSec} onChange={v => поставить(['offer', 'maxTtlSec'], v)} единица="с"
          поУмолчанию={УМОЛЧАНИЯ_ПАСПОРТА.maxTtlSec} подпись="Ждём ответа оператора, секунд" min={1} />
      </Field>
      <Field имя="Оператор сам выбирает звонок" подсказка="Может взять любой ждущий звонок линии, а не только тот, что дал КЦ" было={ч.было('/offer/allowPick')}>
        <Switch checked={!!п.offer?.allowPick} onCheckedChange={v => поставить(['offer', 'allowPick'], v)} aria-label="Оператор сам выбирает звонок" />
      </Field>
      <More подпись="Подробнее: совместимость версий">
        <Field имя="Старшая версия, которую ещё принимаем" было={ч.было('/minAcceptedVersion')}
          подсказка={`Команды КЦ с паспортом старше этой версии узел отклонит. Действует r${действует ?? '—'}; поднять выше — ломающее изменение`}>
          <NumberInput значение={п.minAcceptedVersion} onChange={v => поставить(['minAcceptedVersion'], v)} подпись="Старшая принимаемая версия" min={1} />
        </Field>
      </More>
    </div>
  )
}

// ——— Что КЦ хранит ———

function RetentionTab({ п, ч, поставить }: Части) {
  const r = п.kcRetention ?? {}
  return (
    <div>
      <Field имя="Сколько дней КЦ хранит" подсказка="Не больше трёх лет (1095 дней)" было={ч.было('/kcRetention/days')}>
        <NumberInput значение={r.days} onChange={v => поставить(['kcRetention', 'days'], v)} единица="дн" подпись="Сколько дней КЦ хранит" />
      </Field>
      <Field имя="Поля итога, которые КЦ хранит" подсказка="Через запятую" было={ч.было('/kcRetention/dispositionFields')}>
        <TextInput значение={списокИз(r.dispositionFields)} подпись="Поля итога" моно
          onChange={v => { const l = списокВ(v); поставить(['kcRetention', 'dispositionFields'], l.length ? l : undefined) }} />
      </Field>
      <Field имя="Номер заявки" было={ч.было('/kcRetention/ticketNumber')}>
        <Switch checked={!!r.ticketNumber} onCheckedChange={v => поставить(['kcRetention', 'ticketNumber'], v)} aria-label="Номер заявки" />
      </Field>
      <Field имя="Предпочтительный оператор" подсказка="КЦ помнит, кто говорил со звонящим, чтобы соединить с ним снова" было={ч.было('/kcRetention/preferredOperator')}>
        <Switch checked={!!r.preferredOperator} onCheckedChange={v => поставить(['kcRetention', 'preferredOperator'], v)} aria-label="Предпочтительный оператор" />
      </Field>
    </div>
  )
}

// ——— Подсказки (и экран «Распознавание и подсказки») ———

export function EnrichmentTab({ п, ч, поставить }: Части) {
  const e = п.liveEnrichment ?? {}
  return (
    <div>
      <Field имя="Подсказки оператору" подсказка="Узел распознаёт речь и подсказывает оператору тему и поля итога" было={ч.было('/liveEnrichment/enabled')}>
        <Switch checked={!!e.enabled} onCheckedChange={v => поставить(['liveEnrichment', 'enabled'], v)} aria-label="Подсказки оператору" />
      </Field>
      <Field имя="Показывать оператору расшифровку" было={ч.было('/liveEnrichment/showTranscript')}>
        <Switch checked={!!e.showTranscript} onCheckedChange={v => поставить(['liveEnrichment', 'showTranscript'], v)} aria-label="Показывать расшифровку" />
      </Field>
      <Field имя="Языковая модель для подсказок" подсказка="Без неё — только правила" было={ч.было('/liveEnrichment/llmEnabled')}>
        <Switch checked={!!e.llmEnabled} onCheckedChange={v => поставить(['liveEnrichment', 'llmEnabled'], v)} aria-label="Языковая модель" />
      </Field>
      <Field имя="Порог уверенности" подсказка="От 0 до 1: подсказка ниже порога не показывается" было={ч.было('/liveEnrichment/threshold')}>
        <NumberInput значение={e.threshold} onChange={v => поставить(['liveEnrichment', 'threshold'], v === undefined ? undefined : Math.min(1, v))}
          поУмолчанию={УМОЛЧАНИЯ_ПАСПОРТА.threshold} подпись="Порог уверенности" целое={false} />
      </Field>
      <Field имя="Облачный запасной вариант" подсказка="Звук не уходит из узла заказчика">
        <Fact>запрещён протоколом</Fact>
      </Field>
    </div>
  )
}
