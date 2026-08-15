/**
 * Мастерская — настоящий Claude Code в терминале, а не наша прослойка поверх него.
 *
 * Здесь намеренно НЕТ своей логики: ни выбора навыков, ни разбора ответа, ни находок.
 * Всё, что умеет CLI — сессии, `/clear`, `/login`, горячие клавиши, новые версии, — идёт
 * как есть. Прослойка отставала бы от CLI и молча меняла его поведение; на этом мы уже
 * обожглись, когда мастерская из панели была потоком текста без tty.
 *
 * На той стороне PTY в контейнере пространства (`services/auditor`, `/ws/terminal`),
 * рабочий каталог `/work`. Доступ — админ пространства и включённый `AUDITOR_WORKSHOP`.
 */
import { useEffect, useRef, useState } from 'react'
import { Loader2, TerminalSquare } from 'lucide-react'
import { DictateButton, useDictation } from './DictateButton'
import { useQuery } from '@tanstack/react-query'
import * as auditor from '@/services/spaceAuditorService'
// Стили статикой, а не `import()`: rollup не резолвит CSS как динамический модуль и
// роняет сборку целиком. Сам компонент ленивый, поэтому его CSS и так уедет в свой чанк.
import '@xterm/xterm/css/xterm.css'
import { getToken } from '@/services/apiClient'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'

export function AuditorTerminal() {
  const { companyId } = useCompany()
  const hostRef = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<'connecting' | 'open' | 'closed'>('connecting')
  const [error, setError] = useState('')
  // Диктовка в терминал: текст ПЕЧАТАЕТСЯ в PTY, а не отправляется — человек видит его
  // в приглашении и жмёт Enter сам. Отправлять за него нельзя: распознавание ошибается,
  // а команда в мастерской может быть недешёвой.
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<number | undefined>(undefined)
  // Диктовка удержанием клавиши: в терминале руки на клавиатуре, и тянуться мышью к
  // кнопке микрофона неудобно. Текст ПЕЧАТАЕТСЯ в приглашение, а не отправляется:
  // распознавание ошибается, а команда в мастерской может быть недешёвой.
  const dictation = useDictation((text) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'data', data: text }))
    }
  })
  const dictRef = useRef(dictation)
  dictRef.current = dictation
  // Пересоединение без перезагрузки страницы: счётчик перезапускает эффект целиком, и
  // терминал собирается заново. `fresh` — начать сеанс с нуля, а не вернуться в идущий.
  const [attempt, setAttempt] = useState(0)
  const freshRef = useRef(false)
  const reconnect = (fresh: boolean) => {
    freshRef.current = fresh
    setState('connecting')
    setAttempt((n) => n + 1)
  }
  // Вкладки — как несколько окон терминала на своей машине: разные задачи идут
  // параллельно, и все продолжают работать, пока смотришь в одну. Переключение это
  // просто аттач к другому сеансу, поэтому отдельного состояния на вкладку не нужно.
  const [tab, setTab] = useState(0)
  const { data: sessions } = useQuery({
    queryKey: ['auditor-sessions'], queryFn: auditor.getSessions,
    refetchInterval: 15_000, retry: false,
  })
  const { data: health } = useQuery({
    queryKey: ['auditor-health'], queryFn: auditor.getHealth, staleTime: 60_000, retry: false,
  })

  useEffect(() => {
    if (!hostRef.current || !companyId) return
    let disposed = false
    let cleanup = () => {}

    // Терминал грузится лениво: xterm и его стили нужны только тут, а тянуть их в общий
    // чанк ради раздела, куда заходит один админ, — лишние килобайты всем остальным.
    void (async () => {
      const [{ Terminal }, { FitAddon }] = await Promise.all([
        import('@xterm/xterm'),
        import('@xterm/addon-fit'),
      ])
      if (disposed || !hostRef.current) return

      const term = new Terminal({
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        fontSize: 13,
        cursorBlink: true,
        convertEol: true,
        // Цвета берём у страницы, а не жёстко: панель живёт и в тёмной, и в светлой теме.
        theme: pageTheme(),
      })
      const fit = new FitAddon()
      term.loadAddon(fit)
      term.open(hostRef.current)
      fit.fit()

      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${location.host}/auditor/ws/terminal`)
      wsRef.current = ws

      ws.onopen = () => {
        setState('open')
        setError('')   // связь вернулась — старое сообщение об ошибке иначе висит навсегда
        // Токен уходит ПЕРВЫМ СООБЩЕНИЕМ, а не в адресе: адрес попадает в логи кромки.
        ws.send(JSON.stringify({
          type: 'start', token: getToken() ?? '', companyId,
          cols: term.cols, rows: term.rows, fresh: freshRef.current, tab,
        }))
        freshRef.current = false
      }
      ws.onmessage = (e) => term.write(typeof e.data === 'string' ? e.data : '')
      ws.onerror = () => setError('Терминал недоступен: сервис аудитора не отвечает')
      ws.onclose = () => {
        if (disposed) return
        // Возвращаемся САМИ. Сеанс на той стороне живёт в tmux и продолжает работать без
        // нас, поэтому обрыв — это не конец работы, а несколько секунд без картинки.
        // Просить человека нажать кнопку здесь незачем: он в это время смотрит на экран
        // и ждёт ответа агента, а не разбирается со связью.
        term.write('\r\n\x1b[33m— связь оборвалась, возвращаюсь в сеанс…\x1b[0m\r\n')
        setState('connecting')
        retryRef.current = window.setTimeout(() => setAttempt((n) => n + 1), 2000)
      }

      // Встречный такт. Серверные ping-кадры браузеру не видны, поэтому о своей жизни
      // сообщаем сами: сервер такое сообщение игнорирует, но трафик идёт, и мёртвое
      // соединение обнаруживается за десятки секунд, а не висит молча.
      const tick = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
      }, 25_000)

      term.onData((d) => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'data', data: d })) })

      // Копирование и вставка. Из мастерской копируют постоянно — цифры, запросы, куски
      // ответа, — и без этого приходится переписывать руками.
      //
      // Ctrl+C двусмысленна: с выделением это «скопировать», без выделения — прерывание
      // работы агента. Различаем по наличию выделения, как делают все терминалы.
      // Ctrl+Shift+C / Ctrl+Shift+V — привычная пара, работает всегда.
      const copy = () => { void navigator.clipboard.writeText(term.getSelection()) }
      const paste = () => {
        void navigator.clipboard.readText().then((t) => {
          if (t && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'data', data: t }))
        })
      }
      term.attachCustomKeyEventHandler((e) => {
        // Диктовка, пока держишь Ctrl+Пробел. Одиночный пробел под это не отдать: в
        // терминале он обычный символ, и «удержание» ничем не отличается от набора.
        // В нативном CLI это работает от микрофона машины, а здесь микрофон у браузера.
        if (e.code === 'Space' && (e.ctrlKey || e.metaKey)) {
          if (e.type === 'keydown' && dictRef.current.state === 'idle') void dictRef.current.start()
          if (e.type === 'keyup' && dictRef.current.state === 'rec') dictRef.current.stop()
          return false
        }
        if (e.type !== 'keydown' || !(e.ctrlKey || e.metaKey)) return true
        if (e.code === 'KeyC' && (e.shiftKey || term.hasSelection())) { copy(); return false }
        if (e.code === 'KeyV' && e.shiftKey) { paste(); return false }
        // Insert-пара: Ctrl+Insert копирует, Shift+Insert вставляет — так привыкли в Windows.
        if (e.code === 'Insert' && term.hasSelection()) { copy(); return false }
        return true
      })

      // Размер окна должен доезжать до PTY: TUI рисует рамки по нему, и без ресайза
      // интерфейс разъезжается при первом же изменении ширины панели.
      const ro = new ResizeObserver(() => {
        try { fit.fit() } catch { /* элемент скрыт */ }
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
        }
      })
      ro.observe(hostRef.current)

      cleanup = () => { clearInterval(tick); ro.disconnect(); ws.close(); term.dispose() }
    })()

    return () => { disposed = true; clearTimeout(retryRef.current); cleanup() }
  }, [companyId, attempt, tab])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border/60 px-4 py-2 text-xs text-muted-foreground">
        <TerminalSquare className="size-3.5" />
        <span className="shrink-0">Мастерская · <span className="text-foreground">/work</span></span>
        {/* Вкладка с работающим агентом помечена точкой: он считает и без открытого окна. */}
        <span className="flex shrink-0 items-center gap-0.5">
          {(sessions ?? [{ tab: 0, live: false }]).map((s) => (
            <button key={s.tab} type="button" onClick={() => setTab(s.tab)}
              title={s.live ? 'здесь идёт работа' : 'свободная вкладка'}
              className={cn('flex min-h-6 items-center gap-1 rounded-md px-2 py-0.5 transition-colors',
                s.tab === tab ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent hover:text-foreground')}>
              {s.tab + 1}
              {s.live && <span className={cn('size-1.5 rounded-full',
                s.tab === tab ? 'bg-primary' : 'bg-emerald-500')} />}
            </button>
          ))}
        </span>
        {state === 'connecting' && <Loader2 className="size-3.5 animate-spin" />}
        {health?.dictation && state === 'open' && (
          <>
            <span className="ml-2">
              <DictateButton title="Продиктовать команду"
                onText={(t) => wsRef.current?.readyState === WebSocket.OPEN
                  && wsRef.current.send(JSON.stringify({ type: 'data', data: t }))} />
            </span>
            <span className="max-xl:hidden">
              {dictation.state === 'rec' ? (
                <span className="text-foreground">говорите — отпустите Ctrl+Пробел, чтобы распознать</span>
              ) : dictation.state === 'busy' ? 'распознаю…' : 'диктовка — Ctrl+Пробел, копирование — Ctrl+C'}
            </span>
          </>
        )}
        {/* Сеанс живёт на той стороне и переживает обрыв, поэтому «начать заново» — это
            осознанное действие (закрыть работу агента), а не способ починить связь. */}
        <button type="button" onClick={() => reconnect(true)}
          className="ml-auto rounded-md border border-border/60 px-2 py-0.5 hover:bg-accent hover:text-foreground">
          Начать заново
        </button>
      </div>
      {error && <div className="border-b border-red-500/40 bg-red-500/5 px-4 py-2 text-sm text-red-600 dark:text-red-400">{error}</div>}
      {/* 🔴 Никаких отступов на контейнере терминала.
          FitAddon считает число колонок по `clientWidth`, а он ВКЛЮЧАЕТ padding: с `px-2`
          выходило на два символа больше, чем помещается. Строки переносились не там, где
          видно, и при прокрутке слева оставался столбик из первых двух символов прошлого
          кадра — «Чт», «Зн», «Чу». Отступ теперь у обёртки, снаружи. */}
      <div className="min-h-0 flex-1 overflow-hidden px-2 py-1">
        <div ref={hostRef} className="size-full" />
      </div>
    </div>
  )
}

/** Цвета терминала из вычисленных цветов страницы — чтобы он не был белым на тёмной. */
function pageTheme() {
  const cs = getComputedStyle(document.body)
  return { background: cs.backgroundColor || '#0b1220', foreground: cs.color || '#e5e7eb' }
}
