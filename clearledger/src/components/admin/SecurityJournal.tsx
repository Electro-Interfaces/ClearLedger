/**
 * «Безопасность» — журнал враждебных действий снаружи и блокировки адресов
 * (МАГ 07.10.2026: «фиксировать такие действия третьих лиц и поставить тревоги»).
 *
 * Данные пишет `server/app/guard.py`: ловушки для сканеров, инструменты взлома,
 * шквал отказов, подбор пароля, массовая выкачка. Тревога по тем же эпизодам уходит
 * письмом, в чат «Секретаря» и в Telegram; здесь — разбор и снятие блокировки.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, ShieldAlert, Unlock } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { get, post } from '@/services/apiClient'

interface SecEvent { id: string; at: string; kind: string; label: string; ip: string; path: string; userAgent: string | null; hits: number; detail: string | null }
interface SecEvents { events: SecEvent[]; byKind: { kind: string; label: string; count: number }[]; byIp: { ip: string; count: number; last: string }[] }
interface SecBlock { id: string; ip: string; until: string; reason: string; createdAt: string; active: boolean; liftedAt: string | null; liftedBy: string | null }

const dt = (s: string) => new Date(s).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

export function SecurityJournal() {
  const qc = useQueryClient()
  const [days, setDays] = useState(7)
  const [kind, setKind] = useState<string | null>(null)
  const [ip, setIp] = useState<string | null>(null)
  const ev = useQuery({ queryKey: ['security-events', days], queryFn: () => get<SecEvents>('/api/security/events', { days: String(days) }), refetchInterval: 60_000 })
  const bl = useQuery({ queryKey: ['security-blocks'], queryFn: () => get<{ blocks: SecBlock[] }>('/api/security/blocks'), refetchInterval: 60_000 })
  const lift = useMutation({
    mutationFn: (id: string) => post(`/api/security/blocks/${id}/lift`, {}),
    onSuccess: async () => { toast.success('Блокировка снята — адрес пускается в течение 30 секунд'); await qc.invalidateQueries({ queryKey: ['security-blocks'] }) },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось снять'),
  })
  if (ev.isLoading) return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  if (ev.isError || !ev.data) return <Card><CardContent className="py-6 text-sm">Журнал не загрузился: {ev.error instanceof Error ? ev.error.message : 'нет связи'}</CardContent></Card>
  const rows = ev.data.events.filter((e) => (!kind || e.kind === kind) && (!ip || e.ip === ip))
  const active = (bl.data?.blocks ?? []).filter((b) => b.active)

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-base"><ShieldAlert className="h-4 w-4" />Безопасность пространства</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="text-xs text-muted-foreground">
            Враждебные действия снаружи: обращения к ловушкам (сканеры ищут <code>.env</code>, <code>.git</code>, WordPress), инструменты взлома, шквал отказов,
            подбор пароля к учётной записи, массовая выкачка данных. Ловушка и инструмент взлома закрывают адрес для API на час; тревога уходит
            письмом, в чат «Секретаря» и в Telegram — по одному эпизоду (вид + адрес) не чаще раза в час.
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            {[1, 7, 30].map((d) => <Button key={d} size="sm" variant={days === d ? 'default' : 'outline'} onClick={() => setDays(d)}>{d === 1 ? 'Сутки' : `${d} дней`}</Button>)}
            <span className="mx-2 h-4 w-px bg-border" />
            <Button size="sm" variant={kind == null ? 'default' : 'outline'} onClick={() => setKind(null)}>Все {ev.data.byKind.reduce((a, k) => a + k.count, 0)}</Button>
            {ev.data.byKind.map((k) => <Button key={k.kind} size="sm" variant={kind === k.kind ? 'default' : 'outline'} title={k.label} onClick={() => setKind(k.kind)}>{k.label.split(' (')[0].split(' — ')[0]} {k.count}</Button>)}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Блокировки адресов · действует {active.length}</CardTitle></CardHeader>
        <CardContent>
          {(bl.data?.blocks ?? []).length === 0 ? <p className="text-sm text-muted-foreground">За неделю блокировок не было.</p>
            : <div className="overflow-x-auto"><table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground"><tr className="text-left"><th className="py-1 pr-3">Адрес</th><th className="pr-3">Причина</th><th className="pr-3">С</th><th className="pr-3">До</th><th /></tr></thead>
              <tbody>{(bl.data?.blocks ?? []).map((b) => (
                <tr key={b.id} className={`border-t ${b.active ? '' : 'text-muted-foreground'}`}>
                  <td className="py-1.5 pr-3 font-mono text-xs">{b.ip}</td>
                  <td className="pr-3">{b.reason}</td>
                  <td className="pr-3 whitespace-nowrap">{dt(b.createdAt)}</td>
                  <td className="pr-3 whitespace-nowrap">{b.liftedAt ? `снята ${dt(b.liftedAt)}${b.liftedBy ? ` · ${b.liftedBy}` : ''}` : dt(b.until)}</td>
                  <td className="text-right">{b.active && <Button size="sm" variant="outline" disabled={lift.isPending} onClick={() => lift.mutate(b.id)}><Unlock className="mr-1 h-3.5 w-3.5" />Снять</Button>}</td>
                </tr>))}</tbody></table></div>}
        </CardContent>
      </Card>

      {ev.data.byIp.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Чаще всего · адреса</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-1.5">
            {ip && <Button size="sm" variant="ghost" onClick={() => setIp(null)}>сбросить</Button>}
            {ev.data.byIp.map((r) => <Button key={r.ip} size="sm" variant={ip === r.ip ? 'default' : 'outline'} className="font-mono text-xs" title={`последний эпизод ${dt(r.last)}`} onClick={() => setIp(ip === r.ip ? null : r.ip)}>{r.ip} · {r.count}</Button>)}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Эпизоды · {rows.length}</CardTitle></CardHeader>
        <CardContent>
          {rows.length === 0 ? <p className="text-sm text-muted-foreground">За период эпизодов нет.</p>
            : <div className="overflow-x-auto"><table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground"><tr className="text-left"><th className="py-1 pr-3">Когда</th><th className="pr-3">Что</th><th className="pr-3">Адрес</th><th className="pr-3">Путь</th><th>Подробно</th></tr></thead>
              <tbody>{rows.map((e) => (
                <tr key={e.id} className="border-t align-top">
                  <td className="py-1.5 pr-3 whitespace-nowrap">{dt(e.at)}</td>
                  <td className="pr-3">{e.label}</td>
                  <td className="pr-3 font-mono text-xs">{e.ip}</td>
                  <td className="pr-3 max-w-64 truncate font-mono text-xs" title={e.path}>{e.path}</td>
                  <td className="max-w-80 truncate text-xs text-muted-foreground" title={[e.detail, e.userAgent].filter(Boolean).join('\n')}>{e.detail ?? e.userAgent ?? (e.hits > 1 ? `${e.hits} запросов` : '')}</td>
                </tr>))}</tbody></table></div>}
        </CardContent>
      </Card>
    </div>
  )
}
