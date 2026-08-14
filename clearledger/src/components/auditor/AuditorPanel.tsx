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
import { useQuery } from '@tanstack/react-query'
import { Bot, CornerDownLeft, Loader2, Paperclip, RotateCcw, ShieldOff, Square, ThumbsDown, ThumbsUp, TriangleAlert } from 'lucide-react'
import { toast } from 'sonner'
import { DictateButton } from './DictateButton'
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
  /** id записи журнала — есть только у ответов по данным: их и оценивают. */
  runId?: string
  verdict?: auditor.AuditorVerdict
}

/**
 * Оценка ответа — вход петли обучения, а не рейтинг.
 *
 * «Это не ошибка» ценнее прочего: за ним стоит причина, из которой рождается правило
 * исключения, и агент перестаёт повторять ложную находку. Поэтому у неверного ответа и
 * у ложной находки спрашивается «почему» — оценка без объяснения ничего не исправляет.
 */
const VERDICTS: { key: auditor.AuditorVerdict; label: string; icon: typeof ThumbsUp; ask: boolean }[] = [
  { key: 'ok', label: 'Верно', icon: ThumbsUp, ask: false },
  { key: 'wrong', label: 'Неверно', icon: ThumbsDown, ask: true },
  { key: 'not_an_issue', label: 'Это не ошибка', icon: ShieldOff, ask: true },
]

function Rating({ runId, verdict, onRated }: {
  runId: string
  verdict?: auditor.AuditorVerdict
  onRated: (v: auditor.AuditorVerdict) => void
}) {
  const { companyId } = useCompany()
  const [asking, setAsking] = useState<auditor.AuditorVerdict | null>(null)
  const [why, setWhy] = useState('')
  const [busy, setBusy] = useState(false)

  async function send(v: auditor.AuditorVerdict, feedback?: string) {
    setBusy(true)
    try {
      await auditor.rateRun(companyId, runId, v, feedback)
      onRated(v)
      setAsking(null)
      setWhy('')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (asking) {
    const item = VERDICTS.find((x) => x.key === asking)!
    return (
      <div className="mt-2 rounded-lg border border-border/60 bg-muted/30 p-2">
        <div className="mb-1.5 text-xs text-muted-foreground">
          {asking === 'not_an_issue' ? 'Почему это не ошибка? Ответ станет правилом — агент перестанет её повторять.' : 'Что именно не так? Это войдёт в разбор.'}
        </div>
        <textarea value={why} onChange={(e) => setWhy(e.target.value)} rows={2} autoFocus
          className="w-full resize-none rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:border-primary" />
        <div className="mt-1.5 flex gap-1.5">
          <Button size="sm" disabled={busy} onClick={() => send(item.key, why)}>Сохранить</Button>
          <Button size="sm" variant="ghost" onClick={() => { setAsking(null); setWhy('') }}>Отмена</Button>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-1.5 flex items-center gap-1">
      {VERDICTS.map((v) => (
        <button key={v.key} type="button" disabled={busy}
          onClick={() => (v.ask ? setAsking(v.key) : send(v.key))}
          title={v.label}
          className={cn('inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] transition-colors',
            verdict === v.key
              ? 'bg-primary/10 text-primary'
              : 'text-muted-foreground/60 hover:bg-accent hover:text-foreground')}>
          <v.icon className="size-3.5" />
          {verdict === v.key && <span>{v.label}</span>}
        </button>
      ))}
    </div>
  )
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
  // Приложенные файлы живут до следующего вопроса: спросили — отпустили. Держать их
  // на весь разговор значит незаметно гонять выписку в каждый следующий запрос.
  const [files, setFiles] = useState<auditor.AuditorFile[]>([])
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [reloading, setReloading] = useState(false)
  const ctrlRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)


  // Микрофон показываем, только если распознаватель в стеке поднят.
  const { data: health } = useQuery({
    queryKey: ['auditor-health'], queryFn: auditor.getHealth, staleTime: 60_000, retry: false,
  })

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

  async function attach(f: File | null | undefined) {
    if (!f || !companyId) return
    setUploading(true)
    try {
      // Загрузка ждётся ДО setFiles: `await` внутри не-async колбэка обновления
      // состояния не компилируется, и сборка падала на всём фронте.
      const uploaded = await auditor.uploadFile(companyId, f)
      setFiles((prev) => [...prev, uploaded])
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function send(text: string) {
    const question = text.trim()
    if (!question || busy || !companyId) return
    setInput('')
    setError('')
    setBusy(true)
    setStatus('Думаю…')

    const ids = files.map((f) => f.id)
    const names = files.map((f) => f.name)
    setFiles([])

    const history = messages.map((m) => ({ role: m.role, content: m.content }))
    setMessages((prev) => [...prev,
      { role: 'user', content: names.length ? `${question}\n📎 ${names.join(', ')}` : question },
      { role: 'assistant', content: '' }])

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
      onRun: (runId) => {
        setMessages((prev) => {
          const next = [...prev]
          next[next.length - 1] = { ...next[next.length - 1], runId }
          return next
        })
      },
      onError: (message) => setError(message),
      onDone: () => { setBusy(false); setStatus('') },
    }, ids)
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
                {/* Оценка — только у ответов по данным: разговорной реплике «верно
                    или неверно» не про что. */}
                {m.runId && (
                  <Rating runId={m.runId} verdict={m.verdict}
                    onRated={(v) => setMessages((prev) => prev.map((x, k) => (k === i ? { ...x, verdict: v } : x)))} />
                )}
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
        {/* Приложенное — перед строкой ввода: человек должен видеть, что уйдёт вместе
            с вопросом, и успеть снять лишнее. */}
        {!!files.length && (
          <div className="mb-1.5 flex flex-wrap gap-1.5">
            {files.map((f) => (
              <span key={f.id} className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-muted/40 px-2 py-1 text-xs">
                <Paperclip className="size-3" />
                {f.name}
                <span className="text-muted-foreground">{Math.round(f.size / 1024)} КБ</span>
                <button type="button" title="Убрать"
                  onClick={() => setFiles((prev) => prev.filter((x) => x.id !== f.id))}
                  className="text-muted-foreground hover:text-foreground">×</button>
              </span>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2">
          <input ref={fileRef} type="file" className="hidden"
            accept=".xlsx,.xlsm,.xls,.csv,.tsv,.pdf,.docx,.doc,.txt,.md,.json,.xml"
            onChange={(e) => attach(e.target.files?.[0])} />
          {health?.dictation && (
            <DictateButton disabled={busy}
              onText={(t) => setInput((v) => (v ? `${v} ${t}` : t))}
              title="Продиктовать вопрос" />
          )}
          <Button size="icon" variant="outline" disabled={uploading || busy}
            onClick={() => fileRef.current?.click()}
            title="Приложить файл: выписку, реестр, акт">
            {uploading ? <Loader2 className="size-4 animate-spin" /> : <Paperclip className="size-4" />}
          </Button>
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
