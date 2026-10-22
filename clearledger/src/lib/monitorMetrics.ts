/** Суммы строятся из точной энергии, а не из округлённых значений строк. */
export function monitorEnergy(row: { energyKwh: number; energyKwhRaw?: number }): number {
  return row.energyKwhRaw ?? row.energyKwh
}

const UPKEEP = new Set(['meter', 'service', 'check'])

/** Плитка профилактики объединяет станции, а не складывает число причин. */
export function worklistReasonMatches(reasons: readonly { kind: string }[], filter: string): boolean {
  return filter === 'all' || reasons.some((reason) => filter === 'upkeep' ? UPKEEP.has(reason.kind) : reason.kind === filter)
}

export function worklistUpkeepCount(rows: readonly { reasons: readonly { kind: string }[] }[]): number {
  return rows.filter((row) => worklistReasonMatches(row.reasons, 'upkeep')).length
}
