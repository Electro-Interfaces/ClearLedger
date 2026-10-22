// Только вымышленные данные. Рабочие выгрузки и учётные данные не нужны.
const snapshot = { asOf: '2026-10-22T10:00:00Z', dataThrough: '2026-10-22T10:00:00Z', dataLagHours: 0, note: 'Учебный набор' }
const stations = Array.from({ length: 60 }, (_, i) => ({
  locationId: `station-${i}`, code: String(i + 1), number: String(i + 1), name: `Учебная ЭЗС ${i + 1}`,
  region: i % 2 ? 'Учебный регион Б' : 'Учебный регион А', city: 'Учебный город',
  status: 'working', statusLabel: 'Работает', statusRaw: null, lifeStatus: 'active',
  lastSessionAt: '2026-10-20T10:00:00Z', silentDays: 2, sessions90d: 20, sessions7d: 5,
  revenuePerMonth: 100, connectors: 2, mismatch: false, loss: 10, attention: true,
  brand: 'Учебная марка', vendor: 'Учебная марка', model: 'Учебная модель', powerKwt: 60,
  visits: 10, visitsOk: 8, visitsFailed: 2, failedVisitsPct: 20, attemptsPerVisit: 2,
  clientsLost: 1, sessions: 20, failed: 2, failedPct: 10, empty: 1, emptyPct: 5,
  clients: 10, clientsAffected: 2, energyKwh: 100, revenue: 200, kwhPerSession: 5,
}))

export const responses: Record<string, unknown> = {
  '/api/ops/network-state': { ...snapshot, stations, regions: [], statusLabels: { working: 'Работает' }, totals: {
    stations: 60, active: 60, charging2d: 60, chargingWeek: 60, silentWeek: 0, silentMonth: 0,
    neverCharged: 0, mismatch: 0, mismatchRevenue: 0, attention: 60, lossPerMonth: 600, byStatus: { working: 60 },
  } },
  '/api/registry/objects/open-tickets': { app: 'support', objects: [], total: 0 },
  '/api/ops/reliability': { ...snapshot, stations, regions: [], days: 90, minSessions: 1, threshold: 15,
    trend: { current: { visits: 600, failed: 120, failedPct: 20 }, previous: { visits: 600, failed: 120, failedPct: 20 }, deltaPp: 0 },
    totals: { populationStations: 60, stations: 60, stationsCounted: 60, visits: 600, visitsOk: 480,
      visitsFailed: 120, failedVisitsPct: 20, attemptsPerVisit: 2, sessions: 1200, failed: 120,
      failedPct: 10, empty: 60, emptyPct: 5, badStations: 60, clientsAffected: 120 } },
  '/api/ops/vendors': { ...snapshot, days: 90, threshold: 15, regions: ['Учебный регион А', 'Учебный регион Б'],
    vendor: null, stations, totals: { vendors: 1, stations: 60, visits: 600, visitsFailed: 120, failedVisitsPct: 20, badStations: 60 },
    vendors: [{ vendor: 'Учебная марка', stations: 60, active: 60, working: 60, noLink: 0, decommissioned: 0,
      charging2d: 60, livePct: 100, silentWeek: 0, neverCharged: 0, visits: 600, visitsFailed: 120,
      failedVisitsPct: 20, attemptsPerVisit: 2, failedSessionsPct: 10, energyKwh: 6000, revenue: 12000,
      badStations: 60, models: ['Учебная модель'], modelsCount: 1, avgPowerKwt: 60, kwhPerStationDay: 1 }] },
  '/api/ops/tickets': { ...snapshot, days: 90, shown: 1, withoutStation: 0, gaps: [], by: {},
    totals: { total: 1, open: 1, inWindow: 1, breached: 0, openBeforeWindow: 0, urgentOpen: 0,
      staleOpen: 0, objects: 1, openObjects: 1, avgHours: null },
    rows: [{ id: 'ticket-1', number: 'УЧ-1', title: 'Учебная заявка', status: 'open', statusLabel: 'Открыта',
      priority: 'normal', priorityLabel: 'Обычная', kind: 'Обращение', stage: null, source: 'web',
      createdAt: '2026-10-20T10:00:00Z', closedAt: null, ageDays: 2, slaBreached: false, assignee: null,
      locationId: 'station-0', station: 'Учебная ЭЗС 1', stationNumber: '1', brand: 'Учебная марка',
      region: 'Учебный регион А', city: 'Учебный город', ownerClass: 'internal', owner: 'Учебная организация',
      stationStatus: 'working', isOpen: true, inWindow: true }] },
}
