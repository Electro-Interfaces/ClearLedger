/**
 * Клиентский планировщик автообновления 1С (аналог channelScheduler).
 *
 * Пока приложение открыто, по интервалу запускает полную синхронизацию (sync/full)
 * для подключений с включённым автообновлением. Настройки и время последнего
 * прогона хранятся в localStorage per-connection. Backend-планировщик (настоящее
 * фоновое обновление) — отдельный следующий шаг; здесь клиентский вариант.
 */

export interface AutoSyncCfg {
  enabled: boolean
  intervalSec: number
}

const cfgKey = (id: string) => `onec-autosync-${id}`
const runKey = (id: string) => `onec-autosync-lastrun-${id}`

export function getAutoSyncCfg(id: string, defaultIntervalSec = 300): AutoSyncCfg {
  try {
    const raw = localStorage.getItem(cfgKey(id))
    if (raw) {
      const p = JSON.parse(raw)
      return {
        enabled: !!p.enabled,
        intervalSec: Number.isFinite(p.intervalSec) && p.intervalSec >= 60 ? p.intervalSec : defaultIntervalSec,
      }
    }
  } catch { /* ignore */ }
  return { enabled: false, intervalSec: defaultIntervalSec }
}

export function setAutoSyncCfg(id: string, cfg: AutoSyncCfg): void {
  try { localStorage.setItem(cfgKey(id), JSON.stringify(cfg)) } catch { /* ignore */ }
}

export function getLastAutoRun(id: string): number {
  const v = Number(localStorage.getItem(runKey(id)))
  return Number.isFinite(v) ? v : 0
}

export function setLastAutoRun(id: string, ts: number): void {
  try { localStorage.setItem(runKey(id), String(ts)) } catch { /* ignore */ }
}

/** Время следующего автозапуска для подключения, либо null если выключено. */
export function getNextAutoRun(id: string, defaultIntervalSec = 300): Date | null {
  const cfg = getAutoSyncCfg(id, defaultIntervalSec)
  if (!cfg.enabled) return null
  const last = getLastAutoRun(id)
  return new Date((last || Date.now()) + cfg.intervalSec * 1000)
}
