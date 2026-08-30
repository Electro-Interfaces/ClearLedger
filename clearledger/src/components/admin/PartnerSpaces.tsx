/**
 * Пространства-соседи: кого мы обслуживаем и кто обслуживает нас.
 *
 * Не путать с разделом «Компании»: там сторонние организации, ДОПУЩЕННЫЕ в это
 * пространство своими людьми. Здесь — другие пространства целиком, со своим
 * Ядром, людьми и данными; общего у нас с ними ровно два канала: разговор
 * поддержки и пропуск инженера.
 *
 * Уровень контейнера, а не организации: связь между пространствами заводит тот,
 * кто владеет обоими концами, — он же держит ключи.
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ExternalLink, Loader2, MessagesSquare, Network, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { formatDateTime } from '@/lib/formatDate'
import { listPartnerSpaces, partnerFeed, visitPartnerSpace } from '@/services/partnerSpaceService'

export function PartnerSpaces() {
  const { companyId } = useCompany()
  const [openFeed, setOpenFeed] = useState<string | null>(null)

  const spaces = useQuery({
    queryKey: ['partner-spaces', companyId],
    queryFn: () => listPartnerSpaces(companyId),
    enabled: !!companyId,
  })
  const feed = useQuery({
    queryKey: ['partner-feed', openFeed, companyId],
    queryFn: () => partnerFeed(openFeed!, companyId),
    enabled: !!openFeed && !!companyId,
  })
  const visit = useMutation({
    mutationFn: (code: string) => visitPartnerSpace(code, companyId),
    // Пропуск живёт две минуты — открываем сразу, а не даём ссылку «на потом».
    onSuccess: (res) => window.open(res.url, '_blank', 'noopener'),
  })

  const items = spaces.data?.items || []

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-start gap-3">
        <Network className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
        <div>
          <h2 className="text-base font-semibold text-foreground">Пространства</h2>
          <p className="text-sm text-muted-foreground">
            Соседние пространства экосистемы: чьи обращения приходят к нам и куда
            наши инженеры входят своей учётной записью.
          </p>
        </div>
      </div>

      {spaces.isLoading ? (
        <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Читаю реестр…
        </div>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          Связей нет. Пространства соединяются парой записей — по одной с каждой
          стороны — и ключом, который живёт в окружении стека, а не в базе.
        </p>
      ) : items.map((p) => (
        <div key={p.code} className="rounded-lg border border-border bg-card p-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-medium text-foreground">{p.name}</span>
            <span className="rounded bg-secondary px-1.5 py-0.5 text-xs text-muted-foreground">
              {p.role === 'client' ? 'наш клиент' : 'наш поставщик'}
            </span>
            {p.linked ? (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                <ShieldCheck className="h-3.5 w-3.5" />связь включена
              </span>
            ) : (
              <span className="text-xs text-amber-600 dark:text-amber-400">нет адреса или ключа</span>
            )}
            {p.lastSeenAt && (
              <span className="text-xs text-muted-foreground">последний обмен {formatDateTime(p.lastSeenAt)}</span>
            )}
            <div className="ml-auto flex gap-2">
              <Button size="sm" variant="outline" className="gap-1.5"
                onClick={() => setOpenFeed(openFeed === p.code ? null : p.code)}>
                <MessagesSquare className="h-4 w-4" />Переписка
              </Button>
              {/* Входим только к клиенту: у поставщика своё пространство, и наш
                  пропуск там ничего не значит — он выписан нашим ключом. */}
              {p.role === 'client' && (
                <Button size="sm" className="gap-1.5" disabled={!p.linked || visit.isPending}
                  onClick={() => visit.mutate(p.code)}>
                  {visit.isPending ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <ExternalLink className="h-4 w-4" />}
                  Войти
                </Button>
              )}
            </div>
          </div>

          {openFeed === p.code && (
            <div className="mt-3 space-y-2 border-t border-border/60 pt-3">
              {feed.isLoading ? (
                <div className="text-xs text-muted-foreground">Открываю переписку…</div>
              ) : (feed.data?.messages.length ? feed.data.messages.map((m) => (
                <div key={m.id} className="text-sm">
                  <span className="text-xs text-muted-foreground">
                    {m.direction === 'out' ? 'мы' : 'они'} · {m.authorName || '—'}
                    {m.createdAt ? ` · ${formatDateTime(m.createdAt)}` : ''}
                  </span>
                  <div className="text-foreground">{m.body}</div>
                </div>
              )) : <div className="text-xs text-muted-foreground">Разговора ещё не было.</div>)}
            </div>
          )}
        </div>
      ))}

      {visit.isError && (
        <p className="text-sm text-red-600 dark:text-red-400">
          {(visit.error as Error).message || 'Пропуск не выписан'}
        </p>
      )}
    </div>
  )
}

export default PartnerSpaces
