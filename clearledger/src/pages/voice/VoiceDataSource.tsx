/** Общий выбор источника: собственный узел и независимая история каждого провайдера. */
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { ApiError } from '@/services/apiClient'
import { getPbxSources, isCallSource, SOURCE_NAMES, type CallSource } from '@/services/pbxVoiceService'

export function useVoiceDataSource(pathname: string) {
  const { companyId } = useCompany()
  const [params, setParams] = useSearchParams()
  const path = pathname.replace(/\/$/, '')
  const managed = ['/voice/calls', '/voice/stats', '/voice/report'].includes(path)
  const directPbx = path === '/voice/pbx' || path === '/voice/megafon'
  const nodeLink = ['id', 'metric', 'servedBy', 'topic', 'back', 'cc'].some(key => params.has(key))
    || ['week', 'month', 'yesterday'].includes(params.get('period') ?? '')
    || /^(cc|staff):/.test(params.get('operator') ?? '')
    || (params.has('line') && !/^\+?\d{6,}$/.test(params.get('line') ?? ''))
  const explicit = params.get('source')
  const fixedNode = explicit === 'node' || (!isCallSource(explicit) && nodeLink)
  const connection = useQuery({
    queryKey: ['voice-pbx-sources', companyId], queryFn: () => getPbxSources(companyId),
    enabled: !!companyId && path !== '/voice/connections', staleTime: 5 * 60_000, retry: false,
  })
  const unavailable = connection.error instanceof ApiError && connection.error.status === 404
  const error = managed && !fixedNode && !isCallSource(explicit) && connection.isError && !unavailable ? connection.error : null
  const loading = managed && !fixedNode && !isCallSource(explicit) && connection.isPending
  const source: CallSource = fixedNode ? 'node' : isCallSource(explicit) ? explicit : connection.data?.default_source ?? 'node'
  const providerHistory = managed && source !== 'node'
  const configured = connection.data?.sources.some(item => item.source !== 'node' && item.enabled) ?? false
  return { managed, directPbx, providerHistory, loading, error, configured, source,
    select: (value: string) => { if (isCallSource(value)) setParams({ source: value }, { replace: false }) },
    retry: () => void connection.refetch() }
}

export function VoiceDataSourceBar({ state, pathname }: { state: ReturnType<typeof useVoiceDataSource>; pathname: string }) {
  if (pathname.replace(/\/$/, '') === '/voice/connections' || state.directPbx) return null
  if (!state.managed && !state.configured) return null
  const section = pathname.split('/')[2] ?? ''
  let description = 'Этот раздел показывает данные нашего узла. Историю провайдера можно выбрать в журнале, статистике и отчёте.'
  if (section === '') description = 'Текущие звонки и операторы нашего узла. История провайдера доступна отдельно в разделе «АТС».'
  if (['contact', 'callbacks'].includes(section)) description = 'Задачи обратного звонка нашего узла. Пропуски из истории провайдера сами по себе не создают эти задачи.'
  if (section === 'report') description = 'Отчёт нашего узла. Для отчёта по истории ВАТС выберите провайдера в источнике данных.'
  if (section === 'reconcile') description = 'Детализация сравнивается с журналом нашего узла. История провайдера автоматически в сверку не добавляется.'
  if (['reception', 'passport', 'targets', 'sounds', 'enrichment', 'cc', 'webhooks', 'versions'].includes(section)) description = 'Настройки нашего узла. Подключения Mango и МегаФона настраиваются отдельно в разделе подключений.'
  if (['audit', 'retention'].includes(section)) description = 'Аудит и записи нашего узла. История провайдера хранится отдельно.'
  if (section === 'health') description = 'Состояние нашего узла и его транка. Подключение API истории ВАТС проверяется отдельно.'
  return <aside aria-label="Источник данных Телефонии" className="m-3 flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-3 text-sm">
    {state.managed ? <label className="flex flex-wrap items-center gap-2">Источник данных
      <select aria-label="Источник данных" value={state.loading ? '' : state.source} onChange={event => state.select(event.target.value)}
        className="min-h-9 max-w-full rounded-md border border-input bg-background px-2 text-sm">
        {state.loading ? <option value="">Проверяем подключение…</option> : null}
        {Object.entries(SOURCE_NAMES).map(([key, label]) => <option key={key} value={key}>{key === 'node' ? 'Все звонки узла' : `${label} · история API`}</option>)}
      </select>
    </label> : <p className="font-medium">Источник: наш узел</p>}
    <p className="text-xs text-muted-foreground">{state.providerHistory ? `${SOURCE_NAMES[state.source]} · история провайдера. При смене источника период и фильтры сбрасываются.` : description}</p>
    {state.error ? <div role="alert" className="flex flex-wrap items-center gap-2"><span>Не удалось определить источник: {state.error instanceof Error ? state.error.message : 'Ошибка API'}</span><Button variant="outline" size="sm" onClick={state.retry}>Повторить</Button></div> : null}
    {!state.managed ? <Link className="text-primary underline text-xs" to="/voice/pbx">Журнал и подключения АТС</Link> : null}
  </aside>
}
