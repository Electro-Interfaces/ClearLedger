/**
 * Почтовый коннектор пространства (docs/MAIL.md).
 *
 * Один коннектор, много ящиков: `info@`, `buh@`, `edo@`. У каждого своё назначение
 * человеческими словами — без него через месяц никто не помнит, чем ящики
 * отличаются и какие письма куда идут.
 *
 * Экран живёт в двух местах и показывает разное (`mode`): в «Подключениях» —
 * НАСТРОЙКУ (ящики, правила, известные адреса), потому что коннекторы заводят там
 * же, где все подключения пространства; в «Загрузке» — РАБОТУ (переписка, карантин,
 * разбор вложений). Настройка в разделе приёма данных выглядела бы вторым местом
 * для того же, а два места настройки одного объекта всегда расходятся.
 *
 * Пароль ящика вводит сотрудник, база хранит его под шифром ключом стека, а сервер
 * отдаёт только почтовому серверу и никогда обратно в интерфейс.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle, CheckCircle2, ChevronDown, FileCheck, Inbox, Loader2, Mail, Paperclip,
  PlugZap, Plus, RefreshCw, RotateCw, Send, Trash2,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import {
  createMailAccount, createMailRule, deleteMailAccount, deleteMailRule, getMailAccounts,
  getMailAddresses, getMailRules, getMailThread, getMailThreads, learnMailAddress,
  decideMailQuarantine, getMailQuarantine, mailAttachmentUrl, mailToIntake, pollMail,
  retryMailRoute, sendMail, testMailAccount, updateMailAccount, updateMailRule,
  type MailAccount, type MailAccountInput, type MailRule, type MailRuleInput,
} from '@/services/mailService'
import { useCounterparties } from '@/hooks/useReferences'
import { get } from '@/services/apiClient'

const EMPTY: MailAccountInput = {
  address: '', title: '', purpose: '', mode: 'both',
  imapHost: '', imapPort: 993, imapFolder: 'INBOX', imapSecurity: 'ssl',
  login: '', secretEnv: '', password: '',
  smtpHost: '', smtpPort: 587, smtpSecurity: 'starttls',
  displayName: '', signature: '', pollIntervalMin: 15, isActive: true,
}

/** Готовые настройки известных почтовиков: сотрудник не обязан помнить порты. */
const PRESETS: { label: string; imapHost: string; smtpHost: string }[] = [
  { label: 'Яндекс', imapHost: 'imap.yandex.ru', smtpHost: 'smtp.yandex.ru' },
  { label: 'Mail.ru', imapHost: 'imap.mail.ru', smtpHost: 'smtp.mail.ru' },
  { label: 'Gmail', imapHost: 'imap.gmail.com', smtpHost: 'smtp.gmail.com' },
  { label: 'Наш Mailcow', imapHost: 'mail.dataworker.ru', smtpHost: 'mail.dataworker.ru' },
]

const SECURITY: { key: 'ssl' | 'starttls' | 'none'; label: string }[] = [
  { key: 'ssl', label: 'SSL' },
  { key: 'starttls', label: 'STARTTLS' },
  { key: 'none', label: 'без шифрования' },
]

const MODES: { key: MailAccountInput['mode']; label: string }[] = [
  { key: 'both', label: 'приём и отправка' },
  { key: 'in', label: 'только приём' },
  { key: 'out', label: 'только отправка' },
]

/**
 * Режим экрана. Коннектор ЗАВОДЯТ и настраивают в «Подключениях» — там же, где
 * живут все подключения пространства; «Загрузка» им ПОЛЬЗУЕТСЯ: читает переписку,
 * разбирает вложения, разгребает карантин. Компонент один на оба места: механика
 * одна, и разводить её по двум файлам значило бы чинить дважды.
 */
export function MailConnector({ mode = 'all' }: { mode?: 'setup' | 'work' | 'all' }) {
  const showSetup = mode === 'setup' || mode === 'all'
  const showWork = mode === 'work' || mode === 'all'
  const { companyId, companies, isCompanyAdmin } = useCompany()
  const companyName = companies.find((c) => c.id === companyId)?.name ?? ''
  const qc = useQueryClient()
  const [form, setForm] = useState<(MailAccountInput & { id?: string }) | null>(null)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [ruleForm, setRuleForm] = useState<(MailRuleInput & { id?: string }) | null>(null)
  // Кого учим: адрес, по которому человек говорит «это письмо от такого-то».
  const [learning, setLearning] = useState<string | null>(null)
  const { data: counterparties = [] } = useCounterparties()
  // Комнаты нужны правилу «в чат»: письмо кладётся в конкретную комнату, а не
  // «куда-нибудь в чат».
  const { data: roomsResp } = useQuery({
    queryKey: ['chat', 'rooms-for-mail', companyId],
    queryFn: () => get<{ rooms?: { id: string; name: string }[] }>(
      `/api/chat/rooms?company_id=${companyId}`),
    enabled: !!companyId,
  })
  const rooms = roomsResp?.rooms ?? []

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

  // Проверка подключения — то, без чего самостоятельная настройка невозможна:
  // человек должен узнать «сервер не принял пароль» сразу, а не по пустой ленте.
  const test = useMutation({
    mutationFn: (id: string) => testMailAccount(companyId, id),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['mail'] })
      const parts = [
        r.imap && `приём: ${r.imap.ok ? '✓' : '✗'} ${r.imap.text}`,
        r.smtp && `отправка: ${r.smtp.ok ? '✓' : '✗'} ${r.smtp.text}`,
      ].filter(Boolean).join('\n')
      const ok = !!r.imap?.ok
      if (ok) toast.success(parts)
      else toast.error(parts)
    },
    onError: () => toast.error('Проверка не выполнена'),
  })

  const rules = useQuery({
    queryKey: ['mail', 'rules', companyId],
    queryFn: () => getMailRules(companyId),
    enabled: !!companyId,
  })
  const addresses = useQuery({
    queryKey: ['mail', 'addresses', companyId],
    queryFn: () => getMailAddresses(companyId),
    enabled: !!companyId,
  })
  const saveRule = useMutation({
    mutationFn: (r: MailRuleInput & { id?: string }) =>
      r.id ? updateMailRule(companyId, r.id, r) : createMailRule(companyId, r),
    onSuccess: () => {
      setRuleForm(null)
      qc.invalidateQueries({ queryKey: ['mail'] })
      toast.success('Правило сохранено')
    },
    onError: (error) => toast.error(`Правило не сохранено: ${(error as Error).message}`),
  })
  const removeRule = useMutation({
    mutationFn: (id: string) => deleteMailRule(companyId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mail'] }),
    onError: (error) => toast.error(`Правило не удалено: ${(error as Error).message}`),
  })
  const retryRoute = useMutation({
    mutationFn: (messageId: string) => retryMailRoute(companyId, messageId),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['mail', 'thread', companyId, threadId] })
      if (result.delivered) toast.success('Документ создан из письма')
      else toast.error(result.error || 'Маршрут снова не выполнен')
    },
    onError: (error) => toast.error(`Повтор не выполнен: ${(error as Error).message}`),
  })
  // Ответ пишется в той же ленте, где читают письмо: уходить в почтовый клиент,
  // чтобы ответить на письмо, которое ты открыл здесь, — это разрыв работы.
  const [reply, setReply] = useState<{ to: string; subject: string; body: string } | null>(null)
  const send = useMutation({
    mutationFn: (v: { accountId: string; to: string[]; subject: string; body: string
                      threadId?: string | null; replyTo?: string | null }) =>
      sendMail(companyId, {
        account_id: v.accountId, to: v.to, subject: v.subject, body: v.body,
        thread_id: v.threadId ?? null, reply_to_message_id: v.replyTo ?? null,
      }),
    onSuccess: (r) => {
      if (r.error) { toast.error(r.error); return }
      setReply(null)
      qc.invalidateQueries({ queryKey: ['mail'] })
      toast.success('Письмо отправлено')
    },
    onError: () => toast.error('Письмо не ушло'),
  })

  const quarantine = useQuery({
    queryKey: ['mail', 'quarantine', companyId],
    queryFn: () => getMailQuarantine(companyId),
    enabled: !!companyId,
  })
  const decide = useMutation({
    mutationFn: (v: { ids: string[]; decision: 'accept' | 'reject' }) =>
      decideMailQuarantine(companyId, v.ids, v.decision),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['mail'] })
      toast.success('Решение принято')
    },
  })

  const toIntake = useMutation({
    mutationFn: (messageId: string) => mailToIntake(companyId, messageId),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['mail'] })
      qc.invalidateQueries({ queryKey: ['intake-docs'] })
      toast.success(r.items
        ? `Разобрано документов: ${r.items} — смотрите вкладку «Первичные документы»`
        // Называем сами файлы: «нет таблиц» при видимом вложении читается как сбой.
        : r.skipped?.length
          ? `Разбирать нечего: ${r.skipped.join(', ')} — не таблица (xlsx/csv)`
          : 'В письме нет вложений для разбора')
    },
    onError: () => toast.error('Не удалось разобрать вложения'),
  })

  const learn = useMutation({
    mutationFn: (v: { address: string; cpId: string }) =>
      learnMailAddress(companyId, v.address, v.cpId),
    onSuccess: (r) => {
      setLearning(null)
      qc.invalidateQueries({ queryKey: ['mail'] })
      toast.success(`Адрес запомнен: обновлено писем ${r.messages}`)
    },
    onError: () => toast.error('Не удалось запомнить адрес'),
  })

  return (
    <div className="space-y-4">
      {showSetup && (
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
              {isCompanyAdmin && <Button size="sm" onClick={() => setForm({ ...EMPTY })}>
                <Plus className="size-4 mr-1.5" /> Ящик
              </Button>}
            </div>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Один коннектор на компанию: ящики отличаются учёткой, назначением и правилами.
            Пароль хранится в базе под шифром — сервер отдаёт его только почтовому
            серверу и никогда обратно в интерфейс.
          </p>

          <div className="space-y-2">
            {(accounts.data?.rows ?? []).map((a) => (
              <AccountRow key={a.id} a={a}
                canManage={isCompanyAdmin}
                onEdit={() => setForm({ ...a })}
                onPoll={() => poll.mutate(a.id)}
                onTest={() => test.mutate(a.id)}
                onDelete={() => remove.mutate(a.id)} />
            ))}
            {(accounts.data?.rows ?? []).length === 0 && (
              // Пустое состояние учит работе: что завести первым и что случится
              // дальше. «Ящиков пока нет» сообщает факт и оставляет человека одного.
              <div className="rounded-lg border border-dashed p-4">
                {/* Компания названа прямо тут: ящики заводятся НА компанию, и,
                    глядя на пустой список, администратор решал, что подключение не
                    сохранилось — хотя ящики стоят у соседней компании пространства. */}
                <div className="text-sm font-medium">
                  Ящиков пока нет{companyName ? ` — у компании «${companyName}»` : ''}
                </div>
                <p className="mt-1 max-w-prose text-[13px] leading-relaxed text-muted-foreground">
                  Начните с того, куда контрагенты присылают закрывающие документы.
                  После проверки подключения письма начнут приходить сами, а вложения
                  можно будет разбирать в документы — на вкладке «Загрузка».
                  {companies.length > 1 && ' Ящики у каждой компании свои — переключатель в шапке.'}
                </p>
                {isCompanyAdmin && <Button size="sm" className="mt-3" onClick={() => setForm({ ...EMPTY })}>
                  <Plus className="size-4 mr-1.5" /> Завести ящик
                </Button>}
              </div>
            )}
          </div>
        </CardContent>
      </Card>
      )}

      {showSetup && form && (
        <Card>
          <CardContent className="p-0">
            {/* Действия у заголовка, а не под простынёй полей: форма длинная, и
                кнопка «Сохранить» на её дне заставляет прокручивать туда-обратно
                при каждой правке. Проверка подключения стоит рядом — это часть
                настройки, а не отдельный поход в список. */}
            <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
              <span className="text-sm font-medium">
                {form.id ? form.address || 'Ящик' : 'Новый ящик'}
              </span>
              {form.id && (
                <span className="text-[11px] text-muted-foreground">{form.title}</span>
              )}
              <div className="ml-auto flex items-center gap-2">
                {form.id && (
                  <Button size="sm" variant="outline" disabled={test.isPending}
                    onClick={() => test.mutate(form.id!)}>
                    {test.isPending
                      ? <Loader2 className="size-4 mr-1.5 animate-spin" />
                      : <PlugZap className="size-4 mr-1.5" />}
                    Проверить подключение
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setForm(null)}>Отмена</Button>
                <Button size="sm" onClick={() => save.mutate(form)}
                  disabled={!form.address || save.isPending}>
                  {save.isPending && <Loader2 className="size-4 mr-1.5 animate-spin" />}
                  Сохранить
                </Button>
              </div>
            </div>

            <div className="divide-y">
              <Section title="Ящик" note="как он называется и что с ним делает пространство">
                <Field label="Адрес" hint="то, что видит контрагент">
                  <Input value={form.address} placeholder="buh@company.ru"
                    onChange={(e) => setForm({ ...form, address: e.target.value })} />
                </Field>
                <Field label="Название" hint="как называть в пространстве">
                  <Input value={form.title} placeholder="Бухгалтерия"
                    onChange={(e) => setForm({ ...form, title: e.target.value })} />
                </Field>
                <Field label="Назначение" span
                  hint="что сюда приходит и что с этим делать — через месяц это единственное, по чему ящик узнают">
                  <Textarea rows={2} value={form.purpose ?? ''}
                    placeholder="Контрагенты присылают закрывающие документы и счета"
                    onChange={(e) => setForm({ ...form, purpose: e.target.value })} />
                </Field>
                <Field label="Режим" span>
                  <div className="flex flex-wrap gap-1">
                    {MODES.map((m) => (
                      <Toggle key={m.key} on={form.mode === m.key} label={m.label}
                        onClick={() => setForm({ ...form, mode: m.key })} />
                    ))}
                  </div>
                </Field>
              </Section>

              {form.mode !== 'out' && (
                <Section title="Приём" note="откуда забираем письма и как часто">
                  <Field label="Почтовый сервис" span
                    hint="подставит серверы, порты и шифрование — остальное можно не трогать">
                    <div className="flex flex-wrap gap-1">
                      {PRESETS.map((p) => (
                        <Toggle key={p.label} on={form.imapHost === p.imapHost} label={p.label}
                          onClick={() => setForm({
                            ...form, imapHost: p.imapHost, smtpHost: p.smtpHost,
                            imapPort: 993, smtpPort: 587,
                            imapSecurity: 'ssl', smtpSecurity: 'starttls',
                          })} />
                      ))}
                    </div>
                  </Field>
                  <Field label="Сервер (IMAP)">
                    <Input value={form.imapHost ?? ''} placeholder="imap.company.ru"
                      onChange={(e) => setForm({ ...form, imapHost: e.target.value })} />
                  </Field>
                  <Field label="Порт и шифрование">
                    <div className="flex flex-wrap items-center gap-1">
                      <Input className="w-20" type="number" value={form.imapPort}
                        onChange={(e) => setForm({ ...form, imapPort: Number(e.target.value) })} />
                      {SECURITY.map((x) => (
                        <Toggle key={x.key} on={form.imapSecurity === x.key} label={x.label}
                          onClick={() => setForm({ ...form, imapSecurity: x.key })} />
                      ))}
                    </div>
                  </Field>
                  <Field label="Логин">
                    <Input value={form.login ?? ''} placeholder="buh@company.ru"
                      onChange={(e) => setForm({ ...form, login: e.target.value })} />
                  </Field>
                  <Field label="Пароль"
                    hint={form.id ? 'пусто — оставить прежний' : 'хранится в базе под шифром'}>
                    <Input type="password" value={form.password ?? ''} placeholder="••••••••"
                      onChange={(e) => setForm({ ...form, password: e.target.value })} />
                  </Field>
                  <Field label="Папка">
                    <Input value={form.imapFolder} placeholder="INBOX"
                      onChange={(e) => setForm({ ...form, imapFolder: e.target.value })} />
                  </Field>
                  <Field label="Забирать почту" hint="0 — только вручную">
                    <div className="flex items-center gap-2">
                      <Input className="w-20" type="number" value={form.pollIntervalMin}
                        onChange={(e) => setForm({ ...form,
                          pollIntervalMin: Number(e.target.value) })} />
                      <span className="text-xs text-muted-foreground">минут</span>
                    </div>
                  </Field>
                </Section>
              )}

              {form.mode !== 'in' && (
                <Section title="Отправка" note="с этого адреса уходят ответы из пространства">
                  <Field label="Сервер (SMTP)">
                    <Input value={form.smtpHost ?? ''} placeholder="smtp.company.ru"
                      onChange={(e) => setForm({ ...form, smtpHost: e.target.value })} />
                  </Field>
                  <Field label="Порт и шифрование">
                    <div className="flex flex-wrap items-center gap-1">
                      <Input className="w-20" type="number" value={form.smtpPort}
                        onChange={(e) => setForm({ ...form, smtpPort: Number(e.target.value) })} />
                      {SECURITY.map((x) => (
                        <Toggle key={x.key} on={form.smtpSecurity === x.key} label={x.label}
                          onClick={() => setForm({ ...form, smtpSecurity: x.key })} />
                      ))}
                    </div>
                  </Field>
                  <Field label="Имя отправителя" hint="что видит контрагент в поле «От кого»">
                    <Input value={form.displayName ?? ''} placeholder="Бухгалтерия компании"
                      onChange={(e) => setForm({ ...form, displayName: e.target.value })} />
                  </Field>
                  <Field label="Подпись" hint="приклеивается к каждому письму" span>
                    <Textarea rows={2} value={form.signature ?? ''}
                      placeholder="С уважением, бухгалтерия · телефон"
                      onChange={(e) => setForm({ ...form, signature: e.target.value })} />
                  </Field>
                </Section>
              )}

              {/* Путь внедренца: секрет в окружении стека вместо пароля в базе.
                  Сотруднику он не нужен ни разу, поэтому свёрнут — но и прятать
                  его некуда: без него нельзя настроить ящик, чей пароль в .env. */}
              <details className="group">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70 hover:text-muted-foreground">
                  <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" />
                  Пароль в окружении стека
                </summary>
                <div className="grid gap-4 px-4 pb-4 sm:grid-cols-2">
                  <Field label="Переменная с паролем" span
                    hint="для ящиков, которые настраивает внедренец: значение живёт в .env стека, в базу не попадает">
                    <Input value={form.secretEnv ?? ''} placeholder="MAIL_BUH_PASSWORD"
                      onChange={(e) => setForm({ ...form, secretEnv: e.target.value })} />
                  </Field>
                </div>
              </details>
            </div>
          </CardContent>
        </Card>
      )}

      {showSetup && (
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">Правила разбора</span>
            <span className="text-[11px] text-muted-foreground">
              читаются по порядку — первое подходящее решает судьбу письма
            </span>
            {isCompanyAdmin && <Button size="sm" variant="outline" className="ml-auto"
              disabled={accounts.isLoading || accounts.isError}
              onClick={() => setRuleForm({
                name: '', accountId: null,
                sort: Math.max(0, ...(rules.data?.rows ?? []).map((rule) => rule.sort)) + 10,
                fromEmail: null, fromDomain: null,
                subjectLike: null, hasAttachment: null, unknownSender: null,
                action: 'archive', setCounterpartyId: null, setContractId: null,
                setRoomId: null, setObjectId: null, isActive: false,
              })}>
              <Plus className="size-4 mr-1.5" /> Правило
            </Button>}
          </div>

          {accounts.isError && (
            <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/30 p-3 text-sm">
              <span className="text-destructive">Почтовые ящики не загрузились. Правила нельзя включать.</span>
              <Button size="sm" variant="outline" onClick={() => accounts.refetch()}>Повторить</Button>
            </div>
          )}

          {(rules.data?.rows ?? []).map((r) => (
            <RuleRow key={r.id} r={r} counterparties={counterparties}
              accounts={accounts.data?.rows ?? []}
              canManage={isCompanyAdmin} deleting={removeRule.isPending}
              onEdit={() => setRuleForm({ ...r })}
              onDelete={() => removeRule.mutate(r.id)} />
          ))}
          {rules.isError && (
            <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/30 p-3 text-sm">
              <span className="text-destructive">Правила не загрузились</span>
              <Button size="sm" variant="outline" onClick={() => rules.refetch()}>Повторить</Button>
            </div>
          )}
          {rules.isLoading && <div className="text-sm text-muted-foreground">Загрузка правил…</div>}
          {rules.isSuccess && (rules.data?.rows ?? []).length === 0 && (
            <div className="rounded-lg border border-dashed p-4">
              <div className="text-sm font-medium">Правил нет</div>
              <p className="mt-1 max-w-prose text-[13px] leading-relaxed text-muted-foreground">
                Письма складываются в переписку и ждут человека. Правило делает за него
                первый шаг: «с домена контрагента с вложением — в приёмку документов»,
                «со словом „счёт“ — в задачу», «от незнакомых — в карантин».
              </p>
            </div>
          )}

          {ruleForm && (
            <div className="rounded-md border p-3 space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Название">
                  <Input value={ruleForm.name} placeholder="Документы от ТСМ"
                    onChange={(e) => setRuleForm({ ...ruleForm, name: e.target.value })} />
                </Field>
                <Field label="Порядок" hint="меньше — раньше">
                  <Input type="number" value={ruleForm.sort}
                    onChange={(e) => setRuleForm({ ...ruleForm, sort: Number(e.target.value) })} />
                </Field>
                <Field label="Почтовый ящик" hint="пусто — правило действует для всех ящиков">
                  <select aria-label="Почтовый ящик правила"
                    className="w-full rounded-md border bg-background px-2 py-1.5 text-sm"
                    disabled={accounts.isLoading || accounts.isError}
                    value={ruleForm.accountId ?? ''}
                    onChange={(e) => setRuleForm({ ...ruleForm,
                      accountId: e.target.value || null })}>
                    <option value="">— все ящики —</option>
                    {(accounts.data?.rows ?? []).map((account) => (
                      <option key={account.id} value={account.id}>{account.address}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Адрес отправителя">
                  <Input value={ruleForm.fromEmail ?? ''} placeholder="sales@tsm.ru"
                    onChange={(e) => setRuleForm({ ...ruleForm, fromEmail: e.target.value })} />
                </Field>
                <Field label="Домен отправителя">
                  <Input value={ruleForm.fromDomain ?? ''} placeholder="tsm.ru"
                    onChange={(e) => setRuleForm({ ...ruleForm, fromDomain: e.target.value })} />
                </Field>
                <Field label="Тема содержит">
                  <Input value={ruleForm.subjectLike ?? ''} placeholder="акт"
                    onChange={(e) => setRuleForm({ ...ruleForm, subjectLike: e.target.value })} />
                </Field>
                <Field label="Условия" hint="пустое условие не проверяется">
                  <div className="flex flex-wrap gap-1">
                    <Toggle on={ruleForm.hasAttachment === true} label="есть вложение"
                      onClick={() => setRuleForm({ ...ruleForm,
                        hasAttachment: ruleForm.hasAttachment === true ? null : true })} />
                    <Toggle on={ruleForm.unknownSender === true} label="отправитель неизвестен"
                      onClick={() => setRuleForm({ ...ruleForm,
                        unknownSender: ruleForm.unknownSender === true ? null : true })} />
                  </div>
                </Field>
                <Field label="Действие">
                  <div className="flex flex-wrap gap-1">
                    {ACTIONS.map((a) => (
                      <Toggle key={a.key} on={ruleForm.action === a.key} label={a.label}
                        onClick={() => setRuleForm({ ...ruleForm, action: a.key })} />
                    ))}
                  </div>
                </Field>
                <Field label="Состояние" hint="новое правило безопасно сохраняется выключенным">
                  <Toggle on={ruleForm.isActive}
                    label={ruleForm.isActive ? 'Включено' : 'Выключено'}
                    disabled={accounts.isLoading || accounts.isError}
                    onClick={() => setRuleForm({ ...ruleForm,
                      isActive: !ruleForm.isActive })} />
                </Field>
                {ruleForm.action === 'doc' && (
                  <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-[11px] text-muted-foreground sm:col-span-2">
                    Создаётся черновик входящего документа — без автоматической регистрации.
                    Нужны непустое вложение, известный контрагент и подтверждённая почтовым
                    сервером подлинность письма. Ошибка останется в переписке для повтора.
                  </div>
                )}
                {ruleForm.action === 'chat' && (
                  <Field label="Комната чата" hint="куда положить письмо">
                    <select className="w-full rounded-md border bg-background px-2 py-1.5 text-sm"
                      value={ruleForm.setRoomId ?? ''}
                      onChange={(e) => setRuleForm({ ...ruleForm,
                        setRoomId: e.target.value || null })}>
                      <option value="">— выберите комнату —</option>
                      {(rooms ?? []).map((r) => (
                        <option key={r.id} value={r.id}>{r.name}</option>
                      ))}
                    </select>
                  </Field>
                )}
                {ruleForm.action === 'ticket' && (
                  <Field label="Объект" hint="заявка всегда про объект">
                    <Input value={ruleForm.setObjectId ?? ''} placeholder="код объекта"
                      onChange={(e) => setRuleForm({ ...ruleForm,
                        setObjectId: e.target.value })} />
                  </Field>
                )}
                <Field label="Проставить контрагента" hint="кому относится письмо">
                  <select className="w-full rounded-md border bg-background px-2 py-1.5 text-sm"
                    value={ruleForm.setCounterpartyId ?? ''}
                    onChange={(e) => setRuleForm({ ...ruleForm,
                      setCounterpartyId: e.target.value || null })}>
                    <option value="">— не проставлять —</option>
                    {counterparties.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </Field>
              </div>
              <div className="flex gap-2">
                <Button size="sm" disabled={saveRule.isPending || !accounts.isSuccess}
                  onClick={() => saveRule.mutate(ruleForm)}>
                  {ruleForm.isActive ? 'Сохранить и включить' : 'Сохранить выключенным'}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setRuleForm(null)}>Отмена</Button>
              </div>
            </div>
          )}

          {(addresses.data?.rows ?? []).length > 0 && (
            <div className="pt-1">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">
                Известные адреса — {addresses.data!.rows.length}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {addresses.data!.rows.slice(0, 24).map((a) => (
                  <span key={a.id} className="rounded border px-2 py-0.5 text-[11px]">
                    {a.address} <span className="text-muted-foreground">→ {a.counterpartyName}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
      )}

      {showWork && (quarantine.data?.rows ?? []).length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 border-b">
              <div className="text-sm font-medium">
                Карантин — {quarantine.data!.rows.length}
              </div>
              <div className="text-[11px] text-muted-foreground">
                Отложено до решения: неизвестный отправитель, отказ проверки подлинности
                или правило. Карантин без разбора — та же корзина, поэтому это очередь
                решений, а не список мусора.
              </div>
            </div>
            <table className="w-full text-sm">
              <tbody>
                {quarantine.data!.rows.map((m) => (
                  <tr key={m.id} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-3 py-1.5 w-[92px]">
                      <span className={cn('rounded border px-1.5 py-0.5 text-[11px]',
                        m.status === 'quarantine'
                          ? 'border-amber-500/40 text-amber-700 dark:text-amber-400'
                          : 'border-border text-muted-foreground')}>
                        {m.status === 'quarantine' ? 'карантин' : 'отклонено'}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 max-w-[280px] truncate" title={m.subject ?? ''}>
                      {m.subject || '(без темы)'}
                    </td>
                    <td className="px-3 py-1.5 text-muted-foreground">{m.fromEmail}</td>
                    <td className="px-3 py-1.5 text-[11px] text-muted-foreground max-w-[220px] truncate"
                      title={m.authVerdict ?? ''}>
                      {m.authVerdict ? 'не прошло проверку подлинности' : ''}
                    </td>
                    <td className="px-3 py-1.5 text-right whitespace-nowrap">
                      {m.status === 'quarantine' && (
                        <>
                          <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]"
                            onClick={() => decide.mutate({ ids: [m.id], decision: 'accept' })}>
                            принять
                          </Button>
                          <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]"
                            onClick={() => decide.mutate({ ids: [m.id], decision: 'reject' })}>
                            отклонить
                          </Button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {showWork && (
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
              {threadId && (thread.data?.rows ?? []).length > 0 && (
                <div className="px-3 py-2 bg-muted/20 space-y-2">
                  {!reply ? (
                    <Button size="sm" variant="outline"
                      onClick={() => {
                        const last = thread.data!.rows[thread.data!.rows.length - 1]
                        setReply({
                          to: last.direction === 'in' ? (last.fromEmail ?? '') : (last.to[0] ?? ''),
                          subject: last.subject?.startsWith('Re:')
                            ? last.subject : `Re: ${last.subject ?? ''}`,
                          body: '',
                        })
                      }}>
                      <Send className="size-4 mr-1.5" /> Ответить
                    </Button>
                  ) : (
                    <div className="space-y-2">
                      <Input value={reply.to} placeholder="кому"
                        onChange={(e) => setReply({ ...reply, to: e.target.value })} />
                      <Input value={reply.subject} placeholder="тема"
                        onChange={(e) => setReply({ ...reply, subject: e.target.value })} />
                      <Textarea rows={4} value={reply.body} placeholder="текст письма"
                        onChange={(e) => setReply({ ...reply, body: e.target.value })} />
                      <div className="flex gap-2">
                        <Button size="sm" disabled={send.isPending || !reply.to || !reply.body}
                          onClick={() => {
                            const rows = thread.data!.rows
                            const last = rows[rows.length - 1]
                            const acc = (accounts.data?.rows ?? []).find(
                              (a) => a.mode !== 'in') ?? (accounts.data?.rows ?? [])[0]
                            if (!acc) { toast.error('Нет ящика для отправки'); return }
                            send.mutate({
                              accountId: acc.id, to: [reply.to], subject: reply.subject,
                              body: reply.body, threadId, replyTo: last.id,
                            })
                          }}>
                          Отправить
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setReply(null)}>
                          Отмена
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}
              {(thread.data?.rows ?? []).map((m) => (
                <div key={m.id} className="px-3 py-2 space-y-1">
                  <div className="flex flex-wrap items-baseline gap-2 text-sm">
                    {m.routedTo && (m.routedDocId
                      ? <a href={`/docs?view=all&doc=${m.routedDocId}`}
                        className="rounded border border-emerald-500/40 px-1 text-[10px] text-emerald-600 hover:underline dark:text-emerald-400">
                        в документ «Трека»
                      </a>
                      : <span className="rounded border border-emerald-500/40 px-1 text-[10px] text-emerald-600 dark:text-emerald-400">
                        {({ chat: 'в чат', task: 'в задачу', ticket: 'в заявку',
                            intake: 'в приёмку', doc: 'в документ «Трека»' } as Record<string, string>)[m.routedTo]
                          ?? m.routedTo}
                      </span>)}
                    {m.direction === 'out' && (
                      <span className="rounded border border-primary/40 px-1 text-[10px] text-primary">
                        мы
                      </span>
                    )}
                    <span className="font-medium">{m.fromName || m.fromEmail}</span>
                    <span className="text-[11px] text-muted-foreground">{m.fromEmail}</span>
                    <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
                      {m.sentAt?.slice(0, 16).replace('T', ' ')}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="text-[11px] text-muted-foreground">{m.subject}</div>
                    {!m.counterpartyId && m.fromEmail && isCompanyAdmin && (
                      // Опознание одним движением там, где человек и так смотрит на
                      // непонятое письмо: дальше все письма с адреса встают на место.
                      learning === m.fromEmail ? (
                        <select autoFocus
                          className="rounded-md border bg-background px-2 py-1 text-xs"
                          onChange={(e) => e.target.value
                            && learn.mutate({ address: m.fromEmail!, cpId: e.target.value })}
                          defaultValue="">
                          <option value="">чей это адрес…</option>
                          {counterparties.map((c) => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                        </select>
                      ) : (
                        <button onClick={() => setLearning(m.fromEmail)}
                          className="text-[11px] text-primary hover:underline">
                          указать контрагента
                        </button>
                      )
                    )}
                  </div>
                  {m.routeError && (
                    <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-[11px]">
                      <span className="text-amber-800 dark:text-amber-300">{m.routeError}</span>
                      {isCompanyAdmin && m.status !== 'quarantine' && m.status !== 'rejected' && (
                        <Button size="sm" variant="outline" className="h-7"
                          disabled={retryRoute.isPending}
                          onClick={() => retryRoute.mutate(m.id)}>
                          <RotateCw className="mr-1 h-3.5 w-3.5" />Повторить маршрут
                        </Button>
                      )}
                    </div>
                  )}
                  {m.text && (
                    <pre className="whitespace-pre-wrap text-sm font-sans text-foreground/90">
                      {m.text.slice(0, 4000)}
                    </pre>
                  )}
                  {m.attachments.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2 pt-1">
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
                      {/* Вложение-таблица — это документы: разбор идёт тем же
                          кодом, что файл с диска, и попадает на тот же экран. */}
                      {m.attachments.some((a) => /\.(xlsx|xlsm|csv)$/i.test(a.name)) && (
                        <Button size="sm" variant="outline" className="h-6 px-2 text-[11px]"
                          disabled={toIntake.isPending}
                          onClick={() => toIntake.mutate(m.id)}>
                          <FileCheck className="size-3 mr-1" /> Разобрать как документы
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      )}
    </div>
  )
}

function AccountRow({ a, canManage, onEdit, onPoll, onTest, onDelete }: {
  a: MailAccount; onEdit: () => void; onPoll: () => void
  onTest: () => void; onDelete: () => void; canManage: boolean
}) {
  // Ящик готов, если есть сервер и пароль — неважно, введён он сотрудником или
  // задан переменной окружения.
  const ready = !!a.imapHost && (a.passwordSet || a.secretPresent)
  return (
    <div className="group rounded-lg border p-3 transition-colors hover:border-border">
      <div className="flex flex-wrap items-center gap-2">
        <Inbox className="size-4 shrink-0 text-muted-foreground" />
        <button onClick={canManage ? onEdit : undefined} disabled={!canManage}
          className="text-sm font-medium enabled:hover:text-primary">
          {a.address}
        </button>
        {a.title && <span className="text-xs text-muted-foreground">{a.title}</span>}
        {/* Состояние словом, а не только цветом: цвет — второй носитель, не первый. */}
        <span className={cn('inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px]',
          ready ? 'border-emerald-500/40 text-emerald-600 dark:text-emerald-400'
                : 'border-amber-500/40 text-amber-700 dark:text-amber-400')}>
          {ready ? <CheckCircle2 className="size-3" /> : <AlertTriangle className="size-3" />}
          {ready ? 'настроен' : !a.imapHost ? 'нет сервера' : 'нет пароля'}
        </span>
        <div className="ml-auto flex items-center gap-1">
          {canManage && <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]" onClick={onTest}
            title="Проверить подключение к серверам">
            проверить
          </Button>}
          <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onPoll}
            title="Забрать почту из этого ящика">
            <RefreshCw className="size-3.5" />
          </Button>
          {canManage && <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onDelete}>
            <Trash2 className="size-3.5" />
          </Button>}
        </div>
      </div>
      {a.purpose && <div className="mt-1 text-[11px] text-muted-foreground">{a.purpose}</div>}
      <div className="mt-1 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        <span>{MODES.find((m) => m.key === a.mode)?.label}</span>
        <span>{a.pollIntervalMin > 0
          ? `забирать каждые ${a.pollIntervalMin} мин`
          : 'только вручную'}</span>
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

/** Действия правила — те же, что в docs/MAIL.md. */
const ACTIONS: { key: MailRule['action']; label: string }[] = [
  { key: 'intake', label: 'в приёмку' },
  { key: 'ticket', label: 'в заявку' },
  { key: 'chat', label: 'в чат' },
  { key: 'task', label: 'в задачу' },
  { key: 'doc', label: 'в документ «Трека»' },
  { key: 'archive', label: 'в архив' },
  { key: 'quarantine', label: 'в карантин' },
  { key: 'reject', label: 'отклонить' },
]

function Toggle({ on, label, onClick, disabled = false }: {
  on: boolean; label: string; onClick: () => void; disabled?: boolean
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on} disabled={disabled}
      className={cn('rounded-md border px-2 py-1 text-xs transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-50',
        on ? 'border-primary bg-primary/10 text-primary'
           : 'text-muted-foreground hover:bg-muted')}>
      {label}
    </button>
  )
}

function RuleRow({ r, counterparties, accounts, canManage, deleting, onEdit, onDelete }: {
  r: MailRule; counterparties: { id: string; name: string }[]
  accounts: MailAccount[]
  onEdit: () => void; onDelete: () => void; canManage: boolean; deleting: boolean
}) {
  const cond = [
    r.fromEmail && `от ${r.fromEmail}`,
    r.fromDomain && `домен ${r.fromDomain}`,
    r.subjectLike && `тема «${r.subjectLike}»`,
    r.hasAttachment && 'есть вложение',
    r.unknownSender && 'отправитель неизвестен',
  ].filter(Boolean).join(' · ') || 'любое письмо'
  const cp = counterparties.find((c) => c.id === r.setCounterpartyId)
  const account = accounts.find((item) => item.id === r.accountId)
  return (
    <div className="rounded-md border p-2.5 flex flex-wrap items-center gap-2">
      <span className="text-[11px] tabular-nums text-muted-foreground w-8">{r.sort}</span>
      <button onClick={canManage ? onEdit : undefined} disabled={!canManage}
        className="text-sm font-medium enabled:hover:text-primary">
        {r.name || 'без названия'}
      </button>
      <span className="text-[11px] text-muted-foreground">{cond}</span>
      <span className="rounded border px-1.5 py-0.5 text-[10px] border-primary/40 text-primary">
        {ACTIONS.find((a) => a.key === r.action)?.label ?? r.action}
      </span>
      <span className="text-[11px] text-muted-foreground">
        {account ? `ящик ${account.address}` : 'все ящики'}
      </span>
      {!r.isActive && (
        <span className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">
          выключено
        </span>
      )}
      {cp && <span className="text-[11px] text-muted-foreground">→ {cp.name}</span>}
      {r.setRoomId && <span className="text-[11px] text-muted-foreground">→ в комнату</span>}
      {r.setObjectId && (
        <span className="text-[11px] text-muted-foreground">→ объект {r.setObjectId}</span>
      )}
      <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
        сработало {r.hits}
      </span>
      {canManage && <ConfirmActionDialog
        trigger={<Button size="sm" variant="ghost" className="h-7 px-2"
          aria-label={`Удалить правило «${r.name || 'без названия'}»`} disabled={deleting}>
          <Trash2 className="size-3.5" />
        </Button>}
        title="Удалить почтовое правило?"
        description={`Письма больше не будут обрабатываться правилом «${r.name || 'без названия'}».`}
        confirmLabel="Удалить" destructive onConfirm={onDelete}
      />}
    </div>
  )
}

/**
 * Поле формы: имя сверху, подсказка ПОД полем.
 *
 * Подсказка в одной строке с именем («Порт и шифрование приёма — для ответов из
 * пространства») делает лейбл длиннее самого поля, и глаз перестаёт находить
 * начало строки. Снизу она читается как пояснение к тому, что уже введено.
 */
function Field({ label, hint, span, children }: {
  label: string; hint?: string; span?: boolean; children: React.ReactNode
}) {
  return (
    <label className={cn('block', span && 'sm:col-span-2')}>
      <span className="mb-1 block text-xs font-medium text-foreground/80">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  )
}

/** Секция настройки: заголовок с пояснением и сетка полей под ним. */
function Section({ title, note, children }: {
  title: string; note?: string; children: React.ReactNode
}) {
  return (
    <div className="px-4 py-4">
      <div className="mb-3">
        <div className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">
          {title}
        </div>
        {note && <div className="mt-0.5 text-[11px] text-muted-foreground">{note}</div>}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </div>
  )
}
