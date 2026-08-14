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
// Стили статикой, а не `import()`: rollup не резолвит CSS как динамический модуль и
// роняет сборку целиком. Сам компонент ленивый, поэтому его CSS и так уедет в свой чанк.
import '@xterm/xterm/css/xterm.css'
import { getToken } from '@/services/apiClient'
import { useCompany } from '@/contexts/CompanyContext'

export function AuditorTerminal() {
  const { companyId } = useCompany()
  const hostRef = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<'connecting' | 'open' | 'closed'>('connecting')
  const [error, setError] = useState('')

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

      ws.onopen = () => {
        setState('open')
        // Токен уходит ПЕРВЫМ СООБЩЕНИЕМ, а не в адресе: адрес попадает в логи кромки.
        ws.send(JSON.stringify({
          type: 'start', token: getToken() ?? '', companyId,
          cols: term.cols, rows: term.rows,
        }))
      }
      ws.onmessage = (e) => term.write(typeof e.data === 'string' ? e.data : '')
      ws.onerror = () => setError('Терминал недоступен: сервис аудитора не отвечает')
      ws.onclose = () => setState('closed')

      term.onData((d) => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'data', data: d })) })

      // Размер окна должен доезжать до PTY: TUI рисует рамки по нему, и без ресайза
      // интерфейс разъезжается при первом же изменении ширины панели.
      const ro = new ResizeObserver(() => {
        try { fit.fit() } catch { /* элемент скрыт */ }
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
        }
      })
      ro.observe(hostRef.current)

      cleanup = () => { ro.disconnect(); ws.close(); term.dispose() }
    })()

    return () => { disposed = true; cleanup() }
  }, [companyId])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border/60 px-4 py-2 text-xs text-muted-foreground">
        <TerminalSquare className="size-3.5" />
        <span>Мастерская · Claude Code в <span className="text-foreground">/work</span></span>
        {state === 'connecting' && <Loader2 className="size-3.5 animate-spin" />}
        {state === 'closed' && (
          <button type="button" onClick={() => location.reload()}
            className="ml-auto rounded-md border border-border/60 px-2 py-0.5 hover:bg-accent hover:text-foreground">
            Сессия закрыта — начать заново
          </button>
        )}
      </div>
      {error && <div className="border-b border-red-500/40 bg-red-500/5 px-4 py-2 text-sm text-red-600 dark:text-red-400">{error}</div>}
      <div ref={hostRef} className="min-h-0 flex-1 overflow-hidden px-2 py-1" />
    </div>
  )
}

/** Цвета терминала из вычисленных цветов страницы — чтобы он не был белым на тёмной. */
function pageTheme() {
  const cs = getComputedStyle(document.body)
  return { background: cs.backgroundColor || '#0b1220', foreground: cs.color || '#e5e7eb' }
}
