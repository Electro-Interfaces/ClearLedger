/**
 * Свёрнута строка каталога приложений или раскрыта — одно состояние на человека.
 *
 * Решение МАГа 06.09.2026: строки открываются свёрнутыми, чтобы каталог не занимал
 * экран целиком, а раскрытое человеком остаётся раскрытым. Потребителей двое —
 * каталог пространства (`EcosystemHomePage`) и быстрое меню в рельсе
 * (`AppsQuickMenu`), и расклад у них обязан совпадать: свернул строку в каталоге —
 * она свёрнута и в меню, иначе одно и то же место отвечает на вопрос «что открыто»
 * двумя разными способами.
 *
 * Живёт в браузере, как и вид стола: это привычка человека, а не настройка
 * пространства.
 */
import { useState } from 'react'

const OPEN_KEY = 'space.launcher.open'

export function readSectionOpen(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(`${OPEN_KEY}.${key}`)
    return raw === null ? fallback : raw === '1'
  } catch {
    return fallback   // приватное окно или запрет на хранилище
  }
}

export function useSectionOpen(key: string, defaultOpen = false): [boolean, () => void] {
  const [open, setOpen] = useState(() => readSectionOpen(key, defaultOpen))
  function toggle() {
    const next = !open
    setOpen(next)
    try { localStorage.setItem(`${OPEN_KEY}.${key}`, next ? '1' : '0') } catch { /* хранилище недоступно */ }
  }
  return [open, toggle]
}
