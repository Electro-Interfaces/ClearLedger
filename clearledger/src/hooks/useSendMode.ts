/**
 * Чем отправляется сообщение — Enter или Ctrl+Enter.
 *
 * Привычка тут у каждого своя и меняться не должна от экрана к экрану: кто-то
 * годами шлёт по Enter и переносит строку через Shift, кто-то пишет в поле
 * абзацами и жмёт кнопку. Поэтому выбор личный и общий для всего пространства —
 * чат и обсуждение задачи ведут себя одинаково.
 *
 * Хранение и способ подписки повторяют useUiLevel: localStorage плюс
 * useSyncExternalStore, без провайдера в App.tsx. Настройка привязана к
 * устройству — на рабочем компьютере и в телефоне удобны разные.
 */
import { useCallback, useSyncExternalStore } from 'react'

/** enter — Enter шлёт, Shift+Enter переносит; ctrlEnter — наоборот. */
export type SendMode = 'enter' | 'ctrlEnter'

const KEY = 'clearledger-send-mode'
const EVENT = 'cl-sendmode-change'

function read(): SendMode {
  try {
    return localStorage.getItem(KEY) === 'ctrlEnter' ? 'ctrlEnter' : 'enter'
  } catch {
    return 'enter'
  }
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(EVENT, cb)
  window.addEventListener('storage', cb)
  return () => {
    window.removeEventListener(EVENT, cb)
    window.removeEventListener('storage', cb)
  }
}

export function setSendMode(mode: SendMode): void {
  try {
    localStorage.setItem(KEY, mode)
  } catch { /* приватный режим — просто не запомним */ }
  window.dispatchEvent(new Event(EVENT))
}

/**
 * shouldSend — нажатие отправляет сообщение?
 *
 * Ctrl+Enter шлёт при любом режиме: это привычка, которую ждут и те, кто выбрал
 * отправку по Enter, и ломать её незачем. Изменяется только смысл голого Enter.
 */
export function useSendMode(): {
  mode: SendMode
  byEnter: boolean
  setMode: (m: SendMode) => void
  toggle: () => void
  shouldSend: (e: { key: string; shiftKey: boolean; ctrlKey: boolean; metaKey: boolean }) => boolean
  hint: string
} {
  const mode = useSyncExternalStore(subscribe, read, () => 'enter' as SendMode)

  const shouldSend = useCallback((e: { key: string; shiftKey: boolean; ctrlKey: boolean; metaKey: boolean }) => {
    if (e.key !== 'Enter') return false
    if (e.ctrlKey || e.metaKey) return true
    return mode === 'enter' && !e.shiftKey
  }, [mode])

  return {
    mode,
    byEnter: mode === 'enter',
    setMode: useCallback((m: SendMode) => setSendMode(m), []),
    toggle: useCallback(() => setSendMode(read() === 'enter' ? 'ctrlEnter' : 'enter'), []),
    shouldSend,
    hint: mode === 'enter' ? 'Enter — отправить, Shift+Enter — новая строка'
                           : 'Enter — новая строка, Ctrl+Enter — отправить',
  }
}
