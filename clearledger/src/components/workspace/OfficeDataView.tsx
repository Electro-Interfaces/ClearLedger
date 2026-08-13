/**
 * «Данные» для компании без объектов (профиль `office`).
 *
 * Данные — первый слой, с которого всё начинается: пока не видно, ОТКУДА цифры и
 * сходятся ли они между собой, витринам верить нельзя. До этого офисный профиль
 * попадал в общую панель нормализации и получал конвейер, правила и агентов из
 * топливного контура — с честной плашкой «демонстрационные данные», но всё равно
 * не про свою жизнь.
 *
 * Три вопроса, три раздела:
 *   Источники — что и когда приехало (сейчас выгрузка бухгалтерии, дальше коннектор);
 *   База пространства — какие сущности живут в нормализованном слое и где разрывы;
 *   Качество — сходятся ли данные сами с собой и что требует решения.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Database, FileStack, Info, Network, XCircle } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { getQuality, getSources, type QualityCheck } from '@/services/booksService'
import { getSpaceDataModel } from '@/services/spaceObjectsService'
import { cn } from '@/lib/utils'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'

const num = new Intl.NumberFormat('ru-RU')

const MENU: CentralMenuItem[] = [
  { key: 'sources', label: 'Источники' },
  { key: 'model', label: 'База пространства' },
  { key: 'quality', label: 'Качество' },
]

const STATUS: Record<QualityCheck['status'], { icon: typeof CheckCircle2; cls: string; label: string }> = {
  ok: { icon: CheckCircle2, cls: 'border-emerald-500/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400', label: 'сходится' },
  warn: { icon: AlertTriangle, cls: 'border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400', label: 'требует внимания' },
  error: { icon: XCircle, cls: 'border-red-500/40 bg-red-500/5 text-red-700 dark:text-red-400', label: 'ошибка' },
  info: { icon: Info, cls: 'border-blue-500/40 bg-blue-500/5 text-blue-700 dark:text-blue-400', label: 'к сведению' },
}

export function OfficeDataView() {
  const [tab, setTab] = useState('sources')
  return (
    <CentralPanelLayout items={MENU} activeKey={tab} onSelect={setTab}>
      <div className="h-full overflow-y-auto p-4">
        {tab === 'sources' && <SourcesTab />}
        {tab === 'model' && <ModelTab />}
        {tab === 'quality' && <QualityTab />}
      </div>
    </CentralPanelLayout>
  )
}

function SourcesTab() {
  const { companyId } = useCompany()
  const q = useQuery({ queryKey: ['books', 'sources', companyId], queryFn: () => getSources(companyId) })
  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="text-sm text-muted-foreground">Загрузка…</div>

  return (
    <div className="space-y-3">
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
              {s.datasets.map((d) => (
                <MetricTile key={d.key} label={d.label} value={num.format(d.records)} />
              ))}
            </div>

            {/* Документы и справочники — списком по видам, а не одним числом:
                срез компании читается именно по составу («390 счетов покупателю,
                485 регламентных операций»), а «1500 документов» не говорит ничего. */}
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
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Сущностей" value={num.format(t.entities)} />
        <MetricTile label="Записей" value={num.format(t.records)} />
        <MetricTile label="Заполнено" value={`${t.filled} из ${t.entities}`}
          tone={t.filled === t.entities ? 'success' : 'warning'} />
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
