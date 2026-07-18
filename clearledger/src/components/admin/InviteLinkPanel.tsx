/**
 * Результат создания/перевыпуска приглашения: честный статус письма плюс
 * ссылка регистрации, которую можно скопировать и отправить мессенджером.
 *
 * Ссылка приходит только в ответе на создание и перевыпуск — в базе лежит
 * хеш токена. Поэтому панель показывается сразу после действия и не может
 * быть восстановлена позже: об этом предупреждаем прямо в интерфейсе.
 */
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Check, Copy, Mail, MailWarning, MessageSquareShare } from 'lucide-react'
import type { Invitation } from '@/services/invitationService'

/** Копирование с запасным вариантом: navigator.clipboard недоступен вне
 *  secure context (http-адрес во внутренней сети — обычный случай на проде). */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* падаем в запасной вариант */ }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

function CopyButton({ text, label, icon, variant = 'outline' }: {
  text: string
  label: string
  icon: React.ReactNode
  variant?: 'default' | 'outline'
}) {
  const [done, setDone] = useState(false)
  return (
    <Button
      type="button" size="sm" variant={variant} className="h-8"
      onClick={async () => {
        if (await copyText(text)) {
          setDone(true)
          setTimeout(() => setDone(false), 2000)
        } else {
          toast.error('Не удалось скопировать — выделите ссылку вручную')
        }
      }}
    >
      {done ? <Check className="h-3.5 w-3.5 mr-1.5" /> : icon}
      {done ? 'Скопировано' : label}
    </Button>
  )
}

/** Готовый текст для мессенджера — чтобы админ не сочинял его каждый раз. */
function messageText(inv: Invitation, companyName?: string): string {
  const where = companyName ? `в TradeLedger («${companyName}»)` : 'в TradeLedger'
  return (
    `Приглашаю вас ${where}. Перейдите по ссылке, укажите ФИО и задайте пароль:\n` +
    `${inv.invite_url}\n` +
    `Ссылка действует до ${new Date(inv.expires_at).toLocaleDateString('ru')}.`
  )
}

export function InviteLinkPanel({ invitation, companyName }: {
  invitation: Invitation
  companyName?: string
}) {
  const url = invitation.invite_url
  if (!url) return null
  const sent = invitation.email_sent === true

  return (
    <div className="space-y-3 rounded-lg border border-border bg-muted/40 p-3">
      <div className="flex items-start gap-2 text-sm">
        {sent
          ? <Mail className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
          : <MailWarning className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />}
        <div>
          <p className="font-medium">
            {sent
              ? `Письмо отправлено на ${invitation.email}`
              : 'Письмо не отправлено — почта не настроена'}
          </p>
          <p className="text-xs text-muted-foreground">
            {sent
              ? 'Если письмо не дойдёт — передайте ссылку ниже любым мессенджером.'
              : 'Передайте ссылку сотруднику вручную: мессенджером или почтой.'}
          </p>
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="rounded-md border border-border bg-background px-2.5 py-2">
          <code className="block break-all font-mono text-xs leading-relaxed text-foreground">{url}</code>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <CopyButton
            text={url} label="Копировать ссылку" variant="default"
            icon={<Copy className="h-3.5 w-3.5 mr-1.5" />}
          />
          <CopyButton
            text={messageText(invitation, companyName)} label="Копировать сообщение"
            icon={<MessageSquareShare className="h-3.5 w-3.5 mr-1.5" />}
          />
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Ссылка одноразовая, действует до {new Date(invitation.expires_at).toLocaleDateString('ru')}.
        Позже её не восстановить — только выпустить новую кнопкой «Ссылка» в списке приглашений.
      </p>
    </div>
  )
}
