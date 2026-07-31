/**
 * Общие детали «Пульса»: форматирование чисел, плитка показателя, состояния
 * загрузки/ошибки/пустоты. Один модуль на все четыре раздела — раньше форматтеры
 * и плитки жили в двух файлах двумя расходящимися копиями.
 *
 * Плитка построена на общем `Kpi` пространства (components/workspace/analytics),
 * а не на своих div'ах: у «Пульса» нет причин выглядеть иначе, чем «Продажи».
 */
import { Loader2, TrendingDown, TrendingUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { PulseKpi } from './pulseService'

const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
// Крупные суммы — компактно («1,1 млн ₽»): на телефоне «1 147 344 ₽» переносится
// на вторую строку, а руководителю нужен порядок величины, а не рубли до копейки.
const nfShort = new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 })

export function fmtNum(value: number | null, unit?: string | null): string {
  if (value == null) return '—'
  const s = (Math.abs(value) >= 100_000 ? nfShort : nf).format(value)
  return unit ? `${s} ${unit}` : s
}

export const fmtDate = (s: string | null) =>
  s ? new Date(s).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }) : '—'

/** «1 требует», «3 требуют» — счётчик на экране директора читает человек. */
export function plural(n: number, one: string, few: string, many: string): string {
  const t = Math.abs(n) % 100
  if (t >= 11 && t <= 14) return many
  return { 1: one, 2: few, 3: few, 4: few }[t % 10] ?? many
}

/**
 * Плитка показателя. Канон пространства: `Card` с `bg-card`, подпись
 * `uppercase tracking-wider`, значение `text-lg font-semibold tabular-nums`
 * (`components/workspace/analytics/Kpi.tsx`).
 *
 * Отличия «Пульса» от базового `Kpi` — ровно два, и оба по делу:
 *  * `state` красит рамку, когда показатель просит внимания или устарел;
 *  * `onClick` делает плитку входом в разрез (лестница погружения, PULSE.md §2).
 */
export function KpiTile({ k, onOpen }: { k: PulseKpi; onOpen?: () => void }) {
  // Полярность задаёт сервер: рост выручки — хорошо, рост потока заявок — нет.
  // Раньше зелёным красился любой плюс, и «заявок поступило +30%» выглядело победой.
  const good = k.delta_pct == null ? null
    : (k.higher_is_better === false ? k.delta_pct < 0 : k.delta_pct >= 0)
  const showDelta = k.delta_pct != null && Math.abs(k.delta_pct) <= 500
  const Arrow = (k.delta_pct ?? 0) >= 0 ? TrendingUp : TrendingDown

  const body = (
    <CardContent className="p-3 text-left">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{k.title}</div>
      {/* Значение и дельта в одной строке; при нехватке места ужимается дельта,
          а не число — оно и есть ответ. overflow-hidden: длинные значения
          («271,8 тыс. кВт·ч») вылезали за рамку плитки на телефоне. */}
      <div className="mt-0.5 flex items-baseline gap-x-1.5 overflow-hidden">
        <span className="truncate text-lg font-semibold tabular-nums">
          {fmtNum(k.value, k.unit)}
        </span>
        {showDelta && (
          <span className={cn('flex shrink-0 items-center gap-0.5 text-[11px] font-medium tabular-nums',
            good ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
            <Arrow className="h-3 w-3" />{Math.abs(k.delta_pct!).toFixed(1)}%
          </span>
        )}
      </div>
      {k.note && <div className="mt-0.5 text-[11px] text-muted-foreground">{k.note}</div>}
    </CardContent>
  )

  const cls = cn('py-0 transition-colors',
    k.state === 'warn' && 'border-amber-500/40 bg-amber-500/5',
    // Устаревшие данные — рамкой и подписью, а не прозрачностью: гашение
    // приглушённого текста уводило подпись ниже порога контраста.
    k.state === 'stale' && 'border-dashed',
    onOpen && 'cursor-pointer hover:border-primary/50 hover:bg-accent/40')

  if (!onOpen) return <Card className={cls}>{body}</Card>
  // Кликабельная плитка — настоящая кнопка: клавиатура и скринридер получают её
  // бесплатно, в отличие от div с onClick.
  return (
    <button type="button" onClick={onOpen}
      className="rounded-xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <Card className={cls}>{body}</Card>
    </button>
  )
}

export function PulseLoading({ what }: { what: string }) {
  return (
    <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />Загрузка {what}…
    </div>
  )
}

/** Отказ ручки — с объяснением и кнопкой: пустой экран у руководителя недопустим. */
export function PulseError({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div className="rounded-lg border p-6 text-center text-sm">
      <p className="text-destructive">Не удалось загрузить {what}</p>
      <Button variant="outline" size="sm" className="mt-2 h-8" onClick={onRetry}>Повторить</Button>
    </div>
  )
}
