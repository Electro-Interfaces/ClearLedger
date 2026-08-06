/**
 * PIN станции участника — короткий код для входа на рабочем месте АЗС (edge).
 *
 * Профиль тот же, что в пространстве; PIN лишь разблокирует его локально на
 * кассе, при мёртвом канале — пароль пространства наружу не выходит. Задаётся
 * здесь, едет вниз в ростере привязанных станций. Пустой — снять PIN.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { KeyRound, Loader2 } from 'lucide-react'
import * as userService from '@/services/userService'
import type { AdminUser } from '@/services/userService'

export function StationPinDialog({ member, companyId, onSaved }: {
  member: AdminUser; companyId: string; onSaved: () => void
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [pin, setPin] = useState('')
  const has = !!member.has_station_pin

  const openChange = (v: boolean) => {
    if (v) setPin('')
    setOpen(v)
  }

  const save = useMutation({
    mutationFn: (value: string) => userService.setStationPin(member.id, companyId, value),
    onSuccess: (_res, value) => {
      toast.success(value ? 'PIN станции задан' : 'PIN станции снят')
      qc.invalidateQueries({ queryKey: ['team-members', companyId] })
      onSaved(); setOpen(false)
    },
    onError: (e) => toast.error('Не сохранено', { description: (e as Error).message }),
  })

  const valid = /^\d{4,8}$/.test(pin)

  return (
    <Dialog open={open} onOpenChange={openChange}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm"
          className={`h-6 gap-1 px-1.5 text-[11px] ${has ? 'text-primary' : 'text-muted-foreground'} hover:text-foreground`}
          title="PIN для входа на рабочем месте АЗС">
          <KeyRound className="h-3.5 w-3.5" /> {has ? 'PIN задан' : 'PIN'}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader><DialogTitle>PIN станции: {member.name}</DialogTitle></DialogHeader>
        <p className="-mt-1 text-xs text-muted-foreground">
          Короткий код (4–8 цифр) для входа под своим профилем на рабочем месте АЗС —
          работает без связи. Пароль пространства при этом наружу не выходит.
          После сохранения PIN уезжает в ростер привязанных станций.
        </p>
        <Input value={pin} inputMode="numeric" autoComplete="off" autoFocus
          onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 8))}
          placeholder="4–8 цифр" className="text-center tracking-[0.3em]" />
        <DialogFooter className="gap-2 sm:justify-between">
          {has ? (
            <Button variant="ghost" className="text-destructive" disabled={save.isPending}
              onClick={() => save.mutate('')}>Снять PIN</Button>
          ) : <span />}
          <span className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>Отмена</Button>
            <Button onClick={() => save.mutate(pin)} disabled={save.isPending || !valid}>
              {save.isPending && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}Сохранить
            </Button>
          </span>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
