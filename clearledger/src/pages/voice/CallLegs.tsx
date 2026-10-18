/**
 * Участки звонка (волна 7, Р3): кто говорил со звонящим, сколько, кто пытался и не
 * ответил, кому передали — поверх технических этапов узла (`legs` карточки).
 *
 * Сверху — цепочка одной строкой («Ждал 25 с › оператор КЦ … › консультация › передан ›
 * завершён»), под ней — участки с длительностью, удержанием, итогом и записью: плеер
 * участка открывает запись с его секунды (`offsetSec`). Приветствие и парковка — в
 * технических этапах, вместе с этапами узла: их смотрят при разборе, а не каждый раз.
 */
import { ChevronRight, Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type * as voice from '@/services/voiceService'
import { ГЛАВНЫЙ_УЧАСТОК, ИСХОД, ИТОГ_УЧАСТКА, ктоНаУчастке, сек, время, участок } from './format'

export interface ЗвукУчастка { id: string; url: string; offset: number; leg: number }

/** «1:05» — секунда записи, с которой начинается участок. */
const метка = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

/** Короткая надпись участка для цепочки. */
function звено(l: voice.Leg) {
  const кто = ктоНаУчастке(l.who)
  if (l.kind === 'queue') return `Ждал ${сек(l.durationSec)}`
  if (l.kind === 'attempt') return `${кто ?? 'оператор'}: ${ИТОГ_УЧАСТКА[l.result ?? ''] ?? 'не ответил'}`
  if (l.kind === 'consult') return `консультация${кто ? `: ${кто}` : ''}`
  if (l.kind === 'talk') return `${l.role && l.role !== 'answer' ? `${участок(l).toLowerCase()}: ` : ''}${кто ?? 'оператор'} · ${сек(l.durationSec)}`
  return участок(l).toLowerCase()
}

export function CallLegs({ legs, outcome, звук, onPlay, onEnded }: {
  legs: voice.Leg[]
  outcome?: voice.Outcome | null
  звук: ЗвукУчастка | null
  onPlay: (recordingId: string, offset: number, leg: number) => void
  onEnded: () => void
}) {
  const главные = legs.map((l, i) => ({ l, i })).filter(x => ГЛАВНЫЙ_УЧАСТОК.has(x.l.kind))
  if (!главные.length) return null
  return (
    <section aria-label="Участки звонка" className="space-y-2">
      <h2 className="text-sm font-medium">Кто говорил со звонящим</h2>
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-1 text-sm">
        {главные.map(({ l, i }) => (
          <li key={i} className="flex items-center gap-1">
            <span className={cn('rounded-md border px-1.5 leading-6',
              l.kind === 'talk' ? 'border-primary/40 bg-primary/5' : 'border-border',
              l.kind === 'attempt' && 'text-muted-foreground')}>
              {звено(l)}
            </span>
            <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          </li>
        ))}
        <li className="rounded-md border border-border px-1.5 leading-6">
          {outcome ? `завершён: ${ИСХОД[outcome] ?? outcome}` : 'идёт'}
        </li>
      </ol>

      <ol className="divide-y divide-border/60 rounded-lg border border-border">
        {главные.map(({ l, i }) => {
          const кто = ктоНаУчастке(l.who)
          return (
            <li key={i} className="space-y-1 px-2.5 py-2 text-sm">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="w-16 shrink-0 font-mono text-xs text-muted-foreground">{время(l.startedAt)}</span>
                <span className="min-w-0 flex-1">
                  <span className={cn(l.kind === 'attempt' && 'text-muted-foreground')}>{участок(l)}</span>
                  {кто && <span className="font-medium"> · {кто}</span>}
                  {l.kind === 'consult' && l.conference && <span className="text-muted-foreground"> · втроём</span>}
                </span>
                <span className="tabular-nums">{l.endedAt ? сек(l.durationSec) : 'идёт'}</span>
              </div>
              <p className="pl-[4.5rem] text-xs text-muted-foreground">
                {l.result ? ИТОГ_УЧАСТКА[l.result] ?? <span className="font-mono">{l.result}</span> : 'участок не закончился'}
                {!!l.holdSec && <> · на удержании {сек(l.holdSec)}</>}
              </p>
              {!!l.recordings.length && (
                <div className="flex flex-wrap gap-1.5 pl-[4.5rem]">
                  {l.recordings.map(r => (
                    <Button key={`${r.recordingId}-${r.side}`} variant="outline" size="xs"
                      onClick={() => onPlay(r.recordingId, r.offsetSec, i)}
                      aria-label={`${r.side === 'caller' ? 'Запись звонящего' : 'Запись оператора'} с ${метка(r.offsetSec)}`}>
                      <Play />{r.side === 'caller' ? 'звонящий' : 'оператор'} с {метка(r.offsetSec)}
                    </Button>
                  ))}
                </div>
              )}
              {звук?.leg === i && (
                // Ссылка разовая (60 с, одно открытие): повтор — новый запрос с причиной.
                <audio controls autoPlay src={звук.url} className="w-full"
                  onLoadedMetadata={e => { e.currentTarget.currentTime = звук.offset }} onEnded={onEnded} />
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
