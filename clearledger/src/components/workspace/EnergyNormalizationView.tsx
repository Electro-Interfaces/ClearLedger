/**
 * Раздел «Нормализация» для energy-профиля (ЭЗС) — вертикальное меню как в
 * «Разрезах учёта» (тот же CentralPanelLayout + меню, построенное из каналов):
 *   • «Обзор» (дефолт) — кросс-канальное здоровье нормализации (что каждый канал
 *     принял в L2, полнота, обогащение); клик по строке → таб канала;
 *   • таб на канал — витрина модели его набора данных (слои/звезда/качество).
 *
 * Меню строится динамически из каналов компании (loadChannels), в меню попадают
 * только каналы с известной витриной нормализации (карта NORM_TEMPLATES).
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { loadChannels } from '@/services/channelService'
import { isApiEnabled } from '@/services/apiClient'
import { getChargeModel, getStationsModel, getStationsLinkage } from '@/services/analyticsService'
import { usePaymentDisciplineSummary } from '@/hooks/useReferences'
import type { Channel } from '@/types/channel'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtN } from '@/components/balance/balanceCalc'
import { Database, ChevronRight } from 'lucide-react'
import { EnergyNormalizationModel } from './EnergyNormalizationModel'

/* Карта: шаблон канала → набор данных нормализации (метка L2-сущности).
   Канал без записи здесь в меню нормализации не попадёт (как в «Разрезах учёта»). */
const NORM_TEMPLATES: Record<string, { entity: string }> = {
  charge_sessions: { entity: 'Зарядные сессии (ChargeSession)' },
  reestr_contracts_payments: { entity: 'Договоры и оплаты ЭЗС (Settlement)' },
  stations: { entity: 'Станции ЭЗС (объекты)' },
}

const STATIONS_SUBTITLE =
  'Внутренняя многослойная база объектов (L1 RAW → L2 CLEAN → L3 EXPORT → L4 1C_REF), организованная звёздной схемой: '
  + 'факт «Станция ЭЗС» (паспорт) + измерения (регион / владелец / бренд / мощность). Готова к сводным, карте и дашбордам.'

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card><CardContent className="pt-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground/70">{sub}</div>}
    </CardContent></Card>
  )
}

/* ── РЕАЛЬНЫЙ блок: нормализация реестра «Энергоснабжение и аренда ЭЗС» (L1→L2) ── */
function ReestrNormalizationBlock() {
  const q = usePaymentDisciplineSummary()
  const s = q.data
  if (!s || (s.l1Raw === 0 && s.settlements === 0)) {
    return <div className="px-6 py-10 text-sm text-muted-foreground">Реестр ещё не загружен — нормализовать нечего.</div>
  }
  const stages = [
    { t: 'Приём L1 (RAW)', d: 'Строки реестра «как есть» (одна строка = одна ЭЗС).', n: s.l1Raw, tone: 'bg-slate-500/15 text-slate-600 dark:text-slate-300' },
    { t: 'Нормализация', d: 'Резолв станции по № ЭЗС, разбор «оплачено по» → статус, основание (договор/разрешение).', n: s.l1Raw, tone: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
    { t: 'L2 (CLEAN)', d: 'Контрагенты, договоры и платёжная дисциплина по ЭЗС → разрезы «Поставщики э/э»/«Аренда».', n: s.l2Clean, tone: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  ]
  return (
    <div className="space-y-5 px-6 py-6">
      <Card className="border-l-2 border-l-primary"><CardContent className="space-y-3 pt-5">
        <div className="flex items-center gap-2">
          <div className="text-sm font-medium">Нормализация реестра «Энергоснабжение и аренда ЭЗС»</div>
          <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Записей L1 (RAW)" value={fmtN(s.l1Raw)} />
          <Kpi label="Нормализовано (L2)" value={fmtN(s.l2Clean)} />
          <Kpi label="Записей платёжной дисциплины" value={fmtN(s.settlements)} />
          <Kpi label="ЭЗС охвачено" value={fmtN(s.stationsCovered)} />
        </div>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
          {stages.map((st, i) => (
            <div key={st.t} className="flex flex-1 items-stretch gap-3">
              <div className="flex-1 rounded-lg border bg-muted/30 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{st.t}</span>
                  <Badge variant="secondary" className={`text-[10px] ${st.tone}`}>{fmtN(st.n)}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{st.d}</p>
              </div>
              {i < stages.length - 1 && <div className="hidden self-center text-muted-foreground/60 lg:block">→</div>}
            </div>
          ))}
        </div>
        <p className="text-xs text-muted-foreground/70">
          Источник «Реестр энергоснабжения и аренды ЭЗС» → канал «Энергоснабжение и аренда ЭЗС» (загрузка xlsx →
          L1 RAW → нормализация → L2). Витрины «Поставщики э/э» / «Аренда» строятся на L2.
        </p>
      </CardContent></Card>
    </div>
  )
}

/* ── Связь каналов по станции (конформная размерность): покрытие и разрывы ── */
const pctCls = (p: number) => (p >= 90 ? 'text-emerald-600 dark:text-emerald-400' : p >= 70 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400')

function ChannelLinkageBlock({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['stations-linkage', companyId],
    queryFn: () => getStationsLinkage(companyId),
    enabled: !!companyId, staleTime: 60_000,
  })
  const lk = q.data
  if (!lk || lk.objects === 0) return null
  return (
    <Card><CardContent className="space-y-3 overflow-x-auto pt-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-sm font-medium">Связь каналов по станции</div>
        <Badge className="bg-blue-500/15 text-[10px] text-blue-600 dark:text-blue-400">конформная размерность</Badge>
        <span className="ml-auto text-[11px] text-muted-foreground">ключ: {lk.key_label}</span>
      </div>
      <p className="text-xs text-muted-foreground">
        Объект-станция (<span className="font-mono">service_locations</span>) — общий хаб; каналы-факты ссылаются на него.
        Объектов <b className="text-foreground">{fmtN(lk.objects)}</b> · с типизированным паспортом <b className="text-foreground">{fmtN(lk.objects_enriched)}</b> · без сессий <b className="text-foreground">{fmtN(lk.objects_without_sessions)}</b>.
      </p>
      <Table>
        <TableHeader><TableRow>
          <TableHead>Канал</TableHead>
          <TableHead>Ключ связи</TableHead>
          <TableHead className="text-center">Тип</TableHead>
          <TableHead className="text-right">Станций связано</TableHead>
          <TableHead className="text-right">Записей связано</TableHead>
          <TableHead className="text-right">Сироты</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {lk.channels.map((c) => (
            <TableRow key={c.template}>
              <TableCell className="font-medium">{c.name}</TableCell>
              <TableCell className="text-[11px] text-muted-foreground">{c.key}</TableCell>
              <TableCell className="text-center">
                <Badge variant="secondary" className={`text-[10px] ${c.materialized
                  ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                  : 'bg-amber-500/15 text-amber-600 dark:text-amber-400'}`}>
                  {c.materialized ? 'FK ✓' : 'строкой'}
                </Badge>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {fmtN(c.linked)} / {fmtN(c.stations)} <span className={pctCls(c.linked_pct)}>({c.linked_pct}%)</span>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {c.records ? <>{fmtN(c.records_linked)} / {fmtN(c.records)} <span className={pctCls(c.records_pct)}>({c.records_pct}%)</span></> : '—'}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {c.orphans > 0 ? <span className="text-amber-600 dark:text-amber-400">{fmtN(c.orphans)}</span> : '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-[11px] text-muted-foreground/70">
        «FK ✓» — реальная ссылка на объект; «строкой» — связь по значению (станция № как текст), не материализована.
        «Сироты» — станции канала без карточки-объекта (напр. сессии со станций вне справочника) → кандидаты на дозагрузку/сверку.
      </p>
    </CardContent></Card>
  )
}

/* ── Обзор: кросс-канальное здоровье нормализации (первый таб по умолчанию) ── */
interface ChMetric { entity: string; records: number; unit: string; enrich: string; ok: boolean }

function NormalizationOverview({ channels, onOpen }: { channels: Channel[]; onOpen: (id: string) => void }) {
  const { companyId } = useCompany()
  const modelQ = useQuery({
    queryKey: ['charge-model', companyId],
    queryFn: () => getChargeModel(companyId),
    enabled: !!companyId, staleTime: 60_000,
  })
  const stationsQ = useQuery({
    queryKey: ['stations-model', companyId],
    queryFn: () => getStationsModel(companyId),
    enabled: !!companyId && channels.some((c) => c.templateId === 'stations'), staleTime: 60_000,
  })
  const disc = usePaymentDisciplineSummary()
  const m = modelQ.data
  const sm = stationsQ.data
  const d = disc.data

  function metric(ch: Channel): ChMetric {
    if (ch.templateId === 'charge_sessions') {
      const rows = m?.rows ?? 0
      const client = m?.dimensions?.find((x) => x.key === 'client')
      return { entity: 'Сессии зарядки', records: rows, unit: 'сессий',
               enrich: client && client.fill_pct > 0 ? `ЮЛ ${client.fill_pct}%` : '—', ok: rows > 0 }
    }
    if (ch.templateId === 'stations') {
      const rows = sm?.rows ?? 0
      const region = sm?.dimensions?.find((x) => x.key === 'region')
      return { entity: 'Станции ЭЗС', records: rows, unit: 'станций',
               enrich: region && region.fill_pct > 0 ? `регион ${region.fill_pct}%` : '—', ok: rows > 0 }
    }
    if (ch.templateId === 'reestr_contracts_payments') {
      const setl = d?.settlements ?? 0
      return { entity: 'Договоры и оплаты', records: setl, unit: 'записей', enrich: '—', ok: setl > 0 }
    }
    return { entity: '—', records: 0, unit: '', enrich: '—', ok: false }
  }

  const rows = channels.map((ch) => ({ ch, m: metric(ch) }))
  const totalL2 = rows.reduce((a, r) => a + r.m.records, 0)
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
        <Kpi label="Всего записей L2" value={fmtN(totalL2)} sub="по всем каналам" />
        <Kpi label="Наборов данных" value={fmtN(rows.length)} sub="L2-сущностей" />
        <Kpi label="Профиль" value="Энергетика (ЭЗС)" />
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
                Нет каналов с витриной нормализации. Подключите канал «Зарядные сессии ЭЗС» или «Реестр договоров и оплат ЭЗС».
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent></Card>

      <ChannelLinkageBlock companyId={companyId} />
    </div>
  )
}

export function EnergyNormalizationView() {
  const { company } = useCompany()
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
    const tpl = ch?.templateId ?? ''
    if (tpl === 'charge_sessions') return <EnergyNormalizationModel />
    if (tpl === 'stations') return (
      <EnergyNormalizationModel
        fetchModel={getStationsModel} queryKey="stations-model"
        title="Модель данных · станции ЭЗС" subtitle={STATIONS_SUBTITLE} entityUnit="Станций"
        showPivotExport={false}
        emptyText="Нет загруженных станций. Загрузите справочник станций в канале «Справочник станций ЭЗС», затем модель данных (слои, звёздная схема, качество паспорта) отобразится здесь на реальных объектах."
      />
    )
    if (tpl === 'reestr_contracts_payments') return <ReestrNormalizationBlock />
    return <div className="px-6 py-10 text-sm text-muted-foreground">Витрина нормализации для этого канала в разработке.</div>
  }

  return (
    <CentralPanelLayout items={menu} activeKey={activeKey} onSelect={setTab}>
      <ScrollArea className="h-full">{render()}</ScrollArea>
    </CentralPanelLayout>
  )
}
