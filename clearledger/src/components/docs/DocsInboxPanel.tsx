/**
 * Приём документов из папки корпоративной системы.
 *
 * Устроено как приёмка первички: система показывает, что нашла в папке, человек
 * смотрит и решает. Автоматически карточки не заводим — чужой мусор и дубли
 * чистить из реестра документов дороже, чем разобрать десяток файлов.
 *
 * Файлы в папке не трогаем: она принадлежит той стороне.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileDown, FolderSearch } from 'lucide-react'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import * as docsService from '@/services/docsService'
import { openAuthAttachment } from '@/lib/authFiles'
import { DocsErrorState, DocsLoadingState } from './DocsQueryState'

export function DocsInboxPanel() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const companyId = company?.id ?? ''
  const [rejectNote, setRejectNote] = useState('')

  const itemsQ = useQuery({
    queryKey: ['docs-inbox', companyId],
    queryFn: () => docsService.listInbox(companyId),
    enabled: !!companyId,
  })
  const kindsQ = useQuery({
    queryKey: ['doc-kinds', companyId],
    queryFn: () => docsService.listKinds(companyId),
    enabled: !!companyId,
    staleTime: 5 * 60 * 1000,
  })

  const scan = useMutation({
    mutationFn: () => docsService.scanInbox(companyId),
    onSuccess: (r) => {
      if (r.errors?.length) {
        toast.error(r.errors.map((item) => `${item.target}: ${item.error}`).join('; '))
      } else {
        toast.success(r.added
          ? `Найдено новых файлов: ${r.added}`
          : 'Новых файлов в папке нет')
      }
      qc.invalidateQueries({ queryKey: ['docs-inbox', companyId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const decide = useMutation({
    mutationFn: (v: { id: string; accept: boolean; kindId?: string; note?: string }) =>
      docsService.decideInbox(companyId, v.id, {
        accept: v.accept, kind_id: v.kindId ?? null, note: v.note ?? null,
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['docs-inbox', companyId] })
      qc.invalidateQueries({ queryKey: ['docs', companyId] })
      if (r.status === 'accepted' && r.doc_id) {
        toast.success('Документ заведён')
        navigate(`/docs?view=all&doc=${r.doc_id}`)
      } else {
        toast.success('Файл отклонён')
      }
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const items = itemsQ.data ?? []
  const incomingKinds = (kindsQ.data ?? []).filter((k) => k.family === 'incoming' && k.is_active)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-base font-semibold">Приём из корпоративной системы</h1>
          <p className="text-xs text-muted-foreground">
            {itemsQ.isLoading ? 'Загрузка…'
              : itemsQ.isError ? 'Количество не определено' : `Ждут решения: ${items.length}`}
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => scan.mutate()}
          disabled={scan.isPending || itemsQ.isError}>
          <FolderSearch className="mr-1.5 h-4 w-4" />Проверить папку
        </Button>
      </div>

      {itemsQ.isLoading && (
        <DocsLoadingState>Загружаем очередь приёма…</DocsLoadingState>
      )}

      {itemsQ.isError && (
        <DocsErrorState error={itemsQ.error} title="Приём из СЭД недоступен"
          detail="Не удалось получить список входящих файлов. Проверьте подключение и повторите запрос."
          onRetry={() => { void itemsQ.refetch() }} />
      )}

      {kindsQ.isError && !itemsQ.isError && (
        <DocsErrorState error={kindsQ.error} title="Виды документов не загрузились"
          detail="Принятие заблокировано до повторной загрузки."
          onRetry={() => { void kindsQ.refetch() }} />
      )}
      {kindsQ.isSuccess && incomingKinds.length === 0 && !itemsQ.isError && (
        <Card role="status" className="border-amber-500/30 p-4 text-sm text-muted-foreground">
          Сначала включите хотя бы один входящий вид документа в настройке видов.
        </Card>
      )}

      {itemsQ.isSuccess && <Card className="divide-y divide-border/60">
        {items.map((it) => (
          <div key={it.id} className="space-y-2 px-3 py-2.5">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <button type="button" disabled={!it.file_id}
                  onClick={() => it.file_id && openAuthAttachment(
                    `/api/files/${it.file_id}`, { cache: false },
                  ).catch((error) => toast.error(`Файл не открыт: ${error.message}`))}
                  className="flex items-center gap-1.5 text-left text-sm hover:underline disabled:no-underline">
                  <FileDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate">{it.file_name}</span>
                </button>
                <div className="text-[11px] text-muted-foreground">
                  {it.target ? `${it.target} · ` : ''}
                  {Math.max(1, Math.round(it.size / 1024))} КБ
                  {it.found_at ? ` · ${it.found_at.slice(0, 16).replace('T', ' ')}` : ''}
                </div>
                {Object.keys(it.parsed).length > 0 && (
                  <div className="pt-1 text-[12px]">
                    {it.parsed.title && <div>{it.parsed.title}</div>}
                    <div className="text-muted-foreground">
                      {[it.parsed.kind, it.parsed.reg_number, it.parsed.counterparty_name]
                        .filter(Boolean).join(' · ')}
                    </div>
                  </div>
                )}
              </div>
              <div className="flex w-full flex-wrap items-center gap-1.5 sm:w-auto sm:shrink-0">
                <label htmlFor={`kind-${it.id}`} className="sr-only">
                  Вид принимаемого документа
                </label>
                <select id={`kind-${it.id}`}
                  className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-xs sm:flex-none"
                  defaultValue="">
                  <option value="">вид по умолчанию</option>
                  {incomingKinds.map((k) => (
                    <option key={k.id} value={k.id}>{k.name}</option>
                  ))}
                </select>
                <Button size="sm" disabled={decide.isPending || !kindsQ.isSuccess
                  || incomingKinds.length === 0}
                  onClick={() => {
                    const el = document.getElementById(
                      `kind-${it.id}`) as HTMLSelectElement | null
                    decide.mutate({ id: it.id, accept: true, kindId: el?.value || undefined })
                  }}>
                  Принять
                </Button>
                <ConfirmActionDialog
                  trigger={(
                    <Button size="sm" variant="ghost" disabled={decide.isPending}>
                      Отклонить
                    </Button>
                  )}
                  title={`Отклонить файл «${it.file_name}»?`}
                  description="Файл останется в источнике, но исчезнет из очереди приёма. Причина сохранится вместе с решением."
                  confirmLabel="Отклонить файл"
                  destructive
                  pending={decide.isPending}
                  confirmDisabled={rejectNote.trim().length < 3}
                  content={(
                    <div className="space-y-1.5">
                      <Label htmlFor={`inbox-reject-${it.id}`}>Причина отклонения</Label>
                      <Textarea id={`inbox-reject-${it.id}`} rows={3} value={rejectNote}
                        onChange={(event) => setRejectNote(event.target.value)}
                        placeholder="Не менее трёх символов" />
                    </div>
                  )}
                  onOpenChange={(open) => { if (!open) setRejectNote('') }}
                  onConfirm={() => decide.mutateAsync({
                    id: it.id, accept: false, note: rejectNote.trim(),
                  })}
                />
              </div>
            </div>
          </div>
        ))}
        {itemsQ.isSuccess && items.length === 0 && (
          <div className="px-3 py-8 text-center text-sm text-muted-foreground">
            Новых файлов нет. Нажмите «Проверить папку», если головная компания
            только что выложила документы.
          </div>
        )}
      </Card>}
    </div>
  )
}

export default DocsInboxPanel
