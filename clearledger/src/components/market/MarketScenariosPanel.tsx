/**
 * «Сценарии» (docs/MARKET-ROADMAP.md §9, этап 5) — замкнутый цикл продукта:
 * гипотеза → действие → замер → вывод.
 *
 * Главное здесь не форма, а контрольная группа. Рост сессий после снижения цены с
 * тем же успехом объясняется погодой и отпусками; отличить своё действие от фона
 * можно только сравнением с похожими объектами, которых действие не касалось.
 * Поэтому планировщик подбирает контроль сам и ЗАРАНЕЕ говорит, читаемым ли будет
 * замер: если группы расходятся ещё до вмешательства, честнее узнать это сейчас.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { useCompany } from '@/contexts/CompanyContext'
import { listSpaceObjects } from '@/services/spaceObjectsService'
import {
  createMarketScenario, listMarketScenarios, measureMarketScenario,
  suggestScenarioControl, type MarketScenario,
} from '@/services/marketService'

const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

const ВИДЫ = [
  { k: 'plan', label: 'Планировщик' },
  { k: 'running', label: 'В работе' },
  { k: 'done', label: 'Итоги' },
] as const

const ACTION_LABEL: Record<string, string> = {
  tariff: 'тариф',
  build: 'стройка',
  promo: 'акция',
  schedule: 'режим работы',
  partnership: 'партнёрство',
}

const VERDICT_LABEL: Record<string, string> = {
  worked: 'сработало',
  no_effect: 'без эффекта',
  backfired: 'сделало хуже',
  unclear: 'не ясно',
}

function pct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${nf1.format(v)} п.п.`
}

/** Сценарий в списке: ожидание рядом с фактом — иначе итог не с чем сравнить. */
function ScenarioCard({ row, onMeasure, measuring }: {
  row: MarketScenario; onMeasure: (id: string) => void; measuring: boolean
}) {
  const m = row.measure
  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="font-headline text-sm font-semibold">{row.title}</span>
          <span className="text-xs text-muted-foreground">
            {ACTION_LABEL[row.actionKind] ?? row.actionKind}
            {row.startedOn ? ` · действие с ${row.startedOn}` : ''}
            {row.checkOn ? ` · замер ${row.checkOn}` : ''}
          </span>
        </div>
        {row.description && <p className="text-xs text-muted-foreground">{row.description}</p>}
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
          <span>объектов действия: <span className="tabular-nums">{row.scope.length}</span></span>
          <span className={row.control.length === 0 ? 'text-warning' : ''}>
            контрольная группа: <span className="tabular-nums">{row.control.length}</span>
            {row.control.length === 0 && ' — без неё эффект не отличить от сезона'}
          </span>
          {row.ownerName && <span className="text-muted-foreground">ведёт: {row.ownerName}</span>}
        </div>

        {m ? (
          <div className="rounded-md border border-border bg-muted/30 p-3 text-xs">
            <div className="mb-1 font-medium">
              Замер {m.measuredOn}: {VERDICT_LABEL[m.verdict ?? 'unclear'] ?? m.verdict}
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-1">
              <span>разность разностей по выручке: <b className="tabular-nums">{pct(m.didRevenue)}</b></span>
              <span>по сессиям: <span className="tabular-nums">{pct(m.didSessions)}</span></span>
            </div>
            <div className="mt-1 text-muted-foreground">
              объекты действия {pct(m.fact?.scope?.revenuePct)} выручки, контроль{' '}
              {pct(m.fact?.control?.revenuePct)} — разница и есть эффект.
              {m.note ? ` ${m.note}` : ''}
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" disabled={!row.startedOn || measuring}
              onClick={() => onMeasure(row.id)}>
              {measuring && <Loader2 className="mr-1 size-3.5 animate-spin" />}
              Замерить
            </Button>
            {!row.startedOn && (
              <span className="text-xs text-muted-foreground">
                нужна дата действия — от неё считаются окна до и после
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function MarketScenariosPanel() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [вид, setВид] = useState<string>('plan')
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState('tariff')
  const [startedOn, setStartedOn] = useState('')
  const [scope, setScope] = useState<string[]>([])
  const [control, setControl] = useState<string[]>([])
  const [parallel, setParallel] = useState<{ ok: boolean; note: string; gapPct: number | null } | null>(null)

  const list = useQuery({
    queryKey: ['market-scenarios', companyId],
    queryFn: () => listMarketScenarios(companyId),
    enabled: !!companyId,
  })
  const objects = useQuery({
    queryKey: ['market-our-objects', companyId],
    queryFn: () => listSpaceObjects(companyId),
    enabled: !!companyId && вид === 'plan',
  })

  const suggest = useMutation({
    mutationFn: () => suggestScenarioControl(companyId, scope),
    onSuccess: (data) => {
      setControl(data.control)
      setParallel({ ok: data.parallel.ok, note: data.parallel.note, gapPct: data.parallel.gapPct })
    },
  })
  const create = useMutation({
    mutationFn: () => createMarketScenario(companyId, {
      title, action_kind: kind, scope, control,
      started_on: startedOn || null, status: startedOn ? 'running' : 'draft',
    }),
    onSuccess: () => {
      setTitle(''); setScope([]); setControl([]); setParallel(null)
      qc.invalidateQueries({ queryKey: ['market-scenarios', companyId] })
      setВид('running')
    },
  })
  const measure = useMutation({
    mutationFn: (id: string) => measureMarketScenario(companyId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['market-scenarios', companyId] }),
  })

  const rows = list.data?.scenarios ?? []
  const running = rows.filter((r) => r.status === 'running' || r.status === 'draft')
  const done = rows.filter((r) => r.measure)
  const worked = done.filter((r) => r.measure?.verdict === 'worked').length

  const ourObjects = (objects.data ?? []).filter((o) => o.latitude != null)

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <FlaskConical className="size-4 text-primary" aria-hidden />
            {done.length === 0
              ? 'Замеренных сценариев пока нет: цикл «гипотеза → действие → замер» ещё не проходили.'
              : `Замерено ${done.length} сценариев, сработало ${worked}.`}
          </span>
          <span className="text-xs text-muted-foreground">в работе {running.length}</span>
        </CardContent>
      </Card>

      <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={setВид} />

      {вид === 'plan' && (
        <Card>
          <CardContent className="space-y-3 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Input value={title} onChange={(e) => setTitle(e.target.value)}
                placeholder="Что делаем: «поднять тариф на 1,5 ₽ в Иркутске»"
                className="h-8 w-[380px] text-xs" />
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger className="h-8 w-[160px] text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(ACTION_LABEL).map(([k, label]) => (
                    <SelectItem key={k} value={k}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input type="date" value={startedOn} onChange={(e) => setStartedOn(e.target.value)}
                className="h-8 w-[150px] text-xs" aria-label="Дата действия" />
            </div>

            <div>
              <div className="mb-1 text-xs font-medium">
                Объекты действия{scope.length > 0 && `: выбрано ${scope.length}`}
              </div>
              <div className="max-h-40 overflow-auto rounded-md border border-border p-2">
                {ourObjects.map((o) => (
                  <label key={o.id} className="flex items-center gap-2 py-0.5 text-xs">
                    <input type="checkbox" className="size-4" checked={scope.includes(o.id)}
                      onChange={(e) => setScope((prev) => e.target.checked
                        ? [...prev, o.id] : prev.filter((x) => x !== o.id))} />
                    <span className="truncate">{o.name}
                      {o.city && <span className="text-muted-foreground"> · {o.city}</span>}
                    </span>
                  </label>
                ))}
                {ourObjects.length === 0 && (
                  <p className="text-xs text-muted-foreground">Объектов с координатами нет.</p>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" disabled={scope.length === 0 || suggest.isPending}
                onClick={() => suggest.mutate()}>
                {suggest.isPending && <Loader2 className="mr-1 size-3.5 animate-spin" />}
                Подобрать контрольную группу
              </Button>
              {control.length > 0 && (
                <span className="text-xs">
                  контроль: <span className="tabular-nums">{control.length}</span> объектов
                </span>
              )}
              <Button size="sm" disabled={!title || scope.length === 0 || create.isPending}
                onClick={() => create.mutate()}>
                Завести сценарий
              </Button>
            </div>

            {parallel && (
              <p className={`text-xs ${parallel.ok ? 'text-muted-foreground' : 'text-warning'}`}>
                {parallel.ok ? 'Проверка пройдена: ' : 'Внимание: '}{parallel.note}
                {parallel.gapPct != null && ` (расхождение трендов до действия ${nf1.format(parallel.gapPct)} п.п.)`}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              Контрольная группа — объекты, которых действие не коснётся. Эффект считается
              как разница изменений: если у контроля сессии выросли так же, значит сработал
              не тариф, а сезон.
            </p>
          </CardContent>
        </Card>
      )}

      {вид !== 'plan' && (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          {(вид === 'running' ? running : done).map((row) => (
            <ScenarioCard key={row.id} row={row}
              measuring={measure.isPending && measure.variables === row.id}
              onMeasure={(id) => measure.mutate(id)} />
          ))}
          {(вид === 'running' ? running : done).length === 0 && (
            <Card><CardContent className="p-6 text-center text-xs text-muted-foreground">
              {вид === 'running'
                ? 'Запущенных сценариев нет. Заведите гипотезу в планировщике — с датой действия и контрольной группой.'
                : 'Замеров пока нет. Сценарий попадает сюда после кнопки «Замерить».'}
            </CardContent></Card>
          )}
        </div>
      )}
    </div>
  )
}
