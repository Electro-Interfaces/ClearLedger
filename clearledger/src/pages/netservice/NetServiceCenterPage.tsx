/**
 * «Сервисный центр» — управление сервисом сети (MVP: 3-я линия HubEx).
 * Standalone рабочая область (как ReconciliationPage): тулбар режимов + панель.
 * Режим в URL (/netservice/:mode). Drill-down по станции → окно станции (cockpit).
 */
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Headset } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { useLocations } from '@/hooks/useLocations'
import { runHubexSync, type NetFilters } from '@/services/netServiceService'
import {
  NetServiceToolbar, periodRange, type NetMode, type PeriodPreset,
} from '@/components/netservice/NetServiceToolbar'
import { OverviewDashboard } from '@/components/netservice/OverviewDashboard'
import { RequestsListPanel } from '@/components/netservice/RequestsListPanel'
import { SlaDashboard } from '@/components/netservice/SlaDashboard'
import { LocationCockpitModal } from '@/components/locations/LocationCockpitModal'
import type { ServiceLocation } from '@/types/location'

const VALID: NetMode[] = ['overview', 'requests', 'sla']

export function NetServiceCenterPage() {
  const { mode: modeParam } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { companyId, isCompanyAdmin } = useCompany()
  const { regionIds } = useFilters()
  const locations = useLocations()

  const mode: NetMode = (VALID as string[]).includes(modeParam ?? '')
    ? (modeParam as NetMode) : 'overview'
  const [period, setPeriod] = useState<PeriodPreset>('90')
  const [syncing, setSyncing] = useState(false)
  const [cockpit, setCockpit] = useState<ServiceLocation | null>(null)

  // Регион из глобального фильтра шапки (бэкенд принимает один; при мультивыборе — все).
  const filters: NetFilters = {
    ...periodRange(period),
    region: regionIds.length === 1 ? regionIds[0] : undefined,
  }

  function setMode(m: NetMode) {
    navigate(m === 'overview' ? '/netservice' : `/netservice/${m}`)
  }

  function openStation(locationId: string | null) {
    if (!locationId) {
      toast.info('Заявка не связана с точкой обслуживания')
      return
    }
    const loc = locations.find((l) => l.id === locationId)
    if (loc) setCockpit(loc)
    else toast.info('Точка не найдена в справочнике')
  }

  async function doSync() {
    setSyncing(true)
    try {
      await runHubexSync(companyId)
      toast.success('Синхронизация HubEx завершена')
      await qc.invalidateQueries({ queryKey: ['netservice'] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка синхронизации')
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2.5">
        <Headset className="h-4 w-4 text-primary" />
        <h1 className="text-sm font-semibold">Сервисный центр</h1>
        <span className="text-xs text-muted-foreground">сервис сети · 3-я линия (HubEx)</span>
      </div>
      <NetServiceToolbar
        mode={mode} onModeChange={setMode}
        period={period} onPeriodChange={setPeriod}
        canSync={isCompanyAdmin} syncing={syncing} onSync={doSync}
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {mode === 'overview' && (
          <OverviewDashboard companyId={companyId} filters={filters} onOpenStation={openStation} />
        )}
        {mode === 'requests' && (
          <RequestsListPanel companyId={companyId} filters={filters} onOpenStation={openStation} />
        )}
        {mode === 'sla' && (
          <SlaDashboard companyId={companyId} filters={filters} />
        )}
      </div>

      <LocationCockpitModal
        location={cockpit}
        onClose={() => setCockpit(null)}
      />
    </div>
  )
}

export default NetServiceCenterPage
