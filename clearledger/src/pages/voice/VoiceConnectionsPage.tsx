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
import { Heading } from './parts'

const SOURCE: Record<links.ConnectionSource, string> = {
  connector: 'в настройках подключения', config: 'в настройках подключения',
  env: 'в настройках установки', environment: 'в настройках установки', missing: 'не задан',
}
const date = (value: string | null | undefined) => value && Number.isFinite(Date.parse(value))
  ? new Date(value).toLocaleString('ru-RU') : 'ещё не было'
const errorText = (error: unknown) => voice.узелНедоступен(error)
  ? 'Узел заказчика не отвечает. Проверьте, запущен ли узел и виден ли он из пространства.'
  : error instanceof Error ? error.message : 'Не удалось проверить связь'

/**
 * Узел отдаёт точную причину отказа пробы Ядра (`code`), а не только «не вышло».
 * Показываем её словами: `not_configured` и `wrong_company` требуют разных действий.
 */
const CORE_CHECK: Record<string, string> = {
  ok: 'Доступ узла к Ядру и компания подтверждены.',
  not_configured: 'Проба не выполнялась: адрес Ядра или ключ не заданы в настройках установки узла.',
  invalid_url: 'Адрес Ядра задан неверно: нужен http(s) без параметров, якоря и логина с паролем.',
  timeout: 'Ядро не ответило за 3 секунды. Проверьте сеть между узлом и Ядром.',
  unreachable: 'Узел не смог подключиться к Ядру по этому адресу.',
  http_error: 'Ядро отклонило запрос узла. Чаще всего ключ недействителен или отозван.',
  invalid_response: 'По адресу Ядра ответило не Ядро: ответ не той формы.',
  wrong_company: 'Ключ узла принадлежит другой компании. Нужен ключ вашей компании.',
}

function Detail({ name, children }: { name: string; children: ReactNode }) {
  return <div className="grid min-w-0 gap-1 sm:grid-cols-[10rem_1fr]"><dt className="text-muted-foreground">{name}</dt>
    <dd className="min-w-0 break-words [overflow-wrap:anywhere]">{children}</dd></div>
}
/** Итог проверки отделён от пояснения над ним: иначе в узком окне строки сливаются. */
function Result({ ok, children }: { ok: boolean; children: ReactNode }) {
  return <p role="status" className={`border-t pt-3 text-sm ${ok ? 'text-success' : 'text-destructive'}`}>{children}</p>
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
  const [opening, setOpening] = useState<'megafon' | 'asterisk' | null>(null)
  const providers = useQuery({ queryKey: ['voice-connections', companyId], queryFn: () => links.connections(companyId), enabled: !!companyId, retry: false })
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
  const busy = providers.isFetching || node.isFetching || cc.isFetching || health.isFetching || webhooks.isFetching
  async function settings(provider: 'megafon' | 'asterisk') {
    setOpening(provider)
    try { await links.providerSettings(companyId, provider) }
    catch (error) { toast.error(errorText(error)) }
    finally { setOpening(null) }
  }
  async function refresh() {
    checkHistory.reset(); checkCore.reset()
    await Promise.all([providers.refetch(), node.refetch(), cc.refetch(), health.refetch(), webhooks.refetch()])
  }
  const forbidden = providers.error instanceof ApiError && [401, 403].includes(providers.error.status)
  if (!companyId) return <p className="p-4" role="alert">Выберите компанию</p>
  if (forbidden) return <div className="p-4"><QueryError error={providers.error} /></div>
  const pending = (loading: boolean) => loading ? 'Проверяем…' : 'Нет данных'
  const configured = (value?: boolean) => value ? 'Параметры заданы' : 'Не настроено'
  const apiSource = megafon?.sources.api_key
  const hookSource = megafon?.sources.crm_token
  const historyConfigured = megafon?.readiness.history?.configured === true
  const historyEnabled = megafon?.readiness.history?.enabled === true
  const staleHistory = megafon?.last_sync_at && Date.now() - Date.parse(megafon.last_sync_at) > 15 * 60_000
  const historyStatus = providers.error ? 'Нет подтверждения' : !megafon ? pending(providers.isPending) : !historyEnabled ? 'Выгрузка выключена'
    : megafon.last_error ? 'Ошибка обмена' : staleHistory ? 'Давно не обновлялось'
    : megafon.last_sync_at ? 'История загружается' : configured(historyConfigured)
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
      <AlertDescription>История МегаФона может загружаться при неподключённой голосовой линии узла. Связь КЦ с узлом подтверждает обмен событий; приём звонков требует отдельной настройки линии.</AlertDescription></Alert>
    <div className="grid min-w-0 gap-4 xl:grid-cols-2">
      <Shell title="МегаФон → история звонков" description="Выгрузка истории по API ВАТС. Действующий маршрут звонков сохраняется." status={historyStatus}
        actions={<><Button variant="outline" size="sm" onClick={() => void settings('megafon')} disabled={opening !== null}>Настроить МегаФон</Button>
          <Button size="sm" variant="outline" disabled={!megafon || !historyConfigured || checkHistory.isPending} onClick={() => checkHistory.mutate()}>{checkHistory.isPending ? 'Проверяем…' : 'Проверить API истории'}</Button>
          <Button asChild variant="ghost" size="sm"><Link to="/voice/megafon">Открыть историю</Link></Button></>}>
        {providers.isPending ? <Skeleton className="h-16" /> : providers.error ? <QueryError error={providers.error} /> : <dl className="flex flex-col gap-2">
          <Detail name="Адрес API">{megafon?.endpoint ?? 'Не задан'}</Detail>
          <Detail name="Ключ API">{apiSource ? SOURCE[apiSource] : 'Не задан'}</Detail>
          <Detail name="Последний обмен">{date(megafon?.last_sync_at)}</Detail>
          <Detail name="Входящие события">{configured(megafon?.readiness.events?.configured)}{hookSource && hookSource !== 'missing' ? `, ключ ${SOURCE[hookSource]}` : ''}</Detail>
        </dl>}
        {megafon?.last_error ? <p role="alert" className="text-destructive">{megafon.last_error}</p> : null}
        <p className="text-xs text-muted-foreground">Проверка читает минимальный ответ API и не сохраняет звонки. Наличие ключа вебхука не подтверждает доставку событий МегаФона.</p>
        {checkHistory.data ? <Result ok={checkHistory.data.ok}>{checkHistory.data.message} Проверено {date(checkHistory.data.at)}.</Result> : null}
        {checkHistory.error ? <QueryError error={checkHistory.error} /> : null}
      </Shell>
      <Shell title="Узел ↔ пространство" description="Вход администратора, карточки клиентов и доступ узла к Ядру." status={node.error ? 'Нет подтверждения' : node.data ? 'Настройки установки прочитаны' : pending(node.isPending)}
        actions={<><Button size="sm" variant="outline" disabled={checkCore.isPending} onClick={() => checkCore.mutate()}>
            {/* кнопка доступна и без ключа: узел ответит not_configured, и человек увидит причину вместо погасшей кнопки */}
            {checkCore.isPending ? 'Проверяем…' : 'Проверить доступ к Ядру'}</Button>
          <Button asChild size="sm" variant="ghost"><Link to="/voice/webhooks">Ключи систем</Link></Button></>}>
        {node.isPending ? <Skeleton className="h-20" /> : node.error ? <QueryError error={node.error} /> : <dl className="flex flex-col gap-2">
          <Detail name="Адрес узла">{node.data?.node.url ?? 'Не задан'}</Detail>
          <Detail name="Адрес Ядра">{core?.url ?? 'Не задан'}</Detail>
          <Detail name="Ключ узла для Ядра">{core?.keyConfigured ? 'Задан в настройках установки' : 'Не задан'}</Detail>
          <Detail name="Проверка входа (JWKS)">{space?.jwksUrl ?? 'Не настроен'}</Detail>
          <Detail name="Издатель входа">{space?.issuer ?? 'Нет данных'}</Detail>
          <Detail name="Компания узла">{space?.companyIds.join(', ') || 'Нет данных'}</Detail>
          <Detail name="Защита канала">{space?.mtls ? 'Клиентский сертификат (mTLS)' : 'Без клиентского сертификата'}</Detail>
        </dl>}
        <p className="text-xs text-muted-foreground">Адреса и сертификаты задаются при установке узла. Проверка подтверждает ключ и компанию без чтения карточек клиентов.</p>
        {checkCore.data ? <Result ok={checkCore.data.status === 'ok'}>{CORE_CHECK[checkCore.data.code] ?? 'Доступ узла к Ядру не подтверждён. Проверьте адрес, ключ и компанию.'}</Result> : null}
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
      <Shell title="МегаФон → голосовая линия узла" description="Соединение, через которое реальные звонки могут попасть в новое приложение КЦ." status={voiceStatus}
        actions={<Button asChild size="sm" variant="outline"><Link to="/voice/health">Состояние узла и транка</Link></Button>}>
        {node.error ? <QueryError error={node.error} /> : <dl className="flex flex-col gap-2">
          <Detail name="Настройка транка">{node.data ? node.data.trunkConfigured ? 'Задана' : 'Не задана' : 'Нет данных'}</Detail>
          <Detail name="Состояние транка">{health.data?.parts?.trunk?.state === 'up' ? 'На связи' : health.data?.parts?.trunk?.state === 'off' ? 'Выключен' : 'Не подтверждено'}</Detail>
        </dl>}
        {health.error ? <QueryError error={health.error} /> : null}
        <p className="text-xs text-muted-foreground">Подключение транка и переключение номеров выполняются отдельным этапом. Этот экран показывает состояние; действующие настройки ВАТС МегаФона он не изменяет.</p>
      </Shell>
      <Shell title="Распознавание и подсказки" description="Обработка разговоров внутри узла компании." status={node.error ? 'Нет подтверждения' : node.data ? node.data.asr.ready ? 'Распознавание готово' : configured(node.data.asr.configured) : pending(node.isPending)}
        actions={<Button asChild size="sm" variant="outline"><Link to="/voice/enrichment">Настройки обработки</Link></Button>}>
        {node.error ? <QueryError error={node.error} /> : <dl className="flex flex-col gap-2">
          <Detail name="Распознавание">{node.data?.asr.ready ? 'Готово' : node.data?.asr.configured ? 'Настроено, готовность не подтверждена' : 'Не подключено'}</Detail>
          <Detail name="Подсказки модели">{node.data?.llm.ready ? 'Готовы' : node.data?.llm.configured ? 'Настроены, готовность не подтверждена' : 'Выключены'}</Detail>
        </dl>}
        <p className="text-xs text-muted-foreground">История МегаФона сама по себе не передаёт звук в распознавание. Записи и расшифровки остаются в узле компании.</p>
      </Shell>
    </div>
  </div>
}
