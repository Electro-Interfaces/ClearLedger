/**
 * Открыть канал или группу пространства (приложение «Чаты», администратор).
 *
 * Канал и группа заводятся одним диалогом, потому что отличаются они не полями, а
 * смыслом: у канала спрашиваем «кто его ведёт» (пишет там только владелец), у группы —
 * «кто в ней разговаривает». Поэтому владелец в канале обязателен и стоит первым, а в
 * группе это просто ответственный за состав.
 *
 * Состав набирается двумя способами: «все люди пространства» одной галкой (так делают
 * канал новостей — он для всех) и точечный выбор (так делают группу под задачу). Люди
 * партнёров в списке помечены компанией: в смешанной группе это первое, что нужно знать.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, Megaphone, Search, Users } from 'lucide-react'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import * as admin from '@/services/chatAdminService'
import { SPACE_PRODUCTS } from '@/config/spaceProducts'
import { PartyBadge } from '@/components/chat/PartyBadge'

export function CreateRoomDialog({ type, open, onOpenChange }: {
  type: 'channel' | 'group'
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const qc = useQueryClient()
  const isChannel = type === 'channel'
  const [name, setName] = useState('')
  const [ownerId, setOwnerId] = useState('')
  const [everyone, setEveryone] = useState(isChannel)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [scope, setScope] = useState('none')
  const [q, setQ] = useState('')

  const people = useQuery({
    queryKey: ['chat-admin-people'],
    queryFn: admin.getPeople,
    enabled: open,
    staleTime: 5 * 60_000,
  })

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const all = people.data ?? []
    if (!needle) return all
    return all.filter((p) => p.name.toLowerCase().includes(needle)
      || (p.email ?? '').toLowerCase().includes(needle)
      || (p.companyName ?? '').toLowerCase().includes(needle))
  }, [people.data, q])

  const reset = () => {
    setName(''); setOwnerId(''); setEveryone(isChannel)
    setPicked(new Set()); setScope('none'); setQ('')
  }

  const create = useMutation({
    mutationFn: () => admin.createRoom({
      type, name: name.trim(), ownerId: ownerId || undefined,
      participantIds: [...picked], everyone,
      scopeProduct: scope === 'none' ? undefined : scope,
    }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['chat-admin-rooms'] })
      qc.invalidateQueries({ queryKey: ['chat-rooms'] })
      toast.success(`${isChannel ? 'Канал' : 'Группа'} «${r.name}» ${isChannel ? 'открыт' : 'открыта'}`)
      reset()
      onOpenChange(false)
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось создать чат'),
  })

  const toggle = (id: string) => setPicked((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })

  const Icon = isChannel ? Megaphone : Users
  const canSubmit = name.trim().length > 0 && !create.isPending

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v) }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-sm">
            <Icon className="size-4 text-blue-600 dark:text-blue-400" />
            {isChannel ? 'Новый канал' : 'Новая группа'}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {isChannel
              ? 'Односторонний: пишет владелец и назначенные им админы, остальные читают. Новости, рассылки, слово руководства.'
              : 'Разговаривают все участники. Под задачу, направление или партнёра.'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">Название</span>
            <Input value={name} onChange={(e) => setName(e.target.value)} className="h-8 text-sm"
              placeholder={isChannel ? 'Например: Кадры и приказы' : 'Например: Ремонт АЗС №205'} />
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">
              {isChannel ? 'Ведёт канал' : 'Ответственный'}
            </span>
            <Select value={ownerId || 'self'} onValueChange={(v) => setOwnerId(v === 'self' ? '' : v)}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="self" className="text-xs">Я</SelectItem>
                {(people.data ?? []).filter((p) => !p.isExternal).map((p) => (
                  <SelectItem key={p.userId} value={p.userId} className="text-xs">{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">Приложение</span>
            <Select value={scope} onValueChange={setScope}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none" className="text-xs">Всё пространство</SelectItem>
                {SPACE_PRODUCTS.map((p) => (
                  <SelectItem key={p.code} value={p.code} className="text-xs">{p.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>

          <div className="space-y-2 rounded-md border border-border p-2.5">
            <label className="flex items-center gap-2 text-xs">
              <Checkbox checked={everyone} onCheckedChange={(v) => setEveryone(v === true)} />
              <span>Все люди пространства</span>
              <span className="text-muted-foreground">
                ({(people.data ?? []).length})
              </span>
            </label>
            {!everyone && (
              <>
                <div className="flex items-center gap-1.5">
                  <Search className="size-3.5 text-muted-foreground" />
                  <Input value={q} onChange={(e) => setQ(e.target.value)} className="h-7 text-xs"
                    placeholder="Имя, почта или компания" />
                </div>
                <div className="max-h-48 space-y-0.5 overflow-y-auto">
                  {people.isLoading ? (
                    <div className="flex justify-center py-4">
                      <Loader2 className="size-4 animate-spin text-muted-foreground" />
                    </div>
                  ) : shown.length === 0 ? (
                    <div className="py-4 text-center text-xs text-muted-foreground">Никого не нашлось</div>
                  ) : shown.map((p) => (
                    <label key={p.userId}
                      className={cn('flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-muted/50',
                        picked.has(p.userId) && 'bg-muted/40')}>
                      <Checkbox checked={picked.has(p.userId)} onCheckedChange={() => toggle(p.userId)} />
                      <span className="truncate">{p.name}</span>
                      {/* Набирая состав, видно, кого зовёшь: инженера платформы, своего
                          или человека партнёра — и какого именно. */}
                      <PartyBadge party={{
                        partyType: p.partyType ?? (p.isExternal ? 'partner' : 'internal'),
                        orgName: p.companyName,
                      }} />
                    </label>
                  ))}
                </div>
                <div className="text-[11px] text-muted-foreground">Выбрано: {picked.size}</div>
              </>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button size="sm" disabled={!canSubmit} onClick={() => create.mutate()}>
            {create.isPending && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
            {isChannel ? 'Открыть канал' : 'Создать группу'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
