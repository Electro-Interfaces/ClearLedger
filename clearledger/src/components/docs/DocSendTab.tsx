/**
 * Отправка документа контрагенту: ссылка на просмотр и письмо с файлами.
 *
 * Ссылка со сроком и отзывом — для тех, у кого нет учётки; письмо — когда нужен
 * сам файл у адресата в почте. Оба следа ложатся в историю документа.
 */
import { useId, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2, Mail, Ban } from 'lucide-react'
import { toast } from 'sonner'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { get, post } from '@/services/apiClient'
import type { DocDetails } from '@/services/docsService'
import { DocExchangeBlock } from './DocExchangeBlock'
import { formatDate } from '@/lib/formatDate'

interface ShareRow {
  id: string
  token: string
  recipient: string | null
  expires_at: string
  revoked: boolean
  opened_count: number
  last_opened_at: string | null
  acknowledged_at: string | null
  acknowledged_by: string | null
}

interface MailAccount { id: string; address: string; mode: string }

export function DocSendTab({ doc, companyId, onChanged }: {
  doc: DocDetails
  companyId: string
  onChanged: () => void
}) {
  const qc = useQueryClient()
  const controlPrefix = useId()
  const [recipient, setRecipient] = useState('')
  const [email, setEmail] = useState('')
  const [days, setDays] = useState(14)
  const [to, setTo] = useState('')
  const [accountId, setAccountId] = useState('')

  const linksQ = useQuery({
    queryKey: ['doc-shares', doc.id, companyId],
    queryFn: () => get<{ links: ShareRow[] }>(`/api/docs/${doc.id}/share`,
      { company_id: companyId }),
  })
  const boxesQ = useQuery({
    queryKey: ['mail-accounts', companyId],
    queryFn: () => get<{ rows: MailAccount[] }>('/api/mail/accounts',
      { company_id: companyId }),
    staleTime: 5 * 60 * 1000,
  })

  const share = useMutation({
    mutationFn: () => post<{ token: string }>(`/api/docs/${doc.id}/share`, {
      company_id: companyId, days,
      recipient_name: recipient.trim() || null,
      recipient_email: email.trim() || null,
    }),
    onSuccess: async (r) => {
      const url = `${window.location.origin}/doc-share/${r.token}`
      try {
        await navigator.clipboard.writeText(url)
        toast.success('Ссылка создана и скопирована')
      } catch {
        window.prompt('Ссылка создана. Скопируйте её вручную', url)
      }
      setRecipient(''); setEmail('')
      qc.invalidateQueries({ queryKey: ['doc-shares', doc.id, companyId] })
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const revoke = useMutation({
    mutationFn: (id: string) => post(`/api/docs/share/${id}/revoke?company_id=${companyId}`, {}),
    onSuccess: () => {
      toast.success('Ссылка отозвана')
      qc.invalidateQueries({ queryKey: ['doc-shares', doc.id, companyId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const send = useMutation({
    mutationFn: () => post<{ attachments: number }>(`/api/docs/${doc.id}/send`, {
      company_id: companyId, account_id: accountId,
      to: to.split(/[,;\s]+/).filter(Boolean), with_files: true,
    }),
    onSuccess: (r) => {
      toast.success(`Отправлено, файлов: ${r.attachments}`)
      setTo('')
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const links = linksQ.data?.links ?? []
  const linksCheckedAt = linksQ.dataUpdatedAt
  const boxes = (boxesQ.data?.rows ?? []).filter((a) => a.mode !== 'in')

  if (!doc.reg_number) {
    return (
      <Card className="mt-3 p-4 text-sm text-muted-foreground">
        Сначала зарегистрируйте документ: наружу уходит номер, и без него
        контрагенту не на что ссылаться.
      </Card>
    )
  }

  return (
    <div className="space-y-3 pt-3">
      <DocExchangeBlock doc={doc} companyId={companyId} />

      <Card className="space-y-3 p-4">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Link2 className="h-4 w-4" />Ссылка на просмотр
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="space-y-1">
            <Label htmlFor={`${controlPrefix}-recipient`} className="text-xs">Получатель</Label>
            <Input id={`${controlPrefix}-recipient`} value={recipient} onChange={(e) => setRecipient(e.target.value)}
              placeholder="Иванов И. И." className="h-9" />
          </div>
          <div className="space-y-1">
            <Label htmlFor={`${controlPrefix}-email`} className="text-xs">Почта (для себя)</Label>
            <Input id={`${controlPrefix}-email`} value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="ivanov@example.ru" className="h-9" />
          </div>
          <div className="space-y-1">
            <Label htmlFor={`${controlPrefix}-days`} className="text-xs">Срок, дней</Label>
            <Input id={`${controlPrefix}-days`} type="number" min={1} max={180} value={days}
              onChange={(e) => setDays(Number(e.target.value) || 14)} className="h-9" />
          </div>
        </div>
        <Button size="sm" onClick={() => share.mutate()} disabled={share.isPending}>
          Создать ссылку
        </Button>
        <p className="text-xs text-muted-foreground">
          Подтверждение по ссылке равнозначно отметке о получении только если такой
          порядок согласован с контрагентом в договоре.
        </p>
      </Card>

      {links.length > 0 && (
        <Card className="divide-y divide-border/60">
          {links.map((l) => {
            const expired = new Date(l.expires_at).getTime() <= linksCheckedAt
            return (
            <div key={l.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <div className="min-w-0 text-sm">
                <div>{l.recipient || 'без имени'}</div>
                <div className="text-xs text-muted-foreground">
                  до {formatDate(l.expires_at)} · открытий {l.opened_count}
                  {l.acknowledged_at
                    ? ` · получение подтвердил ${l.acknowledged_by}`
                    : ''}
                  {l.revoked ? ' · отозвана' : ''}
                  {expired && !l.revoked ? ' · срок истёк' : ''}
                </div>
              </div>
              <div className="flex shrink-0 gap-1">
                {!l.revoked && !expired && (
                  <>
                    <ConfirmActionDialog
                      trigger={(
                        <Button size="sm" variant="ghost" title="Отозвать"
                          aria-label={`Отозвать ссылку для ${l.recipient || 'получателя'}`}
                          disabled={revoke.isPending}>
                          <Ban className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      title="Отозвать публичную ссылку?"
                      description={`Получатель «${l.recipient || 'без имени'}» больше не сможет открыть документ или подтвердить получение по этой ссылке.`}
                      confirmLabel="Отозвать ссылку"
                      destructive
                      pending={revoke.isPending}
                      onConfirm={() => revoke.mutateAsync(l.id)}
                    />
                  </>
                )}
              </div>
            </div>
            )
          })}
        </Card>
      )}

      <Card className="space-y-3 p-4">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Mail className="h-4 w-4" />Отправить письмом
        </div>
        {boxes.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            У пространства нет ящика на отправку. Подключается в «Подключениях».
          </p>
        ) : (
          <>
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor={`${controlPrefix}-account`} className="text-xs">С ящика</Label>
                <select id={`${controlPrefix}-account`} value={accountId} onChange={(e) => setAccountId(e.target.value)}
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
                  <option value="">выберите ящик</option>
                  {boxes.map((b) => (
                    <option key={b.id} value={b.id}>{b.address}</option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <Label htmlFor={`${controlPrefix}-to`} className="text-xs">Кому</Label>
                <Input id={`${controlPrefix}-to`} value={to} onChange={(e) => setTo(e.target.value)}
                  placeholder="buh@example.ru" className="h-9" />
              </div>
            </div>
            <ConfirmActionDialog
              trigger={(
                <Button size="sm" disabled={!accountId || !to.trim() || send.isPending}>
                  Отправить с файлами
                </Button>
              )}
              title="Отправить документ наружу?"
              description={`Письмо с текущими файлами уйдёт с ящика ${
                boxes.find((box) => box.id === accountId)?.address ?? 'пространства'
              } получателям: ${to.split(/[,;\s]+/).filter(Boolean).join(', ')}.`}
              confirmLabel="Отправить"
              pending={send.isPending}
              onConfirm={() => send.mutateAsync()}
            />
          </>
        )}
      </Card>
    </div>
  )
}

export default DocSendTab
