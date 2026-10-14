/**
 * «Записи» — конференции, которые можно пересмотреть.
 *
 * Запись лежит в файлах пространства и открыта тем же, кого касался конференция:
 * организатору, приглашённым и тем, кто в комнате был. Ссылку на файл легко
 * переслать, поэтому право проверяется и при скачивании, а не только здесь.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileVideo, Loader2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import * as conf from '@/services/confService'
import { EmptyBlock } from './EmptyBlock'
import { длительность, когда, предмет } from './format'
import { Link } from 'react-router-dom'

export default function ConfRecordsPage() {
  const { companyId } = useCompany()
  const [открываю, setОткрываю] = useState<string | null>(null)

  async function смотреть(з: conf.ConfRecording) {
    if (открываю) return
    setОткрываю(з.session_id)
    try {
      await conf.openRecording(з.file_url, `${з.title}.mp4`)
    } catch {
      toast.error('Не удалось открыть запись')
    } finally {
      setОткрываю(null)
    }
  }

  // Удаление — в два нажатия: файл уходит насовсем, а кнопка стоит рядом со «Смотреть».
  const [удаляю, setУдаляю] = useState<string | null>(null)
  const qc = useQueryClient()
  const удалить = useMutation({
    mutationFn: (id: string) => conf.removeRecording(companyId, id),
    onSuccess: () => {
      toast.success('Запись удалена')
      setУдаляю(null)
      void qc.invalidateQueries({ queryKey: ['conf-records', companyId] })
    },
    onError: (e: Error) => toast.error(e.message || 'Запись не удалилась'),
  })

  const записи = useQuery({
    queryKey: ['conf-records', companyId],
    queryFn: () => conf.listRecordings(companyId),
  })
  const строки = записи.data?.recordings ?? []

  return (
    <div className="space-y-4 p-4">
      <h1 className="font-headline text-lg font-semibold">Записи</h1>

      {записи.isLoading && <p role="status" className="text-sm">Загружаем…</p>}
      {!записи.isLoading && !строки.length && (
        <EmptyBlock иконка={FileVideo} текст="Записей пока нет"
          подсказка="Запись включает ведущий прямо в конференции. Готовый файл приезжает сюда сам и открыт тем, кого конференция касалась." />
      )}

      {строки.map(з => {
        const пред = предмет(з.subject_ref)
        return (
          <div key={з.session_id} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-border/60 py-3 last:border-0">
            <span className="font-medium">{з.title}</span>
            <p className="w-full text-xs text-muted-foreground">
              {когда(з.started_at)}
              {з.started_by && ` · собрал ${з.started_by}`}
              {з.recording_seconds ? ` · запись ${длительность(з.recording_seconds)}` : ''}
              {пред && ` · ${пред.имя}`}
            </p>
            <div className="ml-auto flex items-center gap-2">
              {з.can_remove && (удаляю === з.session_id ? (
                <>
                  <span className="text-xs text-muted-foreground">Удалить насовсем?</span>
                  <Button size="sm" variant="destructive" disabled={удалить.isPending}
                    onClick={() => удалить.mutate(з.session_id)}>
                    {удалить.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Удалить
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setУдаляю(null)}>Нет</Button>
                </>
              ) : (
                <Button size="sm" variant="ghost" className="h-8 px-2"
                  title="Удалить запись" aria-label={`Удалить запись: ${з.title}`}
                  onClick={() => setУдаляю(з.session_id)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              ))}
              {/* Качаем с пропуском и отдаём браузеру готовый файл: прямая
                  ссылка приходит к серверу без пропуска, и вместо записи
                  открывалось «Требуется авторизация» (замечание МАГа 10.09.2026). */}
              <Button size="sm" variant="outline" disabled={открываю === з.session_id}
                onClick={() => смотреть(з)}>
                {открываю === з.session_id
                  ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  : <Download className="mr-2 h-4 w-4" />}
                Смотреть
              </Button>
            </div>
            {з.event_id && (
              <Link to="/conf/history"
                className="w-full text-xs text-primary underline-offset-2 hover:underline">
                конференция в истории
              </Link>
            )}
          </div>
        )
      })}
    </div>
  )
}
