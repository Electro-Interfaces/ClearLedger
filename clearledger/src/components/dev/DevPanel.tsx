/**
 * DevPanel — плавающая панель инструментов разработчика.
 * Отображается только в dev-режиме (import.meta.env.DEV).
 */

import { useState, useEffect, useCallback } from 'react'
import { Wrench, X, RotateCcw, Trash2, Plus, Zap } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import {
  resetSeed,
  clearAllData,
  generateEntries,
  getStorageStats,
  setAllStatuses,
  deleteAllEntries,
  type StorageStats,
} from '@/services/devToolsService'
import { getEntries } from '@/services/dataEntryService'
import { statuses as statusConfig, type EntryStatus } from '@/config/statuses'

const ALL_STATUSES: EntryStatus[] = ['new', 'recognized', 'verified', 'transferred', 'error']

export function DevPanel() {
  const [open, setOpen] = useState(false)
  const [stats, setStats] = useState<StorageStats | null>(null)
  const [statusDistribution, setStatusDistribution] = useState<Record<string, number>>({})
  const [selectedStatus, setSelectedStatus] = useState<EntryStatus>('verified')
  const queryClient = useQueryClient()
  const { company, companyId, companies, setCompanyId } = useCompany()

  const refreshStats = useCallback(() => {
    setStats(getStorageStats())
    const entries = getEntries(companyId)
    const dist: Record<string, number> = {}
    for (const e of entries) {
      dist[e.status] = (dist[e.status] || 0) + 1
    }
    setStatusDistribution(dist)
  }, [companyId])

  useEffect(() => {
    if (open) refreshStats()
  }, [open, companyId, refreshStats])

  const invalidateAndRefresh = useCallback(() => {
    queryClient.invalidateQueries()
    refreshStats()
  }, [queryClient, refreshStats])

  const handleResetSeed = () => {
    resetSeed()
    invalidateAndRefresh()
  }

  const handleClearAll = () => {
    clearAllData()
    invalidateAndRefresh()
  }

  const handleGenerate = (count: number) => {
    generateEntries(companyId, company.profileId, count)
    invalidateAndRefresh()
  }

  const handleSetAllStatuses = () => {
    setAllStatuses(companyId, selectedStatus)
    invalidateAndRefresh()
  }

  const handleDeleteEntries = () => {
    deleteAllEntries(companyId)
    invalidateAndRefresh()
  }

  const entryCount = stats?.entriesByCompany[companyId] ?? 0

  return (
    <div className="fixed bottom-4 right-4 z-40">
      {/* Кнопка-триггер */}
      {!open && (
        <Button
          size="icon"
          variant="outline"
          onClick={() => setOpen(true)}
          className="size-10 rounded-full bg-zinc-900 border-zinc-700 text-zinc-300 hover:bg-zinc-800 hover:text-white shadow-lg"
        >
          <Wrench className="size-4" />
        </Button>
      )}

      {/* Панель */}
      {open && (
        <div className="w-80 max-h-[80vh] overflow-y-auto rounded-xl border border-zinc-700 bg-zinc-900/95 backdrop-blur-sm text-zinc-200 shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700">
            <div className="flex items-center gap-2">
              <Wrench className="size-4 text-blue-400" />
              <span className="text-sm font-semibold">Dev Tools</span>
            </div>
            <Button
              size="icon-xs"
              variant="ghost"
              onClick={() => setOpen(false)}
              className="text-zinc-400 hover:text-white hover:bg-zinc-800"
            >
              <X className="size-3.5" />
            </Button>
          </div>

          <div className="p-4 space-y-4">
            {/* Компания */}
            <Section title="Компания">
              <Select value={companyId} onValueChange={setCompanyId}>
                <SelectTrigger className="w-full h-8 text-xs bg-zinc-800 border-zinc-600">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {companies.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      <span
                        className="inline-block size-2 rounded-full mr-1"
                        style={{ backgroundColor: c.color }}
                      />
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="text-xs text-zinc-500 mt-1">
                profileId: {company.profileId}
              </div>
            </Section>

            {/* Данные */}
            <Section title="Данные">
              <div className="grid grid-cols-2 gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleResetSeed}
                  className="text-xs bg-zinc-800 border-zinc-600 hover:bg-zinc-700"
                >
                  <RotateCcw className="size-3" />
                  Сбросить seed
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleClearAll}
                  className="text-xs bg-zinc-800 border-zinc-600 hover:bg-red-900/50 hover:border-red-700 hover:text-red-300"
                >
                  <Trash2 className="size-3" />
                  Очистить всё
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleGenerate(50)}
                  className="text-xs bg-zinc-800 border-zinc-600 hover:bg-zinc-700"
                >
                  <Plus className="size-3" />
                  +50 записей
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleGenerate(200)}
                  className="text-xs bg-zinc-800 border-zinc-600 hover:bg-zinc-700"
                >
                  <Plus className="size-3" />
                  +200 записей
                </Button>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={handleDeleteEntries}
                className="w-full text-xs bg-zinc-800 border-zinc-600 hover:bg-red-900/50 hover:border-red-700 hover:text-red-300 mt-2"
              >
                <Trash2 className="size-3" />
                Удалить записи ({entryCount})
              </Button>
            </Section>

            {/* Статусы */}
            <Section title="Статусы">
              <div className="flex flex-wrap gap-1 mb-2">
                {ALL_STATUSES.map((s) => (
                  <Badge
                    key={s}
                    variant="outline"
                    className={`text-[10px] ${statusConfig[s].className}`}
                  >
                    {statusConfig[s].label}: {statusDistribution[s] ?? 0}
                  </Badge>
                ))}
              </div>
              <div className="flex gap-2">
                <Select
                  value={selectedStatus}
                  onValueChange={(v) => setSelectedStatus(v as EntryStatus)}
                >
                  <SelectTrigger className="flex-1 h-8 text-xs bg-zinc-800 border-zinc-600">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ALL_STATUSES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {statusConfig[s].label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleSetAllStatuses}
                  className="text-xs bg-zinc-800 border-zinc-600 hover:bg-zinc-700 whitespace-nowrap"
                >
                  <Zap className="size-3" />
                  Применить
                </Button>
              </div>
            </Section>

            {/* Статистика */}
            <Section title="Статистика">
              {stats ? (
                <div className="space-y-1 text-xs text-zinc-400">
                  <div className="flex justify-between">
                    <span>Записей ({companyId}):</span>
                    <span className="text-zinc-200 font-mono">{entryCount}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Ключей в LS:</span>
                    <span className="text-zinc-200 font-mono">{stats.totalKeys}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Размер LS:</span>
                    <span className="text-zinc-200 font-mono">~{stats.totalSizeKB} KB</span>
                  </div>
                  {Object.keys(stats.entriesByCompany).length > 1 && (
                    <div className="pt-1 border-t border-zinc-700">
                      <div className="text-zinc-500 mb-1">По компаниям:</div>
                      {Object.entries(stats.entriesByCompany).map(([cid, count]) => (
                        <div key={cid} className="flex justify-between">
                          <span>{cid}:</span>
                          <span className="text-zinc-200 font-mono">{count}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-xs text-zinc-500">Загрузка...</div>
              )}
            </Section>
          </div>
        </div>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
        {title}
      </div>
      {children}
    </div>
  )
}
