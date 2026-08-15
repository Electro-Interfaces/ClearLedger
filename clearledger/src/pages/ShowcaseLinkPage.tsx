/**
 * Витрина по ссылке — страница для того, у кого нет учётки.
 *
 * Открывается без входа: заказчик не станет заводить пароль ради одного экрана.
 * Отсюда ничего нельзя сделать — ни написать, ни ответить: аноним с ссылкой
 * смотрит, но не действует. Писать может тот, кто вошёл под собой.
 */
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ShieldCheck } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { getShowcaseByToken } from '@/pulse/pulseService'

export function ShowcaseLinkPage() {
  const { token = '' } = useParams()
  const q = useQuery({
    queryKey: ['showcase-link', token],
    queryFn: () => getShowcaseByToken(token),
    retry: false,
  })

  if (q.isError) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <Card className="max-w-sm">
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            Ссылка недействительна: её отозвали или истёк срок.
            Попросите новую у того, кто её присылал.
          </CardContent>
        </Card>
      </div>
    )
  }
  if (!q.data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Загрузка…
      </div>
    )
  }
  const d = q.data

  return (
    <div className="mx-auto max-w-3xl p-4 space-y-3 md:p-6">
      <div>
        <div className="text-lg font-semibold">{d.name}</div>
        <div className="text-[12px] text-muted-foreground">
          {d.company}{d.audience ? ` · для: ${d.audience}` : ''}
          {d.periodLabel ? ` · цифры ${d.periodLabel}` : ''}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {d.blocks.map((b) => (
          <Card key={b.key}>
            <CardContent className="p-3 space-y-2">
              <div className="text-sm font-medium">{b.title}</div>
              {b.hint && <div className="text-[11px] text-muted-foreground">{b.hint}</div>}
              {b.metrics.length > 0 && (
                <div className="grid gap-2 sm:grid-cols-2">
                  {b.metrics.map((m) => (
                    <div key={m.label} className="rounded-md border border-border px-2.5 py-1.5">
                      <div className="text-[11px] text-muted-foreground">{m.label}</div>
                      <div className="text-[15px] font-semibold tabular-nums">{m.value}</div>
                      {m.delta && (
                        <div className={cn('text-[11px]',
                          m.delta.tone === 'good' && 'text-emerald-600 dark:text-emerald-500',
                          m.delta.tone === 'warning' && 'text-amber-600 dark:text-amber-500',
                          !m.delta.tone && 'text-muted-foreground')}>
                          {m.delta.text}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {b.items.length > 0 && (
                <div className="divide-y divide-border/60">
                  {b.items.map((it, i) => (
                    <div key={i} className="flex items-start justify-between gap-3 py-1.5">
                      <div className="min-w-0">
                        <div className="truncate text-[13px]">{it.title}</div>
                        {it.detail && (
                          <div className="text-[11px] text-muted-foreground">{it.detail}</div>
                        )}
                      </div>
                      {it.amount && (
                        <div className="shrink-0 text-[13px] tabular-nums">{it.amount}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {b.note && <div className="text-[11px] text-muted-foreground">{b.note}</div>}
              {b.link && (
                <a href={b.link.href}
                  className="inline-flex items-center gap-1 text-[12px] text-primary
                             hover:underline">
                  {b.link.title} →
                </a>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border
                      px-3 py-2 text-[11px] text-muted-foreground">
        <ShieldCheck className="h-3.5 w-3.5" />
        <span>Данные на {d.asOf}</span>
        {d.owner && <span>· за цифры отвечает: {d.owner}</span>}
        {d.note && <span>· {d.note}</span>}
      </div>
    </div>
  )
}
