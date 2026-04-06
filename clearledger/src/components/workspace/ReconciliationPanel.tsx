/**
 * Панель сверки — сравнение данных из разных источников.
 * STS (смены) vs MSTO (онлайн-заказы) vs TradeCorp (корп. карты).
 */

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ScrollArea } from '@/components/ui/scroll-area'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { executeMstoReconciliation } from '@/services/reconciliation/mstoReconciliation'
import type { ReconciliationResult } from '@/types/reconciliation'
import { STATUS_COLORS, STATUS_LABELS } from '@/types/reconciliation'
import { GitCompare, Play, Loader2, Fuel, CreditCard } from 'lucide-react'
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
  const settings = getSettings()

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
          <Label className="text-[10px] text-muted-foreground">Период</Label>
          <div className="flex items-center gap-1.5">
            <Input
              type="date"
              className="h-7 text-xs w-[130px]"
              value={params.dateFrom}
              onChange={(e) => setParams((p) => ({ ...p, dateFrom: e.target.value }))}
            />
            <span className="text-[10px] text-muted-foreground">—</span>
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
          <Label className="text-[10px] text-muted-foreground">Станции</Label>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setParams((p) => ({ ...p, allStations: true, selectedStations: [] }))}
              className={`px-2.5 py-1 rounded text-[11px] font-medium border transition-colors ${
                params.allStations
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border text-muted-foreground hover:border-foreground/30'
              }`}
            >
              Все ({settings.stations.length})
            </button>
            <button
              onClick={() => setParams((p) => ({ ...p, allStations: false }))}
              className={`px-2.5 py-1 rounded text-[11px] font-medium border transition-colors ${
                !params.allStations
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border text-muted-foreground hover:border-foreground/30'
              }`}
            >
              Выбрать
            </button>
            {!params.allStations && settings.stations.map((s) => (
              <button
                key={s.code}
                onClick={() => toggleStation(s.code)}
                className={`px-2 py-1 rounded text-[11px] font-medium border transition-colors ${
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
          <label htmlFor="all-shifts" className="text-[11px] text-muted-foreground cursor-pointer">
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

function fmt(n: number): string {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(n)
}

function ReconciliationResultsView({ result }: { result: ReconciliationResult }) {
  const s = result.summary
  return (
    <div className="space-y-4 pt-3">

      {/* Статусы */}
      <div className="flex items-center gap-2 flex-wrap">
        {s.matched > 0 && <Badge variant="outline" className="text-emerald-500 text-[10px]">Совпадает: {s.matched}</Badge>}
        {s.mstoWaitDone > 0 && <Badge variant="outline" className="text-amber-500 text-[10px]">MSTO ожидание: {s.mstoWaitDone}</Badge>}
        {s.onlyMsto > 0 && <Badge variant="outline" className="text-cyan-500 text-[10px]">Только MSTO: {s.onlyMsto}</Badge>}
        {s.onlyTf > 0 && <Badge variant="outline" className="text-blue-500 text-[10px]">Только TF: {s.onlyTf}</Badge>}
        {s.onlyShift > 0 && <Badge variant="outline" className="text-purple-500 text-[10px]">Только смена: {s.onlyShift}</Badge>}
        {s.mismatch > 0 && <Badge variant="outline" className="text-red-500 text-[10px]">Расхождение: {s.mismatch}</Badge>}
        <span className="text-[10px] text-muted-foreground ml-auto">{result.duration}мс</span>
      </div>

      {/* Таблица транзакций */}
      <Table>
        <TableHeader>
          <TableRow className="text-[10px]">
            <TableHead className="h-7 px-2">Дата</TableHead>
            <TableHead className="h-7">Станция</TableHead>
            <TableHead className="h-7">Топливо</TableHead>
            <TableHead className="h-7">Агрегатор</TableHead>
            <TableHead className="h-7 text-right">MSTO, л</TableHead>
            <TableHead className="h-7 text-right">MSTO, ₽</TableHead>
            <TableHead className="h-7 text-right">TF, л</TableHead>
            <TableHead className="h-7 text-right">TF, ₽</TableHead>
            <TableHead className="h-7">Статус</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {result.transactions.map((t) => (
            <TableRow key={t.id} className="text-[11px]">
              <TableCell className="py-1 px-2">{t.date ? format(new Date(t.date), 'dd.MM HH:mm') : ''}</TableCell>
              <TableCell className="py-1">{t.stationName}</TableCell>
              <TableCell className="py-1">{t.fuelType}</TableCell>
              <TableCell className="py-1">{t.aggregatorName}</TableCell>
              <TableCell className="py-1 text-right">{t.mstoVolume != null ? fmt(t.mstoVolume) : '—'}</TableCell>
              <TableCell className="py-1 text-right">{t.mstoSum != null ? fmt(t.mstoSum) : '—'}</TableCell>
              <TableCell className="py-1 text-right">{t.tfVolume != null ? fmt(t.tfVolume) : '—'}</TableCell>
              <TableCell className="py-1 text-right">{t.tfSum != null ? fmt(t.tfSum) : '—'}</TableCell>
              <TableCell className="py-1">
                <span className={`text-[10px] font-medium ${STATUS_COLORS[t.status]}`}>
                  {STATUS_LABELS[t.status]}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function OnlineOrdersView() {
  const [params, setParams] = useReconcileParams()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ReconciliationResult | null>(null)
  const settings = getSettings()
  const { setLastReconcileResult } = useWorkspace()

  async function handleRun() {
    setLoading(true)
    try {
      const stationCodes = params.allStations
        ? settings.stations.map((s) => s.code)
        : params.selectedStations
      const res = await executeMstoReconciliation({
        dateFrom: params.dateFrom,
        dateTo: params.dateTo,
        stationCodes,
        allStations: params.allStations,
        allShifts: params.allShifts,
        systemCode: settings.stsSystemCode,
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
      {result && <ReconciliationResultsView result={result} />}
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
        onRun={() => {}}
        description="Включая станции без перевозок"
      />
    </div>
  )
}

function CorporateCardsView() {
  const [params, setParams] = useReconcileParams()

  function handleRun() {
    // TODO: запуск сверки TradeCorp
  }

  return (
    <div className="p-4 space-y-0">
      <ReconcileParamsForm
        params={params}
        setParams={setParams}
        onRun={handleRun}
        description="Включая без корп. карт"
      />
    </div>
  )
}

export function ReconciliationPanel() {
  const [tab, setTab] = useState<ReconcileTab>('dashboard')

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
