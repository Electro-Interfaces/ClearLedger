/**
 * Витрина подключений пространства: один список всех источников компании — файловых
 * каналов Учёта, живых интеграций Координатора и платформенных сервисов.
 *
 * Пространство одно, поэтому и список один: колонка «Приложение» показывает, кто владеет
 * подключением, а не разводит их по разным экранам. Настройка остаётся у владельца —
 * отсюда только переход (ключи провайдеров живут в приложении, дублировать их нельзя).
 */
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, CircleOff, Loader2, PauseCircle, Settings2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useCompany } from '@/contexts/CompanyContext'
import { useOpenApp } from '@/hooks/useOpenApp'
import { listSpaceConnectors, type SpaceConnector } from '@/services/spaceConnectorsService'
import { listSsoApps } from '@/services/ssoService'

function statusView(c: SpaceConnector) {
  if (c.last_error) return { label: 'Ошибка', cls: 'text-destructive', Icon: AlertTriangle }
  if (!c.enabled || c.status === 'off') return { label: 'Выключен', cls: 'text-muted-foreground', Icon: CircleOff }
  if (c.status === 'paused') return { label: 'Пауза', cls: 'text-amber-500', Icon: PauseCircle }
  if (c.status === 'draft') return { label: 'Черновик', cls: 'text-muted-foreground', Icon: PauseCircle }
  return { label: 'Работает', cls: 'text-emerald-500', Icon: CheckCircle2 }
}

/** «5 минут назад» вместо даты: у живой интеграции важна свежесть, а не момент. */
function sinceLabel(iso: string | null): string {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(ms)) return '—'
  const min = Math.floor(ms / 60000)
  if (min < 1) return 'только что'
  if (min < 60) return `${min} мин назад`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} ч назад`
  return `${Math.floor(h / 24)} дн назад`
}

export function SpaceConnectors() {
  const { companyId } = useCompany()
  const navigate = useNavigate()
  const { openApp } = useOpenApp()

  const q = useQuery({
    queryKey: ['space-connectors', companyId],
    queryFn: () => listSpaceConnectors(companyId),
    enabled: !!companyId,
    staleTime: 30_000,
    refetchInterval: 60_000,   // живые интеграции: список стареет за минуты
    retry: false,
  })
  // Каталог нужен, чтобы увести настраивать в приложение единым входом.
  const appsQ = useQuery({
    queryKey: ['sso-apps', companyId],
    queryFn: () => listSsoApps(companyId),
    staleTime: 5 * 60_000,
    retry: false,
  })

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 py-6 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Собираем подключения пространства…
      </div>
    )
  }
  if (q.isError) return null

  const items = q.data?.connectors ?? []
  const problems = q.data?.problems ?? []
  const live = items.filter((c) => c.enabled && !c.last_error).length
  const failing = items.filter((c) => c.last_error).length

  function openSettings(c: SpaceConnector) {
    if (c.settings_route) { navigate(c.settings_route); return }
    const app = (appsQ.data?.apps ?? []).find((a) => a.code === c.settings_app)
    if (app) openApp(app)
  }

  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold">Подключения пространства</h2>
            <p className="text-sm text-muted-foreground">
              Откуда компания получает данные — во всех приложениях сразу. Настройка живёт
              там, где подключение заведено.
            </p>
          </div>
          <span className="text-xs text-muted-foreground">
            Работают: {live} из {items.length}
            {failing > 0 && <span className="text-destructive"> · с ошибкой: {failing}</span>}
          </span>
        </div>

        {problems.length > 0 && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-muted-foreground">
            {problems.map((p) => (
              <div key={p.app}>
                <span className="font-medium text-foreground">{p.app_name}</span>: {p.error}
              </div>
            ))}
          </div>
        )}

        <div className="overflow-x-auto rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[150px]">Приложение</TableHead>
                <TableHead>Подключение</TableHead>
                <TableHead className="w-[150px]">Вид</TableHead>
                <TableHead className="w-[130px]">Состояние</TableHead>
                <TableHead className="w-[130px]">Последний обмен</TableHead>
                <TableHead className="w-[60px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((c) => {
                const st = statusView(c)
                return (
                  <TableRow key={c.key}>
                    <TableCell>
                      <Badge variant="secondary" className="font-normal">{c.app_name}</Badge>
                    </TableCell>
                    <TableCell className="max-w-[420px]">
                      <div className="truncate font-medium">{c.label}</div>
                      {c.brings && (
                        <div className="truncate text-xs text-muted-foreground" title={c.brings}>{c.brings}</div>
                      )}
                      {c.last_error && (
                        <div className="mt-0.5 text-xs text-destructive">{c.last_error}</div>
                      )}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{c.kind}</TableCell>
                    <TableCell>
                      <span className={`inline-flex items-center gap-1.5 text-sm ${st.cls}`}>
                        <st.Icon className="h-4 w-4" /> {st.label}
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {sinceLabel(c.last_sync_at)}
                      {c.records != null && c.records > 0 && (
                        <div className="text-xs">{c.records.toLocaleString('ru-RU')} записей</div>
                      )}
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="icon" title="Настроить у владельца"
                        onClick={() => openSettings(c)}>
                        <Settings2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
              {items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="py-6 text-center text-sm text-muted-foreground">
                    Подключений пока нет
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
