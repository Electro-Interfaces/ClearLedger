/**
 * «Управление» → «Контрагенты»: юрлица договоров и расчётов пространства.
 *
 * Свой раздел, а не карточка в «Справочниках» рядом с оборудованием: контрагент и
 * компания-партнёр — разные сущности, и в общем списке они читались как одно.
 *  • **Контрагент** — запись справочника: с кем заключён договор, кому платим и кто платит
 *    нам. Доступа к системе у него нет.
 *  • **Компания-партнёр** (раздел «Компании») — организация, ДОПУЩЕННАЯ в пространство:
 *    её люди работают в приложениях и подписаны своей стороной в чатах и заявках.
 * Одно юрлицо может быть и тем, и другим — тогда карточка контрагента одна, а доступ
 * выдаётся его людям отдельно.
 *
 * РОЛЬ контрагента прикладная: в Финансах он поставщик, в Поддержке — подрядчик. Поэтому
 * здесь только реквизиты, без ролевых полей. Ведение — в приложении, здесь общий взгляд
 * пространства и отправка в приложения.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Building2, Handshake, Loader2, Search, Share2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { SpaceContract, SpaceOrganization } from '@/services/spaceObjectsService'
import { listSpaceContracts, listSpaceOrganizations, projectSpaceEntity } from '@/services/spaceObjectsService'
import * as userService from '@/services/userService'

export function Counterparties({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const [search, setSearch] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const orgsQ = useQuery({
    queryKey: ['space-orgs', companyId],
    queryFn: () => listSpaceOrganizations(companyId),
  })
  // Договоры нужны карточке: контрагент без своих договоров — половина ответа на
  // вопрос «кто это». Запрос один на раздел, фильтр по стороне идёт на клиенте.
  const contractsQ = useQuery({
    queryKey: ['space-contracts', companyId],
    queryFn: () => listSpaceContracts(companyId),
  })
  // Кто из контрагентов заодно допущен в пространство: их люди помечены этой карточкой.
  // Без этого признака два раздела выглядели бы несвязанными списками одних и тех же имён.
  const membersQ = useQuery({
    queryKey: ['team-members', companyId],
    queryFn: () => userService.listUsers(companyId),
  })

  const project = useMutation({
    mutationFn: () => projectSpaceEntity(companyId, 'organizations'),
    onSuccess: (r) => toast.success(`Отправлено: ${r.sent}`, {
      description: `Создано ${r.created}, обновлено ${r.updated}`
        + (r.skipped.length ? `, пропущено ${r.skipped.length}` : ''),
    }),
    onError: (e) => toast.error('Проекция не выполнена', { description: (e as Error).message }),
  })

  const orgs = orgsQ.data ?? []
  const peopleByOrg = useMemo(() => {
    const map = new Map<string, number>()
    for (const m of membersQ.data ?? []) {
      if (m.organization_id && (m.party_type === 'partner' || m.party_type === 'vendor')) {
        map.set(m.organization_id, (map.get(m.organization_id) ?? 0) + 1)
      }
    }
    return map
  }, [membersQ.data])

  const open = orgs.find((o) => o.id === openId)
  const q = search.trim().toLowerCase()
  const rows = q
    ? orgs.filter((o) => `${o.name} ${o.shortName ?? ''} ${o.inn ?? ''}`.toLowerCase().includes(q))
    : orgs

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск: наименование или ИНН…" className="h-8 pl-8 text-sm" />
        </div>
        {canManage && orgs.length > 0 && (
          <Button variant="outline" size="sm" className="gap-1.5"
            disabled={project.isPending} onClick={() => project.mutate()}
            title="Отправить контрагентов в приложения экосистемы">
            {project.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Share2 className="h-4 w-4" />}
            В приложения
          </Button>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        Юрлица, с которыми у организации договоры и расчёты. Доступа к системе контрагент
        сам по себе не даёт: если его людям нужно работать в приложениях, они заводятся в
        разделе «Компании» с этой же карточкой.
      </p>

      {orgsQ.isLoading ? (
        <div className="flex items-center gap-2 py-6 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
          {orgs.length === 0 ? 'Контрагентов пока нет' : 'Ничего не найдено'}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <Table className="min-w-[720px]">
            <TableHeader>
              <TableRow>
                <TableHead>Наименование</TableHead>
                <TableHead className="w-[140px]">ИНН</TableHead>
                <TableHead className="w-[120px]">КПП</TableHead>
                <TableHead className="w-[90px]">Тип</TableHead>
                <TableHead className="w-[190px]">Доступ в пространство</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((o) => {
                const people = peopleByOrg.get(o.id) ?? 0
                return (
                  <TableRow key={o.id} className="cursor-pointer" onClick={() => setOpenId(o.id)}>
                    <TableCell className="font-medium">{o.shortName || o.name}</TableCell>
                    <TableCell className="font-mono text-xs">{o.inn}</TableCell>
                    <TableCell className="font-mono text-xs">{o.kpp || '—'}</TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-[10px]">{o.type}</Badge>
                    </TableCell>
                    <TableCell className="text-xs">
                      {people > 0 ? (
                        <span className="flex items-center gap-1.5 text-foreground">
                          <Handshake className="h-3.5 w-3.5 text-primary" />
                          компания-партнёр · {people} чел.
                        </span>
                      ) : (
                        <span className="flex items-center gap-1.5 text-muted-foreground">
                          <Building2 className="h-3.5 w-3.5" /> только договоры
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Контрагентов: {orgs.length}
        {rows.length !== orgs.length ? ` · показано ${rows.length}` : ''}
        {' '}· договоры по ним — в разделе «Договоры и оборудование»
      </p>

      <Sheet open={!!open} onOpenChange={(v) => { if (!v) setOpenId(null) }}>
        <SheetContent side="right" className="w-full sm:max-w-lg p-0">
          <SheetTitle className="sr-only">Карточка контрагента</SheetTitle>
          <SheetDescription className="sr-only">Реквизиты и договоры контрагента</SheetDescription>
          <div className="h-full overflow-y-auto p-5">
            {open && <CounterpartyCard org={open} contracts={contractsQ.data ?? []} />}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}

/** Строка реквизита: пустые не показываем — в карточке из бухгалтерии заполнено не всё. */
export function Req({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null
  return (
    <div className="space-y-0.5">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-sm break-words">{value}</div>
    </div>
  )
}

function CounterpartyCard(
  { org, contracts }: { org: SpaceOrganization; contracts: SpaceContract[] },
) {
  const own = contracts.filter((c) => c.counterpartyId === org.id)
  const bank = [org.bankName, org.bankAccount, org.bankBik && `БИК ${org.bankBik}`]
    .filter(Boolean).join(' · ')
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-2">
        <Building2 className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <h3 className="text-base font-semibold leading-tight">{org.shortName || org.name}</h3>
          {org.fullName && org.fullName !== org.name && (
            <p className="mt-1 text-xs text-muted-foreground">{org.fullName}</p>
          )}
        </div>
        <Badge variant="secondary" className="ml-auto text-[10px]">{org.type}</Badge>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Req label="ИНН" value={org.inn} />
        <Req label="КПП" value={org.kpp} />
        <Req label="ОКПО" value={org.okpo} />
      </div>
      <div className="space-y-3">
        <Req label="Юридический адрес" value={org.legalAddress} />
        <Req label="Фактический адрес"
          value={org.actualAddress && org.actualAddress !== org.legalAddress ? org.actualAddress : null} />
        <Req label="Телефон" value={org.phone} />
        <Req label="Почта" value={org.email} />
        <Req label="Банк" value={bank || null} />
      </div>

      <div className="space-y-2">
        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
          Договоры ({own.length})
        </div>
        {own.length === 0 ? (
          <p className="text-sm text-muted-foreground">Договоров с этим контрагентом нет.</p>
        ) : own.map((c) => (
          <div key={c.id} className="rounded-lg border border-border px-3 py-2 text-sm">
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-medium">№ {c.number}</span>
              <span className="text-xs text-muted-foreground">{c.date}</span>
            </div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              {c.type}
              {' · '}
              {c.direction === 'in' ? 'мы платим' : c.direction === 'out' ? 'платят нам' : 'сторона не задана'}
              {c.validUntil ? ` · до ${c.validUntil}` : ''}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
