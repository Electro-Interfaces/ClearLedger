/**
 * «Магазин» → Станции → Версии агента.
 *
 * Какой код центр считает текущим и что реально стоит на станциях. Обновление
 * агента — осознанная операция с окном и откатом, а не автоматика по факту
 * расхождения: станция кормит кассу, и внезапная подмена бинарника посреди
 * смены стоит дороже, чем отставание на версию.
 *
 * Поэтому экран делает ровно две вещи: объявляет целевую версию (её видит и
 * сам агент — показывает у себя «ожидается такая-то») и показывает, кто
 * отстал. Сам выкат выполняет деплой агента на станцию.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { GitCompareArrows, Check } from 'lucide-react'
import {
  getStoreAgentVersions, setStoreAgentVersion,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function StoreAgentVersionsPanel() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [версия, задатьВерсию] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-agent-versions', company.id],
    queryFn: getStoreAgentVersions,
    refetchInterval: 120_000,
  })

  const объявить = useMutation({
    mutationFn: setStoreAgentVersion,
    onSuccess: (r) => {
      toast.success(`Целевая версия — ${r.desired_version}`)
      задатьВерсию('')
      qc.invalidateQueries({ queryKey: ['store-agent-versions'] })
      qc.invalidateQueries({ queryKey: ['store-stations'] })
    },
    onError: (e: Error) => toast.error('Не удалось объявить версию', { description: e.message }),
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка версий…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить версии агента</div>
  if (!data) return null

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Версии агента</h3>
        <p className="text-xs text-muted-foreground">
          Центр объявляет, какой код считается текущим; станция показывает расхождение у себя.
          Сам выкат — отдельная операция с окном и откатом: агент кормит кассу, и подмена
          бинарника посреди смены стоит дороже отставания на версию.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">Целевая версия</div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums">{data.desired_version}</div>
          <div className="text-[10px] text-muted-foreground/70">
            {data.declared ? 'объявлена в интерфейсе' : `из окружения (${data.fallback_version})`}
          </div>
        </div>
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">Совпадает</div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums text-emerald-400/90">
            {data.total - data.outdated} из {data.total}
          </div>
          <div className="text-[10px] text-muted-foreground/70">станций на целевом коде</div>
        </div>
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">Отстают</div>
          <div className={`mt-0.5 text-xl font-semibold tabular-nums ${data.outdated > 0 ? 'text-amber-300/90' : ''}`}>
            {data.outdated}
          </div>
          <div className="text-[10px] text-muted-foreground/70">не авария — обновление по команде</div>
        </div>
      </div>

      <div className="rounded-lg border border-border/50 bg-card/30 p-3">
        <div className="mb-2 flex items-center gap-1.5 text-sm font-medium">
          <GitCompareArrows className="h-4 w-4 text-primary" />Объявить целевую версию
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input value={версия} onChange={(e) => задатьВерсию(e.target.value)}
            placeholder={data.desired_version} aria-label="Целевая версия агента"
            className="h-8 w-40 rounded-md border border-border/60 bg-background/60 px-2.5 text-xs tabular-nums outline-none focus:border-primary/60" />
          <Button size="sm" disabled={!версия.trim() || объявить.isPending}
            onClick={() => объявить.mutate(версия.trim())}>
            <Check className="mr-1 h-3.5 w-3.5" />Объявить
          </Button>
          {data.versions.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <span>видели на станциях:</span>
              {data.versions.map((v) => (
                <button key={v.version} type="button" onClick={() => задатьВерсию(v.version)}
                  className="rounded-full border border-border/60 px-2 py-0.5 tabular-nums hover:text-foreground">
                  {v.version} · {v.stations}
                </button>
              ))}
            </div>
          )}
        </div>
        <p className="mt-2 text-[10px] text-muted-foreground/70">
          Строка решает, все ли станции считаются отставшими, поэтому объявляет её администратор
          компании. Значение уезжает агенту в ответе на телеметрию — он покажет расхождение у себя.
        </p>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">АЗС</th>
              <th className="px-3 py-2 text-left font-medium">Версия</th>
              <th className="px-3 py-2 text-left font-medium">Связь</th>
              <th className="px-3 py-2 text-left font-medium">Последний ответ</th>
              <th className="px-3 py-2 text-left font-medium">Агент виден с</th>
            </tr>
          </thead>
          <tbody>
            {data.stations.map((s) => (
              <tr key={s.station_id} className="border-t border-border/30">
                <td className="px-3 py-1.5 tabular-nums">{s.station_id}</td>
                <td className={`px-3 py-1.5 tabular-nums ${s.version_ok ? '' : 'text-amber-300/90'}`}>
                  {s.version ?? '—'}
                  {!s.version_ok && s.version && (
                    <span className="ml-2 text-[10px] text-muted-foreground">
                      ожидается {data.desired_version}
                    </span>
                  )}
                </td>
                <td className="px-3 py-1.5 text-muted-foreground">{s.state}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{когда(s.last_seen)}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{когда(s.first_seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.stations.length === 0 && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            Ни один агент ещё не выходил на связь.
          </div>
        )}
      </div>
    </div>
  )
}
