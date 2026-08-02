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
  const days = Math.floor((Date.now() - d.getTime()) / 864e5)
  const stale = days > 3
  const p = (n: number) => String(n).padStart(2, '0')
  const label = `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()}`
  // Возраст словами: «данные на 12.07.2026» не тревожит, пока не увидишь, что это три
  // недели назад. Снимок наполняется отдельным каналом и может стоять неделями.
  const age = days < 1 ? 'сегодня' : days === 1 ? 'вчера' : `${days} дн. назад`
  return (
    <span
      title={`Снимок данных движения/остатков от ${label} (${age}). Продажи могут быть свежее — движение обновляется отдельным пуллом.`}
      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] ${
        stale
          ? 'border-amber-400/50 text-amber-600 dark:text-amber-400'
          : 'border-zinc-600 text-zinc-400'
      }`}
    >
      <Clock className="h-2.5 w-2.5" />
      данные на {label}{stale && ` · ${age}`}
    </span>
  )
}
