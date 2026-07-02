/**
 * Фоновый планировщик автообновления 1С (клиентский).
 * Ничего не рендерит; пока приложение открыто, раз в минуту проверяет
 * подключения и запускает полную синхронизацию по интервалу автообновления.
 */

import { useEffect, useRef } from 'react'
import { useOneCConnections, useSyncFull } from '@/hooks/useOneCSync'
import { getAutoSyncCfg, getLastAutoRun, setLastAutoRun } from '@/services/oneCAutoSync'

export function OneCAutoSync() {
  const { data: connections } = useOneCConnections()
  const syncFull = useSyncFull()

  const connRef = useRef(connections ?? [])
  connRef.current = connections ?? []
  const syncRef = useRef(syncFull)
  syncRef.current = syncFull

  useEffect(() => {
    const tick = () => {
      if (syncRef.current.isPending) return
      for (const c of connRef.current) {
        const cfg = getAutoSyncCfg(c.id, c.syncIntervalSec)
        if (!cfg.enabled) continue
        if (Date.now() - getLastAutoRun(c.id) >= cfg.intervalSec * 1000) {
          setLastAutoRun(c.id, Date.now())
          syncRef.current.mutate(c.id)
          break // один прогон за тик — не грузим бэкенд параллельными full-sync
        }
      }
    }
    const t = setInterval(tick, 60_000)
    return () => clearInterval(t)
  }, [])

  return null
}
