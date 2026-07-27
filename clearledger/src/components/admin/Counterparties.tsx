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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { listSpaceOrganizations, projectSpaceEntity } from '@/services/spaceObjectsService'
import * as userService from '@/services/userService'

export function Counterparties({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const [search, setSearch] = useState('')
  const orgsQ = useQuery({
    queryKey: ['space-orgs', companyId],
    queryFn: () => listSpaceOrganizations(companyId),
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
                  <TableRow key={o.id}>
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
    </div>
  )
}
