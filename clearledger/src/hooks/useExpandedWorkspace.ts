/**
 * «Развернуть экран» — рабочая область на всю ширину окна.
 *
 * Меню приложений, колонка подразделов и правая панель вместе съедают до 700 px:
 * широкие таблицы разрезов и рынка зажимались в узкое окно, а сворачивать три
 * колонки по отдельности никто не догадывался (замечание Чурилова, 23 и 28.09.2026:
 * «везде предусмотреть возможность раскрытия рабочей области»).
 *
 * Одно состояние на всё пространство, помнится в браузере: развернул — и так
 * работаешь, пока не свернёшь, на любом экране.
 */
import { useCallback, useSyncExternalStore } from 'react'

const KEY = 'cl-workspace-expanded'
const EVENT = 'cl-workspace-expanded'

// Без доступа к хранилищу (приватный режим) состояние живёт в памяти вкладки.
let mem = false

function read(): boolean {
  try { return localStorage.getItem(KEY) === '1' } catch { return mem }
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb)
  window.addEventListener('storage', cb)
  return () => {
    window.removeEventListener(EVENT, cb)
    window.removeEventListener('storage', cb)
  }
}

export function useExpandedWorkspace(): [boolean, (v: boolean) => void] {
  const expanded = useSyncExternalStore(subscribe, read, () => false)
  const set = useCallback((v: boolean) => {
    mem = v
    try { localStorage.setItem(KEY, v ? '1' : '0') } catch { /* приватный режим — хватит памяти вкладки */ }
    window.dispatchEvent(new Event(EVENT))
  }, [])
  return [expanded, set]
}
