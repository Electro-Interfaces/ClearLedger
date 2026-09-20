type Params = Record<string, string | number | undefined>
const through = '2026-09-17T21:00:00+03:00'
const stations = [
  { id: 'demo-ezs-1', name: 'ЭЗС «Площадь»', region: 'Демо-регион', status: 'working', vendor: 'Демо DC' },
  { id: 'demo-ezs-2', name: 'ЭЗС «Парк»', region: 'Демо-регион', status: 'no_link', vendor: 'Демо AC' },
  { id: 'demo-ezs-3', name: 'ЭЗС «Новая»', region: 'Второй демо-регион', status: 'unknown', vendor: 'Демо AC' },
]
const attempts = [
  ...Array.from({ length: 12 }, (_, i) => ({ station: 'demo-ezs-1', at: `2026-09-${i < 6 ? '17' : '01'}T12:${String(i).padStart(2, '0')}:00+03:00`, energy: i < 3 ? 0 : 10, amount: i < 3 ? 0 : 200 })),
  ...Array.from({ length: 10 }, (_, i) => ({ station: 'demo-ezs-2', at: `2026-09-01T12:${String(i).padStart(2, '0')}:00+03:00`, energy: 10, amount: 200 })),
]
const pct = (a: number, b: number) => b ? Math.round(a / b * 1000) / 10 : 0
const round = (n: number, digits = 2) => Number(n.toFixed(digits))

export function demoMonitoring(path: string, params: Params = {}) {
  if (!['/api/ops/network-state', '/api/ops/reliability', '/api/ops/vendors', '/api/ops/worklist', '/api/ops/tickets', '/api/ops/intake-health'].includes(path)) return undefined
  const chosen = params.as_of ? `${params.as_of}T23:59:59+03:00` : through
  const end = new Date(Math.min(Date.parse(chosen), Date.parse(through)))
  const days = Number(params.days || 90)
  const begin = end.getTime() - days * 86400000
  const day = (at: string) => Date.parse(`${new Date(at).toLocaleDateString('sv-SE', { timeZone: 'Europe/Moscow' })}T00:00:00+03:00`)
  const scope = stations.filter((s) => !params.region || String(params.region).split('|').includes(s.region))
  const rows = scope.map((s) => {
    const history = attempts.filter((a) => a.station === s.id && Date.parse(a.at) <= end.getTime())
    const period = history.filter((a) => Date.parse(a.at) >= begin)
    const last = history.filter((a) => a.energy > 0).sort((a, b) => Date.parse(b.at) - Date.parse(a.at))[0]
    const silentDays = last ? (day(end.toISOString()) - day(last.at)) / 86400000 : null
    const failed = period.filter((a) => a.energy <= 0).length
    const revenue = period.reduce((n, a) => n + a.amount, 0)
    const revenuePerMonth = round(history.filter((a) => Date.parse(a.at) >= end.getTime() - 90 * 86400000).reduce((n, a) => n + a.amount, 0) / 3)
    const mismatch = s.status === 'working' && (silentDays === null || silentDays > 7)
    const loss = silentDays === null || silentDays >= 3 ? revenuePerMonth : 0
    return { locationId: s.id, code: s.id, number: s.id.split('-').at(-1), name: s.name, region: s.region, city: 'Демо-город',
      status: s.status, statusLabel: s.status === 'working' ? 'Работает' : s.status === 'no_link' ? 'Нет связи' : 'Нет данных', statusRaw: null,
      brand: s.vendor, vendor: s.vendor, model: null, powerKwt: 60, connectors: 2, lifeStatus: 'active',
      lastSessionAt: last?.at ?? null, silentDays, sessions90d: history.filter((a) => Date.parse(a.at) >= end.getTime() - 90 * 86400000).length,
      sessions7d: history.filter((a) => Date.parse(a.at) >= end.getTime() - 7 * 86400000).length,
      revenuePerMonth, mismatch, loss, attention: mismatch || loss > 0,
      sessions: period.length, visits: period.length, visitsOk: period.length - failed, visitsFailed: failed,
      failedVisitsPct: pct(failed, period.length), attemptsPerVisit: period.length ? 1 : 0, clientsLost: failed,
      failed, failedPct: pct(failed, period.length), empty: failed, emptyPct: pct(failed, period.length),
      clients: period.length, clientsAffected: failed, energyKwh: period.reduce((n, a) => n + a.energy, 0), revenue,
      kwhPerSession: period.length ? round(period.reduce((n, a) => n + a.energy, 0) / period.length) : 0 }
  })
  const context = { asOf: end.toISOString(), dataThrough: through, dataLagHours: null,
    snapshotNote: 'Вымышленные ЭЗС и сессии для демонстрации. Статусы — текущие; действия отключены.', note: 'Демонстрационные данные; это не сеть клиента.' }
  const sum = (key: 'visits' | 'visitsOk' | 'visitsFailed' | 'sessions' | 'failed' | 'empty' | 'clientsAffected' | 'loss') => rows.reduce((n, r) => n + r[key], 0)
  const enough = rows.filter((r) => r.visits >= Number(params.min_sessions ?? 10))
  const bad = enough.filter((r) => r.failedVisitsPct >= 20)
  if (path === '/api/ops/intake-health') return { everLoaded: false, hours: null, level: 'unknown', lastLoadAt: through, dataThrough: through, lostFields: [], payments: { total: 0, orphans: 0, orphanAmount: 0 }, sessionsWithoutStation: 0, note: context.note }
  if (path === '/api/ops/network-state') return { ...context,
    totals: { stations: rows.length, active: rows.length, charging2d: rows.filter((r) => r.silentDays !== null && r.silentDays <= 2).length,
      chargingWeek: rows.filter((r) => r.silentDays !== null && r.silentDays <= 7).length,
      silentWeek: rows.filter((r) => r.silentDays === null || r.silentDays > 7).length,
      silentMonth: rows.filter((r) => r.silentDays === null || r.silentDays > 30).length,
      neverCharged: rows.filter((r) => r.silentDays === null).length, mismatch: rows.filter((r) => r.mismatch).length,
      mismatchRevenue: rows.filter((r) => r.mismatch).reduce((n, r) => n + r.revenuePerMonth, 0), attention: rows.filter((r) => r.attention).length,
      lossPerMonth: round(sum('loss')), byStatus: Object.fromEntries([...new Set(rows.map((r) => r.status))].map((s) => [s, rows.filter((r) => r.status === s).length])) },
    stations: params.only_problems === 'true' ? rows.filter((r) => r.attention) : rows, regions: [], statusLabels: {} }
  if (path === '/api/ops/reliability') return { ...context, days, minSessions: Number(params.min_sessions ?? 10), threshold: 20,
    totals: { populationStations: rows.length, stations: rows.filter((r) => r.sessions).length, stationsCounted: enough.length,
      visits: sum('visits'), visitsOk: sum('visitsOk'), visitsFailed: sum('visitsFailed'), failedVisitsPct: pct(sum('visitsFailed'), sum('visits')),
      attemptsPerVisit: sum('visits') ? 1 : 0, sessions: sum('sessions'), failed: sum('failed'), failedPct: pct(sum('failed'), sum('sessions')),
      empty: sum('empty'), emptyPct: pct(sum('empty'), sum('sessions')), badStations: bad.length, clientsAffected: enough.reduce((n, r) => n + r.clientsAffected, 0) }, stations: enough, regions: [] }
  if (path === '/api/ops/worklist') {
    const work = rows.filter((r) => r.silentDays === null || r.silentDays > 7 || r.loss || bad.includes(r)).map((r) => ({ ...r,
      reasons: [...(r.silentDays === null || r.silentDays > 7 || r.loss ? [{ kind: 'silent', label: r.silentDays === null ? 'нет сессий в загруженной истории' : `молчит ${r.silentDays} дн` }] : []),
        ...(bad.includes(r) ? [{ kind: 'failing', label: `${r.failedVisitsPct} % приездов впустую` }] : [])],
      lossPerMonth: r.loss, visitsPerDay: round(r.visits / 90, 1), openTickets: 0, breachedTickets: 0, lastTicketId: null, lastTicketNumber: null }))
    return { ...context, threshold: 20, workKnown: false, rows: work.sort((a, b) => b.lossPerMonth - a.lossPerMonth || b.clientsLost - a.clientsLost || b.visits - a.visits || (b.silentDays ?? 0) - (a.silentDays ?? 0)), dataGaps: rows.map((r) => ({ ...r, units: 1, meterUnknown: 1, serviceUnknown: 1 })),
      totals: { rows: work.length, silent: work.filter((r) => r.reasons.some((x) => x.kind === 'silent')).length, failing: bad.length,
        breached: 0, meter: 0, service: 0, check: 0, upkeepUnknown: rows.length, notTaken: null,
        lossPerMonth: round(sum('loss')), lossNotTaken: null, clientsLost: bad.reduce((n, r) => n + r.clientsLost, 0) } }
  }
  if (path === '/api/ops/vendors') {
    const vendors = [...new Set(rows.map((r) => r.vendor))].map((vendor) => {
      const rs = rows.filter((r) => r.vendor === vendor); const visits = rs.reduce((n, r) => n + r.visits, 0); const failed = rs.reduce((n, r) => n + r.visitsFailed, 0)
      const charging2d = rs.filter((r) => r.silentDays !== null && r.silentDays <= 2).length; const energy = rs.reduce((n, r) => n + r.energyKwh, 0)
      return { vendor, stations: rs.length, active: rs.length, working: rs.filter((r) => r.status === 'working').length, noLink: rs.filter((r) => r.status === 'no_link').length,
        decommissioned: 0, charging2d, livePct: pct(charging2d, rs.length), silentWeek: rs.filter((r) => r.silentDays === null || r.silentDays > 7).length,
        neverCharged: rs.filter((r) => r.silentDays === null).length, visits, visitsFailed: failed, failedVisitsPct: pct(failed, visits), attemptsPerVisit: visits ? 1 : 0,
        failedSessionsPct: pct(failed, visits), energyKwh: energy, revenue: rs.reduce((n, r) => n + r.revenue, 0), badStations: rs.filter((r) => bad.includes(r)).length,
        models: [], modelsCount: 0, avgPowerKwt: 60, kwhPerStationDay: round(energy / rs.length / days, 1) }
    })
    return { ...context, days, threshold: 20, totals: { vendors: vendors.length, stations: rows.length, visits: sum('visits'), visitsFailed: sum('visitsFailed'), failedVisitsPct: pct(sum('visitsFailed'), sum('visits')), badStations: bad.length },
      vendors, stations: rows.filter((r) => params.vendor === '*' || params.vendor === r.vendor), vendor: params.vendor ?? null, regions: [...new Set(stations.map((s) => s.region))] }
  }
  return { ...context, days, totals: { total: 0, open: 0, inWindow: 0, breached: 0, openBeforeWindow: 0, urgentOpen: 0, staleOpen: 0, objects: 0, openObjects: 0, avgHours: null },
    by: {}, rows: [], shown: 0, withoutStation: 0, gaps: ['В этом вымышленном сценарии заявки не заведены.'] }
}
