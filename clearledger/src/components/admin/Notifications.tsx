/**
 * «Управление» → «Оповещения»: о чём сообщать и куда — в чат пространства или на почту.
 *
 * Одна таблица вместо набора форм: строка — категория событий, колонки — включённость и
 * каналы. Получатели по умолчанию — администраторы организации, и это не лень, а решение:
 * список конкретных людей пришлось бы поддерживать руками, и он устаревал бы при каждой
 * смене состава. Явный выбор людей остаётся для случаев, когда оповещения нужны не
 * администраторам.
 *
 * Кнопка «Проверить» отправляет сообщение тем же путём, каким пойдёт настоящее: иначе
 * «настроено» и «дойдёт» — разные вещи, и выясняется это в худший момент.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Bell, ChevronDown, ChevronRight, Loader2, Mail, MessageSquare, Send } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  getNotifyCatalog, listNotifyRules, saveNotifyRules, testNotifyDelivery, type NotifyRule,
} from '@/services/notifyService'
import * as userService from '@/services/userService'

export function Notifications({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const qc = useQueryClient()
  const catalogQ = useQuery({ queryKey: ['notify-catalog'], queryFn: getNotifyCatalog })
  const rulesQ = useQuery({
    queryKey: ['notify-rules', companyId],
    queryFn: () => listNotifyRules(companyId),
  })
  const membersQ = useQuery({
    queryKey: ['team-members', companyId],
    queryFn: () => userService.listUsers(companyId),
    enabled: canManage,
  })

  // Локальная копия: галочки правятся пачкой и уходят одним сохранением — иначе каждый
  // клик был бы запросом, а таблица мигала бы на каждом переключателе.
  const [draft, setDraft] = useState<NotifyRule[]>([])
  const [open, setOpen] = useState<Record<string, boolean>>({})
  useEffect(() => { if (rulesQ.data) setDraft(rulesQ.data) }, [rulesQ.data])

  const save = useMutation({
    mutationFn: () => saveNotifyRules(companyId, draft),
    onSuccess: (saved) => {
      setDraft(saved)
      toast.success('Оповещения сохранены')
      qc.invalidateQueries({ queryKey: ['notify-rules', companyId] })
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const probe = useMutation({
    mutationFn: (category: string) => testNotifyDelivery(companyId, category),
    onSuccess: (r) => {
      if (r.skipped) {
        toast.warning('Оповещение не отправлено', {
          description: r.reason ?? 'категория выключена или каналы не выбраны',
        })
        return
      }
      const ways = [r.chat ? 'чат' : null, r.email ? 'почта' : null].filter(Boolean).join(' и ')
      toast.success(ways ? `Отправлено: ${ways}` : 'Каналы не сработали', {
        description: `Получателей: ${r.recipients ?? 0}`
          + (r.chat === false ? ' · чат недоступен' : '')
          + (r.email === false ? ' · почта не настроена' : ''),
      })
    },
    onError: (e) => toast.error(`Проверка не удалась: ${(e as Error).message}`),
  })

  const cats = catalogQ.data ?? []
  const members = membersQ.data ?? []
  const patch = (category: string, part: Partial<NotifyRule>) =>
    setDraft((d) => d.map((r) => (r.category === category ? { ...r, ...part } : r)))
  const ruleOf = (code: string): NotifyRule =>
    draft.find((r) => r.category === code)
    ?? { category: code, enabled: false, via_chat: true, via_email: false, recipients: null }

  const dirty = JSON.stringify(draft) !== JSON.stringify(rulesQ.data ?? [])

  if (catalogQ.isLoading || rulesQ.isLoading) {
    return <div className="flex items-center gap-2 py-8 text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…</div>
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Bell className="h-5 w-5" /> Что сообщать</CardTitle>
        <CardDescription>
          События пространства уходят в чат организации (комната «Оповещения», её создаёт
          система) и письмом. Источник — журнал событий, поэтому подписка не может ссылаться
          на то, чего система не пишет.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <Table className="min-w-[820px]">
            <TableHeader>
              <TableRow>
                <TableHead>Категория</TableHead>
                <TableHead className="w-[110px]">Сообщать</TableHead>
                <TableHead className="w-[90px]">В чат</TableHead>
                <TableHead className="w-[110px]">На почту</TableHead>
                <TableHead className="w-[230px]">Кому</TableHead>
                <TableHead className="w-[120px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {cats.map((c) => {
                const r = ruleOf(c.code)
                const custom = !!r.recipients?.length
                const expanded = !!open[c.code]
                return [
                  <TableRow key={c.code} className={r.enabled ? undefined : 'opacity-60'}>
                    <TableCell>
                      <div className="font-medium">{c.label}</div>
                      <div className="text-xs text-muted-foreground">{c.description}</div>
                    </TableCell>
                    <TableCell>
                      <Switch checked={r.enabled} disabled={!canManage}
                        onCheckedChange={(v) => patch(c.code, { enabled: v })} />
                    </TableCell>
                    <TableCell>
                      <Switch checked={r.via_chat} disabled={!canManage || !r.enabled}
                        onCheckedChange={(v) => patch(c.code, { via_chat: v })} />
                    </TableCell>
                    <TableCell>
                      <Switch checked={r.via_email} disabled={!canManage || !r.enabled}
                        onCheckedChange={(v) => patch(c.code, { via_email: v })} />
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs"
                        disabled={!canManage}
                        onClick={() => setOpen((o) => ({ ...o, [c.code]: !o[c.code] }))}>
                        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                        {custom ? `выбрано: ${r.recipients!.length}` : 'администраторы'}
                      </Button>
                    </TableCell>
                    <TableCell>
                      <Button variant="outline" size="sm" className="h-7 gap-1 px-2 text-xs"
                        disabled={!r.enabled || probe.isPending}
                        onClick={() => probe.mutate(c.code)}>
                        {probe.isPending && probe.variables === c.code
                          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          : <Send className="h-3.5 w-3.5" />}
                        Проверить
                      </Button>
                    </TableCell>
                  </TableRow>,
                  expanded && (
                    <TableRow key={`${c.code}-who`} className="bg-muted/30 hover:bg-muted/30">
                      <TableCell colSpan={6} className="py-3">
                        <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                          Пусто — администраторы организации (список следует за составом).
                          Отметьте людей, если оповещения нужны не им.
                          {custom && (
                            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs"
                              onClick={() => patch(c.code, { recipients: null })}>
                              Вернуть администраторов
                            </Button>
                          )}
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {members.map((m) => {
                            const on = !!r.recipients?.includes(m.id)
                            return (
                              <Button key={m.id} type="button" size="sm"
                                variant={on ? 'secondary' : 'outline'}
                                className="h-7 px-2 text-xs"
                                onClick={() => {
                                  const cur = new Set(r.recipients ?? [])
                                  on ? cur.delete(m.id) : cur.add(m.id)
                                  patch(c.code, { recipients: [...cur] })
                                }}>
                                {m.name || m.email}
                              </Button>
                            )
                          })}
                          {members.length === 0 && (
                            <span className="text-xs text-muted-foreground">Участников нет</span>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ),
                ]
              })}
            </TableBody>
          </Table>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          {canManage && (
            <Button size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              Сохранить
            </Button>
          )}
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <MessageSquare className="h-3.5 w-3.5" /> чат — комната «Оповещения»
            <Mail className="ml-2 h-3.5 w-3.5" /> почта — SMTP пространства
          </span>
          {!dirty && rulesQ.data && (
            <Badge variant="outline" className="text-[10px]">сохранено</Badge>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
