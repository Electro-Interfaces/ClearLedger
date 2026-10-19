/** Общий выбор источника для журнала/статистики и область действия остальных экранов. */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { ApiError } from '@/services/apiClient'
import { getMegafonVoice, megafonPeriodBounds } from '@/services/megafonVoiceService'

export function useVoiceDataSource(pathname: string) {
  const { companyId } = useCompany()
  const [params, setParams] = useSearchParams()
  const [anchor] = useState(() => new Date())
  const path = pathname.replace(/\/$/, '')
  const managed = path === '/voice/calls' || path === '/voice/stats' || path === '/voice/report'
  const directMegafon = path === '/voice/megafon'
  // Старые ссылки с показателями/идентификаторами узла сохраняют свой источник.
  const nodeLink = ['id', 'metric', 'servedBy', 'topic', 'back', 'cc'].some(key => params.has(key))
    || ['week', 'month', 'yesterday'].includes(params.get('period') ?? '')
    || /^(cc|staff):/.test(params.get('operator') ?? '')
    || (params.has('line') && !/^\+?\d{6,}$/.test(params.get('line') ?? ''))
  const explicit = params.get('source')
  const fixedNode = explicit === 'node' || (explicit !== 'megafon' && nodeLink)
  const connection = useQuery({
    queryKey: ['voice-data-source', companyId],
    queryFn: () => getMegafonVoice(companyId, { ...megafonPeriodBounds('today', anchor), page: 1, page_size: 1 }),
    enabled: !!companyId && !directMegafon && path !== '/voice/connections',
    staleTime: 5 * 60_000,
    retry: false,
  })
  const configured = connection.data?.connection.configured === true
  // Отсутствие карты Поддержки означает, что этот источник не подключён компании.
  // Ошибку доступа, чужую компанию или сбой API не превращаем в пустые данные узла.
  const unavailable = connection.error instanceof ApiError && connection.error.status === 404
  const error = managed && !fixedNode && explicit !== 'megafon' && connection.isError && !unavailable
    ? connection.error : null
  const loading = managed && !fixedNode && explicit !== 'megafon' && connection.isPending
  const megafon = directMegafon || (managed && !fixedNode && (explicit === 'megafon' || configured))
  function select(source: string) {
    // Параметры разных журналов несовместимы; переключаем всю выборку явно.
    setParams({ source }, { replace: false })
  }
  return { managed, directMegafon, megafon, loading, error, configured, source: megafon ? 'megafon' : 'node',
    select, retry: () => void connection.refetch() }
}

export function VoiceDataSourceBar({ state, pathname }: { state: ReturnType<typeof useVoiceDataSource>; pathname: string }) {
  if (pathname.replace(/\/$/, '') === '/voice/connections') return null
  if (state.directMegafon) return null
  if (!state.managed && !state.configured) return null
  const section = pathname.split('/')[2] ?? ''
  let description = 'Этот раздел показывает данные узла ContactHub. История действующей МегаФон ВАТС доступна в журнале и статистике.'
  if (section === '') description = 'Здесь текущие звонки и присутствие операторов узла ContactHub. Живые разговоры и статусы операторов МегаФона сюда не поступают.'
  if (['contact', 'callbacks'].includes(section)) description = 'Здесь задачи обратного звонка узла ContactHub. Пропущенные звонки МегаФона сами по себе не создают эти задачи.'
  if (section === 'report') description = 'Этот месячный отчёт рассчитывается по звонкам узла ContactHub. Для месячного отчёта МегаФона выберите его в источнике данных.'
  if (section === 'reconcile') description = 'Здесь детализация сравнивается с журналом узла ContactHub. История МегаФона в эту сверку не включена.'
  if (['reception', 'passport', 'targets', 'sounds', 'enrichment', 'cc', 'webhooks', 'versions'].includes(section)) description = 'Настройки этого раздела относятся к узлу ContactHub. Настройки действующей ВАТС МегаФона они не изменяют.'
  if (['audit', 'retention'].includes(section)) description = 'Здесь аудит и записи узла ContactHub. Записи и чтение истории МегаФона в эти списки не включены.'
  if (section === 'health') description = 'Здесь состояние узла ContactHub и история его проверок. Состояние его транка не описывает работу действующей ВАТС МегаФона.'
  if (['extensions', 'outbound'].includes(section)) description = 'Этот экран АТС ContactHub ещё не реализован. Добавочные операторов и исходящие звонки действующей ВАТС доступны в истории МегаФона.'
  return <aside aria-label="Источник данных Телефонии" className="m-3 flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-3 text-sm">
    {state.managed ? <label className="flex flex-wrap items-center gap-2">
      Источник данных
      <select aria-label="Источник данных" value={state.loading ? '' : state.source} onChange={event => state.select(event.target.value)}
        className="min-h-9 max-w-full rounded-md border border-input bg-background px-2 text-sm">
        {state.loading ? <option value="">Проверяем подключение…</option> : null}
        <option value="megafon">МегаФон ВАТС</option><option value="node">Узел ContactHub</option>
      </select>
    </label> : <p className="font-medium">Источник: узел ContactHub</p>}
    {state.managed && state.megafon ? <p className="text-xs text-muted-foreground">История действующей МегаФон ВАТС. При смене источника период и фильтры сбрасываются.</p>
      : <p className="text-xs text-muted-foreground">{description}</p>}
    {state.error ? <div role="alert" className="flex flex-wrap items-center gap-2">
      <span>Не удалось определить источник: {state.error instanceof Error ? state.error.message : 'Ошибка API'}</span>
      <Button variant="outline" size="sm" onClick={state.retry}>Повторить</Button>
    </div> : null}
    {state.configured && !state.megafon ? <div className="flex flex-wrap gap-3 text-xs">
      <Link className="text-primary underline" to="/voice/calls?source=megafon">Журнал МегаФона</Link>
      <Link className="text-primary underline" to="/voice/stats?source=megafon">Статистика МегаФона</Link>
      {['contact', 'callbacks'].includes(section) ? <Link className="text-primary underline" to="/voice/calls?source=megafon&missed=true&period=7d">Пропущенные МегаФона</Link> : null}
    </div> : null}
  </aside>
}
