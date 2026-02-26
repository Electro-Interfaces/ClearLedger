/**
 * Предупреждение о заполненности localStorage.
 * Жёлтая плашка >80%, красная >95%.
 */

import { useState, useEffect } from 'react'
import { AlertTriangle, Trash2, Download, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { getStorageUsage, cleanupOldAudit, formatBytes, type StorageUsage } from '@/services/storageMonitor'
import { exportAllData } from '@/services/exportService'
import { useCompany } from '@/contexts/CompanyContext'

export function StorageWarning() {
  const { companyId } = useCompany()
  const [usage, setUsage] = useState<StorageUsage | null>(null)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    const check = () => setUsage(getStorageUsage())
    check()
    const interval = setInterval(check, 30_000) // проверка каждые 30 сек
    return () => clearInterval(interval)
  }, [])

  if (!usage || usage.percent < 80 || dismissed) return null

  const isCritical = usage.percent >= 95

  async function handleCleanupAudit() {
    const removed = cleanupOldAudit(companyId, 500)
    toast.success(`Удалено ${removed} старых записей аудита`)
    setUsage(getStorageUsage())
  }

  async function handleExportAndClean() {
    try {
      await exportAllData(companyId)
      cleanupOldAudit(companyId, 200)
      toast.success('Данные экспортированы, аудит очищен')
      setUsage(getStorageUsage())
    } catch {
      toast.error('Ошибка экспорта')
    }
  }

  return (
    <div
      className={`flex items-center gap-3 px-4 py-2 text-sm rounded-lg ${
        isCritical
          ? 'bg-destructive/15 text-destructive border border-destructive/30'
          : 'bg-yellow-500/15 text-yellow-700 dark:text-yellow-400 border border-yellow-500/30'
      }`}
    >
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span className="flex-1 min-w-0">
        Хранилище: {formatBytes(usage.usedBytes)} / {formatBytes(usage.totalBytes)} ({usage.percent}%)
        {isCritical && ' — данные могут не сохраниться!'}
      </span>
      <div className="flex items-center gap-1 shrink-0">
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={handleCleanupAudit}>
          <Trash2 className="h-3 w-3 mr-1" />
          Очистить аудит
        </Button>
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={handleExportAndClean}>
          <Download className="h-3 w-3 mr-1" />
          Экспорт + Очистка
        </Button>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDismissed(true)}>
          <X className="h-3 w-3" />
        </Button>
      </div>
    </div>
  )
}
