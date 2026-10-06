/**
 * Карта стадий интеграции — вместо графа со стрелками на вкладке «Схема».
 *
 * Граф рисовал у каждой стадии одни и те же стрелки «Отказ, в архив» и «Отложить»
 * и узкие карточки без содержания (замечание МАГа 06.10.2026: «что означают эти
 * стрелочки», «огромное количество места по горизонтали»). Здесь каждая стадия —
 * карточка с тем, что про неё нужно знать: пройдена ли и когда, сколько
 * обязательных пунктов закрыто, есть ли ключевой документ стадии, что держит
 * текущую. Пауза и отказ доступны на любой стадии — одной строкой внизу.
 *
 * Данные — те же, что у чек-листа и хода по маршруту (интеграция + кейс), чтобы
 * карта не стала вторым мнением о проекте.
 */
import { useQuery } from '@tanstack/react-query'
import { Check, Circle, Play, FileCheck2, FileX2, FileClock, PauseCircle, XCircle } from 'lucide-react'
import { getProjectCase, FUNNEL_STAGES, type SiteDetail } from '@/services/sitesService'
import { getIntegration } from '@/services/projectIntegrationService'

/** Ключевой документ стадии — тот, что проверяет её пункт с подписанием. */
const STAGE_DOCS: Record<string, { kinds: string[]; label: string }> = {
  contracting: { kinds: ['nda', 'pilot'], label: 'Пилотное соглашение / NDA' },
  construction: { kinds: ['test_protocol'], label: 'Протокол испытаний' },
  commissioning: { kinds: ['contract'], label: 'Договор' },
}
const PHASE_OF: Record<string, string> = {
  lead: 'Сценарий', screening: 'Сценарий', negotiation: 'Условия', dd: 'Условия',
  decision: 'Пилот', contracting: 'Пилот', construction: 'Пилот', commissioning: 'Запуск', live: 'Запуск',
}
const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '')

export function IntegrationStageMap({ site, companyId, onStage }: {
  site: SiteDetail; companyId: string; onStage?: (code: string) => void
}) {
  const integ = useQuery({ queryKey: ['project-integration', companyId, site.id], queryFn: () => getIntegration(companyId, site.id) })
  const kase = useQuery({ queryKey: ['site-case', companyId, site.id], queryFn: () => getProjectCase(companyId, site.id) })
  if (!integ.data) return <p className="text-sm text-muted-foreground">{integ.isError ? `Не загрузилось: ${integ.error.message}` : 'Загрузка…'}</p>

  const { gates, data } = integ.data
  const stopped = site.stage === 'on_hold' || site.stage === 'archive'
  // На паузе и в отказе текущей считаем стадию, с которой ушли (prevStage).
  const anchor = stopped ? (site.prevStage ?? '') : site.stage
  const curIdx = FUNNEL_STAGES.indexOf(anchor as never)
  const visited = new Map((kase.data?.stages ?? []).map((s) => [s.code, s.visited_at]))
  const step = (kase.data?.actions ?? []).find((a) => a.is_positive === true && !a.is_discretionary)
  const ordered = [...gates].sort((a, b) => FUNNEL_STAGES.indexOf(a.stage) - FUNNEL_STAGES.indexOf(b.stage))

  return (
    <div className="space-y-3">
      {stopped && (
        <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          {site.stage === 'archive' ? <XCircle className="h-4 w-4 text-red-500" /> : <PauseCircle className="h-4 w-4 text-amber-500" />}
          {site.stage === 'archive' ? 'Интеграция отклонена' : 'Интеграция на паузе'}{anchor ? ` на стадии «${ordered.find((g) => g.stage === anchor)?.stageLabel ?? anchor}»` : ''}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {ordered.map((g, i) => {
          const idx = FUNNEL_STAGES.indexOf(g.stage)
          const state = idx < curIdx ? 'done' : idx === curIdx ? (stopped ? 'stopped' : 'current') : 'future'
          const req = g.items.filter((it) => it.required)
          const reqDone = req.filter((it) => it.done || it.waived).length
          const waived = req.filter((it) => it.waived && !it.done).length
          const holding = req.find((it) => !it.done && !it.waived)
          const docDef = STAGE_DOCS[g.stage]
          const docs = docDef ? data.documents.filter((d) => docDef.kinds.includes(d.kind)) : []
          const signed = docs.some((d) => d.signedDocId && d.signingEvidence)
          const date = fmt(visited.get(`int_${g.stage}`))
          const Icon = state === 'done' ? Check : state === 'current' ? Play : state === 'stopped' ? PauseCircle : Circle
          return (
            <button key={g.stage} type="button" disabled={!onStage}
              onClick={() => onStage?.(`int_${g.stage}`)}
              title={onStage ? 'Открыть работу по стадии: чек-лист и что не закрыто' : undefined}
              className={`flex flex-col justify-start text-left rounded-lg border p-3 space-y-2 transition-colors ${onStage ? 'hover:border-primary/60' : ''}
                ${state === 'current' ? 'border-primary bg-primary/5 ring-1 ring-primary/40'
                  : state === 'done' ? 'border-emerald-500/40 bg-emerald-500/5'
                  : state === 'stopped' ? 'border-amber-500/50 bg-amber-500/5' : 'border-dashed border-border'}`}>
              <div className="flex items-start gap-2">
                <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold
                  ${state === 'done' ? 'bg-emerald-500 text-white' : state === 'current' ? 'bg-primary text-primary-foreground'
                    : state === 'stopped' ? 'bg-amber-500 text-white' : 'bg-muted text-muted-foreground'}`}>
                  {state === 'future' ? i + 1 : <Icon className="h-3.5 w-3.5" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="font-medium leading-tight">{g.stageLabel}</div>
                  <div className="text-xs text-muted-foreground">
                    Этап «{PHASE_OF[g.stage] ?? '—'}»
                    {state === 'done' && date && ` · пройдена, вход ${date}`}
                    {state === 'current' && ` · проект здесь${date ? ` с ${date}` : ''}`}
                    {state === 'stopped' && ' · остановлен здесь'}
                  </div>
                </div>
              </div>

              {/* Обязательные пункты стадии: полоска + число */}
              {req.length > 0 && (
                <div className="space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">Обязательные пункты</span>
                    <span className={reqDone === req.length ? 'text-emerald-600 dark:text-emerald-400' : ''}>
                      {reqDone} из {req.length}{waived ? ` · ${waived} без проверки` : ''}
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                    <div className={`h-full ${reqDone === req.length ? 'bg-emerald-500' : 'bg-primary'}`} style={{ width: `${(reqDone / req.length) * 100}%` }} />
                  </div>
                </div>
              )}
              {req.length === 0 && <div className="text-xs text-muted-foreground">Обязательных пунктов нет · всего пунктов {g.done}/{g.total}</div>}

              {/* Ключевой документ стадии */}
              {docDef && (
                <div className={`flex items-center gap-1.5 text-xs ${signed ? 'text-emerald-600 dark:text-emerald-400' : docs.length ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                  {signed ? <FileCheck2 className="h-3.5 w-3.5" /> : docs.length ? <FileClock className="h-3.5 w-3.5" /> : <FileX2 className="h-3.5 w-3.5" />}
                  {docDef.label}: {signed ? 'подписан' : docs.length ? 'есть, не подписан' : 'нет'}
                </div>
              )}

              {/* Что держит текущую стадию и куда ведёт шаг */}
              {state === 'current' && (
                <div className="text-xs border-t pt-2 space-y-0.5">
                  {holding ? <div><span className="text-muted-foreground">Держит: </span>{holding.label}</div>
                    : <div className="text-emerald-600 dark:text-emerald-400">Всё обязательное закрыто</div>}
                  {step && <div className="text-muted-foreground">Следующий шаг — «{step.verb}» → {step.to_name}</div>}
                </div>
              )}
            </button>
          )
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        На любой стадии проект можно <b>отложить</b> (пауза с причиной; вернуть — на ту же стадию) или <b>отклонить</b> (в архив с причиной). Обе кнопки — в «Ходе по маршруту» на вкладке «Работа».
      </p>
    </div>
  )
}
