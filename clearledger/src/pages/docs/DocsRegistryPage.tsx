/**
 * Реестр документов: журнал входящих, исходящих, приказов и внутренних.
 *
 * Пункт раздела задаёт поток (`?view=incoming`), фильтры и открытая карточка
 * живут в адресе. На широком экране карточка открывается рядом с реестром:
 * пользователь не теряет очередь и может последовательно разбирать документы.
 */
import { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookmarkPlus, ChevronLeft, ChevronRight, FilePlus2, Search,
  SlidersHorizontal, X,
} from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import * as docsService from '@/services/docsService'
import { DOC_FAMILY, DOC_STATUS } from '@/services/docsService'
import { DocCardPanel } from '@/components/docs/DocCardPanel'
import { NewDocDialog } from '@/components/docs/NewDocDialog'
import { useDocsScope } from '@/hooks/useDocsScope'
import { useDocsView } from './DocsLayout'
import { DocsBulkBar } from '@/components/docs/DocsBulkBar'
import { DocsErrorState, DocsLoadingState } from '@/components/docs/DocsQueryState'
import { formatDate } from '@/lib/formatDate'

const VIEW_FILTER: Record<string, docsService.DocFilters> = {
  incoming: { family: 'incoming' },
  outgoing: { family: 'outgoing' },
  ord: { family: 'ord' },
  internal: { family: 'internal' },
  contract: { family: 'contract' },
  other: { family: 'other' },
  all: {},
}

const FILTER_KEYS = ['q', 'status', 'kind', 'label', 'date_from', 'date_to',
  'attention'] as const
const PAGE_SIZE = 100

export function DocsRegistryPage() {
  const { company, isCompanyAdmin } = useCompany()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const view = useDocsView('/docs')
  const scope = useDocsScope()
  const [creating, setCreating] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())

  const companyId = company?.id ?? ''
  const openId = params.get('doc')
  const initialTab = params.get('tab') === 'archive' ? 'archive' : undefined
  const q = params.get('q') ?? ''
  const deferredQ = useDeferredValue(q.trim())
  const statusFilter = params.get('status') ?? ''
  const kindFilter = params.get('kind') ?? ''
  const labelFilter = params.get('label') ?? ''
  const dateFrom = params.get('date_from') ?? ''
  const dateTo = params.get('date_to') ?? ''
  // Сужение, с которым пришли из обзора: «просроченные», «без номера».
  const attention = params.get('attention') ?? ''
  const effectiveDateFrom = dateFrom || scope.period.from
  const effectiveDateTo = dateTo || scope.period.to
  const pageValue = Number(params.get('page'))
  const page = Number.isSafeInteger(pageValue) && pageValue >= 1 ? pageValue : 1
  const hasFilters = FILTER_KEYS.some((key) => params.has(key))
  const savedQuery = useMemo(() => {
    const result: Record<string, string> = {
      view, date_from: effectiveDateFrom, date_to: effectiveDateTo,
    }
    for (const key of FILTER_KEYS) {
      const value = params.get(key)
      if (value) result[key] = value
    }
    const globalFilter = params.get('f')
    if (globalFilter) result.f = globalFilter
    return result
  }, [effectiveDateFrom, effectiveDateTo, params, view])
  const filters = useMemo(() => ({
    ...(VIEW_FILTER[view] ?? {}),
    q: deferredQ || undefined,
    status: statusFilter || undefined,
    kind_id: kindFilter || undefined,
    label_id: labelFilter || undefined,
    attention: attention || undefined,
    date_from: effectiveDateFrom,
    date_to: effectiveDateTo,
    object_ids: scope.objectFilter,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  }), [attention, deferredQ, effectiveDateFrom, effectiveDateTo, kindFilter,
    labelFilter, page, scope.objectFilter, statusFilter, view])

  const listQ = useQuery({
    queryKey: ['docs', companyId, view, filters],
    queryFn: () => docsService.listDocs(companyId, filters),
    enabled: !!companyId && scope.ready,
  })
  const kindsQ = useQuery({
    queryKey: ['doc-kinds', companyId],
    queryFn: () => docsService.listKinds(companyId),
    enabled: !!companyId,
    staleTime: 5 * 60 * 1000,
  })
  const labelsQ = useQuery({
    queryKey: ['doc-labels', companyId],
    queryFn: () => docsService.listDocLabels(companyId),
    enabled: !!companyId,
    staleTime: 5 * 60 * 1000,
  })

  const starter = useMutation({
    mutationFn: () => docsService.starterKinds(companyId),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['doc-kinds', companyId] })
      toast.success(result.added ? `Заведено видов: ${result.added}` : 'Виды уже заведены')
    },
    onError: () => toast.error('Не удалось завести базовые виды. Повторите попытку.'),
  })

  const setFilter = (key: typeof FILTER_KEYS[number], value: string) => {
    setSelectedIds(new Set())
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (value) next.set(key, value)
      else next.delete(key)
      next.delete('page')
      return next
    }, { replace: true })
  }
  const clearFilters = () => {
    setSelectedIds(new Set())
    setParams((current) => {
      const next = new URLSearchParams(current)
      FILTER_KEYS.forEach((key) => next.delete(key))
      next.delete('page')
      return next
    }, { replace: true })
  }
  const setPage = (value: number) => {
    setSelectedIds(new Set())
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (value > 1) next.set('page', String(value))
      else next.delete('page')
      next.delete('doc')
      return next
    }, { replace: true })
  }
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
  const allPageSelected = docs.length > 0 && docs.every((doc) => selectedIds.has(doc.id))
  const toggleSelected = (docId: string, on: boolean) => setSelectedIds((current) => {
    const next = new Set(current)
    if (on) next.add(docId)
    else next.delete(docId)
    return next
  })
  const togglePage = (on: boolean) => setSelectedIds(
    on ? new Set(docs.map((doc) => doc.id)) : new Set(),
  )
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
  const семейство = VIEW_FILTER[view]?.family
  const title = DOC_FAMILY[семейство ?? ''] ?? 'Все документы'
  // Виды ЭТОГО потока, а не вообще: «Договорные» пусты не потому, что период
  // не тот, а потому что вида с таким потоком в компании не заводили. Прежняя
  // проверка молчала, если в компании есть хоть один вид любого потока.
  const видыПотока = семейство
    ? kinds.filter((k) => k.family === семейство && k.is_active)
    : kinds.filter((k) => k.is_active)
  const нетВидовПотока = kindsQ.isSuccess && !!семейство && видыПотока.length === 0
  const emptyText = hasFilters
    ? 'По заданным условиям ничего не найдено'
    : нетВидовПотока
      ? `Видов документов с потоком «${title}» ещё нет. Заведите вид в «Настройке» — `
        + 'он задаёт правило нумерации, маршрут согласования и реквизиты карточки'
      : 'В рабочем контуре документов пока нет'

  const registry = (
    <Card className="min-h-0 overflow-hidden">
      <div className={cn('h-full divide-y divide-border/60 overflow-y-auto', !openId && 'md:hidden')}>
        {docs.map((doc) => (
          <div key={doc.id} className={cn('flex items-start gap-1', doc.id === openId && 'bg-primary/5')}>
            <div className="px-2 pt-3">
              <Checkbox checked={selectedIds.has(doc.id)}
                aria-label={`Выбрать документ ${doc.reg_number ?? doc.title}`}
                onCheckedChange={(value) => toggleSelected(doc.id, value === true)} />
            </div>
            <button type="button" onClick={() => open(doc.id)}
              aria-current={doc.id === openId ? 'true' : undefined}
              className="flex min-w-0 flex-1 flex-col gap-1 px-2 py-3 text-left transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
            <div className="flex w-full items-start justify-between gap-3">
              <span className="min-w-0 truncate text-sm font-medium">{doc.title}</span>
              <StatusPill status={doc.status} />
            </div>
            <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              <span>{doc.reg_number ?? 'без номера'}</span>
              <span>{formatDate(doc.reg_date ?? doc.created_at ?? '')}</span>
              <span>{doc.kind_name}</span>
              {doc.organization_name && <span>{doc.organization_name}</span>}
            </div>
              {doc.counterparty_name && (
                <span className="truncate text-xs text-muted-foreground">{doc.counterparty_name}</span>
              )}
              {(doc.labels ?? []).length > 0 && (
                <span className="flex flex-wrap gap-1">
                  {(doc.labels ?? []).map((label) => (
                    <span key={label.id} className="rounded-full bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                      {label.name}
                    </span>
                  ))}
                </span>
              )}
            </button>
          </div>
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
                <th className="w-10 px-3 py-2 text-left font-medium">
                  <Checkbox checked={allPageSelected}
                    aria-label={allPageSelected ? 'Снять выбор со страницы' : 'Выбрать все документы на странице'}
                    onCheckedChange={(value) => togglePage(value === true)} />
                </th>
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
                <tr key={doc.id} className="border-t border-border/60 transition-colors hover:bg-accent/40">
                  <td className="px-3 py-2">
                    <Checkbox checked={selectedIds.has(doc.id)}
                      aria-label={`Выбрать документ ${doc.reg_number ?? doc.title}`}
                      onCheckedChange={(value) => toggleSelected(doc.id, value === true)} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 font-medium">
                    {doc.reg_number ?? <span className="text-muted-foreground">без номера</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    {formatDate(doc.reg_date ?? doc.created_at ?? '')}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{doc.organization_name || '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{doc.kind_name}</td>
                  <td className="px-3 py-2">
                    <button type="button" className="text-left font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() => open(doc.id)}>{doc.title}</button>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{doc.counterparty_name || '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    {doc.external_number || '—'}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2"><StatusPill status={doc.status} /></td>
                </tr>
              ))}
              {listQ.isSuccess && docs.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-sm text-muted-foreground">
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
            headingLevel={1}
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
              {!scope.ready ? 'Рабочий контур ещё не применён'
                : listQ.isLoading ? 'Загрузка…'
                  : listQ.isError ? 'Количество не определено'
                    : `Найдено: ${total}`}
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
            {/* Гаснет и называет причину: диалог, в котором нечего выбрать,
                — тупик, а не форма. */}
            <Button size="sm" onClick={() => setCreating(true)}
              disabled={видыПотока.length === 0}
              title={видыПотока.length === 0
                ? `Нет ни одного вида с потоком «${title}» — заведите его в «Настройке»`
                : undefined}>
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
          <select value={labelFilter} onChange={(event) => setFilter('label', event.target.value)}
            aria-label="Метка документа" disabled={labelsQ.isLoading}
            className="h-8 max-w-56 rounded-md border border-input bg-background px-2 text-xs">
            <option value="">Все метки</option>
            {labelFilter && !(labelsQ.data?.labels ?? []).some((label) => label.id === labelFilter) && (
              <option value={labelFilter}>Выбранная метка</option>
            )}
            {(labelsQ.data?.labels ?? []).map((label) => (
              <option key={label.id} value={label.id}>{label.name}</option>
            ))}
          </select>
          <label className="flex items-center gap-1 text-xs text-muted-foreground"
            title="По умолчанию используется период рабочего контура">
            с
            <Input type="date" value={effectiveDateFrom}
              onChange={(event) => setFilter('date_from', event.target.value)}
              aria-label="Дата с" className="h-8 w-36 text-xs" />
          </label>
          <label className="flex items-center gap-1 text-xs text-muted-foreground"
            title="По умолчанию используется период рабочего контура">
            по
            <Input type="date" value={effectiveDateTo}
              onChange={(event) => setFilter('date_to', event.target.value)}
              aria-label="Дата по" className="h-8 w-36 text-xs" />
          </label>
          {hasFilters && (
            <Button type="button" size="sm" variant="ghost" className="h-8 px-2"
              onClick={clearFilters}>
              <X className="mr-1 h-3.5 w-3.5" />Сбросить
            </Button>
          )}
          <SaveDocView companyId={companyId} query={savedQuery}
            canShare={isCompanyAdmin} />
          {deferredQ && (
            <span className="text-xs text-muted-foreground">
              Поиск включает распознанный текст файлов
            </span>
          )}
          {!dateFrom && !dateTo && (
            <span className="text-xs text-muted-foreground">Период взят из рабочего контура</span>
          )}
        </div>

        {/* Пришли из обзора по цифре. Короткий список без этой строки читается
            как «документы пропали»: человек идёт проверять данные вместо того,
            чтобы делать по ним работу. */}
        {attention && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2.5 py-1">
              <span className="text-muted-foreground">Из обзора:</span>
              <span className="font-medium">
                {docsService.DOC_ATTENTION[attention] ?? attention}
              </span>
              <button type="button" onClick={() => setFilter('attention', '')}
                aria-label="Снять отбор из обзора"
                className="rounded-full p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground">
                <X className="h-3 w-3" />
              </button>
            </span>
          </div>
        )}

        {selectedIds.size > 0 && (
          <DocsBulkBar companyId={companyId} selectedIds={[...selectedIds]}
            onClear={() => setSelectedIds(new Set())}
            onDone={() => {
              setSelectedIds(new Set())
              void listQ.refetch()
            }} />
        )}

        {noKinds && (
          <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div>
              <div className="text-sm font-medium">Виды документов ещё не заведены</div>
              <div className="text-xs text-muted-foreground">
                Вид задаёт правило нумерации: входящее письмо получит номер ВХ-ГИГ-2026-0001,
                приказ — ПР-ГИГ-2026-0001.
              </div>
            </div>
            <Button size="sm" variant="outline" onClick={() => starter.mutate()}
              disabled={starter.isPending}>Завести обычный набор</Button>
          </Card>
        )}

        {listQ.isError && (
          <DocsErrorState error={listQ.error} title="Реестр не загрузился"
            detail="Данные не заменены пустым списком. Проверьте соединение и повторите запрос."
            onRetry={() => { void listQ.refetch() }} />
        )}

        <div className={cn(
          'min-h-0 flex-1',
          openId && 'grid gap-3 lg:grid-cols-[minmax(280px,0.66fr)_minmax(520px,1.4fr)]',
        )}>
          {(listQ.isLoading || !scope.ready) && !scope.failed && (
            <DocsLoadingState>
              {scope.resolving ? 'Применяем область рабочего контура…' : 'Загружаем реестр…'}
            </DocsLoadingState>
          )}
          {listQ.isSuccess && registry}
          {openId && (
            <section aria-label="Открытый документ"
              className="min-h-0 overflow-y-auto rounded-lg border border-border bg-background px-4">
              <DocCardPanel key={`${openId}:${initialTab ?? ''}`}
                id={openId} companyId={companyId} onBack={close}
                headingLevel={2}
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

function SaveDocView({ companyId, query, canShare }: {
  companyId: string
  query: Record<string, string>
  canShare: boolean
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [shared, setShared] = useState(false)
  const save = useMutation({
    mutationFn: () => docsService.createDocView({
      companyId, name: name.trim(), query, shared: canShare && shared,
    }),
    onSuccess: () => {
      toast.success('Отбор сохранён в «Представлениях»')
      setOpen(false)
      setName('')
      setShared(false)
      qc.invalidateQueries({ queryKey: ['doc-views', companyId] })
    },
    onError: () => toast.error('Не удалось сохранить отбор. Повторите попытку.'),
  })

  if (!open) {
    return (
      <Button type="button" size="sm" variant="outline" className="h-8"
        onClick={() => setOpen(true)}>
        <BookmarkPlus className="mr-1.5 h-3.5 w-3.5" />Сохранить отбор
      </Button>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border p-1.5">
      <Input value={name} onChange={(event) => setName(event.target.value)} autoFocus
        aria-label="Название представления" placeholder="Название отбора"
        className="h-8 w-48 text-xs" maxLength={120}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && name.trim()) save.mutate()
          if (event.key === 'Escape') setOpen(false)
        }} />
      {canShare && (
        <label className="flex min-h-8 items-center gap-2 px-1 text-xs text-muted-foreground">
          <input type="checkbox" checked={shared}
            onChange={(event) => setShared(event.target.checked)} />
          Для компании
        </label>
      )}
      <Button type="button" size="sm" className="h-8"
        disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>
        Сохранить
      </Button>
      <Button type="button" size="sm" variant="ghost" className="h-8 px-2"
        aria-label="Отменить сохранение отбора" onClick={() => setOpen(false)}>
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
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

/**
 * Что открывается по голому `/docs`.
 *
 * Приложение открывают с вопросом «что на мне», а не «покажи журнал входящих»,
 * поэтому вход ведёт в «Моё». Реестр остаётся по тому же адресу с названным
 * разрезом (`?view=incoming`), и все прежние ссылки живы: разрез в них уже есть.
 */
export function DocsHome() {
  const [params] = useSearchParams()
  if (!params.get('view')) return <Navigate to="/docs/work" replace />
  return <DocsRegistryPage />
}
