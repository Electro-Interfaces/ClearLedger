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
import { useNavigate } from 'react-router-dom'
import { AlertCircle, FileDown, FolderSearch, RotateCw } from 'lucide-react'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import * as docsService from '@/services/docsService'
import { openAuthAttachment } from '@/lib/authFiles'

export function DocsInboxPanel() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const companyId = company?.id ?? ''

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
    mutationFn: (v: { id: string; accept: boolean; kindId?: string }) =>
      docsService.decideInbox(companyId, v.id, {
        accept: v.accept, kind_id: v.kindId ?? null,
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
            {itemsQ.isLoading ? 'Загрузка…' : `Ждут решения: ${items.length}`}
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => scan.mutate()}
          disabled={scan.isPending || itemsQ.isError}>
          <FolderSearch className="mr-1.5 h-4 w-4" />Проверить папку
        </Button>
      </div>

      {itemsQ.isError && (
        <Card role="alert" className="flex flex-wrap items-center justify-between gap-3 border-destructive/30 p-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-destructive">
              <AlertCircle className="h-4 w-4" />Приём из СЭД недоступен
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {(itemsQ.error as Error).message}
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={() => itemsQ.refetch()}>
            <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
          </Button>
        </Card>
      )}

      {kindsQ.isError && !itemsQ.isError && (
        <Card role="alert" className="flex flex-wrap items-center justify-between gap-3 border-destructive/30 p-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-destructive">
              <AlertCircle className="h-4 w-4" />Виды документов не загрузились
            </div>
            <p className="mt-1 text-xs text-muted-foreground">Принятие заблокировано до повторной загрузки.</p>
          </div>
          <Button size="sm" variant="outline" onClick={() => kindsQ.refetch()}>
            <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
          </Button>
        </Card>
      )}
      {kindsQ.isSuccess && incomingKinds.length === 0 && !itemsQ.isError && (
        <Card role="status" className="border-amber-500/30 p-4 text-sm text-muted-foreground">
          Сначала включите хотя бы один входящий вид документа в настройке видов.
        </Card>
      )}

      {!itemsQ.isError && <Card className="divide-y divide-border/60">
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
                <Button size="sm" variant="ghost" disabled={decide.isPending}
                  onClick={() => decide.mutate({ id: it.id, accept: false })}>
                  Отклонить
                </Button>
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
