/**
 * «Схема» интеграции: путь слева направо и подробности выбранной стадии.
 *
 * Было: граф со стрелками «Отказ/Отложить» у каждой стадии, потом сетка 3×3 с
 * одинаковыми «0 из N» — последовательность терялась, содержания не было
 * (замечания МАГа 06.10.2026). Теперь сверху — четыре этапа колонками, в каждой
 * её стадии строками (✓ / ▶ / ○, «N/M», значок документа), стрелки между этапами;
 * снизу — пункты выбранной стадии со статусами, ответственными и документом.
 *
 * Данные те же, что у чек-листа и хода по маршруту (интеграция + кейс), чтобы
 * схема не стала вторым мнением о проекте.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, Circle, Play, ChevronRight, FileCheck2, FileX2, FileClock, PauseCircle, XCircle, AlertTriangle, MinusCircle } from 'lucide-react'
import { getProjectCase, FUNNEL_STAGES, type SiteDetail, type GateState } from '@/services/sitesService'
import { getIntegration, type IntegrationDocument } from '@/services/projectIntegrationService'
import { Button } from '@/components/ui/button'
import { ROLE_NAMES } from './IntegrationProjectPanels'

/** Ключевой документ стадии — тот, что проверяет её пункт с подписанием. */
const STAGE_DOCS: Record<string, { kinds: string[]; label: string }> = {
  contracting: { kinds: ['nda', 'pilot'], label: 'Пилотное соглашение / NDA' },
  construction: { kinds: ['test_protocol'], label: 'Протокол испытаний' },
  commissioning: { kinds: ['contract'], label: 'Договор' },
}
const PHASES = [
  { key: 'scenario', label: 'Сценарий', stages: ['lead', 'screening'] },
  { key: 'terms', label: 'Условия', stages: ['negotiation', 'dd'] },
  { key: 'pilot', label: 'Пилот', stages: ['decision', 'contracting', 'construction'] },
  { key: 'launch', label: 'Запуск', stages: ['commissioning', 'live'] },
]
type StageState = 'done' | 'current' | 'stopped' | 'future'
const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '')

function docState(stage: string, docs: IntegrationDocument[]) {
  const def = STAGE_DOCS[stage]
  if (!def) return null
  const own = docs.filter((d) => def.kinds.includes(d.kind))
  const signed = own.some((d) => d.signedDocId && d.signingEvidence)
  return { label: def.label, state: signed ? 'signed' : own.length ? 'draft' : 'none' as 'signed' | 'draft' | 'none' }
}
const DocIcon = ({ s, className }: { s: 'signed' | 'draft' | 'none'; className?: string }) =>
  s === 'signed' ? <FileCheck2 className={`text-emerald-500 ${className}`} /> : s === 'draft' ? <FileClock className={`text-amber-500 ${className}`} /> : <FileX2 className={`text-muted-foreground ${className}`} />

export function IntegrationStageMap({ site, companyId, onStage }: {
  site: SiteDetail; companyId: string; onStage?: (code: string) => void
}) {
  const integ = useQuery({ queryKey: ['project-integration', companyId, site.id], queryFn: () => getIntegration(companyId, site.id) })
  const kase = useQuery({ queryKey: ['site-case', companyId, site.id], queryFn: () => getProjectCase(companyId, site.id) })
  const stopped = site.stage === 'on_hold' || site.stage === 'archive'
  // На паузе и в отказе «текущей» считаем стадию, с которой ушли.
  const anchor = stopped ? (site.prevStage ?? '') : site.stage
  const [picked, setPicked] = useState<string>(anchor || 'lead')
  if (!integ.data) return <p className="text-sm text-muted-foreground">{integ.isError ? `Не загрузилось: ${integ.error.message}` : 'Загрузка…'}</p>

  const { gates, data } = integ.data
  const byStage = new Map<string, GateState>(gates.map((g) => [g.stage, g]))
  const curIdx = FUNNEL_STAGES.indexOf(anchor as never)
  const visited = new Map((kase.data?.stages ?? []).map((s) => [s.code, s.visited_at]))
  const step = (kase.data?.actions ?? []).find((a) => a.is_positive === true && !a.is_discretionary)
  const stateOf = (stage: string): StageState => {
    const i = FUNNEL_STAGES.indexOf(stage as never)
    return i < curIdx ? 'done' : i === curIdx ? (stopped ? 'stopped' : 'current') : 'future'
  }
  const req = (g?: GateState) => (g?.items ?? []).filter((it) => it.required)
  const sel = byStage.get(picked)
  const selState = stateOf(picked)
  const selDoc = docState(picked, data.documents)

  return (
    <div className="space-y-4">
      {stopped && (
        <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          {site.stage === 'archive' ? <XCircle className="h-4 w-4 text-red-500" /> : <PauseCircle className="h-4 w-4 text-amber-500" />}
          {site.stage === 'archive' ? 'Интеграция отклонена' : 'Интеграция на паузе'}{anchor ? ` на стадии «${byStage.get(anchor)?.stageLabel ?? anchor}»` : ''}
        </div>
      )}

      {/* Путь: этапы слева направо, в каждом — его стадии */}
      <div className="grid gap-2 md:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] items-stretch">
        {PHASES.map((ph, pi) => {
          const states = ph.stages.map(stateOf)
          const phState = states.every((s) => s === 'done') ? 'done' : states.some((s) => s === 'current' || s === 'stopped') ? 'current' : 'future'
          return [
            <section key={ph.key} className={`rounded-lg border p-2 ${phState === 'current' ? 'border-primary/60 bg-primary/5' : phState === 'done' ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-border'}`}>
              <div className="px-1 pb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{pi + 1}. {ph.label}</div>
              <div className="space-y-1">
                {ph.stages.map((st) => {
                  const g = byStage.get(st); const s = stateOf(st); const r = req(g)
                  const rd = r.filter((it) => it.done || it.waived).length
                  const doc = docState(st, data.documents)
                  const Icon = s === 'done' ? Check : s === 'current' ? Play : s === 'stopped' ? PauseCircle : Circle
                  return (
                    <button key={st} type="button" onClick={() => setPicked(st)}
                      className={`w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors
                        ${picked === st ? 'bg-background ring-1 ring-primary' : 'hover:bg-muted/60'}`}>
                      <Icon className={`h-4 w-4 shrink-0 ${s === 'done' ? 'text-emerald-500' : s === 'current' ? 'text-primary' : s === 'stopped' ? 'text-amber-500' : 'text-muted-foreground/60'}`} />
                      <span className={`flex-1 min-w-0 truncate ${s === 'future' ? 'text-muted-foreground' : s === 'current' ? 'font-medium' : ''}`}>{g?.stageLabel ?? st}</span>
                      {doc && <span title={`${doc.label}: ${doc.state === 'signed' ? 'подписан' : doc.state === 'draft' ? 'есть, не подписан' : 'нет'}`}><DocIcon s={doc.state} className="h-3.5 w-3.5" /></span>}
                      {r.length > 0 && <span className={`text-xs tabular-nums ${rd === r.length ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}`}>{rd}/{r.length}</span>}
                    </button>
                  )
                })}
              </div>
            </section>,
            pi < PHASES.length - 1 && <div key={`${ph.key}-arrow`} className="hidden md:flex items-center"><ChevronRight className="h-5 w-5 text-muted-foreground/60" /></div>,
          ]
        })}
      </div>

      {/* Подробности выбранной стадии */}
      {sel && (
        <section className="rounded-lg border">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b bg-muted/40 px-3 py-2">
            <span className="font-semibold">{sel.stageLabel}</span>
            <span className="text-xs text-muted-foreground">
              {selState === 'done' ? `пройдена${fmt(visited.get(`int_${picked}`)) ? ` · вход ${fmt(visited.get(`int_${picked}`))}` : ''}`
                : selState === 'current' ? `проект здесь${fmt(visited.get(`int_${picked}`)) ? ` с ${fmt(visited.get(`int_${picked}`))}` : ''}`
                : selState === 'stopped' ? 'остановлен здесь' : 'впереди — пункты можно заполнять заранее'}
            </span>
            {onStage && <Button size="sm" variant="outline" className="ml-auto" onClick={() => onStage(`int_${picked}`)}>Открыть работу стадии</Button>}
          </div>
          <div className="p-3 space-y-3">
            {selState === 'current' && step && (
              <div className="text-sm">
                {req(sel).every((it) => it.done || it.waived)
                  ? <span className="text-emerald-600 dark:text-emerald-400">Всё обязательное закрыто — следующий шаг «{step.verb}» → {step.to_name}</span>
                  : <span>Чтобы перейти к «{step.to_name}», закройте обязательные пункты ниже (отмечены ●).</span>}
              </div>
            )}
            <ul className="divide-y">
              {[...sel.items].sort((a, b) => Number(b.required) - Number(a.required)).map((it) => {
                const St = it.done ? Check : it.needsConfirmation ? AlertTriangle : it.waived ? MinusCircle : Circle
                const cls = it.done ? 'text-emerald-500' : it.needsConfirmation ? 'text-amber-500' : it.waived ? 'text-amber-500' : 'text-muted-foreground/60'
                return (
                  <li key={it.key} className="flex items-start gap-2 py-1.5 text-sm">
                    <St className={`mt-0.5 h-4 w-4 shrink-0 ${cls}`} />
                    <span className="w-10 shrink-0 font-mono text-xs text-muted-foreground mt-0.5">{it.key}</span>
                    <span className="flex-1 min-w-0">
                      {it.required && <span className="text-primary mr-1" title="Обязательный: держит переход">●</span>}
                      {it.label}
                      {it.needsConfirmation && <span className="ml-1 text-xs text-amber-600">— данные изменились, подтвердить заново</span>}
                      {it.waived && !it.done && <span className="ml-1 text-xs text-amber-600">— обязательность снята</span>}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">{ROLE_NAMES[it.role ?? ''] ?? it.role}</span>
                  </li>
                )
              })}
            </ul>
            {selDoc && (
              <div className="flex items-center gap-2 text-sm border-t pt-2">
                <DocIcon s={selDoc.state} className="h-4 w-4" />
                {selDoc.label}: {selDoc.state === 'signed' ? 'подписан' : selDoc.state === 'draft' ? 'есть, не подписан' : 'нет'}
              </div>
            )}
          </div>
        </section>
      )}

      <p className="text-xs text-muted-foreground">
        ✓ пройдена · ▶ проект здесь · ○ впереди · «N/M» — закрыто обязательных пунктов · значок документа — ключевой документ стадии (зелёный — подписан, жёлтый — не подписан, серый — нет).
        На любой стадии проект можно отложить или отклонить — кнопки в «Ходе по маршруту» на вкладке «Работа».
      </p>
    </div>
  )
}
