import { useEffect, useState } from 'react'
import { downloadBlob } from '@/services/apiClient'

const blobCache = new Map<string, string>()

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
        blobCache.set(path, objUrl)
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

export function useAuthBlobUrl(path: string | null): string | null {
  return useAuthBlob(path).url
}

export async function downloadAttachment(path: string, name?: string): Promise<void> {
  const cached = blobCache.get(path)
  const objUrl = cached ?? URL.createObjectURL(await downloadBlob(path))
  if (!cached) blobCache.set(path, objUrl)
  const anchor = document.createElement('a')
  anchor.href = objUrl
  anchor.download = name || 'файл'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

export async function openAuthAttachment(path: string): Promise<void> {
  const target = window.open('', '_blank')
  if (!target) throw new Error('Браузер заблокировал новую вкладку')
  try {
    const cached = blobCache.get(path)
    const objUrl = cached ?? URL.createObjectURL(await downloadBlob(path))
    if (!cached) blobCache.set(path, objUrl)
    target.location.href = objUrl
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
