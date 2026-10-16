/**
 * «Распознавание и подсказки» — живое обогащение звонка: узел распознаёт речь и подсказывает
 * оператору КЦ тему и поля итога.
 *
 * Настройки — раздел `liveEnrichment` паспорта для КЦ: правка идёт в тот же черновик
 * паспорта, что и на экране «Паспорт для КЦ», и после применения уходит в контакт-центр.
 * Рядом — факт со стороны узла: работают ли распознавание и языковая модель сейчас и
 * сколько раз распознавание пропадало за сутки (`/health`, `/health/history`). Доля
 * принятых подсказок узел не копит: счётчики уходят в КЦ в итоге звонка, их показывает КЦ.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { CheckResult, DraftBar } from './DraftParts'
import { записать } from './draftDoc'
import { СОСТОЯНИЕ_ЧАСТИ, когда, сек } from './format'
import { Heading, NodeError } from './parts'
import { ПОДПИСИ_ПАСПОРТА, type Паспорт } from './passport'
import { useDraft } from './useDraft'
import { EnrichmentTab } from './VoicePassportPage'

/** Сколько раз и сколько всего распознавание не работало за сутки — по строкам истории. */
function простои(строки: voice.HealthEvent[], с: number, по: number) {
  // Идём от старых к новым и складываем отрезки «не работало»; одна строка могла прийти в обоих запросах.
  const поПорядку = [...new Map(строки.map(r => [r.id, r])).values()].sort((a, b) => Date.parse(a.at) - Date.parse(b.at))
  let раз = 0
  let всего = 0
  let начало: number | null = null
  for (const r of поПорядку) {
    const t = Math.max(с, Date.parse(r.at))
    const плохо = r.state === 'down' || r.state === 'unknown'
    if (плохо && начало === null) { начало = t; раз++ }
    if (!плохо && начало !== null) { всего += t - начало; начало = null }
  }
  if (начало !== null) всего += по - начало
  return { раз, сек: Math.max(0, всего) / 1000 }
}

export default function VoiceEnrichmentPage() {
  const ч = useDraft<Паспорт>('passport')
  const п = ч.тело
  const поставить = (ключи: string[], значение: unknown) => ч.изменить(b => записать(b, ключи, значение))
  const действует = ч.действующая?.body.version
  const ломает = !!ч.проверка?.breaking

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Распознавание и подсказки"
        подпись="Узел распознаёт речь в разговоре и подсказывает оператору тему и поля итога. Звук из узла заказчика не уходит." />

      <Facts />

      {ч.загрузка && <p role="status" className="text-sm">Читаем паспорт у узла…</p>}
      {!!ч.ошибка && <NodeError ошибка={ч.ошибка} что="прочитать паспорт" />}
      {!ч.загрузка && !ч.ошибка && !п && (
        <EmptyBlock иконка={Sparkles} текст="У узла нет действующего паспорта"
          подсказка="Настройки подсказок — часть паспорта для КЦ. Паспорт появляется при первом запуске узла из файла passport.json." />
      )}
      {п && (
        <>
          <DraftBar ч={ч} примечание="это черновик паспорта: после применения уйдёт в контакт-центр" />
          <CheckResult ч={ч} подписи={ПОДПИСИ_ПАСПОРТА}
            последствия={[
              `Паспорт r${ч.черновик?.version} сразу уйдёт в контакт-центр: подсказки начнут работать по-новому со следующего звонка.`,
              ...(ломает ? [<span key="b" className="text-warning">Изменение ломающее: старшая принимаемая версия станет выше r{действует}. Пока КЦ не примет новую версию, его команды будут отклонены.</span>] : []),
            ]}
            подтверждение={ломает ? 'Понимаю: контакт-центр должен принять новую версию, иначе его команды будут отклонены' : undefined} />
          <section aria-label="Настройки подсказок" className="rounded-xl border border-border bg-card px-4">
            <EnrichmentTab п={п} ч={ч} поставить={поставить} />
          </section>
          <p className="text-xs text-muted-foreground">
            Остальное, что знает контакт-центр о линии, — на экране <Link to="/voice/passport" className="text-primary underline-offset-2 hover:underline">«Паспорт для КЦ»</Link>.
            Черновик у них общий.
          </p>
        </>
      )}
    </div>
  )
}

function Facts() {
  const { companyId } = useCompany()
  const [окно] = useState(() => ({ с: Date.now() - 86_400_000, по: Date.now() }))
  const здоровье = useQuery({ queryKey: ['voice-health', companyId], queryFn: () => voice.health(companyId), refetchInterval: 60_000 })
  const история = useQuery({
    queryKey: ['voice-health-history', companyId, 'asr', 'day', окно.с],
    queryFn: async () => {
      // Строка до начала суток говорит, в каком состоянии сутки начались.
      const [за, до] = await Promise.all([
        voice.healthHistory(companyId, { part: 'asr', from: new Date(окно.с).toISOString(), limit: 500 }),
        voice.healthHistory(companyId, { part: 'asr', to: new Date(окно.с).toISOString(), limit: 1 }),
      ])
      return [...за.items, ...до.items]
    },
  })
  const asr = здоровье.data?.parts?.asr
  const llm = здоровье.data?.parts?.llm
  const п = история.data ? простои(история.data, окно.с, окно.по) : null

  const строка = (имя: string, p?: voice.HealthPart) => (
    <p className="text-sm">
      <span className="font-medium">{имя}:</span>{' '}
      <span className={cn(p?.state === 'down' && 'text-destructive', p?.state === 'warn' && 'text-warning')}>
        {p ? СОСТОЯНИЕ_ЧАСТИ[p.state] ?? p.state : '—'}
      </span>
      {p?.since && p.state !== 'up' && <span className="text-muted-foreground"> с {когда(p.since)}</span>}
      {p && p.state !== 'up' && p.detail && <span className="text-muted-foreground"> · {p.detail}</span>}
    </p>
  )

  return (
    <section aria-label="Как работает сейчас" className="space-y-1.5 rounded-xl border border-border bg-card p-4">
      <h2 className="font-headline text-base font-semibold">Как работает сейчас</h2>
      {здоровье.isError && <NodeError ошибка={здоровье.error} что="узнать состояние распознавания" />}
      {здоровье.data && (
        <>
          {строка('Распознавание речи', asr)}
          {строка('Языковая модель', llm)}
        </>
      )}
      {п && (
        <p className="text-sm">
          За сутки распознавание {п.раз ? `пропадало ${п.раз} ${п.раз % 10 >= 2 && п.раз % 10 <= 4 && (п.раз % 100 < 12 || п.раз % 100 > 14) ? 'раза' : 'раз'}, всего ${сек(п.сек)}` : 'не пропадало'}.
          {' '}<Link to="/voice/health" className="text-primary underline-offset-2 hover:underline">История на «Состоянии узла»</Link>
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Сколько подсказок операторы приняли, узел не хранит: эти числа уходят в контакт-центр вместе с итогом звонка, и их показывает КЦ.
        Отставание распознавания от речи узел пока не измеряет — видно только, доступно ли оно.
      </p>
    </section>
  )
}
