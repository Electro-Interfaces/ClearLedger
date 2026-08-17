import { useEffect, useState } from 'react'
import { downloadBlob } from '@/services/apiClient'

const blobCache = new Map<string, string>()
const CACHE_LIMIT = 12

function rememberBlob(path: string, url: string) {
  const previous = blobCache.get(path)
  if (previous && previous !== url) URL.revokeObjectURL(previous)
  blobCache.delete(path)
  blobCache.set(path, url)
  while (blobCache.size > CACHE_LIMIT) {
    const oldest = blobCache.entries().next().value as [string, string] | undefined
    if (!oldest) break
    blobCache.delete(oldest[0])
    URL.revokeObjectURL(oldest[1])
  }
}

export function clearAuthFileCache() {
  blobCache.forEach((url) => URL.revokeObjectURL(url))
  blobCache.clear()
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
  const cached = path ? blobCache.get(path) ?? null : null
  const current = result.path === path ? result : null

  useEffect(() => {
    if (!path || blobCache.has(path)) return
    let alive = true
    downloadBlob(path)
      .then((blob) => {
        if (!alive) return
        const objUrl = URL.createObjectURL(blob)
        rememberBlob(path, objUrl)
        setResult({ path, url: objUrl, error: false })
      })
      .catch(() => {
        if (alive) setResult({ path, url: null, error: true })
      })
    return () => { alive = false }
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

export async function downloadAttachment(path: string, name?: string): Promise<void> {
  const cached = blobCache.get(path)
  const objUrl = cached ?? URL.createObjectURL(await downloadBlob(path))
  if (!cached) rememberBlob(path, objUrl)
  const anchor = document.createElement('a')
  anchor.href = objUrl
  anchor.download = name || 'файл'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

export async function openAuthAttachment(
  path: string, options: { cache?: boolean } = {},
): Promise<void> {
  const target = window.open('', '_blank')
  if (!target) throw new Error('Браузер заблокировал новую вкладку')
  target.opener = null
  try {
    const useCache = options.cache !== false
    const cached = useCache ? blobCache.get(path) : undefined
    const objUrl = cached ?? URL.createObjectURL(await downloadBlob(path))
    if (!cached && useCache) rememberBlob(path, objUrl)
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
