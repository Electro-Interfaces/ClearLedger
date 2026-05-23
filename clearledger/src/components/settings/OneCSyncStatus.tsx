/**
 * Статус синхронизации 1С — badge, кнопки ручного запуска, progress.
 */

import { useState } from 'react'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import {
  RefreshCw, BookOpen, FileText, Loader2, Upload,
  ArrowDownToLine, ArrowUpFromLine, CheckCircle2,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { ru } from 'date-fns/locale'
import {
  useSyncStatus,
  useSyncCatalogs,
  useSyncDocuments,
  useSyncFull,
  useExportTo1C,
} from '@/hooks/useOneCSync'

interface Props {
  connectionId: string
  exchangePath?: string
}

export function OneCSyncStatus({ connectionId, exchangePath }: Props) {
  const { data: status, isLoading } = useSyncStatus(connectionId)
  const syncCatalogs = useSyncCatalogs()
  const syncDocuments = useSyncDocuments()
  const syncFull = useSyncFull()
  const exportTo1C = useExportTo1C()

  const [lastResult, setLastResult] = useState<{ type: string; stats: Record<string, number> } | null>(null)

  const isSyncing = status?.isSyncing ||
    syncCatalogs.isPending || syncDocuments.isPending || syncFull.isPending

  const handleSync = async (type: 'catalogs' | 'documents' | 'full') => {
    const mutations = { catalogs: syncCatalogs, documents: syncDocuments, full: syncFull }
    const labels = { catalogs: 'справочников', documents: 'документов', full: 'полную' }

    try {
      const result = await mutations[type].mutateAsync(connectionId)
      setLastResult({ type, stats: result.stats })
      if (result.status === 'success') {
        toast.success(`Синхронизация ${labels[type]} завершена: ${result.stats.created} новых, ${result.stats.updated} обновлённых`)
      } else {
        toast.error(`Ошибка синхронизации: ${result.stats.errors} ошибок`)
      }
    } catch {
      toast.error('Ошибка синхронизации')
    }
  }

  const handleExport = async () => {
    try {
      const result = await exportTo1C.mutateAsync(connectionId)
      if (result.status === 'success') {
        toast.success(`Экспортировано ${result.entriesCount} записей в папку обмена`)
      } else if (result.status === 'empty') {
        toast.info('Нет верифицированных записей для экспорта')
      } else {
        toast.error(result.error || 'Ошибка экспорта')
      }
    } catch {
      toast.error('Ошибка экспорта в 1С')
    }
  }

  if (isLoading) return null

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
              <RefreshCw className={`size-5 text-blue-500 ${isSyncing ? 'animate-spin' : ''}`} />
            </div>
            <div>
              <CardTitle>Синхронизация</CardTitle>
              <CardDescription>
                {status?.lastSyncAt
                  ? `Последняя: ${formatDistanceToNow(new Date(status.lastSyncAt), { addSuffix: true, locale: ru })}`
                  : 'Ещё не синхронизировано'}
              </CardDescription>
            </div>
          </div>
          <SyncStatusBadge isSyncing={isSyncing} connectionStatus={status?.connectionStatus} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isSyncing && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Синхронизация...
            </div>
            <Progress value={undefined} className="h-2" />
          </div>
        )}

        {/* Кнопки синхронизации */}
        <div className="space-y-2">
          <p className="text-sm font-medium flex items-center gap-2">
            <ArrowDownToLine className="size-4 text-muted-foreground" />
            Импорт из 1С
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleSync('catalogs')}
              disabled={isSyncing}
            >
              <BookOpen className="mr-2 size-4" />
              Справочники
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleSync('documents')}
              disabled={isSyncing}
            >
              <FileText className="mr-2 size-4" />
              Документы
            </Button>
            <Button
              size="sm"
              onClick={() => handleSync('full')}
              disabled={isSyncing}
            >
              {isSyncing ? <Loader2 className="mr-2 size-4 animate-spin" /> : <RefreshCw className="mr-2 size-4" />}
              Полная синхронизация
            </Button>
          </div>
        </div>

        {exchangePath && (
          <>
            <Separator />
            <div className="space-y-2">
              <p className="text-sm font-medium flex items-center gap-2">
                <ArrowUpFromLine className="size-4 text-muted-foreground" />
                Экспорт в 1С
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={handleExport}
                disabled={exportTo1C.isPending}
              >
                {exportTo1C.isPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Upload className="mr-2 size-4" />}
                Экспорт в папку обмена
              </Button>
              <p className="text-xs text-muted-foreground">
                Верифицированные записи → EnterpriseData XML → {exchangePath}/to_1c/
              </p>
            </div>
          </>
        )}

        {/* Результат последней синхронизации */}
        {lastResult && (
          <>
            <Separator />
            <div className="rounded-lg border p-3 bg-muted/30">
              <p className="text-sm font-medium mb-2">Результат</p>
              <div className="grid grid-cols-4 gap-2 text-center">
                <StatBox label="Обработано" value={lastResult.stats.processed} />
                <StatBox label="Создано" value={lastResult.stats.created} color="text-green-500" />
                <StatBox label="Обновлено" value={lastResult.stats.updated} color="text-blue-500" />
                <StatBox label="Ошибок" value={lastResult.stats.errors} color={lastResult.stats.errors > 0 ? 'text-red-500' : undefined} />
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function SyncStatusBadge({ isSyncing, connectionStatus }: { isSyncing: boolean; connectionStatus?: string }) {
  if (isSyncing) {
    return <Badge variant="default" className="bg-blue-500">Синхронизация...</Badge>
  }
  if (connectionStatus === 'error') {
    return <Badge variant="destructive">Ошибка</Badge>
  }
  if (connectionStatus === 'active') {
    return (
      <Badge variant="outline" className="border-green-500/30 text-green-600">
        <CheckCircle2 className="mr-1 size-3" /> Подключено
      </Badge>
    )
  }
  return <Badge variant="secondary">Ожидание</Badge>
}

function StatBox({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div>
      <p className={`text-lg font-bold ${color ?? ''}`}>{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  )
}
