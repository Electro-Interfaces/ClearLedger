import { useState, useEffect, useCallback } from 'react'
import { getSettings, saveSettings } from '@/services/settingsService'

export type ThemePreference = 'light' | 'dark' | 'system'
type ResolvedTheme = 'light' | 'dark'

/** Ключ для index.html inline-скрипта (предотвращает flash) */
const RESOLVED_KEY = 'clearledger-theme'

function resolveTheme(pref: ThemePreference): ResolvedTheme {
  if (pref === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return pref
}

function getInitialPreference(): ThemePreference {
  return getSettings().theme
}

/**
 * Тема, навязанная адресом (`?theme=dark`). Так одевается витрина пространства,
 * встроенная фреймом в другое приложение (`public/eco-rail.js`): у человека тема
 * Ядра может быть светлой, а Поддержка всегда тёмная — и панель выглядела чужой
 * страницей. В хранилище такую тему не пишем: это одежда фрейма, а не выбор человека.
 */
function forcedTheme(): ResolvedTheme | null {
  const t = new URLSearchParams(window.location.search).get('theme')
  return t === 'dark' || t === 'light' ? t : null
}

function apply(resolved: ResolvedTheme) {
  document.documentElement.classList.toggle('dark', resolved === 'dark')
  if (!forcedTheme()) localStorage.setItem(RESOLVED_KEY, resolved)
}

// Применяем тему до React — предотвращаем flash
apply(forcedTheme() ?? resolveTheme(getInitialPreference()))

export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(getInitialPreference)
  const resolved = forcedTheme() ?? resolveTheme(preference)

  useEffect(() => {
    apply(resolved)
  }, [resolved])

  // Слушаем изменение системной темы при preference === 'system'
  useEffect(() => {
    if (preference !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => apply(resolveTheme('system'))
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [preference])

  const setTheme = useCallback((pref: ThemePreference) => {
    saveSettings({ theme: pref })
    setPreference(pref)
  }, [])

  const toggle = useCallback(() => {
    setTheme(resolved === 'dark' ? 'light' : 'dark')
  }, [resolved, setTheme])

  return { theme: resolved, preference, setTheme, toggle }
}
