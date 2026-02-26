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

function apply(resolved: ResolvedTheme) {
  document.documentElement.classList.toggle('dark', resolved === 'dark')
  localStorage.setItem(RESOLVED_KEY, resolved)
}

// Применяем тему до React — предотвращаем flash
apply(resolveTheme(getInitialPreference()))

export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(getInitialPreference)
  const resolved = resolveTheme(preference)

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
