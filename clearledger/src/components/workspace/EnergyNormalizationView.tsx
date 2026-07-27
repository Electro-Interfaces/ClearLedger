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
import { usePaymentDisciplineSummary, useReestrModel, useDispenseRecon } from '@/hooks/useReferences'
import { getSpaceDataModel } from '@/services/spaceObjectsService'
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

/* ── РЕАЛЬНЫЙ блок: нормализация канала реестров «Энергоснабжение и аренда ЭЗС».
   Тот же принцип, что у остальных каналов: L1 RAW (файлы-потоки) → сопряжение со
   справочником объектов (конформная размерность, клеймо _match в сырье) →
   L2-сущности (контрагенты / договоры / платёжная дисциплина / объёмы+тарифы). ── */
function ReestrNormalizationBlock() {
  const q = useReestrModel()
  const m = q.data
  if (q.isLoading) {
    return <div className="px-6 py-10 text-sm text-muted-foreground">Загрузка модели нормализации…</div>
  }
  if (!m || m.streams.every((s) => s.l1Rows === 0)) {
    return <div className="px-6 py-10 text-sm text-muted-foreground">Реестры ещё не загружены — нормализовать нечего. Загрузите файлы в канале «Энергоснабжение и аренда ЭЗС».</div>
  }
  const l1Total = m.streams.reduce((a, s) => a + s.l1Rows, 0)
  const resolvedTotal = m.streams.reduce((a, s) => a + s.resolved, 0)
  const orphanTotal = m.streams.reduce((a, s) => a + s.orphans, 0)
  const importantOrphans = m.orphans.filter((o) => (o.kwh ?? 0) > 0)
  return (
    <div className="space-y-5 px-6 py-6">
      <Card className="border-l-2 border-l-primary"><CardContent className="space-y-3 pt-5">
        <div className="flex items-center gap-2">
          <div className="text-sm font-medium">Нормализация: реестры «Энергоснабжение и аренда ЭЗС»</div>
          <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Строк L1 (файлы-потоки)" value={fmtN(l1Total)} />
          <Kpi label="Сопряжено с объектами" value={`${fmtN(resolvedTotal)} (${l1Total ? Math.round(resolvedTotal / l1Total * 100) : 0}%)`} sub="справочник объектов — хаб" />
          <Kpi label="Сироты (без объекта)" value={fmtN(orphanTotal)} sub={importantOrphans.length ? `${importantOrphans.length} с объёмами э/э!` : 'склады/демонтаж — норма'} />
          <Kpi label="Объектов с данными реестра" value={`${fmtN(m.objectsLinked)} из ${fmtN(m.objectsTotal)}`} />
        </div>

        {/* Потоки: L1 → сопряжение (тот же конвейер, что у сессий/станций) */}
        <Table><TableHeader><TableRow>
          <TableHead>Поток (файл)</TableHead>
          <TableHead className="text-right">Строк L1</TableHead>
          <TableHead className="text-right">Сопряжено</TableHead>
          <TableHead className="text-right">Сироты</TableHead>
        </TableRow></TableHeader><TableBody>
          {m.streams.map((s) => (
            <TableRow key={s.stream}>
              <TableCell className="font-medium">{s.label}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(s.l1Rows)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {fmtN(s.resolved)} <span className={pctCls(s.l1Rows ? s.resolved / s.l1Rows * 100 : 0)}>({s.l1Rows ? Math.round(s.resolved / s.l1Rows * 100) : 0}%)</span>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {s.orphans ? <span className="text-amber-600 dark:text-amber-400">{fmtN(s.orphans)}</span> : '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody></Table>
        <p className="text-xs text-muted-foreground/70">
          Ключ сопряжения: № по БУ → станция № объекта, добор по зав. номеру / OCPP ID / координатам.
          «Сводная» — якорный поток: она прописывает объектам № БУ и № ZOI-1, по которым затем
          резолвятся аренда и тарифы (порядок каскада соблюдается кнопкой «Обработать все»).
        </p>
      </CardContent></Card>

      {/* L2-сущности, которые наполняет канал (разбивка нормализации по сущностям) */}
      <Card><CardContent className="space-y-3 pt-5">
        <div className="flex items-center gap-2">
          <div className="text-sm font-medium">L2-сущности канала</div>
          <span className="text-xs text-muted-foreground/70">потоки наполняют общие справочники и факты — их же используют другие каналы</span>
        </div>
        <Table><TableHeader><TableRow>
          <TableHead>Сущность (L2)</TableHead>
          <TableHead className="text-right">Записей</TableHead>
          <TableHead>Состав</TableHead>
          <TableHead>Потребители</TableHead>
        </TableRow></TableHeader><TableBody>
          {m.entities.map((e) => {
            const consumers: Record<string, string> = {
              counterparties: 'НСИ · Корпоратив · Аренда',
              contracts: 'НСИ · ось «договор ↔ точки»',
              settlements: 'Энергозакупка · Аренда · Дебиторка',
              periods: 'Энергозакупка · (буд.) Баланс ЭЗС: вход vs отпуск из сессий',
              dispense: 'История отпуска 2024–2025 · Сверка со сводной (ниже)',
            }
            return (
              <TableRow key={e.key}>
                <TableCell className="font-medium">{e.label}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtN(e.records)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{e.note || '—'}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{consumers[e.key] || '—'}</TableCell>
              </TableRow>
            )
          })}
        </TableBody></Table>
      </CardContent></Card>

      {/* Сверка отпуска: ручная сводная контрагента ↔ транзакционные сессии */}
      <DispenseReconBlock />

      {/* Сироты: строки реестров без объекта — рабочий список на дозагрузку станций */}
      {m.orphans.length > 0 && (
        <Card><CardContent className="space-y-3 pt-5">
          <div className="flex items-center gap-2">
            <div className="text-sm font-medium">Сироты — строки без объекта в справочнике</div>
            <Badge variant="secondary" className="bg-amber-500/15 text-[10px] text-amber-600 dark:text-amber-400">{fmtN(orphanTotal)}</Badge>
            <span className="text-xs text-muted-foreground/70">с объёмами э/э — сверху; лечится загрузкой свежего справочника станций + «Обработать все»</span>
          </div>
          <div className="max-h-[320px] overflow-auto rounded-md border border-border/40">
            <Table><TableHeader className="sticky top-0 bg-card"><TableRow>
              <TableHead>№ БУ</TableHead><TableHead>№ ZOI-1</TableHead>
              <TableHead>Наименование</TableHead><TableHead>Поток</TableHead>
              <TableHead className="text-right">Σ э/э, кВт·ч</TableHead>
            </TableRow></TableHeader><TableBody>
              {m.orphans.map((o, i) => (
                <TableRow key={i}>
                  <TableCell className="font-medium tabular-nums">{o.bu || '—'}</TableCell>
                  <TableCell className="tabular-nums text-muted-foreground">{o.zoi || '—'}</TableCell>
                  <TableCell className="max-w-[340px] truncate text-xs text-muted-foreground">{o.name || '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{o.stream}</TableCell>
                  <TableCell className={`text-right tabular-nums ${(o.kwh ?? 0) > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>{o.kwh != null ? fmtN(Math.round(o.kwh)) : '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody></Table>
          </div>
        </CardContent></Card>
      )}
    </div>
  )
}

/* ── Сверка отпуска: сводная выработка контрагента ↔ зарядные сессии.
   Пересечение периодов (2026+) — тест достоверности ОБОИХ контуров: ручной
   Excel-свод и транзакционная выгрузка ПК. Стабильное расхождение по станции —
   сигнал дубля объекта или недоучёта в одном из рядов. ── */
function DispenseReconBlock() {
  const q = useDispenseRecon()
  const r = q.data
  if (!r || r.months.length === 0) return null
  const dCls = (pct: number | null) =>
    pct == null ? 'text-muted-foreground'
      : Math.abs(pct) <= 3 ? 'text-emerald-600 dark:text-emerald-400'
      : Math.abs(pct) <= 10 ? 'text-amber-600 dark:text-amber-400'
      : 'text-red-600 dark:text-red-400'
  return (
    <Card><CardContent className="space-y-3 pt-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-sm font-medium">Сверка отпуска: сводная контрагента ↔ зарядные сессии</div>
        <Badge className="bg-blue-500/15 text-[10px] text-blue-600 dark:text-blue-400">качество данных</Badge>
        <span className="ml-auto text-[11px] text-muted-foreground">
          сводная: {r.filePeriodFrom?.slice(0, 7)} — {r.filePeriodTo?.slice(0, 7)}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Помесячные кВт·ч из ручного свода (слот «Сводная выработка») против суммы зарядных
        сессий — на пересечении периодов. Расхождение — сигнал недоучёта в одном из контуров
        или дубля станции в справочнике.
      </p>
      <Table><TableHeader><TableRow>
        <TableHead>Месяц</TableHead>
        <TableHead className="text-right">Сводная, кВт·ч</TableHead>
        <TableHead className="text-right">Сессии, кВт·ч</TableHead>
        <TableHead className="text-right">Δ, кВт·ч</TableHead>
        <TableHead className="text-right">Δ, %</TableHead>
        <TableHead className="text-right">Станций (свод/сессии)</TableHead>
      </TableRow></TableHeader><TableBody>
        {r.months.map((m) => (
          <TableRow key={m.period}>
            <TableCell className="font-medium tabular-nums">{m.period.slice(0, 7)}</TableCell>
            <TableCell className="text-right tabular-nums">{fmtN(Math.round(m.fileKwh))}</TableCell>
            <TableCell className="text-right tabular-nums">{fmtN(Math.round(m.sessionsKwh))}</TableCell>
            <TableCell className={`text-right tabular-nums ${dCls(m.deltaPct)}`}>{fmtN(Math.round(m.deltaKwh))}</TableCell>
            <TableCell className={`text-right tabular-nums ${dCls(m.deltaPct)}`}>
              {m.deltaPct != null && Math.abs(m.deltaPct) <= 1000 ? `${m.deltaPct > 0 ? '+' : ''}${m.deltaPct}%` : '—'}
            </TableCell>
            <TableCell className="text-right tabular-nums text-muted-foreground">{m.fileStations} / {m.sessStations}</TableCell>
          </TableRow>
        ))}
      </TableBody></Table>
      {r.topStations.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            Станции с наибольшим расхождением ({r.topStations.length})
          </summary>
          <div className="mt-2 max-h-[260px] overflow-auto rounded-md border border-border/40">
            <Table><TableHeader className="sticky top-0 bg-card"><TableRow>
              <TableHead>Станция</TableHead>
              <TableHead className="text-right">Сводная, кВт·ч</TableHead>
              <TableHead className="text-right">Сессии, кВт·ч</TableHead>
              <TableHead className="text-right">Δ</TableHead>
            </TableRow></TableHeader><TableBody>
              {r.topStations.map((s) => (
                <TableRow key={s.locationId}>
                  <TableCell className="max-w-[300px] truncate">{s.name}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtN(Math.round(s.fileKwh))}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtN(Math.round(s.sessionsKwh))}</TableCell>
                  <TableCell className={`text-right tabular-nums ${Math.abs(s.deltaKwh) > 5000 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                    {fmtN(Math.round(s.deltaKwh))}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody></Table>
          </div>
        </details>
      )}
    </CardContent></Card>
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
  if (!lk || (lk.objects_total ?? lk.objects) === 0) return null
  const objTotal = lk.objects_total ?? lk.objects
  return (
    <Card><CardContent className="space-y-3 overflow-x-auto pt-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-sm font-medium">Связь каналов по станции</div>
        <Badge className="bg-blue-500/15 text-[10px] text-blue-600 dark:text-blue-400">конформная размерность</Badge>
        <span className="ml-auto text-[11px] text-muted-foreground">ключ: {lk.key_label}</span>
      </div>
      <p className="text-xs text-muted-foreground">
        Объект-станция (<span className="font-mono">service_locations</span>) — общий хаб; каналы-факты ссылаются на него.
        Объектов <b className="text-foreground">{fmtN(objTotal)}</b> · в сети <b className="text-foreground">{fmtN(lk.objects)}</b>
        {(lk.objects_test ?? 0) > 0 && <> · тест <b className="text-foreground">{fmtN(lk.objects_test ?? 0)}</b></>}
        {(lk.objects_decommissioned ?? 0) > 0 && <> · выведено <b className="text-foreground">{fmtN(lk.objects_decommissioned ?? 0)}</b></>}
        {' · '}с типизированным паспортом <b className="text-foreground">{fmtN(lk.objects_enriched)}</b> · без сессий <b className="text-foreground">{fmtN(lk.objects_without_sessions)}</b>.
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

/* ── База пространства: ЧТО лежит в нормализованном слое целиком.
   Каналы отвечают на вопрос «что приехало файлом», а этот таб — «из чего состоит база»:
   там же контрагенты, договоры и весь проектный контур, которые файлом не приезжают.
   Столбец «Связь» показывает долг схемы: где роль до сих пор хранится строкой, а не
   ссылкой на карточку контрагента — такие записи в общий реестр не сводятся. ── */
function SpaceDataModelBlock() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['space-data-model', companyId],
    queryFn: () => getSpaceDataModel(companyId),
    enabled: !!companyId, staleTime: 60_000,
  })
  const m = q.data
  if (q.isLoading) {
    return <div className="px-6 py-10 text-sm text-muted-foreground">Загрузка состава базы…</div>
  }
  if (!m) {
    return <div className="px-6 py-10 text-sm text-muted-foreground">Состав базы недоступен.</div>
  }
  return (
    <div className="space-y-5 px-6 py-6">
      <div>
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-primary" />
          <h1 className="text-xl font-semibold">Нормализованная база пространства</h1>
          <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
        </div>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Из чего состоит общий слой данных компании: сущности, чем наполняются, кто их
          потребляет. Наполняются не только файловыми каналами — контрагенты и договоры
          приходят и из корпоративной зарядки, объекты ведутся в «Управлении», проектный
          контур целиком ведётся руками.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Сущностей в базе" value={`${m.totals.filled} / ${m.totals.entities}`} sub="с данными / всего" />
        <Kpi label="Записей всего" value={fmtN(m.totals.records)} sub="по всем сущностям" />
        <Kpi label="Незакрытых связей" value={fmtN(m.totals.gaps)} sub="строкой вместо ссылки" />
        <Kpi label="Доменов" value={fmtN(m.domains.length)} sub="разрезов базы" />
      </div>

      {m.domains.map((d) => (
        <Card key={d.key}><CardContent className="overflow-x-auto pt-5">
          <div className="mb-3 flex items-center gap-2">
            <div className="text-sm font-medium">{d.label}</div>
            <span className="text-xs text-muted-foreground">
              {fmtN(d.entities.reduce((a, e) => a + e.records, 0))} записей
            </span>
          </div>
          <Table className="min-w-[900px]">
            <TableHeader><TableRow>
              <TableHead>Сущность</TableHead>
              <TableHead className="text-right">Записей</TableHead>
              <TableHead>Чем наполняется</TableHead>
              <TableHead>Кто потребляет</TableHead>
              <TableHead>Связь</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {d.entities.map((e) => (
                <TableRow key={e.key} className={e.records === 0 ? 'opacity-50' : undefined}>
                  <TableCell className="font-medium">
                    {e.label}
                    <div className="font-mono text-[10px] text-muted-foreground">{e.table}</div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{e.records ? fmtN(e.records) : '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{e.sources}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{e.consumers}</TableCell>
                  <TableCell className="text-xs">
                    <div className="text-muted-foreground">{e.link}</div>
                    {e.gap != null && (
                      <div className="text-amber-600 dark:text-amber-400">
                        {fmtN(e.gap)} — {e.gapLabel}
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent></Card>
      ))}

      <p className="px-1 text-[11px] text-muted-foreground/70">
        Жёлтым — записи, где связь ещё не материализована: подрядчик проекта, поставщик
        оборудования и сетевая организация хранятся текстом, поэтому в общем реестре
        контрагентов их не видно. Пока это так, одно юрлицо живёт в базе дважды —
        карточкой в договорах и строкой в проекте.
      </p>
    </div>
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
    const items: CentralMenuItem[] = [
      { key: 'base', label: 'База пространства' },
      { key: 'overview', label: 'Обзор каналов' },
    ]
    for (const ch of normChannels) items.push({ key: ch.id, label: ch.name })
    return items
  }, [normChannels])

  // Первым открывается состав базы, а не каналы: каналов три, а сущностей в базе
  // втрое больше — начинать разговор о данных с трёх файлов вводило в заблуждение.
  const [tab, setTab] = useState('base')
  const activeKey = menu.some((mi) => mi.key === tab) ? tab : 'base'

  function render() {
    if (activeKey === 'base') return <SpaceDataModelBlock />
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
