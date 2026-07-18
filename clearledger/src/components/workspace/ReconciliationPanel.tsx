/**
 * Панель сверки — сравнение данных из разных источников.
 * STS (смены) vs MSTO (онлайн-заказы) vs TradeCorp (корп. карты).
 */

import { useState, useMemo, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { ScrollArea } from '@/components/ui/scroll-area'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import {
  ENERGY_CUTS, ENERGY_CHANNELS, ENERGY_SOURCES, PIPE_STATUS_META,
  energyCut, channelsForCut, energySource,
} from '@/config/energyPipeline'
import { getStsStationsFromLocations } from '@/services/locationService'
import { useLocations } from '@/hooks/useLocations'
import { OnlineReconciliationWorkspace } from '@/components/reconciliation/OnlineReconciliationWorkspace'
import {
  getOnlineReconciliation,
  runOnlineReconciliation,
  type OnlineReconParams,
  type OnlineReconWorkspace,
} from '@/services/onlineReconciliationService'
import { GitCompare, Play, Loader2, Settings2, CheckCircle2, AlertTriangle, Plug } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { getSources, loadSources } from '@/services/sourceService'
import { getChannels, loadChannels } from '@/services/channelService'
import { isApiEnabled } from '@/services/apiClient'
import { toast } from 'sonner'

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
  // Неизвестный ключ разреза — у energy обзор рисует EnergyDashboardView выше,
  // сюда попадаем только при рассинхроне меню; показываем пустое состояние.
  if (!cut) return (
    <div className="flex h-full flex-col items-center justify-center gap-3">
      <GitCompare className="h-10 w-10 text-muted-foreground/30" />
      <p className="text-sm font-medium text-muted-foreground">Выберите разрез в меню слева</p>
    </div>
  )
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

/**
 * Обзор разрезов для топливного профиля.
 *
 * Раньше здесь была заглушка «Выберите тип сверки в меню слева»: пункт «Обзор»
 * подсвечен как активный, а холст пуст — экран выглядел сломанным. Теперь он
 * отвечает на вопрос, ради которого сюда заходят: что уже сверяется, что нет
 * и чего именно не хватает.
 */
function FuelDashboardView({ items, onSelect }: { items: CentralMenuItem[]; onSelect: (key: string) => void }) {
  const cuts = items.filter((i) => i.key !== 'dashboard')
  const ready = cuts.filter((c) => !c.disabled)
  const pending = cuts.filter((c) => c.disabled)

  return (
    <div className="space-y-5 p-6">
      <div>
        <h2 className="text-base font-semibold">Сверка данных · обзор разрезов</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Разрез — сопоставление потока канала с контрольным источником. Готов к сверке тот,
          у которого есть и подключённый источник, и вид сверки.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border/60 p-3">
          <div className="text-xs text-muted-foreground">Всего разрезов</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">{cuts.length}</div>
        </div>
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
          <div className="text-xs text-muted-foreground">Готовы к сверке</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">{ready.length}</div>
        </div>
        <div className="rounded-lg border border-border/60 p-3">
          <div className="text-xs text-muted-foreground">Не настроены</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-muted-foreground">{pending.length}</div>
        </div>
      </div>

      {ready.length > 0 && (
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Можно сверять</div>
          <div className="grid gap-2 sm:grid-cols-2">
            {ready.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => onSelect(c.key)}
                className="flex items-center justify-between gap-3 rounded-lg border border-border/60 px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-accent/40"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{c.label}</span>
                  {c.group ? <span className="block truncate text-[11px] text-muted-foreground">{c.group}</span> : null}
                </span>
                <GitCompare className="size-4 shrink-0 text-muted-foreground/50" />
              </button>
            ))}
          </div>
        </div>
      )}

      {pending.length > 0 && (
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Ждут настройки · {pending.length}
          </div>
          <div className="rounded-lg border border-border/60 divide-y divide-border/60">
            {pending.map((c) => (
              <div key={c.key} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="min-w-0">
                  <span className="block truncate text-sm">{c.label}</span>
                  {c.group ? <span className="block truncate text-[11px] text-muted-foreground">{c.group}</span> : null}
                </span>
                <span className="shrink-0 text-[11px] text-muted-foreground">нет источника или вида сверки</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground/70">
            Источник разреза подключается в карточке канала — «Коннекторы» → канал → «Настройки».
          </p>
        </div>
      )}
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

/**
 * Параметры формы сверки. Стартуют от КОНТУРА рабочей области (период сверху),
 * а не от собственных «последних 7 дней»: иначе на экране два источника правды —
 * шапка говорит «июнь», а сверка молча считает неделю (CLAUDE.md, правило 1).
 * Дальше пользователь может сузить период прямо в форме — это её параметр.
 */
function useReconcileParams(): [ReconcileParams, React.Dispatch<React.SetStateAction<ReconcileParams>>] {
  const { period } = useFilters()
  const [params, setParams] = useState<ReconcileParams>(() => ({
    dateFrom: period.from,
    dateTo: period.to,
    allStations: true,
    selectedStations: [],
    allShifts: false,
  }))

  // Смена периода наверху переносится в форму: контур — единственный источник.
  useEffect(() => {
    setParams((cur) => ({ ...cur, dateFrom: period.from, dateTo: period.to }))
  }, [period.from, period.to])

  return [params, setParams]
}

// ── Источники сверки по разрезу ──────────────────────────────────────────
// Конфиг: какие источники участвуют в сверке разреза (опорный + сверяемые).
// Фактический статус подключения берётся из НСИ/Источники.
interface CutSourceDecl { sourceType: string; role: 'anchor' | 'control'; label: string; note?: string }

const RECON_CUT_SOURCES: Record<string, CutSourceDecl[]> = {
  online: [
    { sourceType: 'sts', role: 'anchor', label: 'Сменный отчёт (STS)', note: 'Итоги онлайн-продаж смены (sbpRevenue)' },
    { sourceType: 'msto', role: 'control', label: 'MSTO — онлайн-заказы', note: 'Заказы агрегаторов: Я.Заправки / Benzuber / FuelUp' },
    { sourceType: 'sts_transactions', role: 'control', label: 'STS — транзакции отпуска', note: 'Факт на ТРК по виду оплаты «онлайн»' },
  ],
  corporate: [
    { sourceType: 'sts', role: 'anchor', label: 'Сменный отчёт (STS)', note: 'Итоги по корп-картам' },
    { sourceType: 'tradecorp', role: 'control', label: 'TradeCorp — корп-карты' },
    { sourceType: 'sts_transactions', role: 'control', label: 'STS — транзакции отпуска' },
  ],
  acquiring: [
    { sourceType: 'sts', role: 'anchor', label: 'Сменный отчёт (STS)' },
    { sourceType: 'acquiring_sber', role: 'control', label: 'Эквайринг Сбербанк' },
    { sourceType: 'sts_transactions', role: 'control', label: 'STS — транзакции отпуска' },
  ],
  receipts: [
    { sourceType: 'sts', role: 'anchor', label: 'Сменный отчёт (STS)' },
    { sourceType: 'ofd', role: 'control', label: 'ОФД — фискальные чеки' },
  ],
}

const CUT_TITLES: Record<string, string> = {
  online: 'Онлайн-заказы', corporate: 'Корп. карты', acquiring: 'Эквайринг', receipts: 'Чеки',
}

function CutSourcesModal({ cutKey, open, onClose }: { cutKey: string; open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const { company } = useCompany()
  useQuery({
    queryKey: ['sources-for-cut', company.id],
    queryFn: () => loadSources(company.id),
    enabled: open && isApiEnabled(),
  })
  const sources = getSources()
  const decls = RECON_CUT_SOURCES[cutKey] ?? []
  const byType = (t: string) => sources.find((s) => s.backendType === t || s.type === t)

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitCompare className="h-4 w-4 text-muted-foreground" />
            Источники сверки · {CUT_TITLES[cutKey] ?? cutKey}
          </DialogTitle>
        </DialogHeader>
        <p className="text-[13px] text-muted-foreground">
          Сверка сопоставляет данные этих источников — транзакционно и суммарно по каждой смене.
        </p>
        <div className="space-y-2 mt-1">
          {decls.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">Для этого разреза источники сверки не заданы.</p>
          ) : decls.map((d) => {
            const src = byType(d.sourceType)
            const connected = !!src && ['connected', 'active'].includes(src.status as string)
            return (
              <div key={d.sourceType} className="rounded-xl border border-border/60 bg-di-surface-low p-3">
                <div className="flex items-center gap-2.5">
                  <span className={`h-2 w-2 rounded-full shrink-0 ${d.role === 'anchor' ? 'bg-primary' : 'bg-emerald-500'}`} />
                  <span className="text-sm font-medium text-foreground/90">{d.label}</span>
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70">
                    {d.role === 'anchor' ? 'опорный' : 'сверяемый'}
                  </span>
                  <span className="ml-auto text-[11px] font-semibold uppercase tracking-wide shrink-0">
                    {!src ? (
                      <span className="text-muted-foreground/60">нет источника</span>
                    ) : connected ? (
                      <span className="flex items-center gap-1 text-emerald-500"><CheckCircle2 className="h-3.5 w-3.5" />подключён</span>
                    ) : (
                      <span className="flex items-center gap-1 text-amber-500"><AlertTriangle className="h-3.5 w-3.5" />настраивается</span>
                    )}
                  </span>
                </div>
                {d.note && <p className="text-[11px] text-muted-foreground mt-1 pl-[18px]">{d.note}</p>}
                <div className="mt-2 pl-[18px]">
                  <Button variant="outline" size="sm" className="h-7 text-xs gap-1.5"
                    onClick={() => { onClose(); navigate(src ? `/sources?focus=${src.id}` : '/sources') }}>
                    <Plug className="h-3.5 w-3.5" />
                    {src ? 'Настроить источник' : 'Завести источник'}
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ReconcileParamsForm({ params, setParams, onRun, description, loading, cutKey }: {
  params: ReconcileParams
  setParams: React.Dispatch<React.SetStateAction<ReconcileParams>>
  onRun: () => void
  description: string
  loading?: boolean
  cutKey?: string
}) {
  const [cfgOpen, setCfgOpen] = useState(false)
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

        {cutKey && (
          <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={() => setCfgOpen(true)}>
            <Settings2 className="h-3 w-3" />
            Настройка сверки
          </Button>
        )}

      </div>

      {/* Базис числа на поверхности (§5 «базис виден всегда»): опорный источник +
          с чем сверяется. Полный состав/статус — в модалке «Настройка сверки». */}
      {cutKey && RECON_CUT_SOURCES[cutKey] && (
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
          <span className="font-medium text-foreground/80">Базис числа:</span>
          <Badge variant="outline" className="border-primary/40 text-primary/90 text-[10px]">
            {RECON_CUT_SOURCES[cutKey].find((d) => d.role === 'anchor')?.label ?? '—'}
          </Badge>
          <span>сверяется с</span>
          {RECON_CUT_SOURCES[cutKey].filter((d) => d.role === 'control').map((c) => (
            <Badge key={c.sourceType} variant="outline" className="border-zinc-600 text-zinc-400 text-[10px]">{c.label}</Badge>
          ))}
        </div>
      )}

      {/* Разделитель */}
      <div className="border-b border-border/50 mt-3" />
      {cutKey && <CutSourcesModal cutKey={cutKey} open={cfgOpen} onClose={() => setCfgOpen(false)} />}
    </div>
  )
}

function OnlineOrdersView() {
  const [params, setParams] = useReconcileParams()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<OnlineReconWorkspace | null>(null)
  const { companyId } = useCompany()
  const { setLastReconcileResult } = useWorkspace()

  function requestParams(): OnlineReconParams {
    return {
      companyId,
      dateFrom: params.dateFrom,
      dateTo: params.dateTo,
      stationCodes: params.allStations ? [] : params.selectedStations,
      includeEmptyShifts: params.allShifts,
    }
  }

  async function reload() {
    const res = await getOnlineReconciliation(requestParams())
    setResult(res)
    setLastReconcileResult(res)
  }

  async function handleRun() {
    setLoading(true)
    try {
      const res = await runOnlineReconciliation(requestParams())
      setResult(res)
      setLastReconcileResult(res)
      if (res.unresolved_count) {
        toast.warning(`Требуют разбора: ${res.unresolved_count}`)
      } else {
        toast.success('Три источника сошлись')
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
        cutKey="online"
        loading={loading}
      />
      {result && (
        <div className="pt-4">
          <OnlineReconciliationWorkspace data={result} params={requestParams()} onReload={reload} />
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
        onRun={() => toast.info('Сверка эквайринга пока не подключена — нужен источник выписок банка-эквайера.')}
        description="Включая смены без эквайринговых операций"
        cutKey="acquiring"
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
        onRun={() => toast.info('Сверка чеков пока не подключена — нужен источник данных ОФД.')}
        description="Включая смены без чеков"
        cutKey="receipts"
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
        cutKey="corporate"
      />
    </div>
  )
}

// doc_type сверяемого разреза → ярлык + реализованный вид сверки (пока только у
// канала «Сменный отчёт» fuel_shift). Остальные разрезы — заглушка «не настроен».
const CUT_DOC_META: Record<string, { label: string; fuelView?: ReconcileTab }> = {
  online_orders: { label: 'Онлайн-заказы', fuelView: 'online' },
  card_transactions: { label: 'Корп-карты', fuelView: 'corporate' },
  card_payments: { label: 'Эквайринг', fuelView: 'acquiring' },
  fiscal_receipts: { label: 'Чеки', fuelView: 'receipts' },
  marking_movement: { label: 'Маркировка' },
}

function CutPlaceholderView({ label, channel }: { label: string; channel?: string }) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="text-center text-muted-foreground max-w-sm">
        <GitCompare className="h-8 w-8 mx-auto mb-3 opacity-30" />
        <p className="text-sm font-medium text-foreground/80">{label}{channel ? ` · ${channel}` : ''}</p>
        <p className="text-xs mt-1.5 leading-relaxed">
          Сверка этого разреза ещё не настроена — нужен подключённый источник и вид сверки.
          Состав источников — в «Настройке сверки» разреза (где доступна).
        </p>
      </div>
    </div>
  )
}

export function ReconciliationPanel() {
  const { company } = useCompany()
  // Набор разрезов: топливные у fuel (динамически из каналов), энергетические у energy.
  const isFuel = company.profileId === 'fuel'

  // Каналы — источник разрезов (группировка по каналу).
  const { data: loadedChannels } = useQuery({
    queryKey: ['recon-channels', company.id],
    queryFn: () => loadChannels(company.id),
    enabled: isFuel && isApiEnabled(),
  })
  const channels = loadedChannels ?? getChannels()

  const menu: CentralMenuItem[] = useMemo(() => {
    if (!isFuel) return ENERGY_RECONCILE_MENU
    const items: CentralMenuItem[] = [{ key: 'dashboard', label: 'Обзор' }]
    for (const ch of channels) {
      for (const s of ch.streams) {
        if (s.role !== 'control') continue
        const meta = CUT_DOC_META[s.docTypeId]
        if (!meta) continue
        const hasView = ch.templateId === 'fuel_shift' && !!meta.fuelView
        items.push({
          key: `${ch.id}:${s.docTypeId}`,
          label: meta.label,
          group: ch.name,
          disabled: !hasView || !s.sourceId,
        })
      }
    }
    // каналы ещё не загрузились → старое плоское меню как fallback
    return items.length > 1 ? items : RECONCILE_MENU
  }, [isFuel, channels])

  const [tab, setTab] = useState<string>('dashboard')
  const menuKeys = menu.map((m) => m.key)
  const activeKey = menuKeys.includes(tab) ? tab : menuKeys[0]

  function renderFuelCut(key: string): React.ReactNode {
    if (key === 'dashboard') return <FuelDashboardView items={menu} onSelect={setTab} />
    // Динамический ключ `${channelId}:${docType}` → вид по каналу/типу.
    if (key.includes(':')) {
      const [chId, docType] = key.split(':')
      const ch = channels.find((c) => c.id === chId)
      const meta = CUT_DOC_META[docType]
      const view = ch?.templateId === 'fuel_shift' ? meta?.fuelView : undefined
      switch (view) {
        case 'online': return <OnlineOrdersView />
        case 'corporate': return <CorporateCardsView />
        case 'acquiring': return <AcquiringView />
        case 'receipts': return <ReceiptsView />
        default: return <CutPlaceholderView label={meta?.label ?? 'Разрез'} channel={ch?.name} />
      }
    }
    // Плоский fallback-ключ (RECONCILE_MENU).
    switch (key) {
      case 'online': return <OnlineOrdersView />
      case 'corporate': return <CorporateCardsView />
      case 'acquiring': return <AcquiringView />
      case 'receipts': return <ReceiptsView />
      default: return <CutPlaceholderView label="Разрез" />
    }
  }

  return (
    <CentralPanelLayout items={menu} activeKey={activeKey} onSelect={setTab}>
      <ScrollArea className="h-full">
        {isFuel ? (
          renderFuelCut(activeKey)
        ) : activeKey === 'dashboard' ? (
          <EnergyDashboardView onSelectCut={setTab} />
        ) : (
          <EnergyCutView tab={activeKey} />
        )}
      </ScrollArea>
    </CentralPanelLayout>
  )
}
