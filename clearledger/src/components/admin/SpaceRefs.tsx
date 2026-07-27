/**
 * Вкладка «Справочники» Центра управления — организации и оборудование пространства
 * (docs/SPACE.md §3, этапы 6–7 плана).
 *
 * Карточки общие для всех разрезов; РОЛЬ у них прикладная: одно и то же юрлицо в Учёте
 * может быть поставщиком топлива, а в Координаторе — подрядчиком. Поэтому здесь только
 * реквизиты и паспорт, без ролевых полей.
 *
 * Ведение остаётся в Учёте (контрагенты и складской контур оборудования — его рабочие
 * разделы), здесь — общий взгляд пространства и отправка в приложения.
 */
import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Building2, Cpu, Loader2, Share2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  listSpaceOrganizations, listSpaceEquipment, projectSpaceEntity,
} from '@/services/spaceObjectsService'

export function SpaceRefs({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const orgsQ = useQuery({
    queryKey: ['space-orgs', companyId],
    queryFn: () => listSpaceOrganizations(companyId),
  })
  const equipQ = useQuery({
    queryKey: ['space-equipment', companyId],
    queryFn: () => listSpaceEquipment(companyId),
  })

  const project = useMutation({
    mutationFn: (entity: 'organizations' | 'equipment') => projectSpaceEntity(companyId, entity),
    onSuccess: (r) => toast.success(
      `Отправлено: ${r.sent}`,
      { description: `Создано ${r.created}, обновлено ${r.updated}` +
        (r.skipped.length ? `, пропущено ${r.skipped.length}` : '') },
    ),
    onError: (e) => toast.error('Проекция не выполнена', { description: (e as Error).message }),
  })

  const orgs = orgsQ.data ?? []
  const units = equipQ.data ?? []

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Building2 className="size-4 text-primary" />
          <span className="text-sm font-medium">Организации</span>
          <span className="text-xs text-muted-foreground">({orgs.length})</span>
          <div className="flex-1" />
          {canManage && orgs.length > 0 && (
            <Button size="sm" variant="outline" className="gap-1.5"
              disabled={project.isPending} onClick={() => project.mutate('organizations')}>
              {project.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Share2 className="h-4 w-4" />}
              В приложения
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Юрлица пространства: реквизиты общие, роль — прикладная (в Финансах поставщик,
          в Поддержке подрядчик). Ведутся в разделе «Контрагенты».
        </p>
        {orgsQ.isLoading ? <Loading /> : orgs.length === 0 ? (
          <Empty text="Организаций пока нет" />
        ) : (
          <div className="rounded-xl border border-border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Наименование</TableHead>
                  <TableHead className="w-[140px]">ИНН</TableHead>
                  <TableHead className="w-[120px]">КПП</TableHead>
                  <TableHead className="w-[80px]">Тип</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orgs.slice(0, 50).map((o) => (
                  <TableRow key={o.id}>
                    <TableCell className="font-medium">{o.shortName || o.name}</TableCell>
                    <TableCell className="font-mono text-xs">{o.inn}</TableCell>
                    <TableCell className="font-mono text-xs">{o.kpp || '—'}</TableCell>
                    <TableCell><Badge variant="secondary" className="text-[10px]">{o.type}</Badge></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {orgs.length > 50 && (
              <div className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
                Показаны первые 50 из {orgs.length}; в приложения уходят все.
              </div>
            )}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Cpu className="size-4 text-primary" />
          <span className="text-sm font-medium">Оборудование</span>
          <span className="text-xs text-muted-foreground">({units.length})</span>
          <div className="flex-1" />
          {canManage && units.length > 0 && (
            <Button size="sm" variant="outline" className="gap-1.5"
              disabled={project.isPending} onClick={() => project.mutate('equipment')}>
              {project.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Share2 className="h-4 w-4" />}
              В приложения
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Паспорт единицы: что за железо и на каком объекте стоит. Сервисная история и
          ремонты остаются в приложениях. Единицы без объекта приложение пропустит.
        </p>
        {equipQ.isLoading ? <Loading /> : units.length === 0 ? (
          <Empty text="Оборудование не заведено" />
        ) : (
          <div className="rounded-xl border border-border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[160px]">Серийный номер</TableHead>
                  <TableHead>Модель</TableHead>
                  <TableHead className="w-[160px]">Производитель</TableHead>
                  <TableHead className="w-[120px]">Состояние</TableHead>
                  <TableHead className="w-[110px]">На объекте</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {units.slice(0, 50).map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-mono text-xs">{u.serialNumber || '—'}</TableCell>
                    <TableCell>{u.model || '—'}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{u.manufacturer || '—'}</TableCell>
                    <TableCell><Badge variant="secondary" className="text-[10px]">{u.state || u.status}</Badge></TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {u.ecoObjectId ? 'да' : <span className="opacity-60">нет</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {units.length > 50 && (
              <div className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
                Показаны первые 50 из {units.length}; в приложения уходят все.
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

function Loading() {
  return (
    <div className="flex items-center gap-2 py-6 text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
      {text}
    </div>
  )
}
