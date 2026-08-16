/**
 * Реестр документов: журнал входящих, исходящих, приказов и внутренних.
 *
 * Пункт раздела задаёт поток (`?view=incoming`), остальное — отбор. Открытая
 * карточка живёт в адресе (`?doc=`), поэтому на конкретный документ можно дать
 * ссылку, а возврат браузером ведёт обратно в список, а не из приложения.
 */
import { useDeferredValue, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FilePlus2, Search } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { toast } from 'sonner'
import * as docsService from '@/services/docsService'
import { DOC_FAMILY, DOC_STATUS } from '@/services/docsService'
import { DocCardPanel } from '@/components/docs/DocCardPanel'
import { NewDocDialog } from '@/components/docs/NewDocDialog'
import { useDocsView } from './DocsLayout'

/** Пункт раздела → отбор реестра. «Все документы» ничего не сужают. */
const VIEW_FILTER: Record<string, docsService.DocFilters> = {
  incoming: { family: 'incoming' },
  outgoing: { family: 'outgoing' },
  ord: { family: 'ord' },
  internal: { family: 'internal' },
  all: {},
}

export function DocsRegistryPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const view = useDocsView('/docs')
  const [q, setQ] = useState('')
  const deferredQ = useDeferredValue(q.trim())
  const [creating, setCreating] = useState(false)

  const companyId = company?.id ?? ''
  const openId = params.get('doc')
  const filters = useMemo(
    () => ({ ...(VIEW_FILTER[view] ?? {}), q: deferredQ || undefined }), [view, deferredQ])

  const listQ = useQuery({
    queryKey: ['docs', companyId, view, deferredQ],
    queryFn: () => docsService.listDocs(companyId, filters),
    enabled: !!companyId,
  })
  const kindsQ = useQuery({
    queryKey: ['doc-kinds', companyId],
    queryFn: () => docsService.listKinds(companyId),
    enabled: !!companyId,
    staleTime: 5 * 60 * 1000,
  })

  const starter = useMutation({
    mutationFn: () => docsService.starterKinds(companyId),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['doc-kinds', companyId] })
      toast.success(r.added ? `Заведено видов: ${r.added}` : 'Виды уже заведены')
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const open = (id: string) => setParams((p) => {
    const n = new URLSearchParams(p); n.set('doc', id); return n
  }, { replace: true })
  const close = () => setParams((p) => {
    const n = new URLSearchParams(p); n.delete('doc'); return n
  }, { replace: true })

  if (!companyId) return null

  if (openId) {
    return (
      <div className="px-4 py-4">
        <DocCardPanel id={openId} companyId={companyId} onBack={close}
          onChanged={() => qc.invalidateQueries({ queryKey: ['docs', companyId] })} />
      </div>
    )
  }

  const docs = listQ.data?.docs ?? []
  const kinds = kindsQ.data ?? []
  // Виды заводит человек кнопкой: без них нельзя завести документ, и молчаливый
  // пустой список выглядел бы поломкой, а не незаконченной настройкой.
  const noKinds = kindsQ.isSuccess && kinds.length === 0

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-base font-semibold">
            {DOC_FAMILY[VIEW_FILTER[view]?.family ?? ''] ?? 'Все документы'}
          </h1>
          <p className="text-xs text-muted-foreground">
            {listQ.isLoading ? 'Загрузка…' : `Документов: ${docs.length}`}
          </p>
        </div>
        <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
          <div className="relative min-w-0 flex-1 sm:flex-none">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Номер, заголовок или текст файла"
              className="h-9 w-full pl-7 text-sm sm:w-64" />
          </div>
          <Button size="sm" onClick={() => setCreating(true)} disabled={kinds.length === 0}>
            <FilePlus2 className="mr-1.5 h-4 w-4" />Завести
          </Button>
        </div>
      </div>

      {noKinds && (
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <div className="text-sm font-medium">Виды документов ещё не заведены</div>
            <div className="text-xs text-muted-foreground">
              Вид задаёт правило нумерации: входящее письмо получит номер ВХ-2026-0001,
              приказ — ПР-2026-0001.
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => starter.mutate()}
            disabled={starter.isPending}>
            Завести обычный набор
          </Button>
        </Card>
      )}

      <Card className="min-h-0 flex-1 overflow-y-auto md:hidden">
        <div className="divide-y divide-border/60">
          {docs.map((d) => (
            <button key={d.id} type="button" onClick={() => open(d.id)}
              className="flex w-full flex-col gap-1 px-3 py-3 text-left hover:bg-accent/40">
              <div className="flex w-full items-start justify-between gap-3">
                <span className="min-w-0 truncate text-sm font-medium">{d.title}</span>
                <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs">
                  {DOC_STATUS[d.status]?.label ?? d.status}
                </span>
              </div>
              <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                <span>{d.reg_number ?? 'без номера'}</span>
                <span>{d.reg_date ?? (d.created_at ?? '').slice(0, 10)}</span>
                <span>{d.kind_name}</span>
              </div>
              {d.counterparty_name && (
                <span className="truncate text-xs text-muted-foreground">{d.counterparty_name}</span>
              )}
            </button>
          ))}
          {!listQ.isLoading && docs.length === 0 && (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              {deferredQ ? 'По этому запросу ничего нет' : 'Документов пока нет'}
            </div>
          )}
        </div>
      </Card>

      <Card className="hidden min-h-0 flex-1 overflow-auto md:block">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Рег. номер</th>
              <th className="px-3 py-2 text-left font-medium">Дата</th>
              <th className="px-3 py-2 text-left font-medium">Вид</th>
              <th className="px-3 py-2 text-left font-medium">Заголовок</th>
              <th className="px-3 py-2 text-left font-medium">Корреспондент</th>
              <th className="px-3 py-2 text-left font-medium">Их номер</th>
              <th className="px-3 py-2 text-left font-medium">Состояние</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id} onClick={() => open(d.id)}
                className="cursor-pointer border-t border-border/60 hover:bg-accent/40">
                <td className="whitespace-nowrap px-3 py-2 font-medium">
                  {d.reg_number ?? <span className="text-muted-foreground">без номера</span>}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                  {d.reg_date ?? (d.created_at ?? '').slice(0, 10)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{d.kind_name}</td>
                <td className="px-3 py-2">{d.title}</td>
                <td className="px-3 py-2 text-muted-foreground">{d.counterparty_name || '—'}</td>
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                  {d.external_number || '—'}
                </td>
                <td className="whitespace-nowrap px-3 py-2">
                  <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs">
                    {DOC_STATUS[d.status]?.label ?? d.status}
                  </span>
                </td>
              </tr>
            ))}
            {!listQ.isLoading && docs.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-sm text-muted-foreground">
                  {deferredQ ? 'По этому запросу ничего нет' : 'Документов пока нет'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>

      {creating && (
        <NewDocDialog companyId={companyId} kinds={kinds}
          defaultFamily={VIEW_FILTER[view]?.family}
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false)
            qc.invalidateQueries({ queryKey: ['docs', companyId] })
            open(id)
          }} />
      )}
    </div>
  )
}

export default DocsRegistryPage
