import { useId, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Copy, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { managedConnectorService, type ManagedConnectorProvider, type ManagedConnectorState } from '@/services/spaceConnectorsService'

type EditorProps = {
  companyId: string
  companyName: string
  provider: ManagedConnectorProvider
  connectorId?: string
  onClose: () => void
  onSaved: () => void
}

export function ManagedConnectorDialog(props: EditorProps) {
  const detail = useQuery({
    queryKey: ['managed-connector', props.companyId, props.provider.app, props.connectorId],
    queryFn: () => managedConnectorService.read(props.companyId, props.provider.app, props.connectorId!),
    enabled: !!props.connectorId,
    retry: false,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
  })
  if (props.connectorId && (!detail.isFetchedAfterMount || detail.isError)) return (
    <Dialog open onOpenChange={(open) => { if (!open) props.onClose() }}>
      <DialogContent><DialogHeader><DialogTitle>{props.provider.title}</DialogTitle><DialogDescription>{props.companyName}</DialogDescription></DialogHeader>
        {!detail.isError ? <div role="status" className="flex items-center gap-2 py-8"><Loader2 className="size-4 animate-spin" />Загружаем настройки…</div>
          : <div role="alert" className="space-y-3 py-4"><p>Не удалось получить настройки. Повторите запрос.</p><Button variant="outline" onClick={() => detail.refetch()}>Повторить</Button></div>}
        <DialogFooter><Button variant="outline" onClick={props.onClose}>Закрыть</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
  return <ManagedConnectorForm {...props} initial={detail.data || null} />
}

function ManagedConnectorForm({ companyId, companyName, provider, connectorId, onClose, onSaved, initial }: EditorProps & { initial: ManagedConnectorState | null }) {
  const prefix = useId()
  const [newId] = useState(() => crypto.randomUUID())
  const [saved, setSaved] = useState(initial)
  const [label, setLabel] = useState(initial?.label || provider.title)
  const [enabled, setEnabled] = useState(initial?.enabled || false)
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(provider.fields.filter((field) => !field.secret).map((field) => {
    const value = initial?.values[field.key] ?? field.fallback ?? ''
    return [field.key, Array.isArray(value) ? value.join('\n') : value]
  })))
  const [credentials, setCredentials] = useState<Record<string, string>>({})
  const [removed, setRemoved] = useState<string[]>([])
  const [dirty, setDirty] = useState(false)
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)
  const [actionResult, setActionResult] = useState<{ ok: boolean; message: string } | null>(null)

  function accept(row: ManagedConnectorState) {
    setSaved(row)
    setLabel(row.label)
    setEnabled(row.enabled)
    setValues(Object.fromEntries(Object.entries(row.values).map(([key, value]) => [key, Array.isArray(value) ? value.join('\n') : value])))
    setCredentials({})
    setRemoved([])
    setDirty(false)
    setActionResult(null)
  }

  const save = useMutation({
    mutationFn: () => {
      const body = {
        label, enabled,
        values: Object.fromEntries(provider.fields.filter((field) => !field.secret).map((field) => [field.key,
          field.list ? (values[field.key] || '').split(/[\n,;]+/).map((value) => value.trim()).filter(Boolean) : values[field.key] || field.fallback || '',
        ])),
        credentials: Object.fromEntries([
          ...Object.entries(credentials).filter(([key, value]) => value.trim() && !removed.includes(key)),
          ...removed.map((key) => [key, null]),
        ]),
      }
      return saved || connectorId
        ? managedConnectorService.update(companyId, provider.app, saved?.id || connectorId!, body)
        : managedConnectorService.create(companyId, provider.app, { ...body, id: newId, provider: provider.provider })
    },
    onSuccess: (row) => { accept(row); onSaved() },
  })
  const action = useMutation({
    mutationFn: (code: string) => managedConnectorService.action(companyId, provider.app, saved!.id, code),
    onSuccess: async (result) => {
      const row = await managedConnectorService.read(companyId, provider.app, saved!.id).catch(() => null)
      if (row) accept(row)
      setActionResult(result)
      onSaved()
    },
  })
  const busy = save.isPending || action.isPending
  const error = save.error || action.error
  const check = actionResult || saved?.last_check
  const webhook = saved?.webhook_path
    ? `${new URL(saved.owner_base_url || provider.owner_base_url, window.location.origin).href.replace(/\/$/, '')}${saved.webhook_path}` : null
  const change = () => { setDirty(true); setActionResult(null); save.reset(); action.reset() }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="flex max-h-[90dvh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{provider.title}</DialogTitle>
          <DialogDescription>{companyName} · {saved ? saved.enabled ? 'Подключение включено' : 'Подключение выключено' : 'Новое подключение'}</DialogDescription>
        </DialogHeader>
            <form id={`${prefix}-form`} onSubmit={(event) => { event.preventDefault(); save.mutate() }} className="min-h-0 space-y-5 overflow-y-auto pr-1">
              <p className="text-sm text-muted-foreground">{provider.intro}</p>
              <fieldset disabled={busy} className="space-y-4">
                <div className="space-y-2"><Label htmlFor={`${prefix}-label`}>Название подключения</Label>
                  <Input id={`${prefix}-label`} value={label} required maxLength={120} onChange={(event) => { setLabel(event.target.value); change() }} />
                </div>
                {provider.fields.filter((field) => !field.readOnly).map((field) => {
                  const id = `${prefix}-${field.key}`
                  const isRemoved = removed.includes(field.key)
                  return <div key={field.key} className="space-y-2">
                    <Label htmlFor={id}>{field.label}</Label>
                    {field.list ? <Textarea id={id} value={values[field.key] || ''} rows={3} placeholder={field.placeholder}
                      onChange={(event) => { setValues((current) => ({ ...current, [field.key]: event.target.value })); change() }} />
                      : <Input id={id} type={field.secret ? 'password' : 'text'} autoComplete={field.secret ? 'new-password' : 'off'} disabled={isRemoved}
                        value={field.secret ? credentials[field.key] || '' : values[field.key] || ''}
                        placeholder={field.secret && saved?.secrets[field.key] ? 'Ключ задан — оставьте пустым, чтобы сохранить' : field.placeholder}
                        onChange={(event) => {
                          const setter = field.secret ? setCredentials : setValues
                          setter((current) => ({ ...current, [field.key]: event.target.value })); change()
                        }} />}
                    {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
                    {field.secret && saved?.secrets[field.key] && <Button type="button" size="sm" variant="ghost"
                      aria-label={`${isRemoved ? 'Отменить удаление' : 'Удалить сохранённый'} ${field.label}`}
                      onClick={() => { setRemoved((current) => isRemoved ? current.filter((key) => key !== field.key) : [...current, field.key]); change() }}>
                      {isRemoved ? 'Ключ будет удалён — отменить' : 'Удалить сохранённый ключ'}
                    </Button>}
                  </div>
                })}
                <div className="flex items-start gap-3 rounded-md border p-3">
                  <Checkbox id={`${prefix}-enabled`} checked={enabled} onCheckedChange={(value) => { setEnabled(value === true); change() }} />
                  <div className="space-y-1"><Label htmlFor={`${prefix}-enabled`}>Подключение включено</Label>
                    <p className="text-xs text-muted-foreground">После сохранения включённое подключение принимает события и загружает историю.</p>
                  </div>
                </div>
              </fieldset>
              {webhook ? <div className="space-y-2 border-t pt-4">
                <Label htmlFor={`${prefix}-webhook`}>Адрес для событий Mango</Label>
                <div className="flex gap-2"><Input id={`${prefix}-webhook`} value={webhook} readOnly className="min-w-0 text-xs" />
                  <Button type="button" variant="outline" size="icon" aria-label="Скопировать адрес для событий" onClick={async () => {
                    setCopyFailed(false)
                    try { await navigator.clipboard.writeText(webhook); setCopied(true) } catch { setCopied(false); setCopyFailed(true) }
                  }}><Copy className="size-4" /></Button></div>
                <p className="text-xs text-muted-foreground" role="status">{copyFailed ? 'Не удалось скопировать адрес. Выделите и скопируйте его вручную.' : copied ? 'Адрес скопирован.' : 'Укажите этот адрес в API-коннекторе личного кабинета Mango Office.'}</p>
              </div> : <p className="text-xs text-muted-foreground">Адрес для приёма событий появится после сохранения.</p>}
              <div className="space-y-3 border-t pt-4">
                <div className="flex flex-wrap gap-2">{provider.actions.map((item) => <Button key={item.code} type="button" variant="outline"
                  disabled={busy || !saved?.configured || dirty || (item.code === 'sync' && !saved.enabled)}
                  onClick={() => action.mutate(item.code)}>{action.isPending && action.variables === item.code && <Loader2 className="size-4 animate-spin" />}{item.label}</Button>)}</div>
                {dirty && saved && <p className="text-xs text-muted-foreground">Сохраните изменения перед проверкой и загрузкой.</p>}
                {check && <div role={check.ok ? 'status' : 'alert'} className={`flex items-start gap-2 text-sm ${check.ok ? 'text-foreground' : 'text-destructive'}`}>
                  {check.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0" />}{check.message}
                </div>}
                {saved?.last_sync_at && <p className="text-xs text-muted-foreground">Последняя загрузка: {new Date(saved.last_sync_at).toLocaleString('ru-RU')}</p>}
                {saved?.last_error && <p role="alert" className="text-sm text-destructive">{saved.last_error}</p>}
              </div>
            </form>
        {error && <p role="alert" className="text-sm text-destructive">{error.message || 'Не удалось сохранить подключение. Повторите запрос.'}</p>}
        {save.isSuccess && !dirty && <p role="status" className="text-sm text-muted-foreground">Изменения сохранены</p>}
        <DialogFooter className="border-t pt-4">
          <Button type="button" variant="outline" onClick={onClose}>Закрыть</Button>
          <Button type="submit" form={`${prefix}-form`} disabled={busy || (!!saved && !dirty)}>
            {save.isPending && <Loader2 className="size-4 animate-spin" />}Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
