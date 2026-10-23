interface OccupancyHour {
  hour: number
  occupied_minutes: number
  available_minutes: number
  starts: number
  occupancy_complete?: boolean
  starts_complete?: boolean
}

/** Каждый выбранный час повторяется в каждый день периода. Граница «до» не входит.
 * Минуты уже получены пересечением реальных сессий с часами на сервере.
 * Процент взвешивается временем: среднее процентов с разными знаменателями неверно. */
export function occupancyInterval(points: readonly OccupancyHour[], from: number, to: number) {
  if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || from >= to || to > 24) {
    throw new Error('Начало интервала должно быть раньше окончания, в пределах 00:00–24:00')
  }
  const selected = points.filter(p => p.hour >= from && p.hour < to)
  if (selected.length !== to - from || new Set(selected.map(p => p.hour)).size !== selected.length) {
    throw new Error('Нет полного набора часов для выбранного интервала')
  }
  const available = selected.reduce((n, p) => n + p.available_minutes, 0)
  const occupied = selected.reduce((n, p) => n + p.occupied_minutes, 0)
  const occupancyComplete = selected.every(p => p.occupancy_complete !== false)
  const startsComplete = selected.every(p => p.starts_complete !== false)
  return {
    occupied_minutes: occupancyComplete ? Math.round(occupied * 1e6) / 1e6 : null,
    available_minutes: available,
    occupancy_pct: occupancyComplete && available > 0 ? Math.round(100 * occupied / available * 1e6) / 1e6 : null,
    starts: startsComplete ? selected.reduce((n, p) => n + p.starts, 0) : null,
  }
}
