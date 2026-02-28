/**
 * Фасад-сервис «Каналы поступления».
 * Строит Channel[] из включённых шаблонов профиля, обогащая данными
 * реальных коннекторов / 1С-подключений. Ручная загрузка — всегда.
 */

import type { Channel, ChannelKind, ChannelStats, DataEntry } from '@/types'
import { getConnectors } from './connectorService'
import { getConnections } from './oneCIntegrationService'
import { getCompanies } from './companyService'
import { getCustomization } from './companyService'
import { getProfile } from '@/config/profiles'
import { isApiEnabled } from './apiClient'
import { getEntries } from './dataEntryService'

function todayStart(): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.toISOString()
}

function countEntries(entries: DataEntry[], filterFn: (e: DataEntry) => boolean): { today: number; total: number } {
  const ts = todayStart()
  let today = 0
  let total = 0
  for (const e of entries) {
    if (!filterFn(e)) continue
    total++
    if (e.createdAt >= ts) today++
  }
  return { today, total }
}

export async function getChannels(companyId: string): Promise<Channel[]> {
  const channels: Channel[] = []

  let entries: DataEntry[] = []
  try {
    entries = await getEntries(companyId)
  } catch { /* empty */ }

  // ── Загружаем реальные коннекторы и 1С-подключения для обогащения ──
  const realConnectors = await getConnectors(companyId)
  let oneCConnections: Awaited<ReturnType<typeof getConnections>> = []
  if (isApiEnabled()) {
    try { oneCConnections = await getConnections(companyId) } catch { /* */ }
  }

  // ── 1. Каналы из включённых шаблонов профиля ──
  try {
    const companies = await getCompanies()
    const company = companies.find((c) => c.id === companyId)
    if (company) {
      const profile = getProfile(company.profileId)
      const customization = await getCustomization(companyId)
      const disabledSet = new Set(customization.disabledConnectors)
      const usedConnectorIds = new Set<string>()
      const usedConnectionIds = new Set<string>()

      for (const tpl of profile.connectorTemplates) {
        if (disabledSet.has(tpl.id)) continue

        const kind: ChannelKind = tpl.type === '1c' ? 'oneC' : 'connector'

        if (kind === 'oneC') {
          // Ищем реальное 1С-подключение по имени
          const conn = oneCConnections.find((c) => c.name === tpl.name)
          if (conn) {
            usedConnectionIds.add(conn.id)
            const counts = countEntries(entries, (e) => e.source === 'oneC')
            const statusMap: Record<string, Channel['status']> = {
              active: 'active', inactive: 'disabled', error: 'error',
            }
            channels.push({
              id: `1c-${conn.id}`,
              kind: 'oneC',
              name: tpl.name,
              type: '1c',
              status: statusMap[conn.status] ?? 'not_configured',
              lastSyncAt: conn.lastSyncAt,
              todayCount: counts.today,
              totalCount: counts.total,
              errorsCount: 0,
              syncStatus: 'idle',
              connectionId: conn.id,
            })
          } else {
            // Шаблон без реального подключения
            channels.push({
              id: `tpl-${tpl.id}`,
              kind: 'oneC',
              name: tpl.name,
              type: '1c',
              status: 'active',
              todayCount: 0,
              totalCount: 0,
              errorsCount: 0,
              syncStatus: 'idle',
            })
          }
        } else {
          // Ищем реальный коннектор по имени
          const rc = realConnectors.find((c) => c.name === tpl.name)
          if (rc) {
            usedConnectorIds.add(rc.id)
            const counts = countEntries(entries, (e) => e.metadata._syncedFrom === rc.id)
            channels.push({
              id: `conn-${rc.id}`,
              kind: 'connector',
              name: tpl.name,
              type: tpl.type,
              status: rc.status,
              lastSyncAt: rc.lastSyncAt ?? rc.lastSync,
              todayCount: counts.today,
              totalCount: rc.recordsCount || counts.total,
              errorsCount: rc.errorsCount,
              syncStatus: rc.syncStatus ?? 'idle',
              connectorId: rc.id,
            })
          } else {
            // Шаблон без реального коннектора
            channels.push({
              id: `tpl-${tpl.id}`,
              kind: 'connector',
              name: tpl.name,
              type: tpl.type,
              status: 'active',
              todayCount: 0,
              totalCount: 0,
              errorsCount: 0,
              syncStatus: 'idle',
            })
          }
        }
      }

      // ── 1b. Реальные коннекторы, не привязанные к шаблонам ──
      for (const c of realConnectors) {
        if (usedConnectorIds.has(c.id)) continue
        const counts = countEntries(entries, (e) => e.metadata._syncedFrom === c.id)
        channels.push({
          id: `conn-${c.id}`,
          kind: 'connector',
          name: c.name,
          type: c.type,
          status: c.status,
          lastSyncAt: c.lastSyncAt ?? c.lastSync,
          todayCount: counts.today,
          totalCount: c.recordsCount || counts.total,
          errorsCount: c.errorsCount,
          syncStatus: c.syncStatus ?? 'idle',
          connectorId: c.id,
        })
      }

      // ── 1c. Реальные 1С-подключения, не привязанные к шаблонам ──
      for (const conn of oneCConnections) {
        if (usedConnectionIds.has(conn.id)) continue
        const counts = countEntries(entries, (e) => e.source === 'oneC')
        const statusMap: Record<string, Channel['status']> = {
          active: 'active', inactive: 'disabled', error: 'error',
        }
        channels.push({
          id: `1c-${conn.id}`,
          kind: 'oneC',
          name: conn.name,
          type: '1c',
          status: statusMap[conn.status] ?? 'not_configured',
          lastSyncAt: conn.lastSyncAt,
          todayCount: counts.today,
          totalCount: counts.total,
          errorsCount: 0,
          syncStatus: 'idle',
          connectionId: conn.id,
        })
      }
    }
  } catch {
    // Fallback: если не удалось прочитать профиль — старая логика
    for (const c of realConnectors) {
      const counts = countEntries(entries, (e) => e.metadata._syncedFrom === c.id)
      channels.push({
        id: `conn-${c.id}`,
        kind: 'connector',
        name: c.name,
        type: c.type,
        status: c.status,
        lastSyncAt: c.lastSyncAt ?? c.lastSync,
        todayCount: counts.today,
        totalCount: c.recordsCount || counts.total,
        errorsCount: c.errorsCount,
        syncStatus: c.syncStatus ?? 'idle',
        connectorId: c.id,
      })
    }
  }

  // ── 2. Ручная загрузка — встроенный канал ──
  const manualCounts = countEntries(entries, (e) =>
    e.source === 'upload' || e.source === 'photo' || e.source === 'manual' || e.source === 'paste'
  )
  channels.push({
    id: 'manual',
    kind: 'manual',
    name: 'Ручная загрузка',
    type: 'upload',
    status: 'active',
    todayCount: manualCounts.today,
    totalCount: manualCounts.total,
    errorsCount: 0,
    syncStatus: 'idle',
  })

  return channels
}

export async function getChannelStats(companyId: string): Promise<ChannelStats> {
  const channels = await getChannels(companyId)
  return {
    total: channels.length,
    active: channels.filter((c) => c.status === 'active').length,
    errors: channels.filter((c) => c.status === 'error').length,
    todayEntries: channels.reduce((sum, c) => sum + c.todayCount, 0),
  }
}
