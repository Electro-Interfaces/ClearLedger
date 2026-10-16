/**
 * «Сейчас» — первый экран «Телефонии»: принимается ли линия и кто ждёт.
 *
 * Экран живой: узел шлёт снимок, затем изменения раз в секунду (поток SSE), без
 * кнопки «Обновить». Сверху одна строка о здоровье узла — «работает» или
 * «работает, кроме: …», под ней тревоги словами, затем числа за сегодня и
 * таблицы: кто ждёт, кто говорит, операторы. Номер — только маской: целиком он
 * открывается в карточке звонка по причине.
 */
import { useEffect, useMemo, useReducer, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, AlertTriangle, CheckCircle2, PhoneIncoming, Radio, Users } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { useСейчас } from '@/pages/conf/format'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import {
  СОСТОЯНИЕ, ТРЕВОГА, оператор, подробностьТревоги, процент, прошло, сек, число, ПРИСУТСТВИЕ,
} from './format'
import { Heading, Flags, NodeError, Stat } from './parts'

type Связь = 'connecting' | 'live' | 'reconnecting' | 'failed'

function свести(s: voice.NowSnapshot | null, e: voice.NowEvent): voice.NowSnapshot | null {
  if (e.type === 'snapshot') return e.data
  if (!s) return s
  switch (e.type) {
    case 'contact': {
      const rest = s.contacts.filter(c => c.contactId !== e.data.contactId)
      return { ...s, contacts: e.data.state === 'ended' ? rest : [...rest, e.data as voice.LiveContact].sort((a, b) => a.since.localeCompare(b.since)) }
    }
    case 'operator': {
      const id = (o: voice.LiveOperator) => `${o.operator.kind}:${o.operator.id}`
      const rest = s.operators.filter(o => id(o) !== id(e.data))
      return { ...s, operators: [...rest, e.data].sort((a, b) => id(a).localeCompare(id(b))) }
    }
    case 'trunk': return { ...s, trunk: e.data.trunk }
    case 'cc': return { ...s, cc: e.data }
    case 'stats': return { ...s, today: e.data.today, callbacksDue: e.data.callbacksDue }
    case 'alert': {
      const rest = (s.alerts ?? []).filter(a => a.id !== e.data.id)
      return { ...s, alerts: e.data.state === 'raised' ? [...rest, e.data] : rest }
    }
  }
  return s
}

/**
 * Снимок «Сейчас» потоком. Экраны «Телефонии» пересоздаются на смену компании
 * (ключ в VoiceLayout), поэтому начальное состояние здесь всегда чистое.
 */
function useLiveNow(companyId: string) {
  const [снимок, dispatch] = useReducer(свести, null)
  const [связь, setСвязь] = useState<Связь>('connecting')
  const [ошибка, setОшибка] = useState<unknown>(null)
  useEffect(() => {
    if (!companyId) return
    return voice.nowStream(companyId, dispatch, (s, e) => {
      setСвязь(s)
      setОшибка(s === 'live' ? null : e ?? null)
    })
  }, [companyId])
  return { снимок, связь, ошибка }
}

const ЖДУТ: voice.LiveState[] = ['ivr', 'waiting', 'offered', 'dialing', 'fallback']

export default function VoiceNowPage() {
  const { companyId } = useCompany()
  const { снимок, связь, ошибка } = useLiveNow(companyId)
  const сейчас = useСейчас(1000)

  const ждут = useMemo(() => снимок?.contacts.filter(c => ЖДУТ.includes(c.state)) ?? [], [снимок])
  const говорят = useMemo(() => снимок?.contacts.filter(c => !ЖДУТ.includes(c.state)) ?? [], [снимок])

  return (
    <div className="space-y-5 p-4">
      <Heading имя="Сейчас" подпись={<LinkState связь={связь} at={снимок?.at} />} />

      {связь === 'failed' && <NodeError ошибка={ошибка} что="открыть поток «Сейчас»" />}
      {связь === 'reconnecting' && !!ошибка && (
        <p role="status" className="text-xs text-muted-foreground">
          Связь с узлом прервалась, переподключаемся. Пока показан последний известный снимок.
        </p>
      )}
      {!снимок && связь !== 'failed' && <p role="status" className="text-sm">Подключаемся к узлу…</p>}

      {снимок && (
        <>
          <HealthLine снимок={снимок} />
          <AlertList тревоги={снимок.alerts ?? []} />
          <TodayTiles снимок={снимок} />

          <section className="space-y-2">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              <PhoneIncoming className="h-4 w-4 text-muted-foreground" />
              Ждут ответа · {ждут.length}
            </h2>
            {ждут.length === 0
              ? <p className="text-sm text-muted-foreground">Сейчас никто не ждёт.</p>
              : <ContactTable строки={ждут} сейчас={сейчас} ожидание />}
          </section>

          <section className="space-y-2">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              <Radio className="h-4 w-4 text-muted-foreground" />
              Разговоры · {говорят.length}
            </h2>
            {говорят.length === 0
              ? <p className="text-sm text-muted-foreground">Разговоров нет.</p>
              : <ContactTable строки={говорят} сейчас={сейчас} />}
          </section>

          <section className="space-y-2">
            <h2 className="flex items-center gap-2 text-sm font-medium">
              <Users className="h-4 w-4 text-muted-foreground" />
              Операторы и сотрудники · {снимок.operators.length}
            </h2>
            {снимок.operators.length === 0
              ? <EmptyBlock иконка={Users} текст="Узел не видит ни одного оператора"
                  подсказка="Операторы контакт-центра появятся после допуска в разделе «Контакт-центры», трубки сотрудников — из правил приёма." />
              : <OperatorTable строки={снимок.operators} />}
          </section>
        </>
      )}
    </div>
  )
}

function LinkState({ связь, at }: { связь: Связь; at?: string }) {
  if (связь === 'live') return <span className="inline-flex items-center gap-1"><Activity className="h-3 w-3 text-success" />обновляется само, раз в секунду</span>
  if (связь === 'reconnecting') return <>переподключаемся{at ? `, снимок на ${new Date(at).toLocaleTimeString('ru-RU')}` : ''}</>
  if (связь === 'failed') return <>поток остановлен</>
  return <>подключаемся</>
}

/** Одна строка о здоровье: перечисляем только то, что не в порядке. */
function HealthLine({ снимок }: { снимок: voice.NowSnapshot }) {
  const кроме: string[] = []
  if (снимок.trunk === 'down') кроме.push('SIP-транк не отвечает')
  if (снимок.trunk === 'unknown') кроме.push('состояние SIP-транка неизвестно')
  if (!снимок.cc.connectionId) кроме.push('контакт-центр не подключён')
  else if (!снимок.cc.online) кроме.push('контакт-центр не на связи')
  const плохо = снимок.trunk === 'down' || (!!снимок.cc.connectionId && !снимок.cc.online)
  return (
    <div className={cn('flex items-start gap-2 rounded-lg border p-3 text-sm',
      плохо ? 'border-destructive/40 bg-destructive/5' : кроме.length ? 'border-warning/50 bg-warning/5' : 'border-border bg-card')}>
      {кроме.length
        ? <AlertTriangle className={cn('mt-0.5 h-4 w-4 shrink-0', плохо ? 'text-destructive' : 'text-warning')} />
        : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />}
      <p className="min-w-0 flex-1">
        {кроме.length ? <>Узел работает, кроме: {кроме.join('; ')}.</> : 'Узел работает: транк на связи, контакт-центр принимает звонки.'}
      </p>
    </div>
  )
}

function AlertList({ тревоги }: { тревоги: voice.Alert[] }) {
  if (!тревоги.length) return null
  return (
    <ul className="space-y-1.5" aria-label="Тревоги узла">
      {тревоги.map(т => {
        const подробно = подробностьТревоги(т)
        return (
          <li key={т.id} className={cn('flex items-start gap-2 rounded-lg border p-3 text-sm',
            т.severity === 'critical' ? 'border-destructive/40 bg-destructive/5' : 'border-warning/50 bg-warning/5')}>
            <AlertTriangle className={cn('mt-0.5 h-4 w-4 shrink-0', т.severity === 'critical' ? 'text-destructive' : 'text-warning')} />
            <div className="min-w-0 flex-1">
              <p>{ТРЕВОГА[т.code] ?? т.code}</p>
              <p className="text-xs text-muted-foreground">
                {т.severity === 'critical' ? 'Срочно' : 'Предупреждение'} · с {new Date(т.raisedAt).toLocaleTimeString('ru-RU')}
                {подробно && <> · {подробно}</>}
              </p>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function TodayTiles({ снимок }: { снимок: voice.NowSnapshot }) {
  const t = снимок.today
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">За сегодня</h2>
      <div className="flex flex-wrap gap-x-8 gap-y-3 border-b border-border pb-4">
        <Stat имя="Поступило" значение={число(t.arrived)}
          пояснение="Все звонки линии, кроме звонков-задач «перезвонить»" />
        <Stat имя="Уровень обслуживания (SL)" значение={процент(t.slPct)}
          тон={t.slPct != null && t.slPct < 80 ? 'warning' : undefined}
          пояснение="Отвечено за целевое время линии от поставленных в очередь, без коротко брошенных" />
        <Stat имя="Среднее ожидание ответа (ASA)" значение={сек(t.asaSec)}
          пояснение="Среднее ожидание отвеченных звонков" />
        <Stat имя="Брошено" значение={процент(t.abandonPct)}
          пояснение="Брошенные из поставленных в очередь, без коротко брошенных (меньше 5 с)" />
        <Stat имя="Вне часов" значение={число(t.afterHours)} />
        <div className="min-w-28">
          <p className="text-xs text-muted-foreground">Перезвонить пора</p>
          <Link to="/voice/callbacks" className={cn('font-headline text-xl font-semibold tabular-nums underline-offset-4 hover:underline',
            снимок.callbacksDue > 0 && 'text-warning')}>
            {число(снимок.callbacksDue)}
          </Link>
        </div>
      </div>
    </section>
  )
}

/** Таблица живых обращений; ожидание идёт на экране без запроса к узлу. */
function ContactTable({ строки, сейчас, ожидание }: { строки: voice.LiveContact[]; сейчас: number; ожидание?: boolean }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-card text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-normal">Номер</th>
            <th className="px-3 py-2 font-normal">Состояние</th>
            <th className="px-3 py-2 font-normal">{ожидание ? 'Ждёт' : 'Идёт'}</th>
            <th className="px-3 py-2 font-normal">{ожидание ? 'Линия' : 'Кто ведёт'}</th>
            <th className="px-3 py-2 font-normal"><span className="sr-only">Карточка</span></th>
          </tr>
        </thead>
        <tbody>
          {строки.map(c => (
            <tr key={c.contactId} className="border-t border-border/60">
              <td className="px-3 py-2">
                <span className="font-mono text-xs">{c.number || '—'}</span>
                <span className="ml-2"><Flags флаги={c.flags} /></span>
              </td>
              <td className="px-3 py-2">{СОСТОЯНИЕ[c.state] ?? c.state}</td>
              <td className="px-3 py-2 tabular-nums">{сек(прошло(c.since, сейчас))}</td>
              <td className="px-3 py-2 text-muted-foreground">{ожидание ? c.lineId : оператор(c.operator)}</td>
              <td className="px-3 py-2 text-right">
                <Link to={`/voice/calls?id=${encodeURIComponent(c.contactId)}`}
                  className="text-xs text-primary underline-offset-4 hover:underline">Карточка</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function OperatorTable({ строки }: { строки: voice.LiveOperator[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-card text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-normal">Кто</th>
            <th className="px-3 py-2 font-normal">Откуда</th>
            <th className="px-3 py-2 font-normal">Присутствие</th>
            <th className="px-3 py-2 font-normal">Сейчас</th>
          </tr>
        </thead>
        <tbody>
          {строки.map(o => (
            <tr key={`${o.operator.kind}:${o.operator.id}`} className="border-t border-border/60">
              <td className="px-3 py-2">{оператор(o.operator)}</td>
              <td className="px-3 py-2 text-muted-foreground">{o.operator.kind === 'cc' ? 'контакт-центр' : 'заказчик'}</td>
              <td className="px-3 py-2">{ПРИСУТСТВИЕ[o.presence] ?? o.presence}</td>
              <td className="px-3 py-2">
                {o.busy
                  ? o.contactId
                    ? <Link to={`/voice/calls?id=${encodeURIComponent(o.contactId)}`} className="text-primary underline-offset-4 hover:underline">в разговоре</Link>
                    : 'в разговоре'
                  : <span className="text-muted-foreground">свободен</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
