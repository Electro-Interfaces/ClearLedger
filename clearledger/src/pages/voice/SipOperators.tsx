import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import * as voice from '@/services/voiceService'

const STATUS: Record<string, string> = { draft: 'Черновик / выключено', registered: 'Зарегистрирован', rejected: 'Регистрация отклонена',
  unregistered: 'Не зарегистрирован', stopped: 'Регистрация остановлена', online: 'SIP-узел отвечает', offline: 'SIP-узел не отвечает', unknown: 'Связь не подтверждена' }
const fresh = (): voice.SipConfig => ({ provider: 'mango', name: '', mode: 'registration', host: '', port: 5060, transport: 'udp', username: '',
  authUsername: '', password: '', domain: '', fromUser: '', proxy: '', contactUser: '700', matches: [] })
const errorText = (e: unknown) => e instanceof Error ? e.message : 'Не удалось изменить подключение'
const inputClass = 'flex h-9 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
type Action = { id: string; action: 'apply' | 'disable' | 'delete' | 'primary'; name: string; revision?: number }

export function SipOperators({ companyId, openHistory }: { companyId: string; openHistory: (p: 'mango' | 'megafon') => void }) {
  const client = useQueryClient(), queryKey = ['voice-sip-operators', companyId]
  const query = useQuery({ queryKey, queryFn: () => voice.sipOperators(companyId), retry: false, refetchInterval: 5000 })
  const [editing, setEditing] = useState<string | null | undefined>(undefined)
  const [editingRevision, setEditingRevision] = useState(0)
  const [form, setForm] = useState<voice.SipConfig>(fresh)
  const [matches, setMatches] = useState('')
  const [confirmation, setConfirmation] = useState<Action | null>(null)
  const [notice, setNotice] = useState('')
  const update = <K extends keyof voice.SipConfig>(key: K, value: voice.SipConfig[K]) => setForm(current => ({ ...current, [key]: value }))
  const mutation = useMutation({ mutationFn: async (task: { kind: 'save' } | { kind: 'action'; value: Action }) => {
    if (!query.data) throw new Error('Сначала обновите список подключений')
    if (task.kind === 'save') return voice.saveSipOperator(companyId, editing ?? null, editingRevision,
      { ...form, matches: matches.split(/[\s,]+/).filter(Boolean) })
    return voice.changeSipOperator(companyId, task.value.id, task.value.revision ?? -1, task.value.action)
  }, onSuccess: (data, task) => {
    client.setQueryData(queryKey, data); setConfirmation(null)
    if (task.kind === 'save') { setEditing(undefined); setForm(fresh()); setNotice('Черновик сохранён. Для включения линии нажмите «Подключить».') }
    else setNotice(task.value.action === 'primary' ? 'Линия для исходящих изменена.' : task.value.action === 'apply'
      ? 'Параметры применены к АТС. Состояние регистрации обновляется автоматически.' : 'Подключение изменено.')
  }, onError: () => { void query.refetch() } })
  const provider = query.data?.operators.find(p => p.id === form.provider)
  const current = query.data?.items.find(p => p.id === editing)
  function edit(profile?: voice.SipProfile) {
    mutation.reset(); setConfirmation(null); setNotice(''); setEditing(profile?.id ?? null); setEditingRevision(query.data?.revision ?? 0)
    if (profile) { const { passwordConfigured: _, ...config } = profile.draft; setForm({ ...config, password: '' }); setMatches(config.matches.join('\n')) }
    else { setForm(fresh()); setMatches('') }
  }
  function request(value: Action) { mutation.reset(); setNotice(''); setConfirmation({ ...value, revision: query.data?.revision }) }
  function save(event: FormEvent) { event.preventDefault(); mutation.mutate({ kind: 'save' }) }
  const busy = mutation.isPending
  return <section aria-label="Операторы связи" className="min-w-0 rounded-lg border bg-card p-4 sm:p-6">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-lg font-semibold">Операторы связи</h2><p className="mt-1 max-w-3xl text-sm text-muted-foreground">SIP-подключения для входящих и исходящих звонков через АТС. Можно подключить несколько операторов и выбрать линию для исходящих.</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={query.isFetching || busy} onClick={() => void query.refetch()}>Проверить состояния</Button>
        <Button size="sm" disabled={!query.data || busy || editing !== undefined} onClick={() => edit()}>Добавить оператора</Button></div>
    </div>
    {query.isPending ? <p className="mt-4 text-sm" role="status">Загружаем подключения…</p> : null}
    {query.error ? <p role="alert" className="mt-4 text-sm text-destructive">{errorText(query.error)}</p> : null}
    {query.data ? <div className="mt-5 divide-y">
      {query.data.legacy ? <div className="flex flex-wrap items-center justify-between gap-3 py-4">
        <div><div className="flex flex-wrap items-center gap-2"><h3 className="font-medium">Действующая установочная линия</h3>{query.data.legacy.primary ? <Badge variant="secondary">Для исходящих</Badge> : null}</div>
          <p className="mt-1 text-sm text-muted-foreground">{query.data.legacy.endpoint}. Параметры заданы при установке узла.</p></div>
        {!query.data.legacy.primary ? <Button size="sm" variant="outline" disabled={busy} onClick={() => request({ id: 'legacy', action: 'primary', name: 'Установочная линия' })}>Использовать для исходящих</Button> : null}
      </div> : null}
      {query.data.items.map(profile => <div key={profile.id} className="flex flex-wrap items-start justify-between gap-3 py-4">
        <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="break-words font-medium">{profile.draft.name}</h3>
          <Badge variant={['registered', 'online'].includes(profile.status) ? 'default' : 'secondary'}>{STATUS[profile.status] ?? 'Нет данных'}</Badge>
          {query.data.primary === profile.id ? <Badge variant="secondary">Для исходящих</Badge> : null}</div>
          <p className="mt-1 break-all text-sm text-muted-foreground">{query.data.operators.find(p => p.id === profile.draft.provider)?.name} · {profile.applied?.host ?? profile.draft.host}:{profile.applied?.port ?? profile.draft.port} · {(profile.applied?.transport ?? profile.draft.transport).toUpperCase()}</p>
          {profile.applied && profile.changed ? <p className="mt-1 text-sm">Сохранены изменения, которые ещё не применены.</p> : null}</div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={busy || editing !== undefined} onClick={() => edit(profile)}>Изменить</Button>
          {!profile.applied || profile.changed ? <Button size="sm" disabled={busy || editing !== undefined} onClick={() => request({ id: profile.id, action: 'apply', name: profile.draft.name })}>{profile.applied ? 'Применить изменения' : 'Подключить'}</Button> : null}
          {profile.applied && query.data.primary !== profile.id ? <Button size="sm" variant="outline" disabled={busy || !['registered', 'online'].includes(profile.status)} onClick={() => request({ id: profile.id, action: 'primary', name: profile.draft.name })}>Для исходящих</Button> : null}
          <Button size="sm" variant="ghost" disabled={busy || query.data.primary === profile.id || editing !== undefined} onClick={() => request({ id: profile.id, action: profile.applied ? 'disable' : 'delete', name: profile.draft.name })}>{profile.applied ? 'Отключить' : 'Удалить'}</Button>
        </div>
      </div>)}
      {!query.data.items.length ? <p className="py-4 text-sm text-muted-foreground">Добавьте Mango, МегаФон, Билайн, МТС или другого SIP-оператора. Действующая установочная линия продолжит работать.</p> : null}
    </div> : null}
    {editing !== undefined ? <form onSubmit={save} aria-label="Настройка SIP-оператора" className="mt-5 border-t pt-5">
      <h3 className="font-semibold">{editing ? 'Изменить подключение' : 'Новое подключение'}</h3>
      <fieldset disabled={busy} className="mt-4 grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <label className="grid min-w-0 gap-1 text-sm">Оператор<select aria-label="Оператор" className={inputClass} value={form.provider} onChange={e => update('provider', e.target.value)}>{query.data?.operators.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label className="grid min-w-0 gap-1 text-sm">Название подключения<Input required maxLength={100} value={form.name} onChange={e => update('name', e.target.value)} placeholder="Основная линия офиса" /></label>
        <label className="grid min-w-0 gap-1 text-sm">Режим подключения<select aria-label="Режим подключения" className={inputClass} value={form.mode} onChange={e => update('mode', e.target.value as voice.SipConfig['mode'])}><option value="registration">Регистрация по логину и паролю</option><option value="ip">Авторизация по IP</option></select></label>
        <p className="text-sm text-muted-foreground sm:col-span-2 lg:col-span-3">{provider?.help} {provider?.docs ? <a className="underline underline-offset-4" href={provider.docs} target="_blank" rel="noreferrer">Инструкция оператора</a> : null}</p>
        <label className="grid min-w-0 gap-1 text-sm">SIP-сервер<Input required value={form.host} onChange={e => update('host', e.target.value.trim())} placeholder="Адрес из кабинета оператора" autoCapitalize="none" spellCheck={false} /></label>
        <label className="grid min-w-0 gap-1 text-sm">Порт<Input required type="number" min={1} max={65535} value={form.port} onChange={e => update('port', Number(e.target.value))} /></label>
        <label className="grid min-w-0 gap-1 text-sm">Транспорт<select aria-label="Транспорт" className={inputClass} value={form.transport} onChange={e => update('transport', e.target.value as voice.SipConfig['transport'])}><option value="udp">UDP</option><option value="tcp">TCP</option><option value="tls">TLS</option></select></label>
        {form.mode === 'registration' ? <><label className="grid min-w-0 gap-1 text-sm">SIP-логин<Input required value={form.username} autoComplete="off" autoCapitalize="none" spellCheck={false} onChange={e => update('username', e.target.value)} /></label>
          <label className="grid min-w-0 gap-1 text-sm">SIP-пароль<Input type="password" autoComplete="new-password" required={!current?.draft.passwordConfigured} value={form.password ?? ''} onChange={e => update('password', e.target.value)} placeholder={current?.draft.passwordConfigured ? 'Сохранён. Пустое поле сохранит пароль.' : 'Пароль от SIP-подключения'} /></label>
          <label className="grid min-w-0 gap-1 text-sm">Номер входящего маршрута<Input aria-label="Номер входящего маршрута" value={form.contactUser} pattern="[0-9]{2,20}" onChange={e => update('contactUser', e.target.value)} /><span className="text-xs text-muted-foreground">Contact user: цифры, по умолчанию 700.</span></label></> : null}
        <label className="grid min-w-0 gap-1 text-sm sm:col-span-2 lg:col-span-3">IP-адреса входящих серверов{form.mode === 'ip' ? ' (обязательно)' : ' (если выданы оператором)'}<textarea className={inputClass + ' h-20 py-2'} required={form.mode === 'ip'} value={matches} onChange={e => setMatches(e.target.value)} placeholder="IP или CIDR, по одному на строку" /><span className="text-xs text-muted-foreground">Укажите только адреса оператора. При регистрации входящие также связываются с линией через SIP-параметр line.</span></label>
      </fieldset>
      <details className="mt-4"><summary className="cursor-pointer text-sm font-medium">Дополнительные параметры SIP</summary><fieldset disabled={busy} className="mt-3 grid gap-4 sm:grid-cols-2">
        <label className="grid gap-1 text-sm">Имя авторизации (Auth ID)<Input value={form.authUsername} onChange={e => update('authUsername', e.target.value)} placeholder="Если отличается от логина" autoComplete="off" /></label>
        <label className="grid gap-1 text-sm">Домен SIP<Input value={form.domain} onChange={e => update('domain', e.target.value)} placeholder="По умолчанию SIP-сервер" /></label>
        <label className="grid gap-1 text-sm">Исходящий прокси<Input value={form.proxy} onChange={e => update('proxy', e.target.value)} placeholder="Сервер или сервер:порт" /></label>
        <label className="grid gap-1 text-sm">From user<Input value={form.fromUser} onChange={e => update('fromUser', e.target.value)} placeholder="Если требует оператор" /></label>
      </fieldset></details>
      <p className="mt-4 text-sm text-muted-foreground">SIP-пароль сохраняется на узле компании. Сохранение черновика не меняет работающую линию.</p>
      <p className="mt-2 text-sm">История и события ВАТС: {provider?.historyApi === 'support' ? <Button type="button" size="sm" variant="link" onClick={() => openHistory(form.provider as 'mango' | 'megafon')}>Настроить API {provider.name}</Button> : 'отдельный API-адаптер этого оператора пока не подключён. Звонки через наш узел попадут в его журнал.'}</p>
      <div className="mt-4 flex flex-wrap gap-2"><Button type="submit" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить черновик'}</Button><Button type="button" variant="outline" disabled={busy} onClick={() => { setEditing(undefined); setForm(fresh()); mutation.reset() }}>Отмена</Button></div>
    </form> : null}
    {confirmation ? <div className="mt-4 rounded-md border p-4" role="group" aria-label="Подтверждение изменения линии">
      <p className="font-medium">{confirmation.name}</p><p className="mt-1 text-sm">{confirmation.action === 'apply' ? 'Применить сохранённые SIP-параметры к АТС? Другие подключения сохранятся.' : confirmation.action === 'primary' ? 'Использовать эту линию для новых исходящих и обратных звонков со стандартным маршрутом?' : confirmation.action === 'disable' ? 'Отключить регистрацию и приём звонков через это подключение?' : 'Удалить черновик подключения?'}</p>
      <p className="mt-1 text-sm text-muted-foreground">Изменение действующей конфигурации доступно после завершения звонков.</p>
      <div className="mt-3 flex gap-2"><Button size="sm" disabled={busy} onClick={() => mutation.mutate({ kind: 'action', value: confirmation })}>{busy ? 'Применяем…' : 'Подтвердить'}</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirmation(null)}>Отмена</Button></div>
    </div> : null}
    {mutation.error ? <p role="alert" className="mt-4 text-sm text-destructive">{errorText(mutation.error)}{mutation.error instanceof voice.VoiceError && mutation.error.code === 'sip_revision_conflict' ? ' Отмените правку и откройте подключение заново, чтобы увидеть свежие параметры.' : ''}</p> : null}
    {notice ? <p role="status" className="mt-4 text-sm">{notice}</p> : null}
  </section>
}
