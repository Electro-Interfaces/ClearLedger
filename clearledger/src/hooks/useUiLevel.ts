/**
 * Режим работы: «Простой» / «Расширенный».
 *
 * Исходная задача продукта: по умолчанию человек видит спокойный экран с тем,
 * что нужно каждый день, а когда требуется — одним переключателем открывает
 * все функции. Функциональность при этом НЕ урезается: простой режим ничего
 * не отключает, он только убирает с глаз редкое.
 *
 * Три правила, без которых режим вредит (стандарт PROGRESSIVE_DISCLOSURE_CONCEPT.md):
 *
 * 1. Критичное для корректности видно ВСЕГДА. Профиль НДС, ключ привязки,
 *    метод себестоимости, предупреждения о демо-данных не прячутся никогда —
 *    иначе человек сдаёт в бухгалтерию число, происхождения которого не видел.
 *    Такое не оборачивать в <AdvancedOnly> ни при каких условиях.
 * 2. Скрытое обозначено. Там, где что-то убрано, показывается, сколько именно
 *    и как открыть (см. AdvancedOnly и AdvancedHint) — «тихо исчезло» хуже,
 *    чем «видно, но сложно».
 * 3. Переключение мгновенно и обратимо, состояние переживает перезагрузку.
 *
 * Механика намеренно повторяет useGuideMode: класс на <html> (`cl-simple`)
 * плюс localStorage. Здесь дополнительно useSyncExternalStore — компонентам
 * нужен реактивный уровень, а не только CSS-хук, при этом провайдер в App.tsx
 * не требуется.
 */
import { useCallback, useSyncExternalStore } from 'react'

export type UiLevel = 'simple' | 'advanced'

const KEY = 'clearledger-ui-level'
const EVENT = 'cl-uilevel-change'
const CLASS = 'cl-simple'

function read(): UiLevel {
  try {
    return localStorage.getItem(KEY) === 'advanced' ? 'advanced' : 'simple'
  } catch {
    return 'simple'
  }
}

function applyClass(level: UiLevel): void {
  document.documentElement.classList.toggle(CLASS, level === 'simple')
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(EVENT, cb)
  // storage — синхронизация между вкладками одного пользователя.
  window.addEventListener('storage', cb)
  return () => {
    window.removeEventListener(EVENT, cb)
    window.removeEventListener('storage', cb)
  }
}

/** Ставит класс до первого рендера, чтобы простой режим не «мигал» расширенным. */
export function initUiLevel(): void {
  applyClass(read())
}

export function setUiLevel(level: UiLevel): void {
  try {
    localStorage.setItem(KEY, level)
  } catch { /* приватный режим — переживём, класс всё равно применится */ }
  applyClass(level)
  window.dispatchEvent(new Event(EVENT))
}

export function useUiLevel(): {
  level: UiLevel
  isSimple: boolean
  isAdvanced: boolean
  setLevel: (level: UiLevel) => void
  toggle: () => void
} {
  const level = useSyncExternalStore(subscribe, read, () => 'simple' as UiLevel)

  const setLevel = useCallback((next: UiLevel) => setUiLevel(next), [])
  const toggle = useCallback(
    () => setUiLevel(read() === 'simple' ? 'advanced' : 'simple'),
    [],
  )

  return {
    level,
    isSimple: level === 'simple',
    isAdvanced: level === 'advanced',
    setLevel,
    toggle,
  }
}
