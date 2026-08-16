import { useId, useMemo, useState } from 'react'
import {
  Download, ExternalLink, FileQuestion, FileText, Image as ImageIcon,
  Loader2, Paperclip, Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  downloadAttachment, humanSize, openAuthAttachment, useAuthBlob, useAuthText,
} from '@/lib/authFiles'
import { cn } from '@/lib/utils'
import type { DocVersion } from '@/services/docsService'

const ROLE_LABEL: Record<string, string> = {
  body: 'Документ',
  appendix: 'Приложение',
  signed_scan: 'Подписанный экземпляр',
  attachment: 'Вложение',
}

function previewKind(version: DocVersion): 'image' | 'pdf' | 'text' | 'unsupported' {
  const mime = (version.mime ?? '').toLowerCase().split(';', 1)[0].trim()
  const name = version.file_name.toLowerCase()
  if (mime) {
    if (['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/bmp'].includes(mime)) {
      return 'image'
    }
    if (mime === 'application/pdf') return 'pdf'
    if (mime === 'text/plain') return 'text'
    return 'unsupported'
  }
  if (name.endsWith('.pdf')) return 'pdf'
  if (/\.(txt|csv|json|xml|md|log)$/.test(name)) return 'text'
  return 'unsupported'
}

export function DocFileWorkspace({ versions, canRemove, removing, onRemove }: {
  versions: DocVersion[]
  canRemove: boolean
  removing: boolean
  onRemove: (versionId: string, reason: string) => void
}) {
  const initial = useMemo(
    () => versions.find((version) => version.role === 'body' && version.is_current)
      ?? versions.find((version) => version.is_current) ?? versions[0] ?? null,
    [versions],
  )
  const [selectedId, setSelectedId] = useState<string | null>(initial?.id ?? null)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const reasonId = useId()

  const selected = versions.find((version) => version.id === selectedId) ?? initial
  const path = selected ? `/api/files/${selected.file_id}` : null
  const kind = selected ? previewKind(selected) : 'unsupported'
  const blob = useAuthBlob(kind === 'text' ? null : path)
  const textPreview = useAuthText(path, kind === 'text')

  const download = async () => {
    if (!selected || !path) return
    try {
      await downloadAttachment(path, selected.file_name)
    } catch (error) {
      toast.error(`Файл не скачан: ${(error as Error).message}`)
    }
  }

  const open = async () => {
    if (!path) return
    try {
      await openAuthAttachment(path)
    } catch (error) {
      toast.error(`Файл не открыт: ${(error as Error).message}`)
    }
  }

  if (versions.length === 0) {
    return (
      <Card className="flex min-h-48 flex-col items-center justify-center gap-2 p-6 text-center">
        <FileQuestion className="h-7 w-7 text-muted-foreground" />
        <div className="text-sm font-medium">Файлов пока нет</div>
        <div className="max-w-md text-xs text-muted-foreground">
          Приложите основной документ, скан или приложение. Каждая редакция сохранит свой хеш.
        </div>
      </Card>
    )
  }

  return (
    <div className="grid min-h-0 gap-3 lg:grid-cols-[minmax(260px,0.75fr)_minmax(420px,1.25fr)]">
      <Card className="order-2 min-h-0 overflow-hidden lg:order-1">
        <div className="border-b border-border px-3 py-2">
          <div className="text-sm font-medium">Редакции и приложения</div>
          <div className="text-xs text-muted-foreground">Выберите файл для просмотра</div>
        </div>
        <div className="max-h-[34rem] divide-y divide-border/60 overflow-y-auto">
          {versions.map((version) => {
            const active = version.id === selected?.id
            return (
              <div key={version.id} className={cn('px-2 py-2', active && 'bg-primary/5')}>
                <div className="flex items-start gap-1">
                  <button type="button" onClick={() => setSelectedId(version.id)}
                    aria-current={active ? 'true' : undefined}
                    className="min-w-0 flex-1 rounded-md px-1 py-0.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <div className="flex items-center gap-1.5 text-sm font-medium">
                      <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate">{version.file_name}</span>
                    </div>
                    <div className="mt-0.5 pl-5 text-[11px] leading-4 text-muted-foreground">
                      {ROLE_LABEL[version.role] ?? version.role} · редакция {version.revision}
                      {version.is_current ? ' · действующая' : ''} · {humanSize(version.size)}
                    </div>
                  </button>
                  {canRemove && (
                    <Button type="button" size="icon" variant="ghost" className="h-8 w-8 shrink-0"
                      aria-label={`Убрать ${version.file_name}`}
                      onClick={() => {
                        setRemovingId(version.id)
                        setReason('')
                      }}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
                {removingId === version.id && (
                  <div className="mt-2 space-y-2 pl-1">
                    <Label htmlFor={reasonId} className="sr-only">Причина удаления редакции</Label>
                    <Input value={reason} onChange={(event) => setReason(event.target.value)}
                      id={reasonId} placeholder="Причина удаления из работы"
                      className="h-8 text-xs" autoFocus />
                    <div className="flex gap-1.5">
                      <Button size="sm" variant="destructive" className="h-8"
                        disabled={reason.trim().length < 3 || removing}
                        onClick={() => onRemove(version.id, reason.trim())}>
                        Убрать редакцию
                      </Button>
                      <Button size="sm" variant="ghost" className="h-8"
                        onClick={() => setRemovingId(null)}>Отмена</Button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </Card>

      <Card className="order-1 min-h-[18rem] overflow-hidden lg:order-2 lg:min-h-[24rem]">
        {selected && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{selected.file_name}</div>
                <div className="text-xs text-muted-foreground">
                  {ROLE_LABEL[selected.role] ?? selected.role} · SHA-256 {selected.sha256.slice(0, 12)}…
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button type="button" size="sm" variant="ghost" onClick={download}>
                  <Download className="mr-1.5 h-3.5 w-3.5" />Скачать
                </Button>
                {(kind === 'image' || kind === 'pdf') && (
                  <Button type="button" size="sm" variant="outline" onClick={open}>
                    <ExternalLink className="mr-1.5 h-3.5 w-3.5" />Открыть
                  </Button>
                )}
              </div>
            </div>
            <div className="flex min-h-[15rem] items-center justify-center bg-muted/20 p-3 lg:min-h-[31rem]">
              {(kind === 'text' ? textPreview.loading : blob.loading) && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />Загружаем защищённый файл…
                </div>
              )}
              {(kind === 'text' ? textPreview.error : blob.error) && (
                <div className="max-w-sm text-center">
                  <FileQuestion className="mx-auto mb-2 h-7 w-7 text-destructive" />
                  <div className="text-sm font-medium">Предпросмотр не загрузился</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    Проверьте доступ или скачайте файл повторно.
                  </div>
                </div>
              )}
              {blob.url && !blob.loading && !blob.error && kind === 'image' && (
                <img src={blob.url} alt={selected.file_name}
                  className="max-h-[31rem] max-w-full object-contain" />
              )}
              {blob.url && !blob.loading && !blob.error && kind === 'pdf' && (
                <iframe src={blob.url} title={`Предпросмотр ${selected.file_name}`}
                  sandbox="" className="h-80 w-full rounded-md border border-border bg-background lg:h-[31rem]" />
              )}
              {textPreview.text !== null && !textPreview.loading && !textPreview.error
                && kind === 'text' && (
                <pre data-testid="doc-text-preview"
                  className="h-80 w-full overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background p-3 font-sans text-sm leading-5 lg:h-[31rem]">
                  {textPreview.text}
                </pre>
              )}
              {!blob.loading && !blob.error && kind === 'unsupported' && (
                <div className="max-w-sm text-center">
                  {selected.mime?.startsWith('image/')
                    ? <ImageIcon className="mx-auto mb-2 h-7 w-7 text-muted-foreground" />
                    : <FileText className="mx-auto mb-2 h-7 w-7 text-muted-foreground" />}
                  <div className="text-sm font-medium">Предпросмотр этого формата недоступен</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    Откройте файл в установленном приложении или скачайте его.
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
