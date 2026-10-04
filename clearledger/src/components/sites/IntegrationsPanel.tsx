/**
 * Раздел «Интеграции» продукта «Проекты»: реестр и отчёт по проектам интеграции.
 *
 * Интеграция с партнёром — проект без площадки: у неё свой маршрут, свой чек-лист
 * и свои вопросы. С кем работаем, в каком формате, сколько наших станций передано
 * партнёру и сколько его — у нас, где подтверждения устарели. Стройка эти проекты
 * в своих сводках больше не считает, а здесь они собраны отдельно.
 *
 * Проект открывается прямо в разделе (`?project=`): «назад» возвращает в реестр
 * интеграций, а не в общий список строительных проектов.
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Loader2, Plus, RefreshCw, AlertTriangle } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  getIntegrationsPortfolio, INTEGRATION_DIRECTIONS, INTEGRATION_FORMATS,
  type IntegrationRow, type IntegrationsPortfolio,
} from '@/services/projectIntegrationService'
import { ProjectWorkspacePanel } from './ProjectWorkspacePanel'
import { NewProjectDialog } from './NewProjectDialog'
import { plural } from '@/lib/textUtils'

const nf0 = new Intl.NumberFormat('ru-RU')
const DIRECTION_SHORT: Record<string, string> = { outgoing: 'Наши → партнёр', incoming: 'Партнёр → нам' }

function useOpenHere() {
  const [, setParams] = useSearchParams()
  return (id: string) => setParams((prev) => {
    const next = new URLSearchParams(prev)
    next.set('project', id)
    next.delete('ptab')
    return next
  }, { replace: true })
}

export function IntegrationsPanel({ companyId, view }: { companyId: string; view: 'registry' | 'report' }) {
  const [params] = useSearchParams()
  if (params.get('project')) return <ProjectWorkspacePanel companyId={companyId} />
  return view === 'report' ? <IntegrationsReport companyId={companyId} /> : <IntegrationsRegistry companyId={companyId} />
}

function usePortfolio(companyId: string) {
  return useQuery({ queryKey: ['pr-integrations', companyId], queryFn: () => getIntegrationsPortfolio(companyId) })
}

function LoadState({ q, what }: { q: ReturnType<typeof usePortfolio>; what: string }) {
  if (q.isLoading) return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  return (
    <div className="p-4">
      <Card className="border-red-400/40">
        <CardContent className="p-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-medium">Не удалось загрузить {what}</div>
            <div className="text-xs text-muted-foreground">{q.error instanceof Error ? q.error.message : 'Сервис не ответил'}</div>
          </div>
          <Button variant="outline" size="sm" onClick={() => void q.refetch()}><RefreshCw className="h-3.5 w-3.5 mr-1.5" />Повторить</Button>
        </CardContent>
      </Card>
    </div>
  )
}

/** «Выбрано / согласовано / подключено» одной строкой: сохранить перечень ≠ подключить. */
function Stations({ c }: { c: { selected: number; agreed: number; connected: number } }) {
  return (
    <span className="font-mono whitespace-nowrap" title="выбрано / согласовано / фактически подключено">
      {nf0.format(c.selected)} / {nf0.format(c.agreed)} / <span className={c.connected ? 'text-emerald-600 dark:text-emerald-400' : ''}>{nf0.format(c.connected)}</span>
    </span>
  )
}

function Formats({ r }: { r: IntegrationRow }) {
  if (!r.scenarios.length) return <span className="text-muted-foreground">сценарий не задан</span>
  return (
    <span className="flex flex-wrap gap-1">
      {r.scenarios.map((s, i) => (
        <span key={i} className="text-xs rounded border px-1.5 py-0.5 whitespace-nowrap">
          {DIRECTION_SHORT[s.direction]} · {INTEGRATION_FORMATS[s.format]}
        </span>
      ))}
    </span>
  )
}

function Checklist({ r }: { r: IntegrationRow }) {
  return (
    <span className="whitespace-nowrap">
      <span className="font-mono">{r.checklist.closed}/{r.checklist.required}</span>
      {r.checklist.stale > 0 && (
        <span className="ml-1 text-xs text-amber-700 dark:text-amber-400" title="Данные изменились после подтверждения">
          · {r.checklist.stale} к повтору
        </span>
      )}
    </span>
  )
}

const CLOSED = ['archive', 'live']

function IntegrationsRegistry({ companyId }: { companyId: string }) {
  const q = usePortfolio(companyId)
  const qc = useQueryClient()
  const open = useOpenHere()
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'active' | 'all' | 'closed'>('active')
  const [creating, setCreating] = useState(false)
  const rows = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase('ru')
    return (q.data?.items ?? []).filter((r) => {
      const closed = CLOSED.includes(r.stage) || r.stage === 'on_hold'
      if (scope === 'active' && closed) return false
      if (scope === 'closed' && !closed) return false
      return !needle || [r.title, r.partner, r.legalEntity, r.projectNo, r.owner]
        .some((v) => v?.toLocaleLowerCase('ru').includes(needle))
    })
  }, [q.data, search, scope])

  if (!q.data) return <LoadState q={q} what="реестр интеграций" />
  const s = q.data.summary
  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Интеграции</h2>
          <p className="text-sm text-muted-foreground">
            {nf0.format(s.active)} в работе · {nf0.format(s.live)} работают · {nf0.format(s.onHold)} на паузе ·
            {' '}{nf0.format(s.archived)} отклонено. Станции: выбрано / согласовано / подключено.
          </p>
        </div>
        <Button size="sm" className="h-9" onClick={() => setCreating(true)}><Plus className="h-4 w-4 mr-1" />Новая интеграция</Button>
      </div>
      <div className="flex flex-wrap gap-2">
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Партнёр, проект, ответственный"
          className="h-9 w-full sm:w-72" aria-label="Поиск по интеграциям" />
        <select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)} aria-label="Какие проекты показать"
          className="h-9 rounded-md border bg-background px-2 text-sm">
          <option value="active">В работе</option>
          <option value="closed">Работают, на паузе, отклонены</option>
          <option value="all">Все</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <Card><CardContent className="p-6 text-sm text-muted-foreground text-center">
          {q.data.items.length ? 'Под отбор ничего не попало' : 'Проектов интеграции пока нет — заведите первый кнопкой «Новая интеграция»'}
        </CardContent></Card>
      ) : (
        <Card><CardContent className="p-0">
          <ul className="sm:hidden divide-y">
            {rows.map((r) => (
              <li key={r.id}>
                <button type="button" className="w-full text-left p-3 space-y-1 min-h-11" onClick={() => open(r.id)}>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">{r.partner || r.title || '—'}</span>
                    <span className="text-xs rounded border px-1.5 py-0.5 shrink-0">{r.stageLabel}</span>
                  </div>
                  <Formats r={r} />
                  <div className="text-xs text-muted-foreground flex flex-wrap gap-x-3">
                    <span>ЭЗС <Stations c={r.stations} /></span>
                    <span>чек-лист <Checklist r={r} /></span>
                    <span>{r.owner ?? 'без руководителя'}</span>
                  </div>
                  {r.nextAction && <div className={`text-xs ${r.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                    {r.nextAction}{r.nextActionDue ? ` · до ${r.nextActionDue}` : ''}</div>}
                </button>
              </li>
            ))}
          </ul>
          <div className="hidden sm:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/20 text-muted-foreground text-left">
                  <th className="p-2 font-medium">Партнёр</th>
                  <th className="p-2 font-medium">Сценарии</th>
                  <th className="p-2 font-medium">Стадия</th>
                  <th className="p-2 font-medium">ЭЗС</th>
                  <th className="p-2 font-medium">Чек-лист</th>
                  <th className="p-2 font-medium">Руководитель</th>
                  <th className="p-2 font-medium">Следующий шаг</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-b border-border/30 hover:bg-muted/30 cursor-pointer" onClick={() => open(r.id)}>
                    <td className="p-2">
                      <div className="font-medium">{r.partner || r.title || '—'}</div>
                      <div className="text-xs text-muted-foreground"><span className="font-mono">{r.projectNo}</span>{r.partner && r.title && r.title !== r.partner ? ` · ${r.title}` : ''}</div>
                    </td>
                    <td className="p-2"><Formats r={r} /></td>
                    <td className="p-2"><span className="text-xs rounded border px-1.5 py-0.5 whitespace-nowrap">{r.stageLabel}</span></td>
                    <td className="p-2"><Stations c={r.stations} /></td>
                    <td className="p-2"><Checklist r={r} /></td>
                    <td className="p-2 whitespace-nowrap text-muted-foreground">{r.owner ?? '—'}</td>
                    <td className={`p-2 max-w-[260px] ${r.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                      <div className="truncate" title={r.nextAction ?? ''}>{r.nextAction ?? '—'}</div>
                      {r.nextActionDue && <div className="text-xs font-mono">{r.nextActionDue}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent></Card>
      )}

      {creating && (
        <NewProjectDialog companyId={companyId} initialKind="integration" onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false)
            void qc.invalidateQueries({ queryKey: ['pr-integrations', companyId] })
            open(id)
          }} />
      )}
    </div>
  )
}

function IntegrationsReport({ companyId }: { companyId: string }) {
  const q = usePortfolio(companyId)
  const open = useOpenHere()
  if (!q.data) return <LoadState q={q} what="отчёт по интеграциям" />
  const d: IntegrationsPortfolio = q.data
  const s = d.summary
  const byId = new Map(d.items.map((r) => [r.id, r]))
  const attention: [string, string[], string][] = [
    ['Требуют повторного подтверждения', s.attention.stale, 'данные изменились после того, как пункт подтвердили'],
    ['Просрочен следующий шаг', s.attention.overdue, ''],
    ['Без руководителя', s.attention.noOwner, ''],
    ['Без сценария подключения', s.attention.noScenario, ''],
    ['Испытания с замечаниями', s.attention.testsFailed ?? [], 'есть испытания со статусом «Замечание»'],
    ['Сверка с расхождением', s.attention.reconDiff ?? [], 'последняя сверка не сошлась и не урегулирована'],
    ['Запуск не закрыт', s.attention.launchOpen ?? [], 'интеграция работает, но обязательные пункты запуска (боевые доступы, первая сверка) не закрыты'],
  ]
  const cells = Object.entries(s.stations)

  return (
    <div className="p-4 space-y-4">
      <div>
        <h2 className="text-base font-semibold">Отчёт по интеграциям</h2>
        <p className="text-sm text-muted-foreground">
          {nf0.format(s.total)} {plural(s.total, 'проект', 'проекта', 'проектов')}: {nf0.format(s.active)} в работе, {nf0.format(s.live)} работают,
          {' '}{nf0.format(s.onHold)} на паузе, {nf0.format(s.archived)} отклонено.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="min-w-0"><CardContent className="p-0">
          <div className="px-3 py-2 border-b bg-muted/40 text-sm font-semibold">Станции по сценариям</div>
          {cells.length === 0 ? <div className="p-3 text-sm text-muted-foreground">Сценарии ещё не заданы</div> : (
            <div className="overflow-x-auto"><table className="w-full text-sm">
              <thead><tr className="text-muted-foreground text-left border-b">
                <th className="p-2 font-medium">Сценарий</th><th className="hidden sm:table-cell p-2 font-medium text-right">Проектов</th>
                <th className="p-2 font-medium text-right">Выбрано</th><th className="p-2 font-medium text-right">Согласовано</th>
                <th className="p-2 font-medium text-right">Подключено</th>
              </tr></thead>
              <tbody>
                {cells.map(([key, c]) => {
                  const [direction, format] = key.split(':')
                  return (
                    <tr key={key} className="border-b border-border/30">
                      <td className="p-2">{INTEGRATION_DIRECTIONS[direction as 'outgoing']} · {INTEGRATION_FORMATS[format as 'roaming']}</td>
                      <td className="hidden sm:table-cell p-2 text-right font-mono">{nf0.format(c.projects)}</td>
                      <td className="p-2 text-right font-mono">{nf0.format(c.selected)}</td>
                      <td className="p-2 text-right font-mono">{nf0.format(c.agreed)}</td>
                      <td className="p-2 text-right font-mono">{nf0.format(c.connected)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table></div>
          )}
        </CardContent></Card>

        <Card><CardContent className="p-0">
          <div className="px-3 py-2 border-b bg-muted/40 text-sm font-semibold">По стадиям</div>
          <ul className="divide-y text-sm">
            {Object.entries(s.byStage).map(([label, n]) => (
              <li key={label} className="flex justify-between p-2"><span>{label}</span><span className="font-mono">{nf0.format(n)}</span></li>
            ))}
          </ul>
        </CardContent></Card>
      </div>

      <Card><CardContent className="p-0">
        <div className="px-3 py-2 border-b bg-muted/40 text-sm font-semibold">Партнёры</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-muted-foreground text-left border-b">
              <th className="p-2 font-medium">Партнёр</th><th className="p-2 font-medium text-right">Проектов</th>
              <th className="p-2 font-medium">ЭЗС: выбрано / согласовано / подключено</th><th className="p-2 font-medium">Стадии</th>
            </tr></thead>
            <tbody>
              {s.partners.map((p) => (
                <tr key={p.partner} className="border-b border-border/30">
                  <td className="p-2 font-medium">{p.partner}</td>
                  <td className="p-2 text-right font-mono">{nf0.format(p.projects)}</td>
                  <td className="p-2"><Stations c={p} /></td>
                  <td className="p-2 text-muted-foreground">{[...new Set(p.stages)].join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent></Card>

      <Card><CardContent className="p-0">
        <div className="px-3 py-2 border-b bg-muted/40 text-sm font-semibold flex items-center gap-2">
          <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />Требует внимания
        </div>
        <ul className="divide-y text-sm">
          {attention.map(([label, ids, hint]) => (
            <li key={label} className="p-2 space-y-1">
              <div className="flex justify-between gap-2"><span title={hint || undefined}>{label}</span><span className="font-mono">{nf0.format(ids.length)}</span></div>
              {ids.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {ids.map((id) => (
                    <button key={id} type="button" className="text-xs underline hover:no-underline text-left min-h-8" onClick={() => open(id)}>
                      {byId.get(id)?.partner || byId.get(id)?.title || id}
                    </button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      </CardContent></Card>

      <Card><CardContent className="p-0">
        <div className="px-3 py-2 border-b bg-muted/40 text-sm font-semibold">Пилоты</div>
        {s.pilots.length === 0 ? <div className="p-3 text-sm text-muted-foreground">Решений о пилоте пока нет</div> : (
          <ul className="divide-y text-sm">
            {s.pilots.map((p) => (
              <li key={p.id} className="p-2">
                <button type="button" className="font-medium underline hover:no-underline text-left" onClick={() => open(p.id)}>{p.partner || p.title}</button>
                {p.decision && <div className="text-muted-foreground">Решение: {p.decision}</div>}
                {p.outcome && <div className="text-muted-foreground">Итог: {p.outcome}</div>}
              </li>
            ))}
          </ul>
        )}
      </CardContent></Card>
    </div>
  )
}
