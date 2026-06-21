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
import { useCompany } from '@/contexts/CompanyContext'
import {
  ENERGY_CUTS, ENERGY_CHANNELS, ENERGY_SOURCES, PIPE_STATUS_META,
  energyCut, channelsForCut, energySource,
} from '@/config/energyPipeline'
import { getSettings } from '@/services/settingsService'
import { getStsStationsFromLocations } from '@/services/locationService'
import { useLocations } from '@/hooks/useLocations'
import { executeMstoReconciliation } from '@/services/mstoReconciliation'
import { MSTOReconciliationResults } from '@/components/reconciliation/MSTOReconciliationResults'
import type { MSTOReconciliationResult, StationInfo } from '@/types/mstoReconciliation'
import { GitCompare, Play, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

type ReconcileTab = 'dashboard' | 'online' | 'corporate' | 'acquiring' | 'receipts' | 'depots' | 'drains' | 'transport'
  | 'orders' | 'corp' | 'rfid' | 'eacq' | 'ofd' | 'suppliers' | 'rent'

// Набор разрезов — НАСТРАИВАЕТСЯ под компанию по профилю (Источник/Канал/Разрез).
// fuel (ГИГ): топливные разрезы. energy (РусГидро): энергетический набор (без Нефтебаз/Сливов/Перевозок).
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

const ENERGY_RECONCILE_MENU: CentralMenuItem[] = [
  { key: 'dashboard', label: 'Обзор' },
  ...ENERGY_CUTS.map((c) => ({ key: c.id, label: c.label })),
]

// Моковые результаты сверки для разрезов в статусе demo — показывают форму отчёта на демо-данных.
interface MockReconRow { left: string; right: string; delta: string; ok: boolean }
interface MockRecon { leftCol: string; rightCol: string; deltaCol: string; rows: MockReconRow[] }
const ENERGY_MOCK_RECON: Record<string, MockRecon> = {
  orders: {
    leftCol: 'ПК (сессии), кВт·ч', rightCol: 'ПУ ЭЗС (отпуск), кВт·ч', deltaCol: 'Δ кВт·ч',
    rows: [
      { left: '12 480', right: '12 480', delta: '0', ok: true },
      { left: '8 215',  right: '8 197',  delta: '−18', ok: false },
      { left: '5 940',  right: '5 940',  delta: '0', ok: true },
    ],
  },
  eacq: {
    leftCol: 'ПК (платёж), ₽', rightCol: 'Эквайер (зачислено), ₽', deltaCol: 'Холд − факт, ₽',
    rows: [
      { left: '1 240 500', right: '1 240 500', delta: '0', ok: true },
      { left: '430 000',   right: '418 600',   delta: '−11 400', ok: false },
      { left: '96 750',    right: '96 750',    delta: '0', ok: true },
    ],
  },
}

function MockReconTable({ data }: { data: MockRecon }) {
  const matched = data.rows.filter((r) => r.ok).length
  const mismatched = data.rows.length - matched
  return (
    <div className="rounded-lg border border-border/50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">Результат сверки</span>
        <span className="rounded-full bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-600 dark:text-sky-400">демо-данные</span>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] text-muted-foreground">
            <th className="py-1 text-right font-medium">{data.leftCol}</th>
            <th className="py-1 text-right font-medium">{data.rightCol}</th>
            <th className="py-1 text-right font-medium">{data.deltaCol}</th>
            <th className="py-1 text-center font-medium">Статус</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i} className="border-t border-border/40">
              <td className="py-1.5 text-right tabular-nums">{r.left}</td>
              <td className="py-1.5 text-right tabular-nums text-muted-foreground">{r.right}</td>
              <td className={`py-1.5 text-right tabular-nums ${r.ok ? 'text-muted-foreground' : 'text-amber-600 dark:text-amber-400'}`}>{r.delta}</td>
              <td className="py-1.5 text-center">
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${r.ok ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' : 'bg-amber-500/15 text-amber-600 dark:text-amber-400'}`}>
                  {r.ok ? 'совпало' : 'расхождение'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-[11px] text-muted-foreground/70">
        Совпало: <span className="font-medium text-foreground">{matched}</span> · расхождений: <span className="font-medium text-foreground">{mismatched}</span>. Демо-модель на синтетических данных сети ЭЗС.
      </p>
    </div>
  )
}

function EnergyCutView({ tab }: { tab: string }) {
  const cut = energyCut(tab)
  if (!cut) return <DashboardView />
  const channels = channelsForCut(cut.id)
  const statusMeta = PIPE_STATUS_META[cut.status]
  const mock = ENERGY_MOCK_RECON[cut.id]
  return (
    <div className="max-w-2xl space-y-4 p-6">
      <div>
        <div className="mb-2 flex items-center gap-2">
          <GitCompare className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">{cut.label}</h2>
          <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${statusMeta.cls}`}>{statusMeta.label}</span>
        </div>
        <p className="text-sm text-muted-foreground">{cut.desc}</p>
      </div>

      {/* Питающая цепочка: Источник → Канал → Разрез */}
      <div className="rounded-lg border border-border/50 p-4">
        <div className="mb-2.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
          Питающая цепочка (Источник → Канал → Разрез)
        </div>
        <div className="space-y-1.5">
          {channels.map((ch) => {
            const src = energySource(ch.sourceId)
            return (
              <div key={ch.id} className="flex flex-wrap items-center gap-1.5 text-sm">
                <span className="rounded bg-muted/60 px-2 py-0.5 text-xs">{src?.label ?? ch.sourceId}</span>
                {src && <span className="text-[10px] text-muted-foreground/70">{src.level === 'station' ? 'станция' : 'компания'}</span>}
                <span className="text-muted-foreground">→</span>
                <span className="rounded bg-muted/60 px-2 py-0.5 text-xs">{ch.label}</span>
                <span className="text-muted-foreground">→</span>
                <span className="font-medium">{cut.label}</span>
              </div>
            )
          })}
        </div>
        <p className="mt-3 text-[11px] text-muted-foreground/70">
          Источники и каналы этого разреза отражены в разделах «Источники» и «Каналы» компании (выводятся обратно от разрезов).
        </p>
      </div>

      {mock && <MockReconTable data={mock} />}
    </div>
  )
}

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

// Осмысленный обзор контура сверки для energy-профиля (РусГидро): объёмы цепочки + плитки разрезов со статусом.
function EnergyDashboardView({ onSelectCut }: { onSelectCut: (cutId: string) => void }) {
  const nSources = ENERGY_SOURCES.length
  const nChannels = ENERGY_CHANNELS.length
  const nCuts = ENERGY_CUTS.length
  return (
    <div className="max-w-3xl space-y-5 p-6">
      <div>
        <div className="mb-2 flex items-center gap-2">
          <GitCompare className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">Сверка данных сети ЭЗС</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Контур сверки РусГидро: <span className="font-medium text-foreground">{nSources}</span> источников →{' '}
          <span className="font-medium text-foreground">{nChannels}</span> каналов нормализации →{' '}
          <span className="font-medium text-foreground">{nCuts}</span> разрезов учёта. Выберите разрез для просмотра цепочки и результата сверки.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {ENERGY_CUTS.map((c) => {
          const meta = PIPE_STATUS_META[c.status]
          return (
            <button
              key={c.id}
              onClick={() => onSelectCut(c.id)}
              className="rounded-lg border border-border/50 p-3 text-left transition-colors hover:border-primary/40 hover:bg-accent/40"
            >
              <div className="mb-1 flex items-center gap-2">
                <span className="text-sm font-medium">{c.label}</span>
                <span className={`ml-auto rounded-full px-1.5 py-0.5 text-[10px] ${meta.cls}`}>{meta.label}</span>
              </div>
              <p className="line-clamp-2 text-[11px] text-muted-foreground">{c.desc}</p>
            </button>
          )
        })}
      </div>
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
  // Гидратируем точки активной компании (наполняет зеркало + ререндер),
  // затем собираем станции из точек обслуживания.
  useLocations()
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
  const { company } = useCompany()
  // Набор разрезов настраивается под компанию: топливные у fuel, энергетические у energy.
  const isFuel = company.profileId === 'fuel'
  const menu = isFuel ? RECONCILE_MENU : ENERGY_RECONCILE_MENU
  const [tab, setTab] = useState<ReconcileTab>(isFuel ? 'online' : 'orders')
  const menuKeys = menu.map((m) => m.key)
  const activeTab = (menuKeys.includes(tab) ? tab : menuKeys[0]) as ReconcileTab

  return (
    <CentralPanelLayout items={menu} activeKey={activeTab} onSelect={(k) => setTab(k as ReconcileTab)}>
      <ScrollArea className="h-full">
        {activeTab === 'dashboard' ? (
          isFuel ? <DashboardView /> : <EnergyDashboardView onSelectCut={(k) => setTab(k as ReconcileTab)} />
        ) : isFuel ? (
          <>
            {activeTab === 'online' && <OnlineOrdersView />}
            {activeTab === 'corporate' && <CorporateCardsView />}
            {activeTab === 'acquiring' && <AcquiringView />}
            {activeTab === 'receipts' && <ReceiptsView />}
            {activeTab === 'depots' && <DepotsView />}
            {activeTab === 'drains' && <DrainsView />}
            {activeTab === 'transport' && <TransportView />}
          </>
        ) : (
          <EnergyCutView tab={activeTab} />
        )}
      </ScrollArea>
    </CentralPanelLayout>
  )
}
