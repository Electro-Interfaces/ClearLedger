/**
 * «Проверить на примере» (волна 7, Р5): что узел сделает со звонком по этим правилам —
 * в такой день и час, с таким звонящим, при таком состоянии контакт-центра.
 *
 * Отвечает сам узел (`POST /config/{вид}/simulate` и `/versions/{v}/simulate`) теми же
 * функциями, что принимают живой звонок, — второй модели маршрута на экране нет.
 * Пример ничего не применяет, не звонит и не пишет в журнал. Черновик проверяется в том
 * виде, в каком он сохранён у узла.
 */
import { useState } from 'react'
import { ChevronDown, FlaskConical } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import type { Черновик } from './useDraft'
import { ПРИЧИНА_ЗАПАСНОГО } from './format'

const ДНИ = [['mon', 'пн'], ['tue', 'вт'], ['wed', 'ср'], ['thu', 'чт'], ['fri', 'пт'], ['sat', 'сб'], ['sun', 'вс']] as const
type День = (typeof ДНИ)[number][0]
const ЗВОНЯЩИЙ = [['normal', 'обычный'], ['vip', 'VIP'], ['repeat', 'повторный']] as const
const КЦ = [['online', 'на связи'], ['offline', 'связь оборвана'], ['none', 'не подключён']] as const
const ОПЕРАТОРЫ = [['ready', 'есть готовые'], ['none', 'нет готовых']] as const

const мс = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

function Выбор<T extends string>({ подпись, value, onChange, варианты }: {
  подпись: string; value: T; onChange: (v: T) => void; варианты: readonly (readonly [T, string])[]
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{подпись}</span>
      <div role="radiogroup" aria-label={подпись} className="flex gap-0.5 rounded-md border border-border p-0.5">
        {варианты.map(([k, т]) => (
          <button key={k} type="button" role="radio" aria-checked={value === k} onClick={() => onChange(k)}
            className={cn('min-h-8 rounded px-2.5 text-sm transition-colors',
              value === k ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent/50')}>
            {т}
          </button>
        ))}
      </div>
    </div>
  )
}

function итогСловами(r: voice.Simulation['result']) {
  const кем = r.by === 'cc' ? 'оператор контакт-центра' : r.by === 'staff' ? 'сотрудник заказчика' : 'оператор'
  if (r.kind === 'operator') return `Ответит ${кем}`
  if (r.kind === 'forward') return 'Уйдёт переадресацией'
  return 'Звонящий услышит сообщение'
}

export function SimulatePanel<B>({ kind, ч }: { kind: 'passport' | 'reception'; ч: Черновик<B> }) {
  const { companyId } = useCompany()
  const сейчас = new Date()
  const [открыт, setОткрыт] = useState(false)
  const [наЧерновике, setНаЧерновике] = useState(true)
  const [день, setДень] = useState<День>(ДНИ[(сейчас.getDay() + 6) % 7][0])
  const [время, setВремя] = useState(`${String(сейчас.getHours()).padStart(2, '0')}:${String(сейчас.getMinutes()).padStart(2, '0')}`)
  const [звонящий, setЗвонящий] = useState<'normal' | 'vip' | 'repeat'>('normal')
  const [кц, setКц] = useState<'online' | 'offline' | 'none'>('online')
  const [операторы, setОператоры] = useState<'ready' | 'none'>('ready')
  const [узелЛежит, setУзелЛежит] = useState(false)
  const [ответ, setОтвет] = useState<voice.Simulation | null>(null)
  const [идёт, setИдёт] = useState(false)

  const черновик = ч.черновик?.version

  async function проверить(e: React.FormEvent) {
    e.preventDefault()
    setИдёт(true)
    try {
      // При быстром нажатии правка ещё может ждать 800 мс автосохранения.
      // Узел симулирует только сохранённую версию, поэтому сначала дожидаемся её номера.
      const версияДляПримера = наЧерновике ? await ч.сохранить() : undefined
      setОтвет(await voice.simulate(companyId, kind,
        { day: день, time: время, caller: звонящий, cc: кц, operators: операторы, nodeDown: узелЛежит }, версияДляПримера))
    } catch (err) {
      setОтвет(null)
      toast.error(err instanceof voice.VoiceError && err.code === 'config_invalid'
        ? 'Черновик с ошибками: проверьте его кнопкой «Проверить» и исправьте поля'
        : err instanceof Error ? err.message : 'Узел не ответил')
    } finally {
      setИдёт(false)
    }
  }

  return (
    <section aria-label="Проверить на примере" className="rounded-xl border border-border bg-card">
      <button type="button" aria-expanded={открыт} onClick={() => setОткрыт(!открыт)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left">
        <FlaskConical className="size-4 shrink-0 text-primary" />
        <span className="min-w-0 flex-1">
          <span className="text-sm font-medium">Проверить на примере</span>
          <span className="block text-xs text-muted-foreground">Куда попадёт звонок в такой день и час — по этим правилам. Ничего не меняет и не звонит.</span>
        </span>
        <ChevronDown className={cn('size-4 shrink-0 transition-transform', открыт && 'rotate-180')} />
      </button>

      {открыт && (
        <div className="space-y-4 border-t border-border/60 px-4 py-3">
          <form onSubmit={проверить} className="flex flex-wrap items-end gap-3">
            {черновик != null && (
              <Выбор подпись="Правила" value={наЧерновике ? 'draft' : 'active'} onChange={v => setНаЧерновике(v === 'draft')}
                варианты={[['draft', `черновик r${черновик}`], ['active', `действующие r${ч.действующая?.version ?? ''}`]]} />
            )}
            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-muted-foreground">Когда</span>
              <div className="flex gap-1.5">
                <select value={день} onChange={e => setДень(e.target.value as День)} aria-label="День недели"
                  className="h-9 rounded-md border border-input bg-card px-2 text-sm">
                  {ДНИ.map(([k, т]) => <option key={k} value={k}>{т}</option>)}
                </select>
                <Input type="time" value={время} onChange={e => setВремя(e.target.value)} aria-label="Время по поясу линии"
                  required className="h-9 w-28" />
              </div>
            </div>
            <Выбор подпись="Звонящий" value={звонящий} onChange={setЗвонящий} варианты={ЗВОНЯЩИЙ} />
            <Выбор подпись="Контакт-центр" value={кц} onChange={setКц} варианты={КЦ} />
            <Выбор подпись="Операторы" value={операторы} onChange={setОператоры} варианты={ОПЕРАТОРЫ} />
            <label className="flex h-9 items-center gap-2 text-sm">
              <Switch checked={узелЛежит} onCheckedChange={setУзелЛежит} aria-label="Узел не работает" />
              узел не работает
            </label>
            <Button type="submit" size="sm" disabled={идёт || !время}>{идёт ? 'Считаем…' : 'Показать маршрут'}</Button>
          </form>
          {ответ && (
            <div className="space-y-3" aria-live="polite">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <p className="font-headline text-base font-semibold">
                  {итогСловами(ответ.result)}{ответ.result.atSec != null && <span className="font-normal text-muted-foreground"> · через {мс(ответ.result.atSec)}</span>}
                </p>
                <p className="text-xs text-muted-foreground">
                  {ответ.local.dayRu ?? ответ.local.day} {ответ.local.date} {ответ.local.time} ({ответ.local.tz})
                  {' · '}паспорт r{ответ.versions.passport} · правила r{ответ.versions.reception}
                </p>
              </div>
              {ответ.decision && (
                <ul className="flex flex-wrap gap-1.5 text-xs">
                  <li className="rounded-md border border-border px-1.5 leading-6">{ответ.decision.inHours ? 'в часы приёма' : 'вне часов приёма'}</li>
                  {ответ.decision.vip && <li className="rounded-md border border-border px-1.5 leading-6">VIP</li>}
                  {ответ.decision.repeat && <li className="rounded-md border border-border px-1.5 leading-6">повторный</li>}
                  {ответ.decision.priority != null && <li className="rounded-md border border-border px-1.5 leading-6">приоритет {ответ.decision.priority}</li>}
                  {ответ.decision.ceilingSec != null && <li className="rounded-md border border-border px-1.5 leading-6">потолок ожидания {мс(ответ.decision.ceilingSec)}</li>}
                </ul>
              )}
              <ol className="space-y-1 border-l border-border pl-3">
                {/* Узел пишет шаги по ходу расчёта; читать их удобнее по времени от прихода звонка. */}
                {[...ответ.steps].sort((a, b) => a.atSec - b.atSec).map((s, i) => (
                  <li key={i} className="flex gap-3 text-sm">
                    <span className="w-12 shrink-0 font-mono text-xs leading-5 text-muted-foreground">{мс(s.atSec)}</span>
                    <span className={cn(i === ответ.steps.length - 1 && 'font-medium')}>{s.title}</span>
                  </li>
                ))}
              </ol>
              {ответ.result.reason && <p className="text-sm text-muted-foreground">Причина: {ПРИЧИНА_ЗАПАСНОГО[ответ.result.reason] ?? ответ.result.reason}</p>}
              {!!ответ.notes.length && (
                <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
                  {ответ.notes.map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
