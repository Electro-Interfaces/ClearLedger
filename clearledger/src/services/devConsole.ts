/**
 * Dev Console — регистрация window.__cl.
 * Side-effect модуль: импортируется в main.tsx под import.meta.env.DEV.
 *
 * Использование в консоли браузера:
 *   __cl.stats()          — статистика хранилища
 *   __cl.entries()        — таблица записей текущей компании
 *   __cl.generate(50)     — сгенерировать 50 записей
 *   __cl.reset()          — сбросить seed + reload
 *   __cl.clear()          — очистить всё + reload
 *   __cl.setStatus('verified') — все записи → verified
 *   __cl.export()         — экспорт данных компании
 */

import {
  resetSeed,
  clearAllData,
  generateEntries,
  getStorageStats,
  setAllStatuses,
  deleteAllEntries,
} from './devToolsService'
import { getEntries } from './dataEntryService'
import { exportAllData } from './exportService'
import { defaultCompanies } from '@/config/companies'
import type { EntryStatus } from '@/config/statuses'

function getCurrentCompanyId(): string {
  try {
    return localStorage.getItem('clearledger-company') ?? 'npk'
  } catch {
    return 'npk'
  }
}

function getProfileId(companyId: string) {
  const company = defaultCompanies.find((c) => c.id === companyId)
  return company?.profileId ?? 'fuel'
}

const cl = {
  reset() {
    resetSeed()
    console.log('[ClearLedger] Seed сброшен и пересоздан. Перезагрузка...')
    location.reload()
  },

  clear() {
    clearAllData()
    console.log('[ClearLedger] Все данные очищены. Перезагрузка...')
    location.reload()
  },

  generate(count: number = 50) {
    const companyId = getCurrentCompanyId()
    const profileId = getProfileId(companyId)
    const entries = generateEntries(companyId, profileId, count)
    console.log(`[ClearLedger] Создано ${entries.length} записей для ${companyId}`)
    return entries
  },

  stats() {
    const stats = getStorageStats()
    console.table(stats.entriesByCompany)
    console.log(`Всего ключей: ${stats.totalKeys}, размер: ~${stats.totalSizeKB} KB`)
    return stats
  },

  entries(companyId?: string) {
    const cid = companyId ?? getCurrentCompanyId()
    const entries = getEntries(cid)
    console.table(
      entries.map((e) => ({
        id: e.id,
        title: e.title,
        status: e.status,
        source: e.source,
        category: e.categoryId,
        created: e.createdAt.slice(0, 10),
      })),
    )
    return entries
  },

  setStatus(status: EntryStatus) {
    const companyId = getCurrentCompanyId()
    const count = setAllStatuses(companyId, status)
    console.log(`[ClearLedger] Изменено ${count} записей → ${status}`)
    return count
  },

  deleteEntries(companyId?: string) {
    const cid = companyId ?? getCurrentCompanyId()
    const count = deleteAllEntries(cid)
    console.log(`[ClearLedger] Удалено ${count} записей для ${cid}`)
    return count
  },

  async export(companyId?: string) {
    const cid = companyId ?? getCurrentCompanyId()
    await exportAllData(cid)
    console.log(`[ClearLedger] Экспорт ${cid} завершён`)
  },
}

// Регистрация на window
declare global {
  interface Window {
    __cl: typeof cl
  }
}

window.__cl = cl

console.log(
  '%c[ClearLedger Dev Tools]%c Доступны через window.__cl — попробуйте __cl.stats()',
  'color: #3b82f6; font-weight: bold',
  'color: inherit',
)
