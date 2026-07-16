/**
 * Индикатор свежести данных «данные на <дата>» (F3): движение товара и остатки
 * ЦБ наполняются отдельным снимком и отстают от продаж — пользователь должен
 * видеть, на какую дату актуальны цифры. Жёлтый, если снимок старше 3 дней.
 */
import { Clock } from 'lucide-react'

export function SnapshotBadge({ at }: { at?: string | null }) {
  if (!at) return null
  const d = new Date(at)
  if (Number.isNaN(d.getTime())) return null
  const stale = (Date.now() - d.getTime()) > 3 * 864e5
  const p = (n: number) => String(n).padStart(2, '0')
  const label = `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()}`
  return (
    <span
      title={`Снимок данных движения/остатков от ${label}. Продажи могут быть свежее — движение обновляется отдельным пуллом.`}
      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] ${
        stale
          ? 'border-amber-400/50 text-amber-600 dark:text-amber-400'
          : 'border-zinc-600 text-zinc-400'
      }`}
    >
      <Clock className="h-2.5 w-2.5" />
      данные на {label}
    </span>
  )
}
