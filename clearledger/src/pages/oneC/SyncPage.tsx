/**
 * «Синхронизация 1С» — единая точка запуска и обновления данных из 1С:Бухгалтерии.
 *
 * Сводит вместе: статус + ручной запуск (OneCSyncStatus), автообновление по
 * расписанию (клиентский планировщик, oneCAutoSync) и историю (OneCSyncHistory).
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Loader2, Plug, Clock, RefreshCw } from 'lucide-react'
import { format } from 'date-fns'
import { useOneCConnections } from '@/hooks/useOneCSync'
import { OneCSyncStatus } from '@/components/settings/OneCSyncStatus'
import { OneCSyncHistory } from '@/components/settings/OneCSyncHistory'
import {
  getAutoSyncCfg, setAutoSyncCfg, getNextAutoRun, type AutoSyncCfg,
} from '@/services/oneCAutoSync'
import type { OneCConnection } from '@/types'

const INTERVAL_OPTIONS = [
  { sec: 300, label: 'Каждые 5 минут' },
  { sec: 900, label: 'Каждые 15 минут' },
  { sec: 1800, label: 'Каждые 30 минут' },
  { sec: 3600, label: 'Каждый час' },
  { sec: 21600, label: 'Каждые 6 часов' },
  { sec: 43200, label: 'Каждые 12 часов' },
  { sec: 86400, label: 'Раз в сутки' },
]

function AutoSyncCard({ conn }: { conn: OneCConnection }) {
  const [cfg, setCfg] = useState<AutoSyncCfg>(() => getAutoSyncCfg(conn.id, conn.syncIntervalSec))
  const next = cfg.enabled ? getNextAutoRun(conn.id, conn.syncIntervalSec) : null

  function update(patch: Partial<AutoSyncCfg>) {
    const nextCfg = { ...cfg, ...patch }
    setCfg(nextCfg)
    setAutoSyncCfg(conn.id, nextCfg)
    if (patch.enabled === true) toast.success('Автообновление 1С включено', { description: 'Полная синхронизация по расписанию, пока приложение открыто' })
    if (patch.enabled === false) toast.info('Автообновление 1С выключено')
  }

  return (
    <Card className="py-4 gap-3">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <Clock className="h-4 w-4 text-muted-foreground" /> Автообновление по расписанию
        </CardTitle>
        <CardDescription className="text-[11px]">
          Клиентский планировщик: полная синхронизация по интервалу, пока открыто приложение.
          Настоящее фоновое обновление на сервере — следующий шаг.
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0 flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="flex items-center gap-2">
          <Switch id="autosync" checked={cfg.enabled} onCheckedChange={(v) => update({ enabled: v })} />
          <Label htmlFor="autosync" className="text-sm cursor-pointer">Включить автообновление</Label>
        </div>

        <div className="flex items-center gap-2">
          <Label className="text-xs text-muted-foreground">Интервал</Label>
          <Select value={String(cfg.intervalSec)} onValueChange={(v) => update({ intervalSec: Number(v) })} disabled={!cfg.enabled}>
            <SelectTrigger className="h-8 w-[190px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {INTERVAL_OPTIONS.map((o) => (
                <SelectItem key={o.sec} value={String(o.sec)} className="text-xs">{o.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {next && (
          <div className="text-xs text-muted-foreground ml-auto">
            Следующее обновление: <span className="text-primary font-medium">{format(next, 'dd.MM HH:mm')}</span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function SyncPage() {
  const { data: connections, isLoading } = useOneCConnections()

  if (isLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  const conn = connections?.find((c) => c.status === 'active') ?? connections?.[0]

  if (!conn) {
    return (
      <div className="max-w-2xl space-y-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Синхронизация 1С</h1>
          <p className="text-sm text-muted-foreground mt-1">Получение и обновление данных из 1С:Бухгалтерии.</p>
        </div>
        <Card className="py-8">
          <CardContent className="flex flex-col items-center justify-center gap-3 text-muted-foreground">
            <Plug className="h-8 w-8 opacity-30" />
            <p className="text-sm">Подключение к 1С не настроено</p>
            <Button asChild size="sm" variant="outline" className="text-xs h-8">
              <Link to="/1c/connection"><Plug className="h-3.5 w-3.5 mr-1.5" /> Настроить подключение</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            <RefreshCw className="h-5 w-5 text-muted-foreground" /> Синхронизация 1С
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Единый запуск и обновление данных из 1С:Бухгалтерии · подключение «{conn.name}».
          </p>
        </div>
        <Button asChild variant="ghost" size="sm" className="h-8 text-xs gap-1.5 shrink-0">
          <Link to="/1c/connection"><Plug className="h-3.5 w-3.5" /> Подключение</Link>
        </Button>
      </div>

      {/* Ручной запуск + статус (готовая панель) */}
      <OneCSyncStatus connectionId={conn.id} exchangePath={conn.exchangePath} />

      {/* Автообновление */}
      <AutoSyncCard conn={conn} />

      {/* История */}
      <OneCSyncHistory connectionId={conn.id} />
    </div>
  )
}

export default SyncPage
