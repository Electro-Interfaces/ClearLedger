import { useMemo, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Archive, Loader2, RotateCw, ShieldAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import * as docsService from '@/services/docsService'

type QueueFilter = 'all' | 'due' | 'hold' | 'legacy' | 'active'

const FILTERS: Array<{ key: QueueFilter; label: string }> = [
  { key: 'all', label: 'Все' },
  { key: 'due', label: 'Срок истёк' },
  { key: 'hold', label: 'Под запретом' },
  { key: 'legacy', label: 'Проверить основание' },
  { key: 'active', label: 'В процессе' },
]

const STATE_LABEL: Record<string, string> = {
  archived: 'В архиве',
  legacy_review: 'Проверить основание',
  permanent: 'Постоянное хранение',
  destruction_ready: 'Готов к акту',
  destruction_authorized: 'Акт утверждён',
  primary_purged: 'Удалён из рабочего хранения',
  destroyed: 'Уничтожение подтверждено',
}

function displayDate(value: string | null): string {
  if (!value) return 'не установлен'
  return new Intl.DateTimeFormat('ru-RU').format(new Date(`${value}T00:00:00`))
}

export function DocsArchiveQueue({ companyId }: { companyId: string }) {
  const [filter, setFilter] = useState<QueueFilter>('all')
  const queueQ = useInfiniteQuery({
    queryKey: ['docs-archive-queue', companyId],
    initialPageParam: '' as string,
    queryFn: ({ pageParam }) => docsService.getArchiveQueue(
      companyId, pageParam || undefined,
    ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: !!companyId,
  })
  const rows = useMemo(
    () => queueQ.data?.pages.flatMap((page) => page.documents) ?? [],
    [queueQ.data],
  )
  const visible = useMemo(() => rows.filter((row) => {
    if (filter === 'due') return !row.blocker && !row.hold
    if (filter === 'hold') return row.hold
    if (filter === 'legacy') return row.retention_state === 'legacy_review'
    if (filter === 'active') return [
      'destruction_ready', 'destruction_authorized', 'primary_purged',
    ].includes(row.retention_state)
    return true
  }), [filter, rows])

  return (
    <div className="space-y-4 px-4 py-4">
      <div>
        <h1 className="flex items-center gap-2 text-base font-semibold">
          <Archive className="h-4 w-4" />Юридический архив
        </h1>
        <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
          Срок сам ничего не удаляет. Сначала фиксируются экспертиза и акт, затем байты
          выводятся из рабочего хранилища, а завершение подтверждается отдельно.
        </p>
      </div>

      <div className="flex flex-wrap gap-2" aria-label="Фильтры архивной очереди">
        {FILTERS.map((item) => (
          <Button key={item.key} type="button" size="sm"
            variant={filter === item.key ? 'default' : 'outline'}
            aria-pressed={filter === item.key}
            onClick={() => setFilter(item.key)}>
            {item.label}
          </Button>
        ))}
      </div>

      {queueQ.isLoading && (
        <Card className="p-6 text-sm text-muted-foreground" aria-live="polite">
          Загружаем архивную очередь…
        </Card>
      )}
      {queueQ.isError && !queueQ.data && (
        <Card role="alert" className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <div className="text-sm font-medium">Архивная очередь не загрузилась</div>
            <div className="text-xs text-muted-foreground">Действия не подменены пустым списком.</div>
          </div>
          <Button type="button" size="sm" variant="outline" onClick={() => queueQ.refetch()}>
            <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
          </Button>
        </Card>
      )}

      {queueQ.data && (
        <>
          <div className="grid gap-3 xl:grid-cols-2">
            {visible.map((row) => (
            <Link key={row.id} to={`/docs?view=all&doc=${row.id}&tab=archive`}
              className="rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Card className="h-full p-4 transition-colors hover:bg-accent/30">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{row.title}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {row.reg_number ?? 'без номера'} · срок {displayDate(
                        row.retention_extended_until ?? row.storage_until,
                      )}
                    </div>
                  </div>
                  <span className="shrink-0 rounded-md bg-muted px-2 py-1 text-xs">
                    {STATE_LABEL[row.retention_state] ?? row.retention_state}
                  </span>
                </div>
                {row.hold && (
                  <div className="mt-3 flex items-center gap-1.5 text-xs font-medium text-destructive">
                    <ShieldAlert className="h-3.5 w-3.5" />Действует запрет уничтожения
                  </div>
                )}
                {row.blocker && !row.hold && (
                  <p className="mt-3 text-xs text-muted-foreground">{row.blocker}</p>
                )}
              </Card>
            </Link>
            ))}
            {visible.length === 0 && (
              <Card className="p-8 text-center text-sm text-muted-foreground xl:col-span-2">
                На загруженных страницах подходящих документов нет.
              </Card>
            )}
          </div>
          {queueQ.isFetchNextPageError && (
            <Card role="alert" className="flex items-center justify-between gap-3 p-3">
              <span className="text-xs text-destructive">
                Следующая страница не загрузилась. Уже показанные документы сохранены.
              </span>
              <Button type="button" size="sm" variant="outline"
                onClick={() => void queueQ.fetchNextPage()}>
                Повторить
              </Button>
            </Card>
          )}
          {queueQ.hasNextPage && (
            <Button type="button" variant="outline" className="w-full"
              disabled={queueQ.isFetchingNextPage}
              onClick={() => void queueQ.fetchNextPage()}>
              {queueQ.isFetchingNextPage && (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              )}
              {queueQ.isFetchingNextPage ? 'Загрузка…' : 'Показать ещё'}
            </Button>
          )}
        </>
      )}
    </div>
  )
}
