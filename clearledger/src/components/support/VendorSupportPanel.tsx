/**
 * Разговор с технической поддержкой поставщика программы — из своего пространства.
 *
 * Замысел МАГа: наши инженеры заведены у клиента и работают внутри его контура,
 * но когда клиент ПИШЕТ нам, разговор обязан идти в нашем пространстве — там
 * очередь дежурных и история по всем клиентам. Отсюда мост: человек пишет здесь,
 * реплика уезжает к нам и встаёт в очередь оператора рядом со звонками, ответ
 * возвращается в эту же ленту.
 *
 * Панель показывается только когда связь включена (адрес и ключ на месте). Не
 * включена — остаётся прежний выход: чат приложения и телефон куратора, потому
 * что «написать некому» человек должен узнать до того, как напишет.
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2, LifeBuoy, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { formatDateTime } from '@/lib/formatDate'
import { partnerFeed, sendToPartner, type PartnerSpaceRef } from '@/services/partnerSpaceService'

export function VendorSupportPanel({ vendor, companyId }: { vendor: PartnerSpaceRef; companyId: string }) {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const bottom = useRef<HTMLDivElement>(null)

  const feed = useQuery({
    queryKey: ['partner-feed', vendor.code, companyId],
    queryFn: () => partnerFeed(vendor.code, companyId),
    // Ответ приходит мостом, а не веб-сокетом: опрос — честная цена за то, что
    // у поддержки и у клиента разные контейнеры и общей шины между ними нет.
    refetchInterval: 20_000,
  })

  const send = useMutation({
    mutationFn: (body: string) => sendToPartner(vendor.code, companyId, body),
    onSuccess: () => {
      setText('')
      qc.invalidateQueries({ queryKey: ['partner-feed', vendor.code, companyId] })
    },
  })

  const messages = feed.data?.messages || []
  useEffect(() => { bottom.current?.scrollIntoView({ block: 'end' }) }, [messages.length])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2.5">
        <LifeBuoy className="h-4 w-4 shrink-0 text-primary" />
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-foreground">{vendor.name}</div>
          <div className="truncate text-xs text-muted-foreground">
            Вопросы и ошибки по работе программы — сюда. Ответ придёт в эту же ленту.
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 py-3">
        {feed.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />Открываю переписку…
          </div>
        ) : messages.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Переписки ещё не было. Опишите, что случилось: экран, шаги и время —
            по ним поддержка найдёт событие быстрее, чем по одному «не работает».
          </p>
        ) : messages.map((m) => (
          <div key={m.id} className={m.direction === 'out' ? 'flex justify-end' : 'flex justify-start'}>
            <div className={`max-w-[85%] rounded-xl border px-3 py-2 text-sm ${
              m.direction === 'out'
                ? 'border-primary/30 bg-primary/10 dark:bg-primary/20'
                : 'border-border/60 bg-secondary/50'}`}>
              <div className="mb-0.5 flex items-baseline gap-2 text-[11px] text-muted-foreground">
                <span className="font-medium text-foreground/80">
                  {m.direction === 'out' ? (m.authorName || 'Вы') : (m.authorName || vendor.name)}
                </span>
                {m.createdAt && <span>{formatDateTime(m.createdAt)}</span>}
              </div>
              <div className="whitespace-pre-wrap break-words text-foreground">{m.body}</div>
              {/* Не дошедшее видно сразу: реплика осталась у нас, и человек должен
                  знать это, а не думать, что поддержка молчит. */}
              {m.direction === 'out' && !m.delivered && (
                <div className="mt-1 flex items-start gap-1 text-[11px] text-amber-600 dark:text-amber-400">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                  <span>{m.error || 'Не доставлено, попробуйте отправить ещё раз'}</span>
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <div className="border-t border-border/60 p-3">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Что случилось? Экран, шаги, время."
          rows={3}
          className="resize-none text-sm"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && text.trim()) send.mutate(text.trim())
          }}
        />
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-[11px] text-muted-foreground">Ctrl + Enter — отправить</span>
          <Button size="sm" className="gap-2" disabled={!text.trim() || send.isPending}
            onClick={() => send.mutate(text.trim())}>
            {send.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Отправить
          </Button>
        </div>
        {send.isError && (
          <p className="mt-2 text-xs text-red-600 dark:text-red-400">
            {(send.error as Error).message || 'Не удалось отправить'}
          </p>
        )}
      </div>
    </div>
  )
}
