/**
 * Реестр документов: журнал входящих, исходящих, приказов и внутренних.
 *
 * Пункт раздела задаёт поток (`?view=incoming`), фильтры и открытая карточка
 * живут в адресе. На широком экране карточка открывается рядом с реестром:
 * пользователь не теряет очередь и может последовательно разбирать документы.
 */
import { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft, ChevronRight, FilePlus2, RotateCw, Search, SlidersHorizontal, X,
} from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import * as docsService from '@/services/docsService'
import { DOC_FAMILY, DOC_STATUS } from '@/services/docsService'
import { DocCardPanel } from '@/components/docs/DocCardPanel'
import { NewDocDialog } from '@/components/docs/NewDocDialog'
import { useDocsView } from './DocsLayout'

const VIEW_FILTER: Record<string, docsService.DocFilters> = {
  incoming: { family: 'incoming' },
  outgoing: { family: 'outgoing' },
  ord: { family: 'ord' },
  internal: { family: 'internal' },
  all: {},
}

const FILTER_KEYS = ['q', 'status', 'kind', 'date_from', 'date_to'] as const
const PAGE_SIZE = 100

export function DocsRegistryPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const view = useDocsView('/docs')
  const [creating, setCreating] = useState(false)

  const companyId = company?.id ?? ''
  const openId = params.get('doc')
  const initialTab = params.get('tab') === 'archive' ? 'archive' : undefined
  const q = params.get('q') ?? ''
  const deferredQ = useDeferredValue(q.trim())
  const statusFilter = params.get('status') ?? ''
  const kindFilter = params.get('kind') ?? ''
  const dateFrom = params.get('date_from') ?? ''
  const dateTo = params.get('date_to') ?? ''
  const pageValue = Number(params.get('page'))
  const page = Number.isSafeInteger(pageValue) && pageValue >= 1 ? pageValue : 1
  const hasFilters = FILTER_KEYS.some((key) => params.has(key))
  const filters = useMemo(() => ({
    ...(VIEW_FILTER[view] ?? {}),
    q: deferredQ || undefined,
    status: statusFilter || undefined,
    kind_id: kindFilter || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  }), [dateFrom, dateTo, deferredQ, kindFilter, page, statusFilter, view])

  const listQ = useQuery({
    queryKey: ['docs', companyId, view, filters],
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
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['doc-kinds', companyId] })
      toast.success(result.added ? `Заведено видов: ${result.added}` : 'Виды уже заведены')
    },
    onError: (error) => toast.error((error as Error).message),
  })

  const setFilter = (key: typeof FILTER_KEYS[number], value: string) => setParams((current) => {
    const next = new URLSearchParams(current)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('page')
    return next
  }, { replace: true })
  const clearFilters = () => setParams((current) => {
    const next = new URLSearchParams(current)
    FILTER_KEYS.forEach((key) => next.delete(key))
    next.delete('page')
    return next
  }, { replace: true })
  const setPage = (value: number) => setParams((current) => {
    const next = new URLSearchParams(current)
    if (value > 1) next.set('page', String(value))
    else next.delete('page')
    next.delete('doc')
    return next
  }, { replace: true })
  const open = (id: string) => setParams((current) => {
    const next = new URLSearchParams(current)
    next.set('doc', id)
    next.delete('tab')
    return next
  }, { replace: true })
  const close = () => setParams((current) => {
    const next = new URLSearchParams(current)
    next.delete('doc')
    next.delete('tab')
    return next
  }, { replace: true })

  const docs = listQ.data?.docs ?? []
  const total = listQ.data?.count ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  useEffect(() => {
    if (!listQ.isSuccess || page <= pages) return
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (pages > 1) next.set('page', String(pages))
      else next.delete('page')
      next.delete('doc')
      return next
    }, { replace: true })
  }, [listQ.isSuccess, page, pages, setParams])

  if (!companyId) return null

  const kinds = kindsQ.data ?? []
  const noKinds = kindsQ.isSuccess && kinds.length === 0
  const title = DOC_FAMILY[VIEW_FILTER[view]?.family ?? ''] ?? 'Все документы'
  const emptyText = hasFilters ? 'По заданным условиям ничего не найдено' : 'Документов пока нет'

  const registry = (
    <Card className="min-h-0 overflow-hidden">
      <div className={cn('h-full divide-y divide-border/60 overflow-y-auto', !openId && 'md:hidden')}>
        {docs.map((doc) => (
          <button key={doc.id} type="button" onClick={() => open(doc.id)}
            aria-current={doc.id === openId ? 'true' : undefined}
            className={cn(
              'flex w-full flex-col gap-1 px-3 py-3 text-left transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
              doc.id === openId && 'bg-primary/5',
            )}>
            <div className="flex w-full items-start justify-between gap-3">
              <span className="min-w-0 truncate text-sm font-medium">{doc.title}</span>
              <StatusPill status={doc.status} />
            </div>
            <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              <span>{doc.reg_number ?? 'без номера'}</span>
              <span>{doc.reg_date ?? (doc.created_at ?? '').slice(0, 10)}</span>
              <span>{doc.kind_name}</span>
              {doc.organization_name && <span>{doc.organization_name}</span>}
            </div>
            {doc.counterparty_name && (
              <span className="truncate text-xs text-muted-foreground">{doc.counterparty_name}</span>
            )}
          </button>
        ))}
        {listQ.isSuccess && docs.length === 0 && (
          <div className="px-3 py-8 text-center text-sm text-muted-foreground">{emptyText}</div>
        )}
      </div>

      {!openId && (
        <div className="hidden h-full overflow-auto md:block">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-muted text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Рег. номер</th>
                <th className="px-3 py-2 text-left font-medium">Дата</th>
                <th className="px-3 py-2 text-left font-medium">Юрлицо</th>
                <th className="px-3 py-2 text-left font-medium">Вид</th>
                <th className="px-3 py-2 text-left font-medium">Заголовок</th>
                <th className="px-3 py-2 text-left font-medium">Корреспондент</th>
                <th className="px-3 py-2 text-left font-medium">Их номер</th>
                <th className="px-3 py-2 text-left font-medium">Состояние</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((doc) => (
                <tr key={doc.id} onClick={() => open(doc.id)} tabIndex={0} role="button"
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      open(doc.id)
                    }
                  }}
                  className="cursor-pointer border-t border-border/60 transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
                  <td className="whitespace-nowrap px-3 py-2 font-medium">
                    {doc.reg_number ?? <span className="text-muted-foreground">без номера</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    {doc.reg_date ?? (doc.created_at ?? '').slice(0, 10)}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{doc.organization_name || '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{doc.kind_name}</td>
                  <td className="px-3 py-2">{doc.title}</td>
                  <td className="px-3 py-2 text-muted-foreground">{doc.counterparty_name || '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    {doc.external_number || '—'}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2"><StatusPill status={doc.status} /></td>
                </tr>
              ))}
              {listQ.isSuccess && docs.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-sm text-muted-foreground">
                    {emptyText}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )

  return (
    <>
      {openId && (
        <div className="h-full min-h-0 overflow-y-auto px-4 py-4 lg:hidden">
          <DocCardPanel key={`${openId}:${initialTab ?? ''}`}
            id={openId} companyId={companyId} onBack={close}
            initialTab={initialTab}
            onChanged={() => qc.invalidateQueries({ queryKey: ['docs', companyId] })} />
        </div>
      )}

      <div data-wave="trek-workspace" className={cn(
        'h-full min-h-0 flex-col gap-3 px-4 py-4',
        openId ? 'hidden lg:flex' : 'flex',
      )}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold">{title}</h1>
            <p className="text-xs text-muted-foreground">
              {listQ.isLoading ? 'Загрузка…' : `Найдено: ${total}`}
            </p>
          </div>
          <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
            <div className="relative min-w-0 flex-1 sm:flex-none">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input value={q} onChange={(event) => setFilter('q', event.target.value)}
                placeholder="Номер, реквизиты или текст файла"
                aria-label="Поиск по документам и содержимому файлов"
                className="h-9 w-full pl-7 text-sm sm:w-72" />
            </div>
            <Button size="sm" onClick={() => setCreating(true)} disabled={kinds.length === 0}>
              <FilePlus2 className="mr-1.5 h-4 w-4" />Завести
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2" aria-label="Фильтры реестра">
          <SlidersHorizontal className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <select value={statusFilter} onChange={(event) => setFilter('status', event.target.value)}
            aria-label="Состояние документа"
            className="h-8 rounded-md border border-input bg-background px-2 text-xs">
            <option value="">Все состояния</option>
            {Object.entries(DOC_STATUS).map(([key, status]) => (
              <option key={key} value={key}>{status.label}</option>
            ))}
          </select>
          <select value={kindFilter} onChange={(event) => setFilter('kind', event.target.value)}
            aria-label="Вид документа"
            className="h-8 max-w-56 rounded-md border border-input bg-background px-2 text-xs">
            <option value="">Все виды</option>
            {kinds.map((kind) => <option key={kind.id} value={kind.id}>{kind.name}</option>)}
          </select>
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            с
            <Input type="date" value={dateFrom}
              onChange={(event) => setFilter('date_from', event.target.value)}
              aria-label="Дата с" className="h-8 w-36 text-xs" />
          </label>
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            по
            <Input type="date" value={dateTo}
              onChange={(event) => setFilter('date_to', event.target.value)}
              aria-label="Дата по" className="h-8 w-36 text-xs" />
          </label>
          {hasFilters && (
            <Button type="button" size="sm" variant="ghost" className="h-8 px-2"
              onClick={clearFilters}>
              <X className="mr-1 h-3.5 w-3.5" />Сбросить
            </Button>
          )}
          {deferredQ && (
            <span className="text-xs text-muted-foreground">
              Поиск включает распознанный текст файлов
            </span>
          )}
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
              disabled={starter.isPending}>Завести обычный набор</Button>
          </Card>
        )}

        {listQ.isError && (
          <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-4">
            <div className="text-sm font-medium text-destructive">Реестр не загрузился</div>
            <div className="mt-1 text-sm text-muted-foreground">{(listQ.error as Error).message}</div>
            <Button size="sm" variant="outline" className="mt-3" onClick={() => listQ.refetch()}>
              <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
            </Button>
          </div>
        )}

        <div className={cn(
          'min-h-0 flex-1',
          openId && 'grid gap-3 lg:grid-cols-[minmax(280px,0.66fr)_minmax(520px,1.4fr)]',
        )}>
          {!listQ.isError && registry}
          {openId && (
            <section aria-label="Открытый документ"
              className="min-h-0 overflow-y-auto rounded-lg border border-border bg-background px-4">
              <DocCardPanel key={`${openId}:${initialTab ?? ''}`}
                id={openId} companyId={companyId} onBack={close}
                initialTab={initialTab}
                onChanged={() => qc.invalidateQueries({ queryKey: ['docs', companyId] })} />
            </section>
          )}
        </div>

        {listQ.isSuccess && total > PAGE_SIZE && !openId && (
          <nav aria-label="Страницы реестра"
            className="flex items-center justify-end gap-2 text-xs text-muted-foreground">
            <span>
              {Math.min((page - 1) * PAGE_SIZE + 1, total)}–{Math.min(page * PAGE_SIZE, total)} из {total}
            </span>
            <Button size="icon" variant="outline" aria-label="Предыдущая страница"
              disabled={page <= 1} onClick={() => setPage(page - 1)}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="min-w-12 text-center">{page} / {pages}</span>
            <Button size="icon" variant="outline" aria-label="Следующая страница"
              disabled={page >= pages} onClick={() => setPage(page + 1)}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </nav>
        )}

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
    </>
  )
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs">
      {DOC_STATUS[status]?.label ?? status}
    </span>
  )
}

export default DocsRegistryPage
