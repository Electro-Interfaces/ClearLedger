/**
 * Журнал событий пространства — один раздел вместо двух.
 *
 * Было: «Журнал» уровня организации (только события людей и доступов) и «Аудит» уровня
 * контейнера (все события всех организаций) — отдельными пунктами меню, с почти
 * одинаковыми таблицами. Разница между ними — охват и фильтр, то есть два переключателя,
 * а не два раздела.
 *
 * Фильтры «человек / период / порядок» — серверные (иначе «последние 200» прячут
 * историю конкретного сотрудника), группа событий — клиентская: она режет уже
 * загруженное. Ссылка `?user=<id>` открывает журнал сразу по человеку — так карточка
 * участника ведёт в его историю.
 *
 * Охват «весь контейнер» доступен владельцу контейнера: `/api/core/audit` гейтится на
 * бэкенде, у админа организации переключателя нет.
 */
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownWideNarrow, ArrowUpNarrowWide, History, Loader2, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import * as roleService from '@/services/roleService'
import * as userService from '@/services/userService'
import { getCoreAudit } from '@/services/coreService'

/** Человекочитаемые имена частых действий; остальные показываем кодом. */
export const ACTION_LABEL: Record<string, string> = {
  'role.create': 'Роль создана', 'role.update': 'Роль изменена', 'role.delete': 'Роль удалена',
  'member.access': 'Доступ изменён', 'member.role': 'Роль сотрудника',
  'member.party': 'Принадлежность', 'member.scope': 'Объекты участника',
  'user.create': 'Человек добавлен', 'user.remove': 'Человек убран',
  'space.object.create': 'Объект создан', 'space.object.update': 'Объект изменён',
  'auth.login': 'Вход в пространство', 'auth.login_failed': 'Вход отклонён',
  'auth.password_reset': 'Пароль изменён', 'sso.handoff': 'Переход в приложение',
  'auth.reset_link_issued': 'Выдана ссылка для входа',
  'member.contracts': 'Основание допуска',
  'department.create': 'Подразделение создано', 'department.update': 'Подразделение изменено',
  'department.delete': 'Подразделение убрано',
  'pulse.ack': 'Отметка в «Пульсе»',
}

/** Группы событий: клиентский срез уже загруженного списка. */
const GROUPS: { key: string; label: string; test: (action: string) => boolean }[] = [
  { key: 'all', label: 'Все события', test: () => true },
  { key: 'logins', label: 'Входы', test: (a) => /^(auth\.|sso\.)/.test(a) },
  { key: 'people', label: 'Люди и доступы', test: (a) => /^(role\.|member\.|user\.)/.test(a) },
]

const PAGE = 200      // первый экран журнала
const PAGE_MORE = 300 // шаг кнопки «Показать ещё»

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
  // Карточка участника даёт ссылку «весь журнал человека» — фильтр приходит адресом.
  const [params, setParams] = useSearchParams()
  const userFromLink = params.get('user')

  const [scope, setScope] = useState<'company' | 'container'>('company')
  const [group, setGroup] = useState(userFromLink ? 'all' : 'people')
  const [userId, setUserId] = useState<string>(userFromLink ?? '')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [limit, setLimit] = useState(PAGE)
  const container = isSuperadmin && scope === 'container'

  const companyQ = useQuery({
    queryKey: ['audit', companyId, userId, dateFrom, dateTo, order, limit],
    queryFn: () => roleService.listAudit(companyId, limit, {
      userId: userId || undefined,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
      order,
    }),
    enabled: !container,
  })
  const coreQ = useQuery({
    queryKey: ['core-audit'],
    queryFn: () => getCoreAudit({ limit: 200 }),
    enabled: container,
  })
  // Состав — для фильтра по человеку. Ключ тот же, что у MembersBoard: кэш общий.
  // retry: false — раздел журнала может видеть и не-админ, тогда селект просто пуст.
  const membersQ = useQuery({
    queryKey: ['team-members', companyId],
    queryFn: () => userService.listUsers(companyId),
    enabled: !container,
    retry: false,
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
  const groupDef = GROUPS.find((g) => g.key === group) ?? GROUPS[0]
  const shown = rows.filter((r) => groupDef.test(r.action))
  // Загрузили ровно limit — на сервере, скорее всего, есть ещё.
  const mayHaveMore = !container && rows.length === limit && limit < 5000

  const setUser = (id: string) => {
    setUserId(id)
    // Адрес держим в согласии с фильтром: скопированная ссылка откроет тот же срез.
    if (id) params.set('user', id); else params.delete('user')
    setParams(params, { replace: true })
  }
  const resetFilters = () => {
    setUser(''); setDateFrom(''); setDateTo(''); setGroup('people'); setLimit(PAGE)
  }
  const hasFilters = !!(userId || dateFrom || dateTo)

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
        <CardDescription>Кто, когда входил и что менял. Только чтение.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex items-center gap-1">
            <span className="mr-1 text-xs text-muted-foreground">Показывать:</span>
            {GROUPS.map((g) => (
              <Toggle key={g.key} on={group === g.key} onClick={() => setGroup(g.key)}>{g.label}</Toggle>
            ))}
          </div>
          {isSuperadmin && (
            <div className="flex items-center gap-1">
              <span className="mr-1 text-xs text-muted-foreground">Охват:</span>
              <Toggle on={scope === 'company'} onClick={() => setScope('company')}>Организация</Toggle>
              <Toggle on={scope === 'container'} onClick={() => setScope('container')}>Весь контейнер</Toggle>
            </div>
          )}
          {!container && (
            <>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Человек:</span>
                <Select value={userId || 'all'} onValueChange={(v) => setUser(v === 'all' ? '' : v)}>
                  <SelectTrigger className="h-7 w-[190px] text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Все люди</SelectItem>
                    {(membersQ.data ?? []).map((m) => (
                      <SelectItem key={m.id} value={m.id}>{m.name || m.email}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Период:</span>
                <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                  className="h-7 rounded-md border border-input bg-background px-2 text-xs" />
                <span className="text-xs text-muted-foreground">—</span>
                <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                  className="h-7 rounded-md border border-input bg-background px-2 text-xs" />
              </div>
              {hasFilters && (
                <Button size="sm" variant="ghost" className="h-7 gap-1 px-2 text-xs text-muted-foreground"
                  onClick={resetFilters}>
                  <X className="h-3 w-3" /> Сбросить
                </Button>
              )}
            </>
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
              <TableHead className="w-[160px]">
                {container ? 'Когда' : (
                  <button type="button" className="flex items-center gap-1 hover:text-foreground"
                    title="Поменять порядок"
                    onClick={() => setOrder((o) => (o === 'desc' ? 'asc' : 'desc'))}>
                    Когда {order === 'desc'
                      ? <ArrowDownWideNarrow className="h-3.5 w-3.5" />
                      : <ArrowUpNarrowWide className="h-3.5 w-3.5" />}
                  </button>
                )}
              </TableHead>
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
        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            Записей: {shown.length}
            {shown.length !== rows.length ? ` из ${rows.length} загруженных` : ''}
          </p>
          {mayHaveMore && (
            <Button size="sm" variant="outline" className="h-7 px-3 text-xs"
              disabled={companyQ.isFetching}
              onClick={() => setLimit((l) => Math.min(l + PAGE_MORE, 5000))}>
              {companyQ.isFetching && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
              Показать ещё
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
