import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Check, Loader2, MapPin, Network, Save, Store, Users } from 'lucide-react'
import * as businessAccess from '@/services/businessAccessService'
import type { BusinessGrant } from '@/services/businessAccessService'
import * as userService from '@/services/userService'
import type { AdminUser } from '@/services/userService'
import { listSpaceObjects } from '@/services/spaceObjectsService'

export function StoreBusinessAccess({ companyId, canManage }: {
  companyId: string
  canManage: boolean
}) {
  const qc = useQueryClient()
  const policyQ = useQuery({
    queryKey: ['store-access-policy', companyId],
    queryFn: businessAccess.getStoreAccessPolicy,
  })
  const membersQ = useQuery({
    queryKey: ['team-members', companyId],
    queryFn: () => userService.listUsers(companyId),
  })
  const objectsQ = useQuery({
    queryKey: ['space-objects-business-access', companyId],
    queryFn: () => listSpaceObjects(companyId),
  })
  const savePolicy = useMutation({
    mutationFn: businessAccess.saveStoreAccessPolicy,
    onSuccess: () => {
      toast.success('Политика Магазина v1 зафиксирована')
      qc.invalidateQueries({ queryKey: ['store-access-policy', companyId] })
    },
    onError: (e) => toast.error('Политика не сохранена', { description: (e as Error).message }),
  })
  const stations = (objectsQ.data ?? [])
    .filter((o) => /^\d+$/.test(o.code) && (o.type === 'fuel_station' || o.type === 'retail'))
    .sort((a, b) => Number(a.code) - Number(b.code))
  const members = (membersQ.data ?? [])
    .filter((m) => m.party_type !== 'partner')
    .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  const policy = policyQ.data

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.8fr)_minmax(520px,1.2fr)]">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Store className="h-5 w-5" /> Политика Магазина</CardTitle>
          <CardDescription>
            Кто принимает коммерческие решения. Технический администратор пространства в эту модель не входит.
          </CardDescription>
          {canManage && (
            <CardAction>
              <Button size="sm" className="gap-1.5" disabled={savePolicy.isPending}
                onClick={() => savePolicy.mutate()}>
                {savePolicy.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                Зафиксировать v1
              </Button>
            </CardAction>
          )}
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <PolicyRow label="Товары и цены" value="В ведении администратора АЗС" active />
          <PolicyRow label="Центр" value="Канон НСИ, аналитика и предложения" />
          <PolicyRow label="Топливо" value="Только аналитические метрики" />
          <div className="rounded-md border border-dashed border-border/70 bg-muted/20 p-3 text-xs text-muted-foreground">
            Сетевое управление ценой и ассортиментом пока не включается. Позже оно появится
            отдельным назначением на категорию или карточку, без смены модели ролей.
          </div>
          {policy && (
            <div className="text-[11px] text-muted-foreground">
              Контракт v{policy.schema_version} · редакция {policy.revision === 'default-v1'
                ? 'по умолчанию' : new Date(policy.revision).toLocaleString('ru-RU')}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Users className="h-5 w-5" /> Бизнес-роли Магазина</CardTitle>
          <CardDescription>
            Права складываются: один человек может администрировать несколько АЗС и одновременно быть товароведом сети.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {(membersQ.isLoading || objectsQ.isLoading) && (
            <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Загрузка назначений…
            </div>
          )}
          {members.map((member) => (
            <div key={member.id} className="flex items-center justify-between gap-3 rounded-md border px-3 py-2.5">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{member.name}</div>
                <div className="truncate text-[11px] text-muted-foreground">{member.email}</div>
                <GrantSummary grants={member.business_grants ?? []} />
              </div>
              {canManage && (
                <BusinessRolesDialog member={member} companyId={companyId} stations={stations}
                  onSaved={() => {
                    qc.invalidateQueries({ queryKey: ['team-members', companyId] })
                    qc.invalidateQueries({ queryKey: ['store-access-policy', companyId] })
                  }} />
              )}
            </div>
          ))}
          {!membersQ.isLoading && members.length === 0 && (
            <p className="text-sm text-muted-foreground">Сотрудников организации пока нет.</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function PolicyRow({ label, value, active }: { label: string; value: string; active?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <Badge variant="outline" className={active ? 'border-emerald-400/40 text-emerald-300/80' : ''}>{value}</Badge>
    </div>
  )
}

function GrantSummary({ grants }: { grants: BusinessGrant[] }) {
  const stations = grants.filter((g) => g.role === 'station_administrator').map((g) => g.scope_id)
  const network = grants.some((g) => g.role === 'network_merchandiser')
  if (!stations.length && !network) return <div className="mt-1 text-[11px] text-muted-foreground">не назначено</div>
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {stations.length > 0 && (
        <Badge variant="outline" className="gap-1 text-[10px]"><MapPin className="h-3 w-3" /> Администратор АЗС: {stations.join(', ')}</Badge>
      )}
      {network && (
        <Badge variant="outline" className="gap-1 text-[10px]"><Network className="h-3 w-3" /> Товаровед сети</Badge>
      )}
    </div>
  )
}

function BusinessRolesDialog({ member, companyId, stations, onSaved }: {
  member: AdminUser
  companyId: string
  stations: { code: string; name: string }[]
  onSaved: () => void
}) {
  const [open, setOpen] = useState(false)
  const [network, setNetwork] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const openChange = (value: boolean) => {
    if (value) {
      const grants = member.business_grants ?? []
      setNetwork(grants.some((g) => g.role === 'network_merchandiser'))
      setSelected(new Set(grants.filter((g) => g.role === 'station_administrator').map((g) => g.scope_id)))
    }
    setOpen(value)
  }
  const save = useMutation({
    mutationFn: () => {
      const grants: BusinessGrant[] = [...selected].map((scopeId) => ({
        role: 'station_administrator', scope_type: 'station', scope_id: scopeId,
      }))
      if (network) grants.push({
        role: 'network_merchandiser', scope_type: 'network', scope_id: companyId,
      })
      return userService.setBusinessGrants(member.id, companyId, grants)
    },
    onSuccess: () => { toast.success('Бизнес-роли сохранены'); onSaved(); setOpen(false) },
    onError: (e) => toast.error('Назначения не сохранены', { description: (e as Error).message }),
  })
  const toggle = (code: string) => setSelected((current) => {
    const next = new Set(current)
    if (next.has(code)) next.delete(code); else next.add(code)
    return next
  })

  return (
    <Dialog open={open} onOpenChange={openChange}>
      <DialogTrigger asChild><Button variant="outline" size="sm">Настроить</Button></DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Бизнес-роли: {member.name}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <label className="flex cursor-pointer items-start gap-3 rounded-md border p-3">
            <input type="checkbox" className="mt-0.5 h-4 w-4" checked={network}
              onChange={(e) => setNetwork(e.target.checked)} />
            <span>
              <span className="block text-sm font-medium">Товаровед сети</span>
              <span className="block text-xs text-muted-foreground">Аналитика и централизованные функции по всей сети. В v1 решения станции не перезаписывает.</span>
            </span>
          </label>
          <div>
            <div className="mb-2 text-sm font-medium">Администратор АЗС</div>
            <div className="max-h-64 space-y-1 overflow-y-auto pr-1">
              {stations.map((station) => {
                const active = selected.has(station.code)
                return (
                  <button key={station.code} type="button" onClick={() => toggle(station.code)}
                    className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left ${active ? 'border-primary/40 bg-primary/10' : 'hover:bg-accent/40'}`}>
                    <span className="text-sm"><b>АЗС {station.code}</b> · {station.name}</span>
                    {active && <Check className="h-4 w-4 text-primary" />}
                  </button>
                )
              })}
              {stations.length === 0 && <p className="text-xs text-muted-foreground">В реестре ядра нет станций с числовым кодом.</p>}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Отмена</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
