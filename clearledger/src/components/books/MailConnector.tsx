/**
 * Почтовый коннектор пространства — вкладка «Загрузка → Почта» (docs/MAIL.md).
 *
 * Один коннектор, много ящиков: `info@`, `buh@`, `edo@`. У каждого своё назначение
 * человеческими словами — без него через месяц никто не помнит, чем ящики
 * отличаются и какие письма куда идут.
 *
 * Пароль ящика в интерфейс не вводится и в базе не лежит: указывается ИМЯ
 * переменной окружения стека, значение живёт в `.env` рядом с остальными
 * секретами. Экран показывает лишь, найдена ли переменная, — иначе «ящик не
 * отвечает» выясняется опросом, а не настройкой.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle, CheckCircle2, Inbox, Mail, Paperclip, Plus, RefreshCw, Trash2,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import {
  createMailAccount, deleteMailAccount, getMailAccounts, getMailThread, getMailThreads,
  mailAttachmentUrl, pollMail, updateMailAccount,
  type MailAccount, type MailAccountInput,
} from '@/services/mailService'

const EMPTY: MailAccountInput = {
  address: '', title: '', purpose: '', mode: 'both',
  imapHost: '', imapPort: 993, imapFolder: 'INBOX', login: '', secretEnv: '',
  smtpHost: '', smtpPort: 587, isActive: true,
}

const MODES: { key: MailAccountInput['mode']; label: string }[] = [
  { key: 'both', label: 'приём и отправка' },
  { key: 'in', label: 'только приём' },
  { key: 'out', label: 'только отправка' },
]

export function MailConnector() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [form, setForm] = useState<(MailAccountInput & { id?: string }) | null>(null)
  const [threadId, setThreadId] = useState<string | null>(null)

  const accounts = useQuery({
    queryKey: ['mail', 'accounts', companyId],
    queryFn: () => getMailAccounts(companyId),
    enabled: !!companyId,
  })
  const threads = useQuery({
    queryKey: ['mail', 'threads', companyId],
    queryFn: () => getMailThreads(companyId),
    enabled: !!companyId,
  })
  const thread = useQuery({
    queryKey: ['mail', 'thread', companyId, threadId],
    queryFn: () => getMailThread(companyId, threadId!),
    enabled: !!companyId && !!threadId,
  })

  const save = useMutation({
    mutationFn: (a: MailAccountInput & { id?: string }) =>
      a.id ? updateMailAccount(companyId, a.id, a) : createMailAccount(companyId, a),
    onSuccess: () => {
      setForm(null)
      qc.invalidateQueries({ queryKey: ['mail'] })
      toast.success('Ящик сохранён')
    },
    onError: () => toast.error('Не удалось сохранить ящик'),
  })

  const poll = useMutation({
    mutationFn: (id?: string) => pollMail(companyId, id),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['mail'] })
      if (r.error) toast.error(r.error)
      else toast.success(`Забрано писем: ${r.fetched ?? 0}, новых: ${r.saved ?? 0}`)
    },
    onError: () => toast.error('Опрос не удался'),
  })

  const remove = useMutation({
    mutationFn: (id: string) => deleteMailAccount(companyId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mail'] }),
  })

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex items-center gap-2">
            <Mail className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium">Ящики компании</span>
            <div className="ml-auto flex gap-2">
              <Button size="sm" variant="outline" onClick={() => poll.mutate(undefined)}
                disabled={poll.isPending}>
                <RefreshCw className={cn('size-4 mr-1.5', poll.isPending && 'animate-spin')} />
                Забрать почту
              </Button>
              <Button size="sm" onClick={() => setForm({ ...EMPTY })}>
                <Plus className="size-4 mr-1.5" /> Ящик
              </Button>
            </div>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Один коннектор на компанию: ящики отличаются учёткой, назначением и правилами.
            Пароль здесь не вводится — указывается имя переменной окружения стека,
            значение живёт в <code>.env</code> рядом с остальными секретами.
          </p>

          <div className="space-y-2">
            {(accounts.data?.rows ?? []).map((a) => (
              <AccountRow key={a.id} a={a}
                onEdit={() => setForm({ ...a })}
                onPoll={() => poll.mutate(a.id)}
                onDelete={() => remove.mutate(a.id)} />
            ))}
            {(accounts.data?.rows ?? []).length === 0 && (
              <div className="text-sm text-muted-foreground">
                Ящиков пока нет. Заведите первый — например, тот, куда контрагенты
                присылают закрывающие документы.
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {form && (
        <Card>
          <CardContent className="p-4 space-y-3">
            <div className="text-sm font-medium">
              {form.id ? 'Ящик' : 'Новый ящик'}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Адрес" hint="то, что видит контрагент">
                <Input value={form.address} placeholder="buh@company.ru"
                  onChange={(e) => setForm({ ...form, address: e.target.value })} />
              </Field>
              <Field label="Название" hint="как называть в пространстве">
                <Input value={form.title} placeholder="Бухгалтерия"
                  onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </Field>
              <Field label="Назначение" hint="что сюда приходит и что с этим делать" span>
                <Textarea rows={2} value={form.purpose ?? ''}
                  placeholder="Контрагенты присылают закрывающие документы и счета"
                  onChange={(e) => setForm({ ...form, purpose: e.target.value })} />
              </Field>
              <Field label="Режим">
                <div className="flex gap-1">
                  {MODES.map((m) => (
                    <button key={m.key} onClick={() => setForm({ ...form, mode: m.key })}
                      className={cn('rounded-md border px-2.5 py-1 text-xs',
                        form.mode === m.key
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'text-muted-foreground hover:bg-muted')}>
                      {m.label}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="IMAP-сервер" hint="откуда забираем письма">
                <Input value={form.imapHost ?? ''} placeholder="imap.company.ru"
                  onChange={(e) => setForm({ ...form, imapHost: e.target.value })} />
              </Field>
              <Field label="Логин">
                <Input value={form.login ?? ''} placeholder="buh@company.ru"
                  onChange={(e) => setForm({ ...form, login: e.target.value })} />
              </Field>
              <Field label="Переменная с паролем" hint="имя в .env стека, не сам пароль">
                <Input value={form.secretEnv ?? ''} placeholder="MAIL_BUH_PASSWORD"
                  onChange={(e) => setForm({ ...form, secretEnv: e.target.value })} />
              </Field>
              <Field label="Папка">
                <Input value={form.imapFolder} placeholder="INBOX"
                  onChange={(e) => setForm({ ...form, imapFolder: e.target.value })} />
              </Field>
              <Field label="SMTP-сервер" hint="для ответов из пространства">
                <Input value={form.smtpHost ?? ''} placeholder="mail"
                  onChange={(e) => setForm({ ...form, smtpHost: e.target.value })} />
              </Field>
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => save.mutate(form)}
                disabled={!form.address || save.isPending}>Сохранить</Button>
              <Button size="sm" variant="ghost" onClick={() => setForm(null)}>Отмена</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(280px,380px)_1fr]">
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground border-b">
              Переписка
            </div>
            <div className="max-h-[520px] overflow-y-auto">
              {(threads.data?.rows ?? []).map((t) => (
                <button key={t.id} onClick={() => setThreadId(t.id)}
                  className={cn('block w-full text-left px-3 py-2 border-b last:border-0 hover:bg-muted/40',
                    t.id === threadId && 'bg-accent')}>
                  <div className="text-sm truncate">{t.subject || '(без темы)'}</div>
                  <div className="text-[11px] text-muted-foreground flex items-center gap-2">
                    <span>{t.counterpartyName ?? t.participants[0] ?? '—'}</span>
                    <span className="ml-auto tabular-nums">
                      {t.messages} · {t.lastAt?.slice(0, 10)}
                    </span>
                  </div>
                </button>
              ))}
              {(threads.data?.rows ?? []).length === 0 && (
                <div className="px-3 py-4 text-sm text-muted-foreground">
                  Писем пока нет. Настройте ящик и нажмите «Забрать почту».
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground border-b">
              Письма нити
            </div>
            <div className="max-h-[520px] overflow-y-auto divide-y">
              {!threadId && (
                <div className="px-3 py-4 text-sm text-muted-foreground">
                  Выберите переписку слева
                </div>
              )}
              {(thread.data?.rows ?? []).map((m) => (
                <div key={m.id} className="px-3 py-2 space-y-1">
                  <div className="flex flex-wrap items-baseline gap-2 text-sm">
                    <span className="font-medium">{m.fromName || m.fromEmail}</span>
                    <span className="text-[11px] text-muted-foreground">{m.fromEmail}</span>
                    <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
                      {m.sentAt?.slice(0, 16).replace('T', ' ')}
                    </span>
                  </div>
                  <div className="text-[11px] text-muted-foreground">{m.subject}</div>
                  {m.text && (
                    <pre className="whitespace-pre-wrap text-sm font-sans text-foreground/90">
                      {m.text.slice(0, 4000)}
                    </pre>
                  )}
                  {m.attachments.length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {m.attachments.map((a) => (
                        <a key={a.id} href={mailAttachmentUrl(companyId, a.id)}
                          className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] hover:border-primary/50">
                          <Paperclip className="size-3" />
                          {a.name}
                          <span className="text-muted-foreground">
                            {Math.round(a.size / 1024)} КБ
                          </span>
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function AccountRow({ a, onEdit, onPoll, onDelete }: {
  a: MailAccount; onEdit: () => void; onPoll: () => void; onDelete: () => void
}) {
  const ready = a.secretPresent && !!a.imapHost
  return (
    <div className="rounded-md border p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <Inbox className="size-4 text-muted-foreground" />
        <button onClick={onEdit} className="text-sm font-medium hover:text-primary">
          {a.address}
        </button>
        {a.title && <span className="text-[11px] text-muted-foreground">{a.title}</span>}
        <span className={cn('rounded border px-1.5 py-0.5 text-[10px]',
          ready ? 'border-emerald-500/40 text-emerald-600 dark:text-emerald-400'
                : 'border-amber-500/40 text-amber-700 dark:text-amber-400')}>
          {ready ? 'настроен' : a.secretEnv ? 'нет пароля в окружении' : 'не настроен'}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onPoll}
            title="Забрать почту из этого ящика">
            <RefreshCw className="size-3.5" />
          </Button>
          <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onDelete}>
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </div>
      {a.purpose && <div className="mt-1 text-[11px] text-muted-foreground">{a.purpose}</div>}
      <div className="mt-1 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        <span>{MODES.find((m) => m.key === a.mode)?.label}</span>
        {a.lastSyncAt && (
          <span className="inline-flex items-center gap-1">
            <CheckCircle2 className="size-3" />
            опрошен {a.lastSyncAt.slice(0, 16).replace('T', ' ')}
          </span>
        )}
        {a.lastError && (
          <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400">
            <AlertTriangle className="size-3" /> {a.lastError.slice(0, 120)}
          </span>
        )}
      </div>
    </div>
  )
}

function Field({ label, hint, span, children }: {
  label: string; hint?: string; span?: boolean; children: React.ReactNode
}) {
  return (
    <label className={cn('block space-y-1', span && 'sm:col-span-2')}>
      <span className="text-[11px] text-muted-foreground">
        {label}{hint && <span className="ml-1 opacity-70">— {hint}</span>}
      </span>
      {children}
    </label>
  )
}
