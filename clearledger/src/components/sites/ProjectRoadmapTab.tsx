/**
 * «Схема реализации» — путь проекта от участка до работающей станции одной лентой.
 *
 * Остальные вкладки отвечают на вопрос «как заполнить», схема — «где мы в
 * проекте, что осталось и что мешает». Поэтому здесь нет форм: только состояние
 * шагов, сроки и то, что держит текущий шаг.
 *
 * Стадии идут последовательно, а присоединение, оборудование, право на землю и
 * связь с сетью — параллельные треки: оборудование заказывают, не дожидаясь
 * исполнения ТП, и рисовать их шагами лестницы было бы враньём про сроки.
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2, Check, Circle, Play, AlertTriangle, XCircle, Minus } from 'lucide-react'
import { getProjectRoadmap, PHASE_META, type SiteDetail } from '@/services/sitesService'

const STATE_META: Record<string, { icon: typeof Check; cls: string; label: string }> = {
  done: { icon: Check, cls: 'text-emerald-600 dark:text-emerald-400', label: 'сделано' },
  current: { icon: Play, cls: 'text-blue-600 dark:text-blue-400', label: 'сейчас' },
  waiting: { icon: Circle, cls: 'text-muted-foreground', label: 'ждёт' },
  overdue: { icon: AlertTriangle, cls: 'text-red-600 dark:text-red-400', label: 'просрочено' },
  failed: { icon: XCircle, cls: 'text-red-600 dark:text-red-400', label: 'отказ' },
  empty: { icon: Minus, cls: 'text-muted-foreground/60', label: 'не заведено' },
  archived: { icon: XCircle, cls: 'text-muted-foreground', label: 'проект отклонён' },
}

export function ProjectRoadmapTab({ site, companyId }: { site: SiteDetail; companyId: string }) {
  const q = useQuery({
    queryKey: ['site-roadmap', companyId, site.id],
    queryFn: () => getProjectRoadmap(companyId, site.id),
  })
  if (q.isLoading || !q.data) {
    return <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  const d = q.data

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[200px]">
          <div className="flex items-baseline justify-between text-xs">
            <span className="font-semibold">Путь проекта</span>
            <span className="text-muted-foreground">пройдено {d.progress}%</span>
          </div>
          <div className="mt-1 h-2 rounded-full bg-muted overflow-hidden">
            <div className={`h-full ${d.archived ? 'bg-zinc-500' : 'bg-emerald-500'}`}
              style={{ width: `${d.progress}%` }} />
          </div>
        </div>
        {d.archived && (
          <span className="text-[11px] rounded border border-zinc-600 text-zinc-500 px-1.5 py-0.5">
            проект отклонён — путь остановлен
          </span>
        )}
      </div>

      {/* Последовательные стадии */}
      <section className="rounded-lg border border-border">
        <div className="px-3 py-2 text-xs font-semibold border-b bg-muted/40">Стадии</div>
        <ol className="p-3 space-y-0">
          {d.steps.map((s, i) => {
            const meta = STATE_META[s.state] ?? STATE_META.waiting
            const Icon = meta.icon
            const last = i === d.steps.length - 1
            return (
              <li key={s.key} className="relative flex gap-3 pb-3">
                {/* линия ленты */}
                {!last && <span className="absolute left-[9px] top-5 bottom-0 w-px bg-border" />}
                <span className={`relative z-10 mt-0.5 h-[18px] w-[18px] rounded-full border bg-background flex items-center justify-center shrink-0 ${meta.cls}`}>
                  <Icon className="h-3 w-3" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`text-xs ${s.state === 'waiting' ? 'text-muted-foreground' : 'font-medium'}`}>
                      {s.label}
                    </span>
                    <span className={`text-[10px] rounded border px-1 ${PHASE_META[s.phase ?? '']?.cls ?? 'text-muted-foreground'}`}>
                      {s.phaseLabel}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      гейт {s.gateDone}/{s.gateTotal}
                    </span>
                    {s.date && <span className="text-[10px] text-muted-foreground">с {s.date}</span>}
                  </div>
                  {s.state === 'current' && (
                    <div className="mt-1 space-y-0.5">
                      {s.items.map((it) => (
                        <div key={it.label} className="flex items-center gap-1.5 text-[11px]">
                          {it.done
                            ? <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400 shrink-0" />
                            : <Circle className="h-3 w-3 text-muted-foreground shrink-0" />}
                          <span className={it.done ? '' : 'text-muted-foreground'}>{it.label}</span>
                          {it.required && !it.done && (
                            <span className="text-[9px] text-red-500/80">держит переход</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </section>

      {/* Параллельные треки */}
      <section className="rounded-lg border border-border">
        <div className="px-3 py-2 text-xs font-semibold border-b bg-muted/40">
          Параллельно: присоединение, оборудование, право, сеть
        </div>
        <div className="divide-y divide-border/40">
          {d.tracks.map((t) => {
            const meta = STATE_META[t.state] ?? STATE_META.waiting
            const Icon = meta.icon
            return (
              <div key={t.key} className="flex items-start gap-3 px-3 py-2">
                <span className={`mt-0.5 shrink-0 ${meta.cls}`}><Icon className="h-3.5 w-3.5" /></span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-xs font-medium">{t.label}</span>
                    <span className="text-[11px] text-muted-foreground">{t.status}</span>
                    {t.date && <span className="text-[10px] text-muted-foreground">· {t.date}</span>}
                  </div>
                  {t.detail && <div className="text-[11px] text-muted-foreground truncate">{t.detail}</div>}
                  {t.note && (
                    <div className={`text-[11px] ${t.state === 'overdue' ? 'text-red-600 dark:text-red-400' : 'text-amber-700 dark:text-amber-400'}`}>
                      {t.note}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* Готовность к субсидии и документы — итог схемы */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <section className="rounded-lg border border-border p-3">
          <div className="text-xs font-semibold mb-1">Документы проекта</div>
          <div className="text-xs text-muted-foreground">
            {d.docs.count === 0
              ? 'Не приложено ни одного документа. Часть пунктов гейта закрывается именно файлом.'
              : `${d.docs.count} шт: ${d.docs.kinds.join(', ')}`}
          </div>
        </section>
        <section className="rounded-lg border border-border p-3">
          <div className="text-xs font-semibold mb-1">
            Субсидия: {d.subsidy.done}/{d.subsidy.total}
          </div>
          <div className="text-xs text-muted-foreground">
            {d.subsidy.eligible
              ? `Требования выполнены${d.subsidy.obligationUntil ? `; обязательство эксплуатации до ${d.subsidy.obligationUntil}` : ''}`
              : `Не закрыто: ${d.subsidy.items.filter((i) => !i.done).map((i) => i.label).join('; ')}`}
          </div>
        </section>
      </div>
    </div>
  )
}
