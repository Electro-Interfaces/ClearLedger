/**
 * Именные входящие ключи пространства (docs/CONNECT.md, В2).
 *
 * Каждому внешнему потребителю — свой ключ: видно, кто ходит и когда ходил в
 * последний раз, любого можно отозвать, не уронив остальных. Сам ключ показывается
 * ОДИН раз при выдаче (в базе — только хеш), как ссылка приглашения.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, KeyRound, Loader2, Plus, ShieldOff } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { copyText } from '@/components/admin/InviteLinkPanel'
import { get, post, del } from '@/services/apiClient'

interface InboundKey {
  id: string
  consumer: string
  prefix: string
  created_at: string | null
  last_used_at: string | null
  revoked_at: string | null
}

const since = (iso: string | null) => {
  if (!iso) return 'ещё не ходил'
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (min < 1) return 'только что'
  if (min < 60) return `${min} мин назад`
  const h = Math.floor(min / 60)
  return h < 24 ? `${h} ч назад` : `${Math.floor(h / 24)} дн назад`
}

export function InboundKeysCard({ canManage }: { canManage: boolean }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [consumer, setConsumer] = useState('')
  // Свежевыданный ключ: показывается до закрытия карточки, потом не восстановить.
  const [issued, setIssued] = useState<{ consumer: string; key: string } | null>(null)

  const q = useQuery({
    queryKey: ['inbound-keys', companyId],
    queryFn: () => get<{ keys: InboundKey[] }>('/api/inbound-keys', { company_id: companyId }),
    enabled: canManage,
    retry: false,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['inbound-keys', companyId] })

  const create = useMutation({
    mutationFn: () => post<{ key: string; consumer: string }>('/api/inbound-keys',
      { company_id: companyId, consumer: consumer.trim() }),
    onSuccess: async (r) => {
      setIssued({ consumer: r.consumer, key: r.key })
      setConsumer('')
      refresh()
      if (await copyText(r.key)) toast.success('Ключ выдан и скопирован — покажется только сейчас')
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const revoke = useMutation({
    mutationFn: (k: InboundKey) =>
      del(`/api/inbound-keys/${k.id}?company_id=${encodeURIComponent(companyId)}`),
    onSuccess: () => { toast.success('Ключ отозван'); refresh() },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  if (!canManage) return null
  const keys = q.data?.keys ?? []

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <KeyRound className="h-4 w-4 text-primary" /> Входящие ключи
        </CardTitle>
        <CardDescription className="text-xs">
          По ним внешние системы присылают данные в пространство (заголовок
          X-Cloud-API-Key). Ключ — на потребителя: видно, кто ходит, и любого
          можно отозвать отдельно.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {issued && (
          <div className="space-y-1 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2">
            <p className="text-xs">
              Ключ для «{issued.consumer}» — сохраните сейчас, позже показать его нельзя:
            </p>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 break-all font-mono text-[11px]">{issued.key}</code>
              <Button variant="outline" size="sm" className="h-7 shrink-0 text-xs"
                onClick={async () => { if (await copyText(issued.key)) toast.success('Скопировано') }}>
                <Copy className="mr-1 h-3 w-3" />Копировать
              </Button>
              <Button variant="ghost" size="sm" className="h-7 shrink-0 text-xs"
                onClick={() => setIssued(null)}>
                <Check className="mr-1 h-3 w-3" />Сохранил
              </Button>
            </div>
          </div>
        )}

        {keys.length === 0 && !q.isLoading && (
          <p className="text-xs text-muted-foreground">
            Именных ключей пока нет — внешние узлы ходят по общему легаси-ключу
            компании. Выдайте ключ каждому потребителю и замените на их стороне.
          </p>
        )}
        {keys.map((k) => (
          <div key={k.id}
            className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-3 py-1.5 text-xs ${
              k.revoked_at ? 'opacity-50' : ''}`}>
            <span className="font-medium">{k.consumer}</span>
            <code className="font-mono text-muted-foreground">{k.prefix}…</code>
            <span className="text-muted-foreground">
              {k.revoked_at ? 'отозван' : `последний обмен: ${since(k.last_used_at)}`}
            </span>
            {!k.revoked_at && (
              <Button variant="ghost" size="sm"
                className="ml-auto h-6 gap-1 px-2 text-[11px] text-muted-foreground hover:text-destructive"
                disabled={revoke.isPending} onClick={() => revoke.mutate(k)}>
                <ShieldOff className="h-3 w-3" />Отозвать
              </Button>
            )}
          </div>
        ))}

        <div className="flex items-center gap-2 pt-1">
          <Input value={consumer} onChange={(e) => setConsumer(e.target.value)}
            placeholder="Кому ключ: напр. Дедуп-нода АЗС 208" className="h-8 text-xs" />
          <Button size="sm" className="h-8 shrink-0"
            disabled={consumer.trim().length < 2 || create.isPending}
            onClick={() => create.mutate()}>
            {create.isPending
              ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              : <Plus className="mr-1.5 h-3.5 w-3.5" />}
            Выдать ключ
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
