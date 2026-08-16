/**
 * «Данные» компании без объектов (профиль `office`).
 *
 * Устроено как «Нормализация» сетевых пространств (`EnergyNormalizationView`): раздел
 * приложения живёт в РЕЛЬСЕ, а его пункты — во ВТОРОЙ колонке. Порядок тот же:
 *   • «База пространства» — модель данных и сущности нормализованного слоя;
 *   • «Качество данных» — постоянный экран проверок, а не итог разбора;
 *   • «Обзор источников» — что приехало (у сетевых это «Обзор каналов»);
 *   • дальше пункт на КАЖДЫЙ набор данных — витрина его модели.
 *
 * Отличается предметная область: там каналы приёма файлов, здесь один источник
 * (бухгалтерия клиента) и наборы, которые из него приехали.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Database, FileStack, Info, Network, XCircle } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { getCompanyProfile, getDataset, getQuality, getSources, type QualityCheck }
  from '@/services/booksService'
import { getSpaceDataModel } from '@/services/spaceObjectsService'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { ScrollArea } from '@/components/ui/scroll-area'
import { OfficeDataModel } from './OfficeDataModel'
import { cn } from '@/lib/utils'

const num = new Intl.NumberFormat('ru-RU')

const STATUS: Record<QualityCheck['status'], { icon: typeof CheckCircle2; cls: string; label: string }> = {
  ok: { icon: CheckCircle2, cls: 'border-emerald-500/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400', label: 'сходится' },
  warn: { icon: AlertTriangle, cls: 'border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400', label: 'требует внимания' },
  error: { icon: XCircle, cls: 'border-red-500/40 bg-red-500/5 text-red-700 dark:text-red-400', label: 'ошибка' },
  info: { icon: Info, cls: 'border-blue-500/40 bg-blue-500/5 text-blue-700 dark:text-blue-400', label: 'к сведению' },
}

// Наборы данных = пункты меню после общих трёх, как каналы приёма у сетевых профилей.
const DATASETS: { key: string; label: string }[] = [
  { key: 'entries', label: 'Проводки регистра' },
  { key: 'docs', label: 'Первичные документы' },
  { key: 'counterparties', label: 'Контрагенты' },
  { key: 'nomenclature', label: 'Номенклатура' },
  { key: 'refs', label: 'Справочники учёта' },
]

// Источник перечисляет наборы ИМЕНАМИ ТАБЛИЦ (`gl_entries`), витрины живут под
// своими ключами (`entries`). Пересечения не было вовсе: карточка источника
// показывала одни названия, а список ссылок под ней — другие пять, и читалось это
// как два разных состава данных. Карта сводит их обратно в один.
const DATASET_BY_TABLE: Record<string, string> = {
  gl_entries: 'entries',
}

const MENU: CentralMenuItem[] = [
  { key: 'base', label: 'База пространства' },
  { key: 'quality', label: 'Качество данных' },
  { key: 'overview', label: 'Обзор источников' },
  ...DATASETS.map((d) => ({ key: d.key, label: d.label })),
]

export function OfficeDataView() {
  const [tab, setTab] = useState('overview')
  return (
    <CentralPanelLayout items={MENU} activeKey={tab} onSelect={setTab}>
      <ScrollArea className="h-full">
        <div className="p-4">
          {tab === 'overview' && <SourcesTab onOpen={setTab} />}
          {tab === 'base' && <ModelTab />}
          {tab === 'quality' && <QualityTab />}
          {DATASETS.some((d) => d.key === tab) && <DatasetTab dsKey={tab} />}
        </div>
      </ScrollArea>
    </CentralPanelLayout>
  )
}

/** Витрина одного набора: объём, ключ связи, заполнение полей, из чего состоит. */
function DatasetTab({ dsKey }: { dsKey: string }) {
  const { companyId } = useCompany()
  const q = useQuery({ queryKey: ['books', 'dataset', companyId, dsKey],
    queryFn: () => getDataset(companyId, dsKey) })
  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="text-sm text-muted-foreground">Загрузка…</div>
  const d = q.data

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-medium">{d.label}</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          <span className="font-mono">{d.table}</span> · ключ связи: {d.link}
          {d.period.from && <> · период {d.period.from} — {d.period.to}</>}
        </p>
      </div>

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Записей в L2" value={num.format(d.records)} />
        {d.fields.slice(0, 3).map((f) => (
          <MetricTile key={f.field} label={f.label} value={`${f.fill_pct}%`}
            hint={`${num.format(f.distinct)} значений`}
            tone={f.fill_pct < 80 ? 'warning' : undefined} />
        ))}
      </div>

      {/* Проводки — центр модели: у них полная витрина со слоями и звездой. */}
      {dsKey === 'entries' && <OfficeDataModel />}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground">
              Заполнение полей
            </div>
            <div className="divide-y border-t">
              {d.fields.map((f) => (
                <div key={f.field} className="flex items-center justify-between gap-3 px-3 py-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm">{f.label}</div>
                    <div className="font-mono text-[10px] text-muted-foreground">{f.field}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
                      <div className={cn('h-full rounded-full',
                        f.fill_pct < 80 ? 'bg-amber-500/70' : 'bg-primary/70')}
                        style={{ width: `${f.fill_pct}%` }} />
                    </div>
                    <span className="w-11 text-right text-xs tabular-nums text-muted-foreground">
                      {f.fill_pct}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground">
              Из чего состоит
            </div>
            <div className="divide-y border-t">
              {d.top.map((t) => (
                <div key={t.label} className="flex items-baseline justify-between px-3 py-1.5 text-sm">
                  <span className="truncate">{t.label}</span>
                  <span className="tabular-nums text-muted-foreground">{num.format(t.count)}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

/**
 * Паспорт компании — то же, что читает агент первым навыком.
 *
 * Стоит над источниками, потому что отвечает на вопрос, который человек задаёт
 * раньше остальных: что за компания, какой режим, за какой период данные и чему
 * верить. Свой запрос, а не сборка из чужих ответов: одна цифра — один расчёт.
 */
function ProfileCard() {
  const { companyId } = useCompany()
  const q = useQuery({ queryKey: ['books', 'profile', companyId],
    queryFn: () => getCompanyProfile(companyId), enabled: !!companyId })
  if (!q.data) return null
  const d = q.data
  const ru = (iso: string | null) => (iso ? new Date(iso + 'T00:00:00').toLocaleDateString('ru') : '—')

  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <div>
            <div className="font-medium">{d.company.name}</div>
            <div className="text-xs text-muted-foreground">
              ИНН {d.company.inn ?? '—'}
              {d.organizations.length > 1 && <> · юрлиц в учёте: {d.organizations.length}</>}
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            {d.taxMode && (
              <span className="rounded-full border px-2 py-0.5">{d.taxMode}</span>
            )}
            <span className="rounded-full border px-2 py-0.5">
              {d.vat ? 'с НДС' : 'без НДС'}
            </span>
            {d.commission && (
              <span className="rounded-full border px-2 py-0.5" title={
                'Часть продаж — товар комитента: покупателю выставлен наш документ, ' +
                'а выручка чужая и на 90.01.1 не попадает'}>
                комиссионная торговля
              </span>
            )}
          </div>
        </div>

        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <MetricTile label="Данные за период"
            value={`${ru(d.data.from)} — ${ru(d.data.to)}`}
            valueClass="whitespace-normal text-lg sm:text-2xl"
            hint={`${num.format(d.data.entries)} проводок`} />
          <MetricTile label="Периодов закрыто"
            value={`${d.data.periodsClosed} из ${d.data.periodsTotal}`}
            valueClass="text-lg sm:text-2xl"
            hint={d.data.lastClosed ? `последний — ${ru(d.data.lastClosed)}` : 'закрытых нет'} />
          <MetricTile label="Остатки на дату" value={ru(d.data.balanceAsOf)}
            valueClass="text-lg sm:text-2xl"
            hint="срез сальдо из источника" />
          <MetricTile label="Замечаний к данным"
            value={`${d.quality.problems} из ${d.quality.checks}`}
            valueClass="text-lg sm:text-2xl"
            tone={d.quality.problems ? 'warning' : 'success'}
            hint={d.quality.worst.map((w) => w.label).slice(0, 2).join(' · ') || 'проверки сходятся'} />
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          {Object.entries(d.volumes).map(([k, v]) => (
            <span key={k}>{k}: <span className="tabular-nums">{num.format(v)}</span></span>
          ))}
          <span>контрагентов с движением: <span className="tabular-nums">
            {num.format(d.activeCounterparties)}</span></span>
        </div>
      </CardContent>
    </Card>
  )
}

function SourcesTab({ onOpen }: { onOpen?: (key: string) => void }) {
  const { companyId } = useCompany()
  const q = useQuery({ queryKey: ['books', 'sources', companyId], queryFn: () => getSources(companyId) })
  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="text-sm text-muted-foreground">Загрузка…</div>

  return (
    <div className="space-y-3">
      <ProfileCard />
      {q.data.sources.map((s) => (
        <Card key={s.kind}>
          <CardContent className="p-4 space-y-3">
            <div className="flex items-start gap-3">
              <div className="rounded-lg bg-primary/10 p-2"><Database className="size-5 text-primary" /></div>
              <div>
                <div className="font-medium">{s.name}</div>
                <div className="text-xs text-muted-foreground">
                  {s.periodFrom
                    ? <>период данных {s.periodFrom} — {s.periodTo}</>
                    : 'данные не загружены'}
                  {s.loadedAt && <> · загружено {new Date(s.loadedAt).toLocaleString('ru')}</>}
                </div>
              </div>
            </div>
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-3">
              {s.datasets.map((d) => {
                const ds = DATASET_BY_TABLE[d.key]
                const tile = <MetricTile label={d.label} value={num.format(d.records)}
                  hint={ds && onOpen ? 'открыть витрину' : undefined} />
                return ds && onOpen
                  ? <button key={d.key} type="button" className="text-left"
                      onClick={() => onOpen(ds)}>{tile}</button>
                  : <div key={d.key}>{tile}</div>
              })}
            </div>

            {/* Документы и справочники — списком по видам, а не одним числом:
                срез компании читается именно по составу («390 счетов покупателю,
                485 регламентных операций»), а «1500 документов» не говорит ничего. */}
            {/* Наборы данных — с переходом в витрину, как канал у сетевых. */}
            {onOpen && (
              <div className="rounded-lg border divide-y">
                {DATASETS.map((d) => (
                  <button key={d.key} onClick={() => onOpen(d.key)}
                    className="flex w-full items-baseline justify-between px-3 py-2 text-left text-sm hover:bg-muted/40">
                    <span>{d.label}</span>
                    <span className="text-xs text-muted-foreground">открыть витрину →</span>
                  </button>
                ))}
              </div>
            )}

            {!!s.documents?.length && (
              <div>
                <div className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
                  Документы по видам
                </div>
                <div className="rounded-lg border divide-y">
                  {s.documents.map((d) => (
                    <div key={d.key} className="flex items-baseline justify-between px-3 py-1.5 text-sm">
                      <span>{d.label}</span>
                      <span className="tabular-nums text-muted-foreground">{num.format(d.records)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!!s.references?.length && (
              <div>
                <div className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
                  Справочники
                </div>
                <div className="rounded-lg border divide-y">
                  {s.references.map((r) => (
                    <div key={r.key} className="flex items-baseline justify-between px-3 py-1.5 text-sm">
                      <span>{r.label}</span>
                      <span className="tabular-nums text-muted-foreground">{num.format(r.records)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
      <p className="text-xs text-muted-foreground">
        Пока источник один — разовая выгрузка бухгалтерии. Следующий шаг: коннектор к живой
        базе, тогда закрытые периоды будут приезжать сами, а открытые обновляться.
      </p>
    </div>
  )
}

function ModelTab() {
  const { companyId } = useCompany()
  const q = useQuery({ queryKey: ['space', 'data-model', companyId], queryFn: () => getSpaceDataModel(companyId) })
  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="text-sm text-muted-foreground">Загрузка…</div>

  const t = q.data.totals
  return (
    <div className="space-y-4">
      {/* Модель данных — то же, что «Нормализация» показывает у сетевых пространств:
          слои приёма, звёздная схема, качество. Ниже — карта сущностей базы. */}
      <OfficeDataModel />

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Сущностей" value={num.format(t.entities)} />
        <MetricTile label="Записей" value={num.format(t.records)} />
        <MetricTile label="Заполнено" value={`${t.filled} из ${t.entities}`}
          tone={!t.entities ? undefined : t.filled === t.entities ? 'success' : 'warning'} />
        <MetricTile label="Разрывов связей" value={num.format(t.gaps)}
          hint="связь записана строкой, а не ссылкой" />
      </div>

      {q.data.domains.map((d) => (
        <Card key={d.key}>
          <CardContent className="p-0">
            <div className="flex items-center gap-2 border-b px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground">
              <Network className="size-3.5" /> {d.label}
            </div>
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr className="border-b">
                  <th className="px-3 py-1.5 text-left font-normal">Сущность</th>
                  <th className="px-3 py-1.5 text-right font-normal">Записей</th>
                  <th className="px-3 py-1.5 text-left font-normal">Чем наполняется</th>
                  <th className="px-3 py-1.5 text-left font-normal">Ключ связи</th>
                </tr>
              </thead>
              <tbody>
                {d.entities.map((e) => (
                  <tr key={e.key} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-3 py-1.5">
                      {e.label}
                      <span className="block text-[10px] text-muted-foreground">{e.table}</span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {num.format(e.records)}
                      {!!e.gap && (
                        <span className="block text-[10px] text-amber-600 dark:text-amber-400">
                          {num.format(e.gap)} · {e.gapLabel}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-xs text-muted-foreground">{e.sources}</td>
                    <td className="px-3 py-1.5 text-xs text-muted-foreground">{e.link}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function QualityTab() {
  const { companyId } = useCompany()
  const q = useQuery({ queryKey: ['books', 'quality', companyId], queryFn: () => getQuality(companyId) })
  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="text-sm text-muted-foreground">Загрузка…</div>

  return (
    <div className="space-y-4">
      <div className="grid gap-3 grid-cols-3">
        <MetricTile label="Сходится" value={num.format(q.data.ok)} tone="success" />
        <MetricTile label="Требует внимания" value={num.format(q.data.warnings)}
          tone={q.data.warnings ? 'warning' : undefined} higherIsBetter={false} />
        <MetricTile label="Ошибок" value={num.format(q.data.errors)}
          tone={q.data.errors ? 'danger' : undefined} higherIsBetter={false} />
      </div>

      <div className="space-y-2">
        {q.data.checks.map((c) => {
          const s = STATUS[c.status]
          return (
            <div key={c.key}
              className={cn('flex items-start gap-3 rounded-lg border p-3', s.cls)}>
              <s.icon className="mt-0.5 size-4 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm font-medium">{c.label}</span>
                  <span className="text-sm tabular-nums">{c.value}</span>
                </div>
                <p className="mt-0.5 text-xs opacity-80">{c.hint}</p>
              </div>
            </div>
          )
        })}
      </div>

      <p className="flex items-start gap-2 text-xs text-muted-foreground">
        <FileStack className="mt-0.5 size-3.5 shrink-0" />
        Проверки идут по бухгалтерии-эталону: она источник, с которым сверяется всё
        остальное. Главная — выручка документов против оборота 90.01.1.
      </p>
    </div>
  )
}
