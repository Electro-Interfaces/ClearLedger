import { CalendarRange, MapPin, RotateCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useDocsScope } from '@/hooks/useDocsScope'
import { formatPeriod } from '@/lib/formatDate'
import { NewWorkButton } from '@/components/work/NewWorkButton'

export function DocsScopeBar() {
  const scope = useDocsScope()
  const selectedObjects = scope.objectIds.length
  return (
    <div className="shrink-0 border-b border-border/60 bg-muted/35 px-3 py-2 text-xs"
      aria-live="polite">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {/* Кнопка создания стоит в шапке продукта, а не на отдельных экранах:
            человек заводит работу оттуда, где он сейчас, — из ленты, с доски,
            из очереди «На мне». */}
        <NewWorkButton />
        <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
          <CalendarRange className="h-3.5 w-3.5" aria-hidden="true" />
          Рабочий контур: {formatPeriod(scope.period.from, scope.period.to)}
        </span>
        <span className="inline-flex items-center gap-1.5 text-muted-foreground">
          <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
          {scope.regionIds.length > 0
            ? `регионов: ${scope.regionIds.length}, объектов: ${selectedObjects}`
            : scope.locationIds.length > 0
              ? `объектов: ${selectedObjects}`
              : 'все объекты'}
        </span>
        <span className="text-muted-foreground">
          Период применён к реестру и отчётам; объекты — к реестру и сводке документов;
          личные очереди показывают все ожидающие действия.
        </span>
        {scope.sourceSpecific && (
          <span className="text-muted-foreground">
            Источник и топливо относятся только к учётным экранам.
          </span>
        )}
        {scope.resolving && <span className="text-muted-foreground">Уточняем объекты региона…</span>}
        {scope.failed && (
          <span role="alert" className="inline-flex items-center gap-2 text-destructive">
            Регион не применён — данные Трека не загружены.
            <Button type="button" size="sm" variant="outline" className="h-7"
              onClick={() => scope.retry()}>
              <RotateCw className="mr-1 h-3 w-3" />Повторить
            </Button>
          </span>
        )}
      </div>
    </div>
  )
}
