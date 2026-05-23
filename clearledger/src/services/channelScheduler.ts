/**
 * Планировщик автоматической загрузки каналов.
 * Работает пока приложение открыто (SPA, no backend).
 * Проверяет каналы с schedule.mode !== 'manual' каждую минуту.
 */

import { getChannels, updateChannel } from './channelService'
import { syncChannel } from './channelSyncService'
import type { Channel, ScheduleConfig } from '@/types/channel'

const CHECK_INTERVAL_MS = 60_000 // проверка каждую минуту

let intervalId: ReturnType<typeof setInterval> | null = null
let syncingChannels = new Set<string>()

function getScheduleConfig(ch: Channel): ScheduleConfig | null {
  if (typeof ch.schedule === 'string') return null // legacy 'manual'
  return ch.schedule
}

function isWithinActiveHours(config: ScheduleConfig): boolean {
  if (!config.activeHoursFrom || !config.activeHoursTo) return true
  const now = new Date()
  const hhmm = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  return hhmm >= config.activeHoursFrom && hhmm <= config.activeHoursTo
}

function shouldSync(ch: Channel): boolean {
  const config = getScheduleConfig(ch)
  if (!config || config.mode === 'manual') return false
  if (ch.status === 'paused') return false
  if (config.pauseOnError && ch.status === 'error') return false
  if (!isWithinActiveHours(config)) return false
  if (syncingChannels.has(ch.id)) return false

  if (config.mode === 'interval' && config.intervalMinutes) {
    if (!ch.lastSync) return true
    const lastSync = new Date(ch.lastSync).getTime()
    const nextSync = lastSync + config.intervalMinutes * 60_000
    return Date.now() >= nextSync
  }

  // cron not implemented in SPA, treat as manual
  return false
}

async function runScheduledSync(ch: Channel): Promise<void> {
  syncingChannels.add(ch.id)
  try {
    await syncChannel(ch, {})
  } catch {
    updateChannel(ch.id, { status: 'error' })
  } finally {
    syncingChannels.delete(ch.id)
  }
}

function tick() {
  try {
    const channels = getChannels()
    for (const ch of channels) {
      if (shouldSync(ch)) {
        runScheduledSync(ch)
      }
    }
  } catch {
    // scheduler tick failed silently
  }
}

/** Запустить планировщик */
export function startScheduler(): void {
  if (intervalId) return
  intervalId = setInterval(tick, CHECK_INTERVAL_MS)
  // Первый тик через 10 секунд — не блокировать загрузку приложения
  setTimeout(tick, 10_000)
}

/** Остановить планировщик */
export function stopScheduler(): void {
  if (intervalId) {
    clearInterval(intervalId)
    intervalId = null
  }
}

/** Проверить, работает ли планировщик */
export function isSchedulerRunning(): boolean {
  return intervalId !== null
}

/** Получить время следующего запуска для канала */
export function getNextSyncTime(ch: Channel): Date | null {
  const config = getScheduleConfig(ch)
  if (!config || config.mode === 'manual') return null
  if (config.mode === 'interval' && config.intervalMinutes) {
    if (!ch.lastSync) return new Date()
    return new Date(new Date(ch.lastSync).getTime() + config.intervalMinutes * 60_000)
  }
  return null
}

/** Получить количество каналов с автозагрузкой */
export function getAutoSyncChannelCount(): number {
  return getChannels().filter((ch) => {
    const config = getScheduleConfig(ch)
    return config && config.mode !== 'manual'
  }).length
}
