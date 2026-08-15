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
import type { Terminal } from '@xterm/xterm'
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
  // Компания нужна ТОЛЬКО чтобы сервис проверил право администратора. Сама мастерская
  // работает с рабочей папкой агента, а она одна на пространство — поэтому смена
  // организации в шапке не должна рвать терминал и уносить открытый сеанс. Берём через
  // ref, а не зависимостью эффекта.
  const { companyId } = useCompany()
  const companyRef = useRef(companyId)
  companyRef.current = companyId
  const hostRef = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<'connecting' | 'open' | 'closed' | 'detached'>('connecting')
  const [error, setError] = useState('')
  // Счётчик подряд идущих неудач. Сбрасывается, как только связь встала: обрыв через час
  // работы — это первая попытка, а не четвёртая.
  const tries = useRef(0)
  // Диктовка в терминал: текст ПЕЧАТАЕТСЯ в PTY, а не отправляется — человек видит его
  // в приглашении и жмёт Enter сам. Отправлять за него нельзя: распознавание ошибается,
  // а команда в мастерской может быть недешёвой.
  const wsRef = useRef<WebSocket | null>(null)
  const termRef = useRef<Terminal | null>(null)
  const retryRef = useRef<number | undefined>(undefined)

  /**
   * Продиктованный текст печатается в приглашение — и фокус возвращается в терминал.
   *
   * Без возврата фокуса текст появлялся, но клавиатура оставалась у кнопки микрофона
   * (или у промиса записи), и Enter уходил в никуда: приходилось тыкать мышью в строку.
   * Отправляем не за человека: распознавание ошибается, а команда бывает недешёвой.
   */
  const typeIntoTerminal = (text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'data', data: text }))
    }
    termRef.current?.focus()
  }
  const dictation = useDictation(typeIntoTerminal)
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

  // Зависим от того, ЕСТЬ ли компания, а не от того, какая именно: терминал должен
  // подняться, когда она загрузилась, и пережить переключение организации в шапке.
  const hasCompany = !!companyId

  useEffect(() => {
    if (!hostRef.current || !hasCompany) return
    let disposed = false
    let cleanup = () => {}

    // Терминал грузится лениво: xterm и его стили нужны только тут, а тянуть их в общий
    // чанк ради раздела, куда заходит один админ, — лишние килобайты всем остальным.
    void (async () => {
      const [{ Terminal }, { FitAddon }, { WebglAddon }] = await Promise.all([
        import('@xterm/xterm'),
        import('@xterm/addon-fit'),
        import('@xterm/addon-webgl'),
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

      // 🔴 Рендерер по умолчанию (DOM) оставлял мусор в ячейках, ставших пустыми: после
      // прокрутки между маркером списка и текстом торчала буква прошлого кадра — «●тПроверю»
      // вместо «● Проверю», а слева выстраивался столбик обрывков «го», «Об», «На».
      // WebGL перерисовывает кадр целиком и этой болезни не имеет.
      //
      // Контекста может не быть (старый драйвер, отключённое ускорение) — тогда молча
      // остаёмся на DOM: терминал с артефактами лучше, чем терминал, который не открылся.
      try {
        const webgl = new WebglAddon()
        webgl.onContextLoss(() => webgl.dispose())
        term.loadAddon(webgl)
      } catch { /* нет WebGL — работаем на DOM-рендерере */ }

      fit.fit()
      termRef.current = term
      term.focus()   // открыли раздел — можно печатать сразу, без клика в поле

      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${location.host}/auditor/ws/terminal`)
      wsRef.current = ws

      ws.onopen = () => {
        setState('open')
        setError('')   // связь вернулась — старое сообщение об ошибке иначе висит навсегда
        tries.current = 0
        // Токен уходит ПЕРВЫМ СООБЩЕНИЕМ, а не в адресе: адрес попадает в логи кромки.
        ws.send(JSON.stringify({
          type: 'start', token: getToken() ?? '', companyId: companyRef.current,
          cols: term.cols, rows: term.rows, fresh: freshRef.current, tab,
        }))
        freshRef.current = false
      }
      ws.onmessage = (e) => term.write(typeof e.data === 'string' ? e.data : '')
      ws.onerror = () => setError('Терминал недоступен: сервис аудитора не отвечает')
      ws.onclose = (e) => {
        if (disposed) return
        // 4001 — сеанс закрыт или отдан другому окну. Возвращаться нельзя: две вкладки
        // начнут выкидывать друг друга по кругу. Ждём решения человека.
        if (e.code === 4001) {
          setState('detached')
          return
        }
        // Обрыв связи — другое дело. Сеанс на той стороне живёт в tmux и продолжает
        // работать без нас, поэтому это не конец работы, а несколько секунд без картинки:
        // возвращаемся сами, человек в это время ждёт ответа агента, а не чинит связь.
        //
        // Попыток три, с растущей паузой: если не вышло и за это время — дело не в связи,
        // и молотить дальше значит грузить сервис впустую.
        tries.current += 1
        if (tries.current > 3) {
          term.write('\r\n\x1b[31m— связь не восстанавливается, откройте мастерскую заново\x1b[0m\r\n')
          setState('closed')
          return
        }
        term.write(`\r\n\x1b[33m— связь оборвалась, возвращаюсь в сеанс (попытка ${tries.current})…\x1b[0m\r\n`)
        setState('connecting')
        retryRef.current = window.setTimeout(() => setAttempt((n) => n + 1), 2000 * tries.current)
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

      cleanup = () => {
        clearInterval(tick); ro.disconnect(); ws.close(); term.dispose()
        termRef.current = null   // иначе диктовка после ухода целится в уничтоженный терминал
      }
    })()

    return () => { disposed = true; clearTimeout(retryRef.current); cleanup() }
  }, [attempt, tab, hasCompany])

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
              <DictateButton title="Продиктовать команду" onText={typeIntoTerminal} />
            </span>
            <span className="max-xl:hidden">
              {dictation.state === 'rec' ? (
                <span className="text-foreground">говорите — отпустите Ctrl+Пробел, чтобы распознать</span>
              ) : dictation.state === 'busy' ? 'распознаю…' : 'диктовка — Ctrl+Пробел, копирование — Ctrl+C'}
            </span>
          </>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-2">
          {/* Отсоединение — не ошибка, а развилка: вернуть работу сюда или оставить там,
              где её открыли. Молча возвращаться нельзя, иначе вкладки зациклятся. */}
          {state === 'detached' && (
            <>
              <span className="text-amber-600 dark:text-amber-400">открыто в другом окне</span>
              <button type="button" onClick={() => reconnect(false)}
                className="rounded-md border border-border/60 px-2 py-0.5 hover:bg-accent hover:text-foreground">
                Вернуть сюда
              </button>
            </>
          )}
          {state === 'closed' && (
            <button type="button" onClick={() => reconnect(false)}
              className="rounded-md border border-border/60 px-2 py-0.5 hover:bg-accent hover:text-foreground">
              Подключиться
            </button>
          )}
          {/* Сеанс живёт на той стороне и переживает обрыв, поэтому «начать заново» — это
              осознанное действие (закрыть работу агента), а не способ починить связь. */}
          <button type="button" onClick={() => reconnect(true)}
            className="rounded-md border border-border/60 px-2 py-0.5 hover:bg-accent hover:text-foreground">
            Начать заново
          </button>
        </span>
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
