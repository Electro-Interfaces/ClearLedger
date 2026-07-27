/**
 * Журнал событий пространства — один раздел вместо двух.
 *
 * Было: «Журнал» уровня организации (только события людей и доступов) и «Аудит» уровня
 * контейнера (все события всех организаций) — отдельными пунктами меню, с почти
 * одинаковыми таблицами. Разница между ними — охват и фильтр, то есть два переключателя,
 * а не два раздела.
 *
 * Охват «весь контейнер» доступен владельцу контейнера: `/api/core/audit` гейтится на
 * бэкенде, у админа организации переключателя нет.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { History, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import * as roleService from '@/services/roleService'
import { getCoreAudit } from '@/services/coreService'

/** Человекочитаемые имена частых действий; остальные показываем кодом. */
const ACTION_LABEL: Record<string, string> = {
  'role.create': 'Роль создана', 'role.update': 'Роль изменена', 'role.delete': 'Роль удалена',
  'member.access': 'Доступ изменён', 'member.role': 'Роль сотрудника',
  'member.party': 'Принадлежность', 'member.scope': 'Объекты участника',
  'user.create': 'Человек добавлен', 'user.remove': 'Человек убран',
  'space.object.create': 'Объект создан', 'space.object.update': 'Объект изменён',
}

/** События людей и доступов — то, что раньше показывал «Журнал» организации. */
const PEOPLE_ACTIONS = /^(role\.|member\.|user\.)/

type Row = {
  id: string
  at?: string | null
  action: string
  who?: string | null
  details?: string | null
  company?: string | null
}

export function AuditLog({ companyId, isSuperadmin = false }: {
  companyId: string; isSuperadmin?: boolean
}) {
  const [scope, setScope] = useState<'company' | 'container'>('company')
  const [only, setOnly] = useState<'people' | 'all'>('people')
  const container = isSuperadmin && scope === 'container'

  const companyQ = useQuery({
    queryKey: ['audit', companyId],
    queryFn: () => roleService.listAudit(companyId, 200),
    enabled: !container,
  })
  const coreQ = useQuery({
    queryKey: ['core-audit'],
    queryFn: () => getCoreAudit({ limit: 200 }),
    enabled: container,
  })

  const isLoading = container ? coreQ.isLoading : companyQ.isLoading
  const rows: Row[] = container
    ? (coreQ.data ?? []).map((e) => ({
        id: e.id, at: e.timestamp, action: e.action, who: e.userName,
        details: e.details, company: e.companyName,
      }))
    : (companyQ.data ?? []).map((e) => ({
        id: e.id, at: e.timestamp, action: e.action, who: e.user_name, details: e.details,
      }))
  const shown = only === 'people' ? rows.filter((r) => PEOPLE_ACTIONS.test(r.action)) : rows

  const Toggle = ({ on, onClick, children }: {
    on: boolean; onClick: () => void; children: React.ReactNode
  }) => (
    <Button size="sm" variant={on ? 'secondary' : 'ghost'} className="h-7 px-2 text-xs" onClick={onClick}>
      {children}
    </Button>
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><History className="h-5 w-5" /> Журнал событий</CardTitle>
        <CardDescription>Кто, когда и что менял. Только чтение.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1">
            <span className="mr-1 text-xs text-muted-foreground">Показывать:</span>
            <Toggle on={only === 'people'} onClick={() => setOnly('people')}>Люди и доступы</Toggle>
            <Toggle on={only === 'all'} onClick={() => setOnly('all')}>Все события</Toggle>
          </div>
          {isSuperadmin && (
            <div className="flex items-center gap-1">
              <span className="mr-1 text-xs text-muted-foreground">Охват:</span>
              <Toggle on={scope === 'company'} onClick={() => setScope('company')}>Организация</Toggle>
              <Toggle on={scope === 'container'} onClick={() => setScope('container')}>Весь контейнер</Toggle>
            </div>
          )}
        </div>

        {isLoading && (
          <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
          </div>
        )}
        <div className="overflow-x-auto">
          <Table className={container ? 'min-w-[760px]' : undefined}>
            <TableHeader><TableRow>
              <TableHead className="w-[150px]">Когда</TableHead>
              <TableHead className="w-[180px]">Действие</TableHead>
              {container && <TableHead className="w-[150px]">Организация</TableHead>}
              <TableHead className="w-[170px]">Кто</TableHead>
              <TableHead>Детали</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {!isLoading && shown.length === 0 && (
                <TableRow><TableCell colSpan={container ? 5 : 4}
                  className="py-6 text-center text-sm text-muted-foreground">
                  {rows.length === 0 ? 'Событий нет' : 'В этом фильтре событий нет'}
                </TableCell></TableRow>
              )}
              {shown.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                    {e.at ? new Date(e.at).toLocaleString('ru-RU') : '—'}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="text-[10px] font-normal">
                      {ACTION_LABEL[e.action] ?? e.action}
                    </Badge>
                  </TableCell>
                  {container && (
                    <TableCell className="text-xs text-muted-foreground">{e.company ?? '—'}</TableCell>
                  )}
                  <TableCell className="text-xs">{e.who ?? '—'}</TableCell>
                  <TableCell className="max-w-0 truncate text-xs text-muted-foreground">
                    {e.details ?? ''}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Записей: {shown.length}
          {shown.length !== rows.length ? ` из ${rows.length}` : ''}
          {' '}· последние 200 событий
        </p>
      </CardContent>
    </Card>
  )
}
