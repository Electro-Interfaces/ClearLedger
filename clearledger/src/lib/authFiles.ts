/**
 * Вложения чата, закрытые JWT: `GET /api/files/{id}` требует заголовок, поэтому
 * прямой адрес в `src` не работает — файл качается через `downloadBlob`, показывается
 * объектная ссылка, а сама ссылка кешируется по пути файла.
 *
 * Политика кеша — в `lib/blobCache.ts`: там правило «пока ссылку показывают, отзывать
 * её нельзя», из-за нарушения которого видео в ленте переставало открываться.
 */
import { useEffect, useState } from 'react'
import { downloadBlob } from '@/services/apiClient'
import {
  взять, найти, отпустить, очистить, положить, состояние,
} from '@/lib/blobCache'

export function clearAuthFileCache(): void {
  очистить()
}

/** Состояние кеша — для проверок политики вытеснения. */
export function authFileCacheState() {
  return состояние()
}

export function useAuthBlob(path: string | null): {
  url: string | null
  error: boolean
  loading: boolean
} {
  const [result, setResult] = useState<{
    path: string | null
    url: string | null
    error: boolean
  }>({ path: null, url: null, error: false })
  const current = result.path === path ? result : null
  // Готовое читаем при отрисовке, а не через состояние: лишний проход по
  // состоянию здесь ничего не добавляет, зато даёт каскад перерисовок.
  const cached = path ? найти(path) : null

  useEffect(() => {
    if (!path) return
    let alive = true
    // Уже скачано — помечаем, что показываем: иначе следующее вложение ленты
    // вытеснит эту ссылку прямо из-под плеера.
    if (взять(path)) return () => { отпустить(path) }
    let взято = false
    downloadBlob(path)
      .then((blob) => {
        if (!alive) return
        const запись = положить(path, URL.createObjectURL(blob))
        запись.держат += 1
        взято = true
        setResult({ path, url: запись.url, error: false })
      })
      .catch(() => {
        if (alive) setResult({ path, url: null, error: true })
      })
    return () => {
      alive = false
      if (взято) отпустить(path)
    }
  }, [path])

  return {
    url: cached ?? current?.url ?? null,
    error: current?.error ?? false,
    loading: Boolean(path && !cached && !current),
  }
}

export function useAuthText(path: string | null, enabled: boolean): {
  text: string | null
  error: boolean
  loading: boolean
} {
  const [result, setResult] = useState<{
    path: string | null
    text: string | null
    error: boolean
  }>({ path: null, text: null, error: false })
  const current = enabled && result.path === path ? result : null

  useEffect(() => {
    if (!path || !enabled) return
    let alive = true
    downloadBlob(path)
      .then((blob) => blob.text())
      .then((text) => {
        if (alive) setResult({ path, text, error: false })
      })
      .catch(() => {
        if (alive) setResult({ path, text: null, error: true })
      })
    return () => { alive = false }
  }, [enabled, path])

  return {
    text: current?.text ?? null,
    error: current?.error ?? false,
    loading: Boolean(path && enabled && !current),
  }
}

export function useAuthBlobUrl(path: string | null): string | null {
  return useAuthBlob(path).url
}

export async function downloadAttachment(
  path: string, name?: string, options: { cache?: boolean } = {},
): Promise<void> {
  const useCache = options.cache !== false
  const cached = useCache ? найти(path) : null
  const objUrl = cached ?? URL.createObjectURL(await downloadBlob(path))
  if (!cached && useCache) положить(path, objUrl)
  const anchor = document.createElement('a')
  anchor.href = objUrl
  anchor.download = name || 'файл'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  if (!useCache) window.setTimeout(() => URL.revokeObjectURL(objUrl), 60_000)
}

export async function openAuthAttachment(
  path: string, options: { cache?: boolean } = {},
): Promise<void> {
  const target = window.open('', '_blank')
  if (!target) throw new Error('Браузер заблокировал новую вкладку')
  target.opener = null
  try {
    const useCache = options.cache !== false
    const cached = useCache ? найти(path) : null
    const objUrl = cached ?? URL.createObjectURL(await downloadBlob(path))
    if (!cached && useCache) положить(path, objUrl)
    target.location.href = objUrl
    if (!useCache) window.setTimeout(() => URL.revokeObjectURL(objUrl), 60_000)
  } catch (error) {
    target.close()
    throw error
  }
}

export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  const mb = bytes / (1024 * 1024)
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} МБ`
}
