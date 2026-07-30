import { useMemo, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import {
  ArrowRight, CalendarDays, Database, GitCompareArrows, History,
  Loader2, RefreshCw, UserRound,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  getProjectChanges, type ProjectChange, type ProjectChangesOverview,
} from '@/services/sitesService'
import { useOpenProject } from './useOpenProject'

const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const dateTime = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
})
const fullDate = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit', month: 'long', year: 'numeric',
})

const CATEGORY_TONE: Record<string, string> = {
  decision: 'border-orange-500/60 text-orange-700 dark:text-orange-300',
  stage: 'border-blue-500/60 text-blue-700 dark:text-blue-300',
  deadline: 'border-amber-500/60 text-amber-700 dark:text-amber-300',
  responsibility: 'border-violet-500/60 text-violet-700 dark:text-violet-300',
  finance: 'border-emerald-500/60 text-emerald-700 dark:text-emerald-300',
  conditions: 'border-cyan-500/60 text-cyan-700 dark:text-cyan-300',
  technical: 'border-slate-500/60 text-slate-700 dark:text-slate-300',
  object: 'border-zinc-500/60 text-zinc-700 dark:text-zinc-300',
}

const CATEGORY_OPTIONS = [
  { value: 'all', label: 'Все изменения' },
  { value: 'decision', label: 'Решения' },
  { value: 'stage', label: 'Стадии' },
  { value: 'deadline', label: 'Сроки' },
  { value: 'responsibility', label: 'Ответственность' },
  { value: 'finance', label: 'Деньги' },
  { value: 'conditions', label: 'Условия' },
  { value: 'technical', label: 'Технические данные' },
  { value: 'object', label: 'Карточка проекта' },
  { value: 'other', label: 'Прочее' },
]

const SOURCE_OPTIONS = [
  { value: 'all', label: 'Все источники' },
  { value: 'user', label: 'Ручные правки' },
  { value: 'import', label: 'Импорт' },
  { value: 'system', label: 'Система' },
]

export function ProjectChangesPanel({ companyId }: { companyId: string }) {
  const openProject = useOpenProject()
  const [days, setDays] = useState(30)
  const [category, setCategory] = useState('all')
  const [source, setSource] = useState('all')
  const query = useInfiniteQuery({
    queryKey: ['project-changes', companyId, days, category, source],
    initialPageParam: '',
    queryFn: ({ pageParam }) => getProjectChanges({
      companyId,
      days,
      category: category === 'all' ? undefined : category,
      source: source === 'all' ? undefined : source,
      cursor: pageParam || undefined,
      limit: 60,
    }),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  })
  const data = query.data?.pages[0]
  const items = useMemo(
    () => query.data?.pages.flatMap((page) => page.items) ?? [],
    [query.data],
  )

  if (query.isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (query.isError || !data) {
    return (
      <div className="p-4">
        <Card className="border-red-400/40">
          <CardContent className="p-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium">Не удалось загрузить историю изменений</div>
              <div className="text-xs text-muted-foreground">
                {query.error instanceof Error ? query.error.message : 'Сервис аналитики не ответил'}
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
              <RefreshCw className="h-3.5 w-3.5 mr-1.5" />Повторить
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Изменения</h2>
          <p className="text-sm text-muted-foreground">
            Что решили и исправили в проектах: прежнее и новое значение рядом.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select value={String(days)} onValueChange={(value) => setDays(Number(value))}>
            <SelectTrigger className="h-8 w-[135px] text-xs" aria-label="Период">
              <CalendarDays className="h-3.5 w-3.5 mr-1.5 text-muted-foreground" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">7 дней</SelectItem>
              <SelectItem value="30">30 дней</SelectItem>
              <SelectItem value="90">90 дней</SelectItem>
              <SelectItem value="365">12 месяцев</SelectItem>
            </SelectContent>
          </Select>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="h-8 w-[185px] text-xs" aria-label="Тип изменения">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CATEGORY_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger className="h-8 w-[155px] text-xs" aria-label="Источник изменения">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SOURCE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="px-3 py-2 border-b bg-muted/40 flex items-center gap-2">
            <GitCompareArrows className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-sm font-semibold">За выбранный период</span>
            <span className="ml-auto text-xs text-muted-foreground">
              с {fullDate.format(new Date(data.period.from))}
            </span>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 divide-x divide-y lg:divide-y-0">
            <SummaryValue label="Проектов менялось" value={data.summary.projects} />
            <SummaryValue label="Сохранений" value={data.summary.events} />
            <SummaryValue label="Полей изменено" value={data.summary.fields} />
            <SummaryValue label="Решений и стадий" value={data.summary.decisions} />
          </div>
        </CardContent>
      </Card>

      {(data.tracking.legacyEvents > 0 || !data.tracking.startedAt) && (
        <div className="border border-amber-500/35 bg-amber-500/[0.06] px-3 py-2.5 flex gap-2.5">
          <Database className="h-4 w-4 mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
          <div>
            <div className="text-sm font-medium">Старая история не содержит прежних значений</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {data.tracking.legacyEvents > 0
                ? `${number.format(data.tracking.legacyEvents)} событий за период сохранены только текстом и не подмешаны в сравнение. `
                : ''}
              Полное «было → стало» накапливается с первого сохранения после включения аналитики.
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[280px_minmax(0,1fr)] gap-4 items-start">
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 border-b bg-muted/40">
              <div className="text-sm font-semibold">Что меняли чаще</div>
              <div className="text-xs text-muted-foreground">по количеству полей, не проектов</div>
            </div>
            {data.byField.length === 0 ? (
              <Empty text="В выбранном срезе нет изменений." />
            ) : (
              <div className="divide-y divide-border/40">
                {data.byField.map((field) => (
                  <button key={field.field} type="button"
                    onClick={() => setCategory(field.category)}
                    className="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm truncate">{field.label}</span>
                      <span className="block text-xs text-muted-foreground truncate">
                        {categoryLabel(data, field.category)}
                      </span>
                    </span>
                    <span className="font-mono text-sm text-muted-foreground">
                      {number.format(field.count)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 border-b bg-muted/40 flex items-center gap-2">
              <History className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-sm font-semibold">Хронология</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {number.format(data.summary.events)} сохранений
              </span>
            </div>
            {items.length === 0 ? (
              <Empty text={data.tracking.startedAt
                ? 'В выбранном периоде и срезе изменений нет.'
                : 'История начнёт накапливаться с первого изменения проекта.'} />
            ) : (
              <div className="divide-y divide-border/50">
                {items.map((item) => (
                  <article key={item.id} className="px-3 py-3">
                    <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
                      <time dateTime={item.createdAt ?? undefined}
                        className="w-24 shrink-0 font-mono text-xs text-muted-foreground pt-0.5">
                        {item.createdAt ? dateTime.format(new Date(item.createdAt)) : '—'}
                      </time>
                      <div className="min-w-0 flex-1">
                        <button type="button" onClick={() => openProject(item.siteId)}
                          className="text-left text-sm font-medium hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                          <span className="font-mono text-xs text-muted-foreground mr-2">
                            {item.projectNo ?? 'без номера'}
                          </span>
                          {item.title}
                        </button>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-xs text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            <UserRound className="h-3 w-3" />{item.author}
                          </span>
                          <span>{sourceLabel(item.source)}</span>
                          {item.text && <span className="truncate max-w-[36rem]" title={item.text}>{item.text}</span>}
                        </div>
                      </div>
                    </div>
                    <div className="mt-2 ml-0 lg:ml-[108px] space-y-1.5">
                      {item.changes.map((change, index) => (
                        <ChangeLine key={`${item.id}-${change.field}-${index}`} change={change} />
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            )}
            {query.hasNextPage && (
              <div className="p-3 border-t">
                <Button variant="outline" size="sm" className="w-full"
                  disabled={query.isFetchingNextPage}
                  onClick={() => void query.fetchNextPage()}>
                  {query.isFetchingNextPage
                    ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    : <History className="h-3.5 w-3.5 mr-1.5" />}
                  Показать более ранние
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function ChangeLine({ change }: { change: ProjectChange }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-[170px_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
      <div className="flex items-center gap-1.5 min-w-0">
        <span className={`border-l-2 pl-1.5 text-xs truncate ${CATEGORY_TONE[change.category] ?? 'border-muted-foreground/50 text-muted-foreground'}`}>
          {change.label}
        </span>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_16px_minmax(0,1fr)] items-start gap-1.5 min-w-0">
        <Value text={change.oldDisplay} tone="old" />
        <ArrowRight className="h-3.5 w-3.5 mt-0.5 text-muted-foreground" aria-hidden="true" />
        <Value text={change.newDisplay} tone="new" />
      </div>
    </div>
  )
}

function Value({ text, tone }: { text: string; tone: 'old' | 'new' }) {
  return (
    <span title={text} aria-label={`${tone === 'old' ? 'Было' : 'Стало'}: ${text}`}
      className={`min-w-0 break-words ${
      tone === 'old' ? 'text-muted-foreground line-through decoration-muted-foreground/40' : 'font-medium'
    }`}>
      {text}
    </span>
  )
}

function SummaryValue({ label, value }: { label: string; value: number }) {
  return (
    <div className="px-3 py-3">
      <div className="font-mono text-xl tabular-nums">{number.format(value)}</div>
      <div className="text-xs text-muted-foreground mt-0.5">{label}</div>
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="px-3 py-8 text-center text-sm text-muted-foreground">{text}</div>
}

function sourceLabel(source: string): string {
  if (source === 'import') return 'из импорта'
  if (source === 'system') return 'системное'
  return 'ручная правка'
}

function categoryLabel(data: ProjectChangesOverview, category: string): string {
  return data.byCategory.find((item) => item.category === category)?.label
    ?? CATEGORY_OPTIONS.find((item) => item.value === category)?.label
    ?? category
}
