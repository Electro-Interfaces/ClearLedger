/**
 * «Аудитор» — страница агента пространства (плитка на столе ведёт сюда).
 *
 * Панель та же, что открывается справа из любого экрана; разница в том, что здесь
 * рядом видно, ЧЕМ он вообще умеет отвечать. Каталог навыков это не украшение: он
 * задаёт разговору рамку и показывает, чего агенту пока не хватает, — новый навык
 * добавляется файлом поставки (`ecosystem-deploy/services/auditor/skills.js`), а не
 * уговорами модели.
 *
 * Не путать с `pages/partner/AuditorPage.tsx` — тот из партнёрского контура и
 * обслуживает внешние инстансы ClearLedger.
 */
import { useQuery } from '@tanstack/react-query'
import { Bot } from 'lucide-react'
import { AuditorPanel } from '@/components/auditor/AuditorPanel'
import { QueryError } from '@/components/common/QueryError'
import { getSkills, type AuditorSkill } from '@/services/spaceAuditorService'

export function AuditorPage() {
  const { data: skills, isLoading, error, refetch } = useQuery({
    queryKey: ['auditor-skills'],
    queryFn: getSkills,
    staleTime: 10 * 60 * 1000,   // каталог меняется с выкаткой образа, не в течение дня
  })

  const groups = (skills || []).reduce<Record<string, AuditorSkill[]>>((acc, s) => {
    (acc[s.group] ||= []).push(s)
    return acc
  }, {})

  return (
    <div className="flex h-full min-h-0 gap-4 p-4">
      <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-border/60 bg-card">
        <AuditorPanel />
      </div>

      <aside className="hidden w-80 shrink-0 flex-col overflow-y-auto rounded-xl border border-border/60 bg-card/50 p-4 lg:flex">
        <div className="mb-3 flex items-center gap-2">
          <Bot className="size-4 text-primary" />
          <h2 className="text-sm font-semibold">Что я умею спросить</h2>
        </div>
        {error && <QueryError message={(error as Error).message} onRetry={() => refetch()} />}
        {isLoading && <div className="text-sm text-muted-foreground">Загружаю каталог…</div>}
        {!isLoading && !error && !skills?.length && (
          <div className="text-sm text-muted-foreground">
            Каталог пуст: сервис аудитора в этом пространстве не поднят.
          </div>
        )}
        <div className="space-y-4">
          {Object.entries(groups).map(([group, items]) => (
            <div key={group}>
              <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{group}</div>
              <ul className="space-y-1.5">
                {items.map((s) => (
                  <li key={s.id} className="rounded-lg border border-border/50 px-2.5 py-1.5">
                    <div className="text-sm font-medium">{s.name}</div>
                    <div className="mt-0.5 text-xs leading-snug text-muted-foreground">{s.when}</div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </aside>
    </div>
  )
}
