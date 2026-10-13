/**
 * Материалы к встрече для её участников: повестка, документ, файл, ссылка.
 *
 * На совещание приходят с тем, что прочитали заранее, а через месяц ищут, по
 * каким бумагам решали. Пока приложить было нечего, повестка ехала письмом, а
 * презентация — в чат, и у самой встречи не оставалось ничего.
 *
 * Не путать с «Материалами» в блоке внешних участников: там документ
 * открывается гостю наружу отдельной ссылкой. Здесь наружу не уходит ничего —
 * список видит тот же круг, что и карточку встречи. Документ «Трека» лежит
 * ссылкой и открывается по собственным правам: приложить не значит открыть.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Link2, Loader2, Paperclip, Trash2, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SearchPicker } from '@/components/tasks/SearchPicker'
import * as workService from '@/services/workService'
import * as docsService from '@/services/docsService'

function размер(байт?: number | null) {
  if (!байт) return ''
  return байт < 1024 * 1024 ? `${Math.max(1, Math.round(байт / 1024))} КБ`
    : `${(байт / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`
}

export function PapersPanel({ companyId, eventId, readOnly = false, onChanged }: {
  companyId: string
  eventId: string
  /** Отменённая встреча: смотреть можно, прикладывать уже не к чему. */
  readOnly?: boolean
  onChanged?: () => void
}) {
  const qc = useQueryClient()
  const файл = useRef<HTMLInputElement>(null)
  const [адрес, setАдрес] = useState('')
  const [имя, setИмя] = useState('')

  const q = useQuery({
    queryKey: ['event-papers', companyId, eventId],
    queryFn: () => workService.listPapers(companyId, eventId),
    enabled: !!eventId,
  })
  const docsQ = useQuery({
    queryKey: ['docs-for-material', companyId],
    queryFn: () => docsService.listDocs(companyId, { limit: 100 }),
    enabled: !!companyId && !readOnly,
    staleTime: 60_000,
  })
  const обновить = () => {
    void qc.invalidateQueries({ queryKey: ['event-papers', companyId, eventId] })
    // Счётчик материалов стоит в строке конференции.
    void qc.invalidateQueries({ queryKey: ['conf-meetings'] })
    onChanged?.()
  }
  const отказ = (чем: string) => (e: Error) => toast.error(e.message || чем)

  const загрузить = useMutation({
    mutationFn: (f: File) => workService.uploadPaper(companyId, eventId, f),
    onSuccess: () => { toast.success('Файл приложен'); обновить() },
    onError: отказ('Файл не приложился'),
  })
  const приложить = useMutation({
    mutationFn: (что: { targetRef?: string; url?: string; title?: string }) =>
      workService.addPaper(companyId, eventId, что),
    onSuccess: () => { setАдрес(''); setИмя(''); toast.success('Приложено'); обновить() },
    onError: отказ('Не приложилось'),
  })
  const убрать = useMutation({
    mutationFn: (id: string) => workService.removePaper(companyId, eventId, id),
    onSuccess: () => { toast.success('Материал убран со встречи'); обновить() },
    onError: отказ('Не убралось'),
  })
  const открыть = useMutation({
    mutationFn: (m: workService.EventPaper) =>
      workService.openPaperFile(companyId, eventId, m.id, m.title),
    onError: отказ('Файл не открылся'),
  })

  const материалы = q.data?.papers ?? []

  return (
    <div className="space-y-3 rounded-md border border-border p-3">
      <div>
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Материалы к встрече
        </h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Повестка, документы и файлы для участников. Видят те же, кто видит встречу.
        </p>
      </div>

      {q.isLoading && <p role="status" className="text-xs text-muted-foreground">Загружаем…</p>}
      {q.isError && (
        <p role="alert" className="text-xs text-destructive">Материалы не загрузились.</p>
      )}
      {!q.isLoading && !q.isError && материалы.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Пока ничего не приложено{readOnly ? '.' : ' — добавьте повестку или документ, который надо прочитать до встречи.'}
        </p>
      )}

      {материалы.length > 0 && (
        <ul className="space-y-1">
          {материалы.map((m) => (
            <li key={m.id} className="flex items-center gap-2 text-sm">
              {m.kind === 'link' ? <Link2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                : m.kind === 'doc' ? <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                : <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
              <span className="min-w-0 flex-1">
                {m.kind === 'link' && (
                  <a href={m.url ?? '#'} target="_blank" rel="noopener noreferrer"
                    className="break-words text-primary underline-offset-2 hover:underline">{m.title}</a>
                )}
                {m.kind === 'doc' && (
                  <Link to={workService.refHref(m.target_ref ?? '') ?? '#'}
                    className="break-words text-primary underline-offset-2 hover:underline">{m.title}</Link>
                )}
                {m.kind === 'file' && (
                  <button type="button" onClick={() => открыть.mutate(m)}
                    disabled={открыть.isPending}
                    className="break-words text-left text-primary underline-offset-2 hover:underline">
                    {m.title}
                  </button>
                )}
                <span className="block text-xs text-muted-foreground">
                  {[m.kind === 'doc' ? 'документ «Трека»' : m.kind === 'link' ? 'ссылка' : размер(m.size),
                    m.added_by,
                    new Date(m.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })]
                    .filter(Boolean).join(' · ')}
                </span>
              </span>
              {m.can_remove && (
                <Button size="sm" variant="ghost" className="h-8 px-2"
                  title="Убрать материал со встречи" aria-label={`Убрать материал ${m.title}`}
                  disabled={убрать.isPending} onClick={() => убрать.mutate(m.id)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {!readOnly && (
        <div className="space-y-2 border-t border-border pt-2">
          <div className="flex flex-wrap items-center gap-2">
            <input ref={файл} type="file" className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) загрузить.mutate(f)
                e.target.value = ''
              }} />
            <Button size="sm" variant="outline" className="h-8 px-2 text-xs"
              disabled={загрузить.isPending} onClick={() => файл.current?.click()}>
              {загрузить.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                : <Upload className="mr-1 h-3.5 w-3.5" />}
              Файл
            </Button>
            <SearchPicker
              items={(docsQ.data?.docs ?? []).map((d) => ({
                id: d.id, name: d.title, hint: d.reg_number ?? undefined }))}
              value="" onChange={(id) => приложить.mutate({ targetRef: `doc:${id}` })}
              placeholder="Документ «Трека»" searchPlaceholder="Название или номер…"
              className="min-w-[12rem] flex-1" loading={docsQ.isLoading} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input value={адрес} onChange={(e) => setАдрес(e.target.value)}
              placeholder="https://…" aria-label="Адрес ссылки"
              className="h-8 min-w-[12rem] flex-1 text-xs" />
            <Input value={имя} onChange={(e) => setИмя(e.target.value)}
              placeholder="как назвать (необязательно)" aria-label="Название ссылки"
              className="h-8 min-w-[10rem] flex-1 text-xs" />
            <Button size="sm" variant="outline" className="h-8 px-2 text-xs"
              disabled={!/^https?:\/\/\S+/i.test(адрес.trim()) || приложить.isPending}
              onClick={() => приложить.mutate({ url: адрес.trim(), title: имя.trim() || undefined })}>
              <Link2 className="mr-1 h-3.5 w-3.5" />Ссылка
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export default PapersPanel
