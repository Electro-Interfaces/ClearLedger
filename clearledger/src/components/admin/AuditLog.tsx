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
import { Fragment, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownWideNarrow, ArrowUpNarrowWide, History, Loader2, X } from 'lucide-react'
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
  'inbound_key.create': 'Выдан входящий ключ', 'inbound_key.revoke': 'Входящий ключ отозван',
}

/** Группы событий: клиентский срез уже загруженного списка. */
const GROUPS: { key: string; label: string; test: (action: string) => boolean }[] = [
  { key: 'all', label: 'Все события', test: () => true },
  { key: 'logins', label: 'Входы', test: (a) => /^(auth\.|sso\.)/.test(a) },
  { key: 'people', label: 'Люди и доступы', test: (a) => /^(role\.|member\.|user\.|department\.)/.test(a) },
]

/** Категория действия задаёт цвет бейджа: журнал читается по цветовым пятнам —
 *  красное «вход отклонён» видно из скролла, не вчитываясь в каждую строку. */
function actionTone(action: string): string {
  if (action === 'auth.login_failed') return 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400'
  if (/^(auth\.|sso\.)/.test(action)) return 'border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-400'
  if (/^(member\.|role\.)/.test(action)) return 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400'
  if (/^(user\.|department\.)/.test(action)) return 'border-primary/40 bg-primary/10 text-primary'
  if (/^space\./.test(action)) return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
  return 'border-border bg-muted/60 text-muted-foreground'
}

/** Ключи внутри details-JSON — по-русски и по делу. */
const DETAIL_KEY: Record<string, string> = {
  set: 'доступ', modules: 'доступ', objects: 'объекты', contracts: 'основание',
  role: 'роль', partyType: 'принадлежность', roleId: 'роль',
}

/**
 * Детали события — словами, а не сырым JSON. Формат в базе: «цель · {json}»
 * (email человека и атрибуты). Длинные списки модулей сворачиваются в «N разделов»
 * — полный список остаётся в подсказке строки.
 */
function humanDetails(details: string | null | undefined): { target: string; note: string; full: string } {
  const raw = (details ?? '').trim()
  if (!raw) return { target: '', note: '', full: '' }
  const [head, ...rest] = raw.split(' · ')
  const jsonPart = rest.join(' · ')
  let target = head
  let note = ''
  const parse = (s: string) => {
    try { return JSON.parse(s) as Record<string, unknown> } catch { return null }
  }
  const obj = jsonPart ? parse(jsonPart) : (head.startsWith('{') ? parse(head) : null)
  if (obj && head.startsWith('{')) target = ''
  if (obj) {
    note = Object.entries(obj).map(([k, v]) => {
      const label = DETAIL_KEY[k] ?? k
      const val = String(v ?? '')
      // «модули: a, b, c, …» — счётчиком: перечень в строке журнала нечитаем.
      const m = val.match(/^модули:\s*(.+)$/)
      if (m) {
        const n = m[1].split(',').length
        return `${label}: ${n} разделов`
      }
      return `${label}: ${val}`
    }).join(' · ')
  } else if (jsonPart) {
    note = jsonPart
  }
  return { target, note, full: raw }
}

/** «31 июля, четверг» — заголовок дня в ленте. */
const dayLabel = (iso: string) => new Date(iso).toLocaleDateString('ru-RU',
  { day: 'numeric', month: 'long', weekday: 'long' })
const dayKey = (iso: string) => iso.slice(0, 10)

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
                {/* Быстрые срезы — прежде календаря: «что было за неделю» спрашивают
                    каждый день, конкретные даты — раз в месяц. */}
                {([['1', 'Сегодня'], ['7', '7 дн'], ['30', '30 дн']] as const).map(([days, label]) => {
                  const from = new Date(Date.now() - (Number(days) - 1) * 86400000).toISOString().slice(0, 10)
                  const on = dateFrom === from && !dateTo
                  return (
                    <Toggle key={days} on={on}
                      onClick={() => { setDateFrom(on ? '' : from); setDateTo('') }}>{label}</Toggle>
                  )
                })}
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
              {shown.map((e, i) => {
                const prev = shown[i - 1]
                const newDay = e.at && (!prev?.at || dayKey(prev.at) !== dayKey(e.at))
                const d = humanDetails(e.details)
                const who = e.who ?? '—'
                const memberId = !container
                  ? (membersQ.data ?? []).find((m) => m.name === e.who || m.email === e.who)?.id
                  : undefined
                return (
                  <Fragment key={e.id}>
                    {/* Лента по дням: дата один раз заголовком, в строках — время. */}
                    {newDay && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={container ? 5 : 4}
                          className="bg-muted/30 py-1.5 text-xs font-medium">
                          {dayLabel(e.at!)}
                        </TableCell>
                      </TableRow>
                    )}
                    <TableRow title={d.full || undefined}>
                      <TableCell className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
                        {e.at ? new Date(e.at).toLocaleTimeString('ru-RU',
                          { hour: '2-digit', minute: '2-digit' }) : '—'}
                      </TableCell>
                      <TableCell>
                        <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-[10px] ${actionTone(e.action)}`}>
                          {ACTION_LABEL[e.action] ?? e.action}
                        </span>
                      </TableCell>
                      {container && (
                        <TableCell className="text-xs text-muted-foreground">{e.company ?? '—'}</TableCell>
                      )}
                      <TableCell className="text-xs">
                        {/* Имя — фильтр: активность сотрудника собирается одним кликом. */}
                        {memberId ? (
                          <button type="button" onClick={() => setUser(memberId)}
                            title={`Показать всю активность: ${who}`}
                            className="text-left hover:text-primary hover:underline">
                            {who}
                          </button>
                        ) : who}
                      </TableCell>
                      <TableCell className="max-w-0 truncate text-xs">
                        {d.target && <span className="text-foreground/90">{d.target}</span>}
                        {d.target && d.note && <span className="text-muted-foreground"> · </span>}
                        {d.note && <span className="text-muted-foreground">{d.note}</span>}
                      </TableCell>
                    </TableRow>
                  </Fragment>
                )
              })}
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
