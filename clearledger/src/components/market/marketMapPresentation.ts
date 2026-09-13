import type { MarketSite, OurMapPoint } from '@/services/marketService'
import type { OurFilters } from './MarketMapFilters'

/** Цвет нашей станции — по выбранному показателю: состояние, загрузка, срывы, деньги.
 *  Один слой отвечает на разные вопросы, не превращаясь в четыре карты. */
export function ourColor(p: OurMapPoint, by: OurFilters['colorBy']): string {
  if (by === 'status') {
    if (p.status === 'working') return '#3b82f6'
    if (p.status === 'no_link') return '#f59e0b'
    if (p.status === 'decommissioned' || p.status === 'disabled') return '#64748b'
    if (p.status === 'not_working') return '#ef4444'
    return '#3b82f6'
  }
  if (by === 'load') {
    const v = p.sessionsPerPortDay
    if (v == null) return '#64748b'
    return v >= 2 ? '#0ea5e9' : v >= 1 ? '#3b82f6' : v >= 0.3 ? '#a5b4fc' : '#cbd5e1'
  }
  if (by === 'errors') {
    const v = p.errorPct
    if (v == null) return '#64748b'
    return v >= 30 ? '#ef4444' : v >= 10 ? '#f59e0b' : '#22c55e'
  }
  const v = p.revenue
  return v >= 1_000_000 ? '#1d4ed8' : v >= 200_000 ? '#3b82f6' : v > 0 ? '#93c5fd' : '#cbd5e1'
}

/** Цвет точки на карте: наши — фирменный, конкуренты — красный, притяжение — серый. */
export function siteColor(s: MarketSite): string {
  if (s.isOurs) return '#3b82f6'
  if (s.kind !== 'ezs') return '#94a3b8'
  // Независимая точка — не сеть: другой цвет, чтобы плотность рынка не выглядела
  // плотностью сетей (полная выгрузка 13.09.2026).
  if (s.siteClass === 'independent') return '#f59e0b'
  if (s.siteClass === 'home') return '#a78bfa'
  return '#ef4444'
}

/** Возраст факта словами: «сегодня» важнее даты — по нему видно, можно ли доверять. */
export function ageLabel(iso: string | null | undefined): { text: string; stale: boolean } {
  if (!iso) return { text: 'не проверялось', stale: true }
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return { text: 'сегодня', stale: false }
  if (days === 1) return { text: 'вчера', stale: false }
  return { text: `${days} дн назад`, stale: days > 30 }
}
