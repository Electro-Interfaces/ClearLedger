import { useState, type ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Cable, ExternalLink, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useCompany } from '@/contexts/CompanyContext'
import { ApiError } from '@/services/apiClient'
import * as links from '@/services/voiceConnectionsService'
import * as voice from '@/services/voiceService'
import { getPbxSources, SOURCE_NAMES } from '@/services/pbxVoiceService'
import { SipOperators } from './SipOperators'
import { Heading } from './parts'

const SOURCE: Record<links.ConnectionSource, string> = {
  connector: 'в настройках подключения', config: 'в настройках подключения',
  env: 'в настройках установки', environment: 'в настройках установки', missing: 'не задан',
}
const date = (value: string | null | undefined) => value && Number.isFinite(Date.parse(value))
  ? new Date(value).toLocaleString('ru-RU') : 'ещё не было'
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Не удалось проверить связь'

function Detail({ name, children }: { name: string; children: ReactNode }) {
  return <div className="grid min-w-0 gap-1 sm:grid-cols-[10rem_1fr]"><dt className="text-muted-foreground">{name}</dt>
    <dd className="min-w-0 break-words [overflow-wrap:anywhere]">{children}</dd></div>
}
function Result({ ok, children }: { ok: boolean; children: ReactNode }) {
  return <p role="status" className={ok ? 'text-sm text-success' : 'text-sm text-destructive'}>{children}</p>
}
function QueryError({ error }: { error: unknown }) {
  return <p role="alert" className="text-sm text-destructive">{errorText(error)}</p>
}
function Shell({ title, description, status, children, actions }: {
  title: string; description: string; status: string; children: ReactNode; actions?: ReactNode
}) {
  return <Card className="min-w-0" aria-label={title}>
    <CardHeader><CardTitle><h2 className="text-base">{title}</h2></CardTitle><CardDescription>{description}</CardDescription>
      <div><Badge variant="secondary">{status}</Badge></div></CardHeader>
    <CardContent className="flex min-w-0 flex-col gap-3 text-sm">{children}</CardContent>
    {actions ? <CardFooter className="mt-auto flex flex-wrap gap-2">{actions}</CardFooter> : null}
  </Card>
}

export default function VoiceConnectionsPage() {
  const { companyId } = useCompany()
  const [opening, setOpening] = useState<'megafon' | 'mango' | 'asterisk' | null>(null)
  const providers = useQuery({ queryKey: ['voice-connections', companyId], queryFn: () => links.connections(companyId), enabled: !!companyId, retry: false })
  const sources = useQuery({ queryKey: ['voice-pbx-sources', companyId], queryFn: () => getPbxSources(companyId), enabled: !!companyId, retry: false })
  const [pickedProvider, setPickedProvider] = useState<'mango' | 'megafon' | null>(null)
  const enabledProvider = sources.data?.sources.find(item => item.source !== 'node' && item.enabled)?.source
  const historyProvider: 'mango' | 'megafon' = pickedProvider ?? (enabledProvider === 'megafon' ? 'megafon' : 'mango')
  const history = sources.data?.sources.find(item => item.source === historyProvider)
  const node = useQuery({ queryKey: ['voice-node-connections', companyId], queryFn: () => voice.nodeConnections(companyId), enabled: !!companyId, retry: false })
  const cc = useQuery({ queryKey: ['voice-cc', companyId], queryFn: () => voice.ccConnections(companyId), enabled: !!companyId, retry: false })
  const health = useQuery({ queryKey: ['voice-health', companyId], queryFn: () => voice.health(companyId), enabled: !!companyId, retry: false })
  const webhooks = useQuery({ queryKey: ['voice-webhooks', companyId], queryFn: () => voice.webhooks(companyId), enabled: !!companyId, retry: false })
  const megafon = providers.data?.connections.find(c => c.provider === 'megafon' && c.enabled)
    ?? providers.data?.connections.find(c => c.provider === 'megafon')
  const support = providers.data?.connections.find(c => c.provider === 'asterisk' && c.enabled)
    ?? providers.data?.connections.find(c => c.provider === 'asterisk')
  const active = cc.data?.items.find(c => c.state === 'active')
  const current = active ?? cc.data?.items.find(c => c.state !== 'revoked')
  const ccUrl = links.ccSettingsUrl(current?.ccIssuer)
  const checkHistory = useMutation({ mutationFn: () => {
    if (!megafon) throw new Error('Для проверки выберите подключение МегаФона в Поддержке')
    return links.checkProvider(companyId, megafon.id)
  } })
  const checkCore = useMutation({ mutationFn: () => voice.checkCoreConnection(companyId) })
  const busy = providers.isFetching || sources.isFetching || node.isFetching || cc.isFetching || health.isFetching || webhooks.isFetching
  async function settings(provider: 'megafon' | 'mango' | 'asterisk') {
    setOpening(provider)
    try { await links.providerSettings(companyId, provider) }
    catch (error) { toast.error(errorText(error)) }
    finally { setOpening(null) }
  }
  async function refresh() {
    checkHistory.reset(); checkCore.reset()
    await Promise.all([providers.refetch(), sources.refetch(), node.refetch(), cc.refetch(), health.refetch(), webhooks.refetch()])
  }
  const forbidden = providers.error instanceof ApiError && [401, 403].includes(providers.error.status)
  if (!companyId) return <p className="p-4" role="alert">Выберите компанию</p>
  if (forbidden) return <div className="p-4"><QueryError error={providers.error} /></div>
  const pending = (loading: boolean) => loading ? 'Проверяем…' : 'Нет данных'
  const configured = (value?: boolean) => value ? 'Параметры заданы' : 'Не настроено'
  const apiSource = megafon?.sources.api_key
  const historyConfigured = megafon?.readiness.history?.configured === true
  const core = node.data?.core
  const space = node.data?.space
  const receiverUrl = support?.webhook_path ? new URL(`/support${support.webhook_path}`, window.location.origin).href : null
  const subscription = webhooks.data?.items.find(w => w.url === receiverUrl)
  const supportEvents: voice.EventType[] = ['call.completed', 'callback.opened', 'callback.merged', 'callback.closed']
  const subscriptionComplete = supportEvents.every(type => subscription?.types.includes(type))
  const supportStatus = providers.error || webhooks.error ? 'Нет подтверждения' : providers.isPending || webhooks.isPending ? 'Проверяем…' : !support ? pending(providers.isPending)
    : !support.readiness.events?.enabled ? 'Приём событий не настроен' : !subscription ? 'Подписка узла не найдена'
    : subscriptionComplete ? 'Получатель и подписка настроены' : 'Состав событий неполный'
  const voiceStatus = node.error || health.error ? 'Нет подтверждения' : !node.data ? pending(node.isPending) : !node.data.trunkConfigured ? 'Голосовая линия не подключена'
    : health.data?.parts?.trunk?.state === 'up' ? 'Транк на связи' : 'Транк требует проверки'

  return <div className="flex flex-col gap-4 p-4">
    <Heading имя="Настройки подключений" подпись="Связи провайдера, пространства, узла и контакт-центра.">
      <Button variant="outline" size="sm" disabled={busy} onClick={() => void refresh()}><RefreshCw data-icon="inline-start" />Обновить состояния</Button>
    </Heading>
    <Alert><Cable /><AlertTitle>Данные и голосовая линия подключаются отдельно</AlertTitle>
      <AlertDescription>История ВАТС может загружаться при неподключённой голосовой линии узла. Связь КЦ с узлом подтверждает обмен событий; приём звонков требует отдельной настройки линии.</AlertDescription></Alert>
    <SipOperators key={companyId} companyId={companyId} openHistory={provider => void settings(provider)} />
    <div className="grid min-w-0 gap-4 xl:grid-cols-2">
      <Shell title="АТС · история провайдера" description="Подключение API Mango или МегаФона для загрузки истории ВАТС."
        status={sources.error ? 'Нет подтверждения' : !history?.connector_id ? 'Подключение не создано' : !history.enabled ? 'Выключено' : history.has_error ? 'Ошибка обмена' : 'Подключение сохранено'}
        actions={<><Button variant="outline" size="sm" onClick={() => void settings(historyProvider)} disabled={opening !== null}>Настроить {SOURCE_NAMES[historyProvider]}</Button>
          {historyProvider === 'megafon' ? <Button size="sm" variant="outline" disabled={!megafon || !historyConfigured || checkHistory.isPending} onClick={() => checkHistory.mutate()}>Проверить API истории</Button> : null}
          <Button asChild variant="ghost" size="sm"><Link to={`/voice/pbx?source=${historyProvider}`}>Открыть историю</Link></Button></>}>
        <label className="flex flex-wrap items-center gap-2 text-sm">Провайдер ВАТС
          <select aria-label="Провайдер ВАТС" value={historyProvider} onChange={event => { setPickedProvider(event.target.value as 'mango' | 'megafon'); checkHistory.reset() }}
            className="min-h-9 max-w-full rounded-md border border-input bg-background px-2 text-sm">
            <option value="mango">Mango</option><option value="megafon">МегаФон</option>
          </select>
        </label>
        {sources.isPending ? <Skeleton className="h-16" /> : sources.error ? <QueryError error={sources.error} /> : <dl className="flex flex-col gap-2">
          <Detail name="Провайдер">{SOURCE_NAMES[historyProvider]}</Detail>
          <Detail name="История по API">{history?.enabled ? 'Загрузка включена' : 'Загрузка не включена'}</Detail>
          <Detail name="Последний обмен">{date(history?.last_sync_at)}</Detail>
          {historyProvider === 'megafon' ? <><Detail name="Адрес API">{megafon?.endpoint ?? 'Не задан'}</Detail><Detail name="Ключ API">{apiSource ? SOURCE[apiSource] : 'Не задан'}</Detail></> : null}
        </dl>}
        <p className="text-xs text-muted-foreground">API истории и голосовая линия SIP настраиваются отдельно. Секреты провайдера сохраняются в Поддержке.</p>
        {historyProvider === 'megafon' && checkHistory.data ? <Result ok={checkHistory.data.ok}>{checkHistory.data.message} Проверено {date(checkHistory.data.at)}.</Result> : null}
        {historyProvider === 'megafon' && checkHistory.error ? <QueryError error={checkHistory.error} /> : null}
      </Shell>
      <Shell title="Узел ↔ пространство" description="Вход администратора, карточки клиентов и доступ узла к Ядру." status={node.error ? 'Нет подтверждения' : node.data ? 'Настройки установки прочитаны' : pending(node.isPending)}
        actions={<><Button size="sm" variant="outline" disabled={!core?.keyConfigured || checkCore.isPending} onClick={() => checkCore.mutate()}>Проверить доступ к Ядру</Button>
          <Button asChild size="sm" variant="ghost"><Link to="/voice/webhooks">Ключи систем</Link></Button></>}>
        {node.isPending ? <Skeleton className="h-20" /> : node.error ? <QueryError error={node.error} /> : <dl className="flex flex-col gap-2">
          <Detail name="Адрес узла">{node.data?.node.url ?? 'Не задан'}</Detail>
          <Detail name="Адрес Ядра">{core?.url ?? 'Не задан'}</Detail>
          <Detail name="Ключ узла">{core?.keyConfigured ? 'Задан в настройках установки' : 'Не задан'}</Detail>
          <Detail name="Вход пространства">{space?.jwksUrl ?? 'Не настроен'}</Detail>
          <Detail name="Защита канала">{space?.mtls ? 'Клиентский сертификат (mTLS)' : 'Без клиентского сертификата'}</Detail>
        </dl>}
        <p className="text-xs text-muted-foreground">Адреса и сертификаты задаются при установке узла. Проверка подтверждает ключ и компанию без чтения карточек клиентов.</p>
        {checkCore.data ? <Result ok={checkCore.data.status === 'ok'}>{checkCore.data.status === 'ok' ? 'Доступ узла к Ядру и компания подтверждены.' : 'Доступ узла к Ядру не подтверждён. Проверьте адрес, ключ и компанию.'}</Result> : null}
        {checkCore.error ? <QueryError error={checkCore.error} /> : null}
      </Shell>
      <Shell title="Контакт-центр ↔ узел" description="Подключение КЦ, поток событий и допуск операторов." status={cc.error ? 'Нет подтверждения' : active ? active.online ? 'Подключён, поток на связи' : 'Подключён, поток вне сети' : current ? 'Требует завершения настройки' : pending(cc.isPending)}
        actions={<><Button asChild size="sm" variant="outline"><Link to="/voice/cc">Подключение и допуски</Link></Button>
          {ccUrl ? <Button asChild size="sm" variant="outline"><a href={ccUrl} target="_blank" rel="noopener noreferrer"><ExternalLink data-icon="inline-start" />Настройки приложения КЦ</a></Button> : null}</>}>
        {cc.isPending ? <Skeleton className="h-16" /> : cc.error ? <QueryError error={cc.error} /> : <dl className="flex flex-col gap-2">
          <Detail name="Адрес КЦ">{current?.ccIssuer ?? 'КЦ ещё не подключён'}</Detail>
          <Detail name="Приём событий">{active?.online ? 'Поток на связи' : 'Не подтверждён'}</Detail>
          <Detail name="Подтверждено событий">{active?.ackedSeq ?? 'Нет данных'}</Detail>
        </dl>}
        <p className="text-xs text-muted-foreground">Приглашение создаётся на узле, принимается в настройках приложения КЦ, затем сверяется отпечаток ключа. Для админки КЦ нужен её собственный вход и второй фактор.</p>
      </Shell>
      <Shell title="Узел → Поддержка" description="Доставка итогов звонков и событий обратного звонка подписанным вебхуком." status={supportStatus}
        actions={<><Button size="sm" variant="outline" disabled={opening !== null} onClick={() => void settings('asterisk')}>Настроить приём в Поддержке</Button>
          <Button asChild size="sm" variant="outline"><Link to="/voice/webhooks">Получатели и доставки узла</Link></Button></>}>
        {providers.error ? <QueryError error={providers.error} /> : <dl className="flex flex-col gap-2">
          <Detail name="Приём событий">{support?.enabled ? 'Включён' : 'Выключен'}</Detail>
          <Detail name="Ключ подписи">{support?.sources.webhook_secret ? SOURCE[support.sources.webhook_secret] : 'Не задан'}</Detail>
          <Detail name="Адрес получателя">{receiverUrl ?? 'Откройте настройки приёма'}</Detail>
          <Detail name="Состав событий">{subscription ? `${supportEvents.filter(type => subscription.types.includes(type)).length} из ${supportEvents.length} необходимых: ${subscriptionComplete ? 'итоги и обратные звонки' : 'проверьте состав'}` : 'Подписка на узле не найдена'}</Detail>
          <Detail name="Последняя доставка">{date(subscription?.lastDeliveredAt)}</Detail>
        </dl>}
        {webhooks.error ? <QueryError error={webhooks.error} /> : null}
        <p className="text-xs text-muted-foreground">На узле и у получателя должен быть один секрет подписи. Изменить состав можно в разделе получателей. Фактическую доставку подтверждает журнал событий.</p>
      </Shell>
      <Shell title="Оператор связи → голосовая линия SIP" description="Соединение, через которое реальные звонки могут попасть в новое приложение КЦ." status={voiceStatus}
        actions={<Button asChild size="sm" variant="outline"><Link to="/voice/health">Состояние узла и транка</Link></Button>}>
        {node.error ? <QueryError error={node.error} /> : <dl className="flex flex-col gap-2">
          <Detail name="Настройка транка">{node.data ? node.data.trunkConfigured ? 'Задана' : 'Не задана' : 'Нет данных'}</Detail>
          <Detail name="Состояние транка">{health.data?.parts?.trunk?.state === 'up' ? 'На связи' : health.data?.parts?.trunk?.state === 'off' ? 'Выключен' : 'Не подтверждено'}</Detail>
        </dl>}
        {health.error ? <QueryError error={health.error} /> : null}
        <p className="text-xs text-muted-foreground">SIP-подключения настраиваются в разделе «Операторы связи» выше. Переключение входящих номеров выполняется также в кабинете оператора связи.</p>
      </Shell>
      <Shell title="Распознавание и подсказки" description="Обработка разговоров внутри узла компании." status={node.error ? 'Нет подтверждения' : node.data ? node.data.asr.ready ? 'Распознавание готово' : configured(node.data.asr.configured) : pending(node.isPending)}
        actions={<Button asChild size="sm" variant="outline"><Link to="/voice/enrichment">Настройки обработки</Link></Button>}>
        {node.error ? <QueryError error={node.error} /> : <dl className="flex flex-col gap-2">
          <Detail name="Распознавание">{node.data?.asr.ready ? 'Готово' : node.data?.asr.configured ? 'Настроено, готовность не подтверждена' : 'Не подключено'}</Detail>
          <Detail name="Подсказки модели">{node.data?.llm.ready ? 'Готовы' : node.data?.llm.configured ? 'Настроены, готовность не подтверждена' : 'Выключены'}</Detail>
        </dl>}
        <p className="text-xs text-muted-foreground">История ВАТС сама по себе не передаёт звук в распознавание. Записи и расшифровки остаются в узле компании.</p>
      </Shell>
    </div>
  </div>
}
