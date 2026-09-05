/**
 * Витрина подключений пространства: один список всех источников компании — файловых
 * каналов Учёта, живых интеграций Координатора и платформенных сервисов.
 *
 * Пространство одно, поэтому и список один: колонка «Приложение» показывает, кто владеет
 * подключением, а не разводит их по разным экранам. Поддерживаемые провайдеры настраиваются
 * здесь через API владельца; ключи сохраняются только в его приложении.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, ArrowDownToLine, CheckCircle2, CircleOff, HelpCircle, Loader2, PauseCircle, Plus, Settings2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useCompany } from '@/contexts/CompanyContext'
import { useOpenApp } from '@/hooks/useOpenApp'
import { listSpaceConnectors, type SpaceConnector } from '@/services/spaceConnectorsService'
import { listSsoApps } from '@/services/ssoService'
import { managedConnectorService, type ManagedConnectorProvider } from '@/services/spaceConnectorsService'
import { ManagedConnectorDialog } from './ManagedConnectorDialog'
import { useCanManage } from '@/hooks/useCanManage'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

/**
 * Состояние подключения одним словом.
 *
 * Порядок веток — не косметика. Ошибка проверяется ПЕРВОЙ и по обоим признакам:
 * раньше сломанный канал (`status: 'error'`, текста ошибки у каналов нет вовсе)
 * проваливался в ветку «не включён» и показывался «Выключен», а упавший Matrix
 * и коннектор приложения со `status: 'unknown'` доходили до конца и красились
 * зелёным «Работает» — то есть живая проверка делалась и терялась здесь.
 */
function statusView(c: SpaceConnector) {
  if (c.last_error || c.status === 'error') {
    return { label: 'Ошибка', cls: 'text-destructive', Icon: AlertTriangle }
  }
  if (c.status === 'paused') return { label: 'Пауза', cls: 'text-amber-500', Icon: PauseCircle }
  if (c.status === 'draft') return { label: 'Черновик', cls: 'text-muted-foreground', Icon: PauseCircle }
  // Заведён, но работать не может: у почтового ящика нет сервера или пароля. Без
  // этой ветки такой ящик показывался «Работает» — витрина обещала приём, которого нет.
  if (c.status === 'setup') return { label: 'Не настроен', cls: 'text-amber-500', Icon: Settings2 }
  if (!c.enabled || c.status === 'off') {
    return { label: 'Выключен', cls: 'text-muted-foreground', Icon: CircleOff }
  }
  // Состояние неизвестно — так и говорим. Зелёная галочка по умолчанию обещала
  // работу там, где её никто не проверял.
  if (c.status === 'unknown') {
    return { label: 'Состояние неизвестно', cls: 'text-muted-foreground', Icon: HelpCircle }
  }
  if (c.status === 'configured') {
    return { label: 'Настроен', cls: 'text-muted-foreground', Icon: Settings2 }
  }
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
  return <CompanySpaceConnectors key={companyId} />
}

function CompanySpaceConnectors() {
  const { companyId, company } = useCompany()
  const { canManage } = useCanManage()
  const queryClient = useQueryClient()
  const [addingFor, setAddingFor] = useState<string | null>(null)
  const [editor, setEditor] = useState<{ companyId: string; provider: ManagedConnectorProvider; id?: string } | null>(null)
  const navigate = useNavigate()
  const { openApp } = useOpenApp()
  const catalog = useQuery({
    queryKey: ['managed-connector-catalog', companyId],
    queryFn: () => managedConnectorService.catalog(companyId),
    enabled: !!companyId && canManage,
    staleTime: 30_000,
    retry: false,
  })

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
  // Молча исчезнуть нельзя: на месте списка оставался чистый экран, и раздел читался
  // как «подключений нет». Пустое место — это утверждение о составе, которого мы не
  // проверяли; лучше сказать, что не ответило Ядро.
  if (q.isError) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          Список подключений сейчас не собрался — Ядро не ответило. Сами подключения при
          этом работают: обновите страницу через минуту.
        </CardContent>
      </Card>
    )
  }

  const items = q.data?.connectors ?? []
  const problems = q.data?.problems ?? []
  const failing = items.filter((c) => c.last_error || c.status === 'error').length
  const live = items.filter(
    (c) => c.enabled && !c.last_error && c.status !== 'error' && c.status !== 'off').length
  // Две стороны обмена (docs/CONNECT.md): наши подключения — мы ходим во внешние
  // системы; входящие — внешний мир стучится к нам. До В1 входящие не были видны
  // нигде, и ответа «кто подключён к нам» у администратора не существовало.
  const ours = items.filter((c) => (c.initiator ?? 'us') !== 'them')
  const inbound = items.filter((c) => c.initiator === 'them')

  function openSettings(c: SpaceConnector) {
    if (c.management) {
      const provider = catalog.data?.providers.find((item) => item.app === c.app && item.provider === c.provider)
      if (canManage && provider) setEditor({ companyId, provider, id: c.management.id })
      return
    }
    if (c.settings_route) { navigate(c.settings_route); return }
    const app = (appsQ.data?.apps ?? []).find((a) => a.code === c.settings_app)
    if (app) openApp(app)
  }

  function rowsOf(list: SpaceConnector[]) {
    return list.map((c) => {
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
            {/* У источника обмена нет: его ведут каналы поверх. Раньше в эту клетку
                подставлялась дата ручной проверки — витрина выдавала проверку за
                обмен данными у всех живых интеграций. */}
            {c.last_sync_at
              ? sinceLabel(c.last_sync_at)
              : c.last_test_at
                ? <span title="Обмена ещё не было — это время последней проверки подключения">
                    проверен {sinceLabel(c.last_test_at)}
                  </span>
                : '—'}
            {c.records != null && c.records > 0 && (
              <div className="text-xs">{c.records.toLocaleString('ru-RU')} записей</div>
            )}
          </TableCell>
          <TableCell>
            {(c.settings_route || c.settings_app) && canManage && (
              <Button variant="ghost" size="icon" title={c.management ? 'Настроить подключение' : 'Настроить у владельца'} aria-label={`Настроить ${c.label}`}
                disabled={!!c.management && !catalog.data?.providers.some((item) => item.app === c.app && item.provider === c.provider)}
                onClick={() => openSettings(c)}>
                <Settings2 className="h-4 w-4" />
              </Button>
            )}
          </TableCell>
        </TableRow>
      )
    })
  }

  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold">Подключения пространства</h2>
            <p className="text-sm text-muted-foreground">
              Источники и обмены выбранной организации. Создавайте подключения, настраивайте доступ и проверяйте связь.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3"><span className="text-xs text-muted-foreground">
            Работают: {live} из {items.length}
            {failing > 0 && <span className="text-destructive"> · с ошибкой: {failing}</span>}
          </span>{canManage && <Button size="sm" onClick={() => setAddingFor(companyId)}><Plus className="size-4" />Добавить подключение</Button>}</div>
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
        {canManage && (catalog.isError || !!catalog.data?.problems.length) && <p className="text-sm text-muted-foreground">
          Настройка некоторых подключений недоступна. <button className="underline underline-offset-4" onClick={() => { setAddingFor(companyId); void catalog.refetch() }}>Показать причину</button>
        </p>}

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
              {rowsOf(ours)}
              {inbound.length > 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={6} className="bg-muted/30 py-1.5 text-xs font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      <ArrowDownToLine className="h-3.5 w-3.5 text-primary" />
                      Входящие — кто подключён к нам
                      <span className="font-normal text-muted-foreground">
                        · внешние системы сами присылают данные в пространство
                      </span>
                    </span>
                  </TableCell>
                </TableRow>
              )}
              {rowsOf(inbound)}
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
        {addingFor === companyId && canManage && <Dialog open onOpenChange={(open) => { if (!open) setAddingFor(null) }}>
          <DialogContent className="sm:max-w-lg"><DialogHeader><DialogTitle>Добавить подключение</DialogTitle>
            <DialogDescription>{company.name} · выберите внешнюю систему</DialogDescription></DialogHeader>
            {catalog.isPending ? <p role="status" className="flex items-center gap-2"><Loader2 className="size-4 animate-spin" />Получаем доступные подключения…</p>
              : <div className="space-y-3">
                {catalog.data?.providers.map((provider) => <button key={`${provider.app}:${provider.provider}`}
                  className="w-full rounded-md border p-4 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => { setAddingFor(null); setEditor({ companyId, provider }) }}>
                  <span className="block font-medium">{provider.title}</span><span className="mt-1 block text-sm text-muted-foreground">{provider.intro}</span>
                </button>)}
                {catalog.data?.problems.map((problem) => <p key={problem.app} role="alert" className="text-sm text-muted-foreground">{problem.message}</p>)}
                {catalog.isError && <p role="alert" className="text-sm text-destructive">Каталог подключений не загрузился. Повторите запрос.</p>}
                {!catalog.isError && !catalog.data?.providers.length && !catalog.data?.problems.length && <p className="text-sm text-muted-foreground">Для этой организации пока нет доступных подключений. Проверьте состав приложений организации.</p>}
                {(catalog.isError || !!catalog.data?.problems.length) && <Button variant="outline" onClick={() => catalog.refetch()}>Повторить</Button>}
              </div>}
          </DialogContent>
        </Dialog>}
        {editor && editor.companyId === companyId && canManage && <ManagedConnectorDialog key={`${companyId}:${editor.id || 'new'}`}
          companyId={companyId} companyName={company.name} provider={editor.provider} connectorId={editor.id}
          onClose={() => setEditor(null)} onSaved={() => {
            void queryClient.invalidateQueries({ queryKey: ['space-connectors', companyId] })
            void queryClient.invalidateQueries({ queryKey: ['managed-connector', companyId] })
          }} />}
      </CardContent>
    </Card>
  )
}
