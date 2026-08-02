/**
 * Раздел «Нормализация» для топливного профиля (ГИГ) — та же логика, что
 * EnergyNormalizationView (РусГидро), но на коннекторах ГИГ:
 *   • «Обзор» (дефолт) — здоровье нормализации по каналам компании: что каждый
 *     канал принял в L2 (смены STS, ТТН, сопутка/общепит ЦБ), клик → витрина;
 *   • таб на канал — витрина модели его набора данных (слои L1→L4 · звёздная
 *     схема · качество/канонизация) на реальных данных — через переиспользуемую
 *     EnergyNormalizationModel с топливным fetchModel.
 *
 * Меню строится из каналов компании (loadChannels); канал без витрины
 * (карта NORM_TEMPLATES) в меню не попадает. Каналы «Сопутка» и «Общепит»
 * ведут на общий набор данных ЦБ (sidegoods) — единый конвейер пула смен ЦБ.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { loadChannels } from '@/services/channelService'
import { isApiEnabled } from '@/services/apiClient'
import { getFuelModel, type ChargeModelResponse, type FuelModelDataset } from '@/services/analyticsService'
import type { Channel } from '@/types/channel'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtN } from '@/components/balance/balanceCalc'
import { Database, ChevronRight } from 'lucide-react'
import { EnergyNormalizationModel } from './EnergyNormalizationModel'
import { MetricTile as Kpi } from '@/components/ui/metric-tile'

/* Карта: шаблон канала ГИГ → набор данных нормализации. */
const NORM_TEMPLATES: Record<string, { entity: string; dataset: FuelModelDataset }> = {
  fuel_shift: { entity: 'Смены АЗС + реализации (FuelShift)', dataset: 'shifts' },
  fuel_delivery: { entity: 'Поступления топлива (FuelReceipt)', dataset: 'receipts' },
  sidegoods: { entity: 'Сопутка/общепит ЦБ (DataEntry)', dataset: 'sidegoods' },
  food: { entity: 'Сопутка/общепит ЦБ (DataEntry)', dataset: 'sidegoods' },
}

const DATASET_PROPS: Record<FuelModelDataset, { title: string; subtitle: string; entityUnit: string; emptyText: string }> = {
  shifts: {
    title: 'Модель данных · смены АЗС (STS)',
    subtitle: 'Внутренняя многослойная база смен (L1 RAW → L2 CLEAN → L3 EXPORT → L4 1C_REF), звёздная схема: '
      + 'факт «Смена АЗС» (выручка/литры/реализации) + измерения (станция / канал оплаты / топливо / время). '
      + 'Реализации (операции ТРК) — связанный факт нижнего грейна с дедупом по STS id.',
    entityUnit: 'Смен',
    emptyText: 'Нет загруженных смен STS. Загрузите период в канале «Топливо: сменный отчёт», затем модель данных отобразится здесь на реальных сменах.',
  },
  receipts: {
    title: 'Модель данных · поступления топлива (ТТН)',
    subtitle: 'Приёмки топлива по ТТН (L1 RAW → L2 CLEAN → L3 EXPORT → L4 1C_REF): объём/масса док↔факт, '
      + 'плотность и расхождения; поверх — себестоимость закупочной партии (₽/л) для маржи FIFO.',
    entityUnit: 'ТТН',
    emptyText: 'Нет загруженных ТТН. Загрузите период в канале «Топливо: приём (ТТН)», затем модель данных отобразится здесь.',
  },
  sidegoods: {
    title: 'Модель данных · сопутка и общепит (ЦБ)',
    subtitle: 'Смены сопутки/общепита из ЦБ ЭЛСИ.АЗК (COM-пул) + приходы ПТУ + выпуски блюд + ТТК + движение '
      + '(инвентаризации/списания/перемещения) + НСИ-кеши (номенклатура, штрихкоды, контрагенты, склады). '
      + 'L3/L4 — пакеты «Выгрузка в БП» и приёмник TradeLedger в БП ГИГ.',
    entityUnit: 'Смен',
    emptyText: 'Нет данных сопутки. Прогоните пул смен ЦБ (коннектор «Сопутка»), затем модель данных отобразится здесь.',
  },
}

/* ── Обзор: кросс-канальное здоровье нормализации ── */
interface ChMetric { entity: string; records: number; unit: string; enrich: string; ok: boolean }

function useDatasetModels(datasets: FuelModelDataset[]) {
  const { companyId } = useCompany()
  const shifts = useQuery({
    queryKey: ['fuel-model', 'shifts', companyId],
    queryFn: () => getFuelModel(companyId, 'shifts'),
    enabled: !!companyId && datasets.includes('shifts'), staleTime: 60_000,
  })
  const receipts = useQuery({
    queryKey: ['fuel-model', 'receipts', companyId],
    queryFn: () => getFuelModel(companyId, 'receipts'),
    enabled: !!companyId && datasets.includes('receipts'), staleTime: 60_000,
  })
  const sidegoods = useQuery({
    queryKey: ['fuel-model', 'sidegoods', companyId],
    queryFn: () => getFuelModel(companyId, 'sidegoods'),
    enabled: !!companyId && datasets.includes('sidegoods'), staleTime: 60_000,
  })
  return { shifts: shifts.data, receipts: receipts.data, sidegoods: sidegoods.data }
}

function NormalizationOverview({ channels, onOpen }: { channels: Channel[]; onOpen: (id: string) => void }) {
  const datasets = useMemo(
    () => Array.from(new Set(channels.map((c) => NORM_TEMPLATES[c.templateId ?? '']?.dataset).filter(Boolean))) as FuelModelDataset[],
    [channels],
  )
  const models = useDatasetModels(datasets)

  const measure = (m: ChargeModelResponse | undefined, key: string): number =>
    m?.fact?.measures.find((x) => x.key === key)?.value ?? 0

  function metric(ch: Channel): ChMetric {
    const tpl = NORM_TEMPLATES[ch.templateId ?? '']
    if (!tpl) return { entity: '—', records: 0, unit: '', enrich: '—', ok: false }
    if (tpl.dataset === 'shifts') {
      const m = models.shifts
      const tx = measure(m, 'tx')
      return { entity: tpl.entity, records: m?.rows ?? 0, unit: 'смен',
               enrich: tx ? `реализации ${fmtN(tx)}` : '—', ok: (m?.rows ?? 0) > 0 }
    }
    if (tpl.dataset === 'receipts') {
      const m = models.receipts
      const costed = measure(m, 'costed_pct')
      return { entity: tpl.entity, records: m?.rows ?? 0, unit: 'ТТН',
               enrich: costed ? `себест. ${costed}%` : '—', ok: (m?.rows ?? 0) > 0 }
    }
    const m = models.sidegoods
    const nom = m?.dimensions?.find((d) => d.key === 'nomenclature')
    return { entity: tpl.entity, records: m?.rows ?? 0, unit: 'смен',
             enrich: nom ? `НСИ ${fmtN(nom.cardinality)}` : '—', ok: (m?.rows ?? 0) > 0 }
  }

  const rows = channels.map((ch) => ({ ch, m: metric(ch) }))
  // Итог L2 — по УНИКАЛЬНЫМ наборам (сопутка и общепит делят один датасет)
  const totalL2 = (models.shifts?.rows ?? 0) + (models.receipts?.rows ?? 0) + (models.sidegoods?.rows ?? 0)
  const active = rows.filter((r) => r.m.ok).length

  return (
    <div className="space-y-5 px-6 py-6">
      <div>
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-primary" />
          <h1 className="text-xl font-semibold">Нормализация · обзор каналов</h1>
          <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
        </div>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Здоровье нормализации по каналам компании: что каждый канал принял в нормализованную базу (L2),
          полнота и обогащение. Клик по каналу — витрина его модели данных (слои · звёздная схема · качество).
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Каналов с данными" value={`${active} / ${rows.length}`} sub="в нормализации" />
        <Kpi label="Всего записей L2" value={fmtN(totalL2)} sub="смены + ТТН + сопутка" />
        <Kpi label="Наборов данных" value={fmtN(new Set(rows.map((r) => r.m.entity)).size)} sub="L2-сущностей" />
        <Kpi label="Профиль" value="АЗС (топливо)" />
      </div>

      <Card><CardContent className="overflow-x-auto pt-5">
        <div className="mb-3 text-sm font-medium">Каналы нормализации</div>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Канал</TableHead>
            <TableHead>Набор данных (L2)</TableHead>
            <TableHead className="text-right">Записей</TableHead>
            <TableHead>Обогащение</TableHead>
            <TableHead className="text-center">Статус</TableHead>
            <TableHead className="w-8"></TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {rows.map(({ ch, m }) => (
              <TableRow key={ch.id} className="cursor-pointer" onClick={() => onOpen(ch.id)}>
                <TableCell className="font-medium">{ch.name}</TableCell>
                <TableCell className="text-muted-foreground">{m.entity}</TableCell>
                <TableCell className="text-right tabular-nums">{m.records ? `${fmtN(m.records)} ${m.unit}` : '—'}</TableCell>
                <TableCell className="text-muted-foreground">{m.enrich}</TableCell>
                <TableCell className="text-center">
                  <Badge variant="secondary" className={`text-[10px] ${m.ok
                    ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                    : 'bg-muted text-muted-foreground'}`}>
                    {m.ok ? 'нормализован' : 'нет данных'}
                  </Badge>
                </TableCell>
                <TableCell><ChevronRight className="h-4 w-4 text-muted-foreground/50" /></TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow><TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                Нет каналов с витриной нормализации. Подключите каналы «Топливо: сменный отчёт», «Топливо: приём (ТТН)» или «Сопутка».
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent></Card>
    </div>
  )
}

export function FuelNormalizationView() {
  const { company, companyId } = useCompany()
  const { data: loaded } = useQuery({
    queryKey: ['norm-channels', company.id],
    queryFn: () => loadChannels(company.id),
    enabled: isApiEnabled(),
  })
  const normChannels = useMemo(
    () => (loaded ?? []).filter((ch) => NORM_TEMPLATES[ch.templateId ?? '']),
    [loaded],
  )

  const menu = useMemo<CentralMenuItem[]>(() => {
    const items: CentralMenuItem[] = [{ key: 'overview', label: 'Обзор' }]
    for (const ch of normChannels) items.push({ key: ch.id, label: ch.name })
    return items
  }, [normChannels])

  const [tab, setTab] = useState('overview')
  const activeKey = menu.some((mi) => mi.key === tab) ? tab : 'overview'

  function render() {
    if (activeKey === 'overview') return <NormalizationOverview channels={normChannels} onOpen={setTab} />
    const ch = normChannels.find((c) => c.id === activeKey)
    const tpl = NORM_TEMPLATES[ch?.templateId ?? '']
    if (!tpl) return <div className="px-6 py-10 text-sm text-muted-foreground">Витрина нормализации для этого канала в разработке.</div>
    const p = DATASET_PROPS[tpl.dataset]
    return (
      <EnergyNormalizationModel
        fetchModel={(cid: string) => getFuelModel(cid ?? companyId, tpl.dataset)}
        queryKey={`fuel-model-${tpl.dataset}`}
        title={p.title} subtitle={p.subtitle} entityUnit={p.entityUnit}
        emptyText={p.emptyText}
        showPivotExport={false}
      />
    )
  }

  return (
    <CentralPanelLayout items={menu} activeKey={activeKey} onSelect={setTab}>
      <ScrollArea className="h-full">{render()}</ScrollArea>
    </CentralPanelLayout>
  )
}
