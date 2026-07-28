/**
 * Лента этапов проекта — общая шкала жизненного цикла ЭЗС.
 *
 * Смысл: у проекта один путь — Подбор → Земля → Реализация → Эксплуатация.
 * Подбор площадки не отдельная дисциплина со своей воронкой, а первый этап
 * того же проекта; присоединение и оборудование — часть третьего. Поэтому лента
 * висит и в карточке проекта, и над обзорными экранами: где бы пользователь ни
 * находился, он видит один и тот же путь и своё место на нём.
 *
 * Два режима:
 *   • `current` — этап конкретного проекта (в карточке), с подсветкой текущего;
 *   • счётчики — сколько проектов на каждом этапе (на обзорных экранах), клик
 *     переводит на экран этого этапа.
 */
import { CheckCircle2, Circle, Play } from 'lucide-react'

export interface PhaseStripItem {
  key: string
  label: string
  hint?: string
  count?: number
}

/** Порядок и смысл этапов — единственное место, где он задан на фронте. */
export const PHASES: PhaseStripItem[] = [
  { key: 'select', label: 'Подбор площадки', hint: 'где строить: лид → скрининг → переговоры → проработка → решение' },
  { key: 'land', label: 'Оформление земли', hint: 'аренда, сервитут или разрешение на размещение' },
  { key: 'build', label: 'Реализация', hint: 'присоединение, оборудование, монтаж, пусконаладка' },
  { key: 'operate', label: 'Эксплуатация', hint: 'станция работает в сети' },
]

const PHASE_ORDER = PHASES.map((p) => p.key)

export function ProjectPhaseStrip({ current, counts, onPick, note }: {
  /** Этап текущего проекта — подсвечивается как «сейчас». */
  current?: string | null
  /** Сколько проектов на каждом этапе (обзорные экраны). */
  counts?: Record<string, number>
  onPick?: (phase: string) => void
  note?: string
}) {
  const curIdx = current ? PHASE_ORDER.indexOf(current) : -1

  return (
    <div className="rounded-lg border border-border bg-muted/20 px-3 py-2">
      <div className="flex items-center gap-1 overflow-x-auto">
        {PHASES.map((p, i) => {
          const state = curIdx < 0 ? 'plain' : i < curIdx ? 'done' : i === curIdx ? 'current' : 'future'
          const Icon = state === 'done' ? CheckCircle2 : state === 'current' ? Play : Circle
          const clickable = !!onPick
          return (
            <div key={p.key} className="flex items-center gap-1 shrink-0">
              <button type="button" disabled={!clickable} onClick={() => onPick?.(p.key)}
                title={p.hint}
                className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-sm transition-colors
                  ${state === 'current' ? 'bg-primary/10 text-primary font-medium'
                    : state === 'done' ? 'text-emerald-600 dark:text-emerald-400'
                    : state === 'future' ? 'text-muted-foreground'
                    : 'text-foreground'}
                  ${clickable ? 'hover:bg-muted' : 'cursor-default'}`}>
                <Icon className="h-3.5 w-3.5 shrink-0" />
                <span className="whitespace-nowrap">
                  {i + 1}. {p.label}
                </span>
                {counts && (
                  <span className="font-mono text-xs text-muted-foreground">
                    {counts[p.key] ?? 0}
                  </span>
                )}
              </button>
              {i < PHASES.length - 1 && <span className="text-muted-foreground/40 text-sm">→</span>}
            </div>
          )
        })}
      </div>
      {note && <div className="text-xs text-muted-foreground mt-1">{note}</div>}
    </div>
  )
}
