/**
 * Панель сверки — сравнение данных из разных источников.
 * STS (смены) vs MSTO (онлайн-заказы) vs TradeCorp (корп. карты).
 */

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { ScrollArea } from '@/components/ui/scroll-area'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { getStsStationsFromLocations } from '@/services/locationService'
import { executeMstoReconciliation } from '@/services/mstoReconciliation'
import { MSTOReconciliationResults } from '@/components/reconciliation/MSTOReconciliationResults'
import type { MSTOReconciliationResult, StationInfo } from '@/types/mstoReconciliation'
import { GitCompare, Play, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

type ReconcileTab = 'dashboard' | 'online' | 'corporate' | 'acquiring' | 'receipts' | 'depots' | 'drains' | 'transport'

const RECONCILE_MENU: CentralMenuItem[] = [
  { key: 'dashboard', label: 'Обзор' },
  { key: 'online', label: 'Онлайн-заказы' },
  { key: 'corporate', label: 'Корп. карты' },
  { key: 'acquiring', label: 'Эквайринг' },
  { key: 'receipts', label: 'Чеки' },
  { key: 'depots', label: 'Нефтебазы' },
  { key: 'drains', label: 'Сливы' },
  { key: 'transport', label: 'Перевозки' },
]

function DashboardView() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3">
      <GitCompare className="h-10 w-10 text-muted-foreground/30" />
      <p className="text-sm font-medium text-muted-foreground">Сверка данных</p>
      <p className="text-xs text-muted-foreground text-center max-w-md">
        Выберите тип сверки в меню слева
      </p>
    </div>
  )
}

interface ReconcileParams {
  dateFrom: string
  dateTo: string
  allStations: boolean
  selectedStations: number[]
  allShifts: boolean
}

function useReconcileParams(): [ReconcileParams, React.Dispatch<React.SetStateAction<ReconcileParams>>] {
  const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)
  return useState<ReconcileParams>({
    dateFrom: format(weekAgo, 'yyyy-MM-dd'),
    dateTo: format(new Date(), 'yyyy-MM-dd'),
    allStations: true,
    selectedStations: [],
    allShifts: false,
  })
}

function ReconcileParamsForm({ params, setParams, onRun, description, loading }: {
  params: ReconcileParams
  setParams: React.Dispatch<React.SetStateAction<ReconcileParams>>
  onRun: () => void
  description: string
  loading?: boolean
}) {
  // Станции из точек обслуживания (settings.stations — легаси-стор, для ГИГ пуст)
  const stations = getStsStationsFromLocations()

  function toggleStation(code: number) {
    setParams((p) => {
      const sel = p.selectedStations.includes(code)
        ? p.selectedStations.filter((c) => c !== code)
        : [...p.selectedStations, code]
      return { ...p, selectedStations: sel }
    })
  }

  return (
    <div className="space-y-3">
      {/* Верхняя строка: период + станции + смены + кнопка */}
      <div className="flex items-end gap-4 flex-wrap">
        {/* Период */}
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">Период</Label>
          <div className="flex items-center gap-1.5">
            <Input
              type="date"
              className="h-7 text-xs w-[130px]"
              value={params.dateFrom}
              onChange={(e) => setParams((p) => ({ ...p, dateFrom: e.target.value }))}
            />
            <span className="text-xs text-muted-foreground">—</span>
            <Input
              type="date"
              className="h-7 text-xs w-[130px]"
              value={params.dateTo}
              onChange={(e) => setParams((p) => ({ ...p, dateTo: e.target.value }))}
            />
          </div>
        </div>

        {/* Станции */}
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">Станции</Label>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setParams((p) => ({ ...p, allStations: true, selectedStations: [] }))}
              className={`px-2.5 py-1 rounded text-sm font-medium border transition-colors ${
                params.allStations
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border text-muted-foreground hover:border-foreground/30'
              }`}
            >
              Все ({stations.length})
            </button>
            <button
              onClick={() => setParams((p) => ({ ...p, allStations: false }))}
              className={`px-2.5 py-1 rounded text-sm font-medium border transition-colors ${
                !params.allStations
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border text-muted-foreground hover:border-foreground/30'
              }`}
            >
              Выбрать
            </button>
            {!params.allStations && stations.map((s) => (
              <button
                key={s.code}
                onClick={() => toggleStation(s.code)}
                className={`px-2 py-1 rounded text-sm font-medium border transition-colors ${
                  params.selectedStations.includes(s.code)
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border text-muted-foreground hover:border-foreground/30'
                }`}
              >
                {s.name}
              </button>
            ))}
          </div>
        </div>

        {/* Все смены */}
        <div className="flex items-center gap-2 pb-0.5">
          <Switch
            id="all-shifts"
            checked={params.allShifts}
            onCheckedChange={(v) => setParams((p) => ({ ...p, allShifts: v }))}
          />
          <label htmlFor="all-shifts" className="text-sm text-muted-foreground cursor-pointer">
            {description}
          </label>
        </div>

        {/* Запустить */}
        <Button size="sm" className="h-7 gap-1.5 text-xs" onClick={onRun} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
          {loading ? 'Загрузка...' : 'Запустить'}
        </Button>

      </div>

      {/* Разделитель */}
      <div className="border-b border-border/50 mt-3" />
    </div>
  )
}

function OnlineOrdersView() {
  const [params, setParams] = useReconcileParams()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<MSTOReconciliationResult | null>(null)
  const settings = getSettings()
  const stsStations = getStsStationsFromLocations()
  const { setLastReconcileResult } = useWorkspace()

  async function handleRun() {
    setLoading(true)
    try {
      const stationCodes = params.allStations
        ? stsStations.map((s) => s.code)
        : params.selectedStations
      // Минимальная StationInfo из точек обслуживания (MSTO-маппинг — из транзакций)
      const stations: StationInfo[] = stsStations
        .filter((s) => params.allStations || stationCodes.includes(s.code))
        .map((s) => ({
          code: String(s.code),
          name: s.name,
          stsStationId: s.code,
        }))
      const res = await executeMstoReconciliation({
        dateFrom: params.dateFrom,
        dateTo: params.dateTo,
        stationIds: stationCodes,
        showAllShifts: params.allShifts,
        stations,
        systemId: settings.stsSystemCode,
      })
      setResult(res)
      setLastReconcileResult(res)
      if (res.summary.hasErrors) {
        toast.error(`Расхождения: ${res.summary.onlyMsto + res.summary.mismatch}`)
      } else {
        toast.success(`Сверка завершена. Совпадений: ${res.summary.matched}`)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Ошибка сверки')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-4 space-y-0">
      <ReconcileParamsForm
        params={params}
        setParams={setParams}
        onRun={handleRun}
        description="Включая без онлайн-заказов"
        loading={loading}
      />
      {result && (
        <div className="pt-4">
          <MSTOReconciliationResults result={result} onNewReconciliation={() => setResult(null)} />
        </div>
      )}
    </div>
  )
}

function AcquiringView() {
  const [params, setParams] = useReconcileParams()
  return (
    <div className="p-4 space-y-0">
      <ReconcileParamsForm
        params={params}
        setParams={setParams}
        onRun={() => {}}
        description="Включая смены без эквайринговых операций"
      />
    </div>
  )
}

function ReceiptsView() {
  const [params, setParams] = useReconcileParams()
  return (
    <div className="p-4 space-y-0">
      <ReconcileParamsForm
        params={params}
        setParams={setParams}
        onRun={() => {}}
        description="Включая смены без чеков"
      />
    </div>
  )
}

function DepotsView() {
  const [params, setParams] = useReconcileParams()
  return (
    <div className="p-4 space-y-0">
      <ReconcileParamsForm
        params={params}
        setParams={setParams}
        onRun={() => {}}
        description="Включая станции без поступлений"
      />
    </div>
  )
}

function DrainsView() {
  const [params, setParams] = useReconcileParams()
  return (
    <div className="p-4 space-y-0">
      <ReconcileParamsForm
        params={params}
        setParams={setParams}
        onRun={() => {}}
        description="Включая смены без сливов"
      />
    </div>
  )
}

function TransportView() {
  const [params, setParams] = useReconcileParams()
  return (
    <div className="p-4 space-y-0">
      <ReconcileParamsForm
        params={params}
        setParams={setParams}
        onRun={() => toast.info('Сверка по транспортным компаниям пока не подключена — данные перевозок появятся после интеграции с TradeFrame')}
        description="Включая станции без перевозок"
      />
    </div>
  )
}

function CorporateCardsView() {
  const [params, setParams] = useReconcileParams()
  return (
    <div className="p-4 space-y-0">
      <ReconcileParamsForm
        params={params}
        setParams={setParams}
        onRun={() => toast.info('Сверка корпоративных карт пока не подключена — нужна интеграция с TradeCorp/процессингом')}
        description="Включая без корп. карт"
      />
    </div>
  )
}

export function ReconciliationPanel() {
  // Первый рабочий разрез — Онлайн-заказы — открыт по умолчанию.
  const [tab, setTab] = useState<ReconcileTab>('online')

  return (
    <CentralPanelLayout items={RECONCILE_MENU} activeKey={tab} onSelect={(k) => setTab(k as ReconcileTab)}>
      <ScrollArea className="h-full">
        {tab === 'dashboard' && <DashboardView />}
        {tab === 'online' && <OnlineOrdersView />}
        {tab === 'corporate' && <CorporateCardsView />}
        {tab === 'acquiring' && <AcquiringView />}
        {tab === 'receipts' && <ReceiptsView />}
        {tab === 'depots' && <DepotsView />}
        {tab === 'drains' && <DrainsView />}
        {tab === 'transport' && <TransportView />}
      </ScrollArea>
    </CentralPanelLayout>
  )
}
