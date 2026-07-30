/**
 * «Схема» — путь проекта, сгруппированный по четырём этапам.
 *
 * Здесь снимается главная путаница: проект — один объект, а подбор площадки,
 * оформление земли, реализация и ввод — его ЭТАПЫ, а не отдельные сущности.
 * Поэтому стадии и параллельные треки сложены под заголовки этапов: видно, что
 * «Лид → Решение» это первый этап проекта, а присоединение и оборудование —
 * части третьего. Одна и та же структура у любого проекта — различается только
 * то, где он сейчас.
 *
 * Отклонённый или замороженный проект не красится сплошными крестами: если
 * известно, докуда он дошёл, пройденное показано как пройденное, а место
 * остановки — отдельной пометкой. У импортированного архива истории нет —
 * тогда честно «путь не прослеживается», а не «0%».
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2, Check, Circle, Play, AlertTriangle, XCircle, Minus, PauseCircle } from 'lucide-react'
import { getProjectRoadmap, getProjectCase, type SiteDetail } from '@/services/sitesService'
import { Button } from '@/components/ui/button'
import { ProjectFlowChart } from './ProjectFlowChart'

const STATE_META: Record<string, { icon: typeof Check; cls: string }> = {
  done: { icon: Check, cls: 'text-emerald-600 dark:text-emerald-400' },
  current: { icon: Play, cls: 'text-blue-600 dark:text-blue-400' },
  stopped: { icon: PauseCircle, cls: 'text-amber-600 dark:text-amber-400' },
  waiting: { icon: Circle, cls: 'text-muted-foreground/50' },
  unknown: { icon: Minus, cls: 'text-muted-foreground/40' },
  overdue: { icon: AlertTriangle, cls: 'text-red-600 dark:text-red-400' },
  failed: { icon: XCircle, cls: 'text-red-600 dark:text-red-400' },
  empty: { icon: Minus, cls: 'text-muted-foreground/40' },
}

// Порядок и подписи этапов — по ним группируется вся схема.
const PHASE_BLOCKS = [
  { key: 'select', n: 1, label: 'Подбор места' },
  { key: 'land', n: 2, label: 'Оформление земли' },
  { key: 'build', n: 3, label: 'Реализация' },
  { key: 'operate', n: 4, label: 'Эксплуатация' },
]

export function ProjectRoadmapTab({ site, companyId }: { site: SiteDetail; companyId: string }) {
  const q = useQuery({
    queryKey: ['site-roadmap', companyId, site.id],
    queryFn: () => getProjectRoadmap(companyId, site.id),
  })
  // Ход по маршруту — та же выборка, что кормит кнопки на вкладке «Работа».
  // Схема обязана рисоваться по тем же данным, иначе она станет вторым мнением
  // о проекте, и однажды оно разойдётся с кнопками.
  const qCase = useQuery({
    queryKey: ['site-case', companyId, site.id],
    queryFn: () => getProjectCase(companyId, site.id),
  })
  if (q.isLoading) {
    return <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  // Ошибку показываем ошибкой. Раньше любой отказ (сеть, 401, 500) оставлял здесь
  // вечный спиннер: `isLoading` уже false, данных нет — и вкладка, открытая первой,
  // встречала человека крутящимся колесом без объяснения.
  if (q.isError || !q.data) {
    return (
      <div className="rounded-lg border border-border px-3 py-3 text-sm space-y-2">
        <div>Путь проекта не загрузился: {q.error instanceof Error ? q.error.message : 'нет связи с сервером'}</div>
        <Button size="sm" variant="outline" onClick={() => q.refetch()}>Повторить</Button>
      </div>
    )
  }
  const d = q.data
  // Этап, на котором проект стоит сейчас (или на котором остановлен).
  const activePhase = d.steps.find((s) => s.state === 'current' || s.state === 'stopped')?.phase ?? null

  return (
    <div className="space-y-3">
      {/* Полоса прогресса / статус остановки */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[200px]">
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-semibold">Путь проекта</span>
            {/* «По стадиям воронки» — не придирка к слову: рядом стоит схема маршрута,
                где проект может быть уже в приёмке, а воронку держит незакрытый гейт.
                Без уточнения два числа на одном экране выглядят как ошибка. */}
            <span className="text-muted-foreground">
              {d.progress == null ? 'путь не прослеживается' : `пройдено ${d.progress}% по стадиям воронки`}
            </span>
          </div>
          <div className="mt-1 h-2 rounded-full bg-muted overflow-hidden">
            <div className={`h-full ${d.offPath ? 'bg-amber-500' : 'bg-emerald-500'}`}
              style={{ width: `${d.progress ?? 0}%` }} />
          </div>
        </div>
        {d.offPath && (
          <span className="text-xs rounded border border-amber-400/50 text-amber-700 dark:text-amber-400 px-1.5 py-0.5">
            {site.stage === 'archive' ? 'Проект отклонён' : 'Проект заморожен'}
            {d.stoppedAt ? ` на этапе «${d.stoppedAt}»` : d.unknownProgress ? ' (история не велась)' : ''}
          </span>
        )}
      </div>

      {/* Схема маршрута: стадии, стрелки и фактический путь проекта. Стоит первой —
          это ответ на «покажи всю картину целиком», ради которого сюда заходят. */}
      {qCase.data?.exists && (
        <section className="rounded-lg border border-border">
          <div className="px-3 py-2 border-b bg-muted/40">
            <span className="text-sm font-semibold">Схема маршрута проекта</span>
            <div className="text-xs text-muted-foreground">
              Тот же граф, по которому работают кнопки на вкладке «Работа». Раскрашено по журналу
              переходов: пройденное — фактом, а не порядком в списке.
            </div>
          </div>
          <div className="p-3"><ProjectFlowChart state={qCase.data} /></div>
        </section>
      )}

      {/* Этапы проекта: стадии + свои параллельные треки под общим заголовком */}
      {PHASE_BLOCKS.map((ph) => {
        const stages = d.steps.filter((s) => s.phase === ph.key)
        const tracks = d.tracks.filter((t) => t.phase === ph.key)
        const isActive = activePhase === ph.key
        if (stages.length === 0 && tracks.length === 0) return null
        return (
          <section key={ph.key}
            className={`rounded-lg border ${isActive ? 'border-primary/50 bg-primary/[0.03]' : 'border-border'}`}>
            <div className="px-3 py-2 border-b flex items-center gap-2 bg-muted/40">
              <span className={`h-5 w-5 rounded-full flex items-center justify-center text-xs font-semibold shrink-0
                ${isActive ? 'bg-primary text-primary-foreground'
                  : stages.every((s) => s.state === 'done') ? 'bg-emerald-500 text-white'
                  : 'bg-muted text-muted-foreground'}`}>
                {ph.n}
              </span>
              <span className="text-sm font-semibold">Этап {ph.n} · {ph.label}</span>
              {isActive && <span className="text-xs text-primary ml-auto">проект здесь</span>}
            </div>

            <div className="p-3 space-y-1.5">
              {/* Стадии этапа */}
              {stages.map((s) => {
                const meta = STATE_META[s.state] ?? STATE_META.waiting
                const Icon = meta.icon
                return (
                  <div key={s.key}>
                    <div className="flex items-center gap-2">
                      <Icon className={`h-3.5 w-3.5 shrink-0 ${meta.cls}`} />
                      <span className={`text-sm ${['waiting', 'unknown'].includes(s.state) ? 'text-muted-foreground' : 'font-medium'}`}>
                        {s.label}
                      </span>
                      <span className="text-xs text-muted-foreground">гейт {s.gateDone}/{s.gateTotal}</span>
                      {s.date && <span className="text-xs text-muted-foreground">с {s.date}</span>}
                    </div>
                    {s.state === 'current' && s.items.length > 0 && (
                      <div className="mt-1 ml-5 space-y-0.5">
                        {s.items.map((it) => (
                          <div key={it.label} className="flex items-center gap-1.5 text-xs">
                            {it.done
                              ? <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400 shrink-0" />
                              : <Circle className="h-3 w-3 text-muted-foreground shrink-0" />}
                            <span className={it.done ? '' : 'text-muted-foreground'}>{it.label}</span>
                            {it.required && !it.done && <span className="text-xs text-red-500/80">держит переход</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}

              {/* Параллельные треки этапа (право, ТП, оборудование, объект сети) */}
              {tracks.length > 0 && (
                <div className={stages.length > 0 ? 'pt-1.5 mt-1.5 border-t border-border/40 space-y-1.5' : 'space-y-1.5'}>
                  {stages.length > 0 && (
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Параллельно на этапе</div>
                  )}
                  {tracks.map((t) => {
                    const meta = STATE_META[t.state] ?? STATE_META.waiting
                    const Icon = meta.icon
                    return (
                      <div key={t.key} className="flex items-start gap-2">
                        <Icon className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${meta.cls}`} />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-baseline gap-2">
                            <span className="text-sm font-medium">{t.label}</span>
                            <span className="text-xs text-muted-foreground">{t.status}</span>
                            {t.date && <span className="text-xs text-muted-foreground">· {t.date}</span>}
                          </div>
                          {t.detail && <div className="text-xs text-muted-foreground truncate">{t.detail}</div>}
                          {t.note && (
                            <div className={`text-xs ${t.state === 'overdue' ? 'text-red-600 dark:text-red-400' : 'text-amber-700 dark:text-amber-400'}`}>
                              {t.note}
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </section>
        )
      })}

      {/* Документы и субсидия — итог по проекту */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <section className="rounded-lg border border-border p-3">
          <div className="text-sm font-semibold mb-1">Документы проекта</div>
          <div className="text-sm text-muted-foreground">
            {d.docs.count === 0
              ? 'Не приложено ни одного документа. Часть пунктов гейта закрывается именно файлом.'
              : `${d.docs.count} шт: ${d.docs.kinds.join(', ')}`}
          </div>
        </section>
        <section className="rounded-lg border border-border p-3">
          <div className="text-sm font-semibold mb-1">Субсидия: {d.subsidy.done}/{d.subsidy.total}</div>
          <div className="text-sm text-muted-foreground">
            {d.subsidy.eligible
              ? `Требования выполнены${d.subsidy.obligationUntil ? `; обязательство эксплуатации до ${d.subsidy.obligationUntil}` : ''}`
              : `Не закрыто: ${d.subsidy.items.filter((i) => !i.done).map((i) => i.label).join('; ')}`}
          </div>
        </section>
      </div>
    </div>
  )
}
