/**
 * «Управление» → «Договоры и оборудование»: обязательства пространства и паспорта единиц
 * (docs/SPACE.md §3, этапы 6–7 плана).
 *
 * Контрагенты уехали в свой раздел («Контрагенты»): в одном списке с оборудованием
 * юрлицо-сторона договора и компания-партнёр с доступом читались как одна сущность.
 * Здесь остались сами обязательства и железо — то, что висит на объектах.
 *
 * Ведение остаётся в приложениях (складской контур оборудования — рабочий раздел Учёта),
 * здесь общий взгляд пространства и отправка в приложения.
 */
import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Cpu, FileSignature, Loader2, Share2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  listSpaceContracts, listSpaceEquipment, projectSpaceEntity,
} from '@/services/spaceObjectsService'

/** Направление обязательства: кто кому платит. Считается на сервере по виду договора. */
const DIRECTIONS = [
  { code: 'all', label: 'Все' },
  { code: 'in', label: 'Входящие' },
  { code: 'out', label: 'Исходящие' },
] as const

export function SpaceRefs({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const [direction, setDirection] = useState<'all' | 'in' | 'out'>('all')
  const contractsQ = useQuery({
    queryKey: ['space-contracts', companyId],
    queryFn: () => listSpaceContracts(companyId),
  })
  const equipQ = useQuery({
    queryKey: ['space-equipment', companyId],
    queryFn: () => listSpaceEquipment(companyId),
  })

  const project = useMutation({
    mutationFn: () => projectSpaceEntity(companyId, 'equipment'),
    onSuccess: (r) => toast.success(
      `Отправлено: ${r.sent}`,
      { description: `Создано ${r.created}, обновлено ${r.updated}` +
        (r.skipped.length ? `, пропущено ${r.skipped.length}` : '') },
    ),
    onError: (e) => toast.error('Проекция не выполнена', { description: (e as Error).message }),
  })

  const allContracts = contractsQ.data ?? []
  const contracts = direction === 'all'
    ? allContracts
    : allContracts.filter((c) => c.direction === direction)
  const units = equipQ.data ?? []

  return (
    <div className="space-y-8">
      {/* Договоры — вторая ось пространства после объекта: по ней сходятся аренда и
          энергоснабжение в Эксплуатации, договоры ЮЛ в Корпоративном процессинге,
          первичка в Финансах и обслуживание в Координаторе. Здесь — общий взгляд:
          с кем, о чём и на какие объекты; суммы и оплата остаются в разрезах. */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <FileSignature className="size-4 text-primary" />
          <span className="text-sm font-medium">Договоры</span>
          <span className="text-xs text-muted-foreground">
            ({contracts.length}{direction === 'all' ? '' : ` из ${allContracts.length}`})
          </span>
          <div className="flex-1" />
          {DIRECTIONS.map((d) => (
            <Button key={d.code} size="sm" className="h-7 px-2 text-xs"
              variant={direction === d.code ? 'secondary' : 'ghost'}
              onClick={() => setDirection(d.code)}>
              {d.label}
            </Button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          База договоров одна на организацию: входящие (организация платит — аренда,
          энергоснабжение, обслуживание) и исходящие (платят ей — поставка,
          зарядка ЭЗС). Приложения берут контрагента и договор отсюда, а показывают
          ровно то, что разрешено правами. Ось: контрагент → договор → объекты; охват
          «весь периметр» действует на все объекты, «объекты» — на выбранные.
        </p>
        {contractsQ.isLoading ? <Loading /> : contracts.length === 0 ? (
          <Empty text={allContracts.length === 0 ? 'Договоров пока нет'
            : 'В этом направлении договоров нет'} />
        ) : (
          <div className="rounded-xl border border-border overflow-x-auto">
            <Table className="min-w-[820px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[150px]">Номер и дата</TableHead>
                  <TableHead>Контрагент</TableHead>
                  <TableHead className="w-[100px]">Сторона</TableHead>
                  <TableHead className="w-[170px]">Предмет</TableHead>
                  <TableHead className="w-[150px]">Охват</TableHead>
                  <TableHead className="w-[110px]">Срок</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {contracts.slice(0, 50).map((c) => (
                  <TableRow key={c.id} className={c.isClosed ? 'opacity-60' : undefined}>
                    <TableCell className="font-medium">
                      {c.number}
                      <div className="text-xs font-normal text-muted-foreground">{c.date}</div>
                    </TableCell>
                    <TableCell>
                      {c.counterpartyName || <span className="text-muted-foreground">не сопоставлен</span>}
                      {c.counterpartyInn && (
                        <div className="font-mono text-xs text-muted-foreground">{c.counterpartyInn}</div>
                      )}
                    </TableCell>
                    <TableCell className="text-xs">
                      {c.direction === 'in' ? 'мы платим'
                        : c.direction === 'out' ? 'платят нам'
                        : <span className="text-muted-foreground">не задана</span>}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {c.basis || c.type || '—'}
                    </TableCell>
                    <TableCell className="text-xs">
                      {c.scopeType === 'company' ? 'весь периметр'
                        : c.scopeType === 'locations' ? `объектов: ${c.objectsCount}`
                        : <span className="text-muted-foreground">не задан</span>}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {c.isClosed
                        ? <Badge variant="secondary" className="text-[10px]">закрыт</Badge>
                        : (c.validUntil || 'бессрочно')}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {contracts.length > 50 && (
              <div className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
                Показаны первые 50 из {contracts.length}.
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
              disabled={project.isPending} onClick={() => project.mutate()}>
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
