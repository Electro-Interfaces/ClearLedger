/**
 * Аудитор — сквозная панель пространства, как чат: открывается справа доком или
 * окном из шапки, но, в отличие от чата, ЗНАЕТ, откуда его позвали. Маршрут и
 * продукт уходят вместе с вопросом, поэтому «а что здесь не так?» на экране
 * закрытия периода и на экране контрагентов означает разные проверки.
 *
 * Панель ничего не решает сама: вопрос уходит в сервис `auditor` стека, тот
 * выбирает навыки, берёт данные ТОКЕНОМ спросившего и отвечает потоком.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Bot, CornerDownLeft, Loader2, Square, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Markdown } from '@/components/info/Markdown'
import { useCompany } from '@/contexts/CompanyContext'
import { productForPath } from '@/config/spaceProducts'
import * as auditor from '@/services/spaceAuditorService'
import { cn } from '@/lib/utils'

interface Message {
  role: 'user' | 'assistant'
  content: string
  findings?: auditor.AuditorFinding[]
}

/** Блоки находок вырезаются из текста: они показываются карточками ниже ответа. */
const withoutFindings = (text: string) => text.replace(/```finding[\s\S]*?```/g, '').trim()

/** Уровень находки: цвет альфа-шкалой — один класс работает в обеих темах. */
const SEVERITY = {
  high: { label: 'важно', cls: 'border-red-500/40 bg-red-500/5 text-red-600 dark:text-red-400' },
  medium: { label: 'стоит посмотреть', cls: 'border-amber-500/40 bg-amber-500/5 text-amber-600 dark:text-amber-400' },
  low: { label: 'к сведению', cls: 'border-border bg-muted/40 text-muted-foreground' },
} as const

export function AuditorPanel() {
  const { pathname } = useLocation()
  const { companyId } = useCompany()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const ctrlRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const product = productForPath(pathname)
  const context = useMemo<auditor.AuditorContext>(() => ({
    path: pathname,
    product: product?.label ?? null,
    params: Object.fromEntries(new URLSearchParams(window.location.search)),
  }), [pathname, product])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, status])
  // Панель закрыли на середине ответа — обрываем поток: незаконченный ответ никто
  // не прочитает, а обращение к модели платное.
  useEffect(() => () => ctrlRef.current?.abort(), [])

  function send(text: string) {
    const question = text.trim()
    if (!question || busy || !companyId) return
    setInput('')
    setError('')
    setBusy(true)
    setStatus('Думаю…')

    const history = messages.map((m) => ({ role: m.role, content: m.content }))
    setMessages((prev) => [...prev, { role: 'user', content: question }, { role: 'assistant', content: '' }])

    let answer = ''
    ctrlRef.current = auditor.ask(question, context, companyId, history, {
      onStatus: setStatus,
      onText: (chunk) => {
        answer += chunk
        setMessages((prev) => {
          const next = [...prev]
          next[next.length - 1] = { role: 'assistant', content: answer }
          return next
        })
      },
      onFindings: (findings) => {
        setMessages((prev) => {
          const next = [...prev]
          next[next.length - 1] = { ...next[next.length - 1], findings }
          return next
        })
      },
      onError: (message) => setError(message),
      onDone: () => { setBusy(false); setStatus('') },
    })
  }

  function stop() {
    ctrlRef.current?.abort()
    setBusy(false)
    setStatus('')
  }

  return (
    <div className="flex h-full flex-col">
      {/* Где стоит человек — видно ему самому: иначе непонятно, почему аудитор
          отвечает про этот раздел, а не про пространство целиком. */}
      <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2 text-xs text-muted-foreground">
        <Bot className="size-3.5 shrink-0" />
        <span className="truncate">
          Смотрю вместе с вами{product ? <> · <span className="text-foreground">{product.label}</span></> : null}
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {!messages.length && (
          <div className="space-y-3 pt-4 text-sm text-muted-foreground">
            <p>Спросите про то, что видите на экране. Я смотрю данные пространства и отвечаю цифрами.</p>
            <div className="flex flex-col gap-1.5">
              {['Что здесь не так?', 'Можно закрывать месяц?', 'Кто должен и сколько?'].map((q) => (
                <button key={q} type="button" onClick={() => send(q)}
                  className="rounded-lg border border-border/60 px-3 py-2 text-left text-foreground transition-colors hover:bg-accent">
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={cn('text-sm', m.role === 'user' && 'flex justify-end')}>
            {m.role === 'user' ? (
              <div className="max-w-[85%] rounded-xl bg-primary px-3 py-2 text-white">{m.content}</div>
            ) : (
              <div className="space-y-2">
                {m.content
                  ? <Markdown content={withoutFindings(m.content)} />
                  : busy && <span className="text-muted-foreground">{status || 'Думаю…'}</span>}
                {m.findings?.map((f, j) => (
                  <div key={j} className={cn('rounded-lg border px-3 py-2', SEVERITY[f.severity]?.cls ?? SEVERITY.low.cls)}>
                    <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide">
                      <TriangleAlert className="size-3.5" />
                      {SEVERITY[f.severity]?.label ?? f.severity}
                    </div>
                    <div className="mt-1 font-medium text-foreground">{f.title}</div>
                    {f.detail && <div className="mt-0.5 text-sm text-muted-foreground">{f.detail}</div>}
                    {f.action && <div className="mt-1 text-sm text-foreground">Что сделать: {f.action}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}

        {busy && status && messages.at(-1)?.content && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />{status}
          </div>
        )}
        {error && (
          <div className="rounded-lg border border-red-500/40 bg-red-500/5 px-3 py-2 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-border/60 p-2">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) }
            }}
            rows={2}
            placeholder="Спросите про этот экран…"
            className="min-h-[44px] flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          />
          {busy ? (
            <Button size="icon" variant="outline" onClick={stop} title="Остановить"><Square className="size-4" /></Button>
          ) : (
            <Button size="icon" onClick={() => send(input)} disabled={!input.trim()} title="Спросить (Enter)">
              <CornerDownLeft className="size-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
