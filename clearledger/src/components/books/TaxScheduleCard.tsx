/**
 * Сроки по режиму и взносы ИП.
 *
 * Дополняет календарь из 1С, а не заменяет его: тот показывает задачи, которые
 * завёл бухгалтер, а этот — обязанности, вытекающие из режима. Они существуют
 * независимо от того, вспомнил о них человек (docs/TAXES.md §7).
 *
 * Взносы стоят здесь же, потому что это одна тема: уплаченные взносы уменьшают
 * налог УСН «Доходы» и патента, иногда до нуля. Разносить «сколько платить» и
 * «что уже уплачено» по разным экранам значит заставлять сверять их в уме.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Wallet, Plus, Trash2, AlertTriangle, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCompany } from '@/contexts/CompanyContext'
import { get, post, del } from '@/services/apiClient'
import { cn } from '@/lib/utils'

interface ScheduleItem {
  due: string; title: string; kind: string; regime: string | null
  note: string | null; state: string
}

interface Schedule {
  year: number
  organization: { id: string; name: string; legalForm: string | null } | null
  regime: { code: string; short: string; combined: string[] } | null
  items: ScheduleItem[]
  next: ScheduleItem | null
  note?: string
}

interface Contributions {
  year: number
  income: number
  due: {
    known: boolean; fixed?: number; extra?: number; total?: number; paid?: number
    confidence?: string; note?: string | null
  }
  payments: { id: string; kind: string; amount: number; paidOn: string; note: string | null }[]
}

const money = (v: number) =>
  `${v.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽`
const ruDate = (s: string) => s.split('-').reverse().join('.')

const KIND_LABEL: Record<string, string> = {
  payment: 'уплата', report: 'отчёт', notice: 'уведомление',
}

export function TaxScheduleCard({ organizationId }: { organizationId: string }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const year = new Date().getFullYear()
  const [pay, setPay] = useState({ amount: '', paidOn: '', kind: 'fixed' })

  const schedule = useQuery({
    queryKey: ['tax-schedule', companyId, organizationId, year],
    queryFn: () => get<Schedule>('/api/books/tax-schedule',
      { company_id: companyId, organization_id: organizationId, year }),
    enabled: !!organizationId,
  })

  const contrib = useQuery({
    queryKey: ['tax-contributions', companyId, organizationId, year],
    queryFn: () => get<Contributions>(
      `/api/books/organizations/${organizationId}/contributions`,
      { company_id: companyId, year }),
    // Взносы платит ИП за себя: у юрлица этого раздела нет вовсе.
    enabled: !!organizationId && schedule.data?.organization?.legalForm === 'ip',
  })

  const addPay = useMutation({
    mutationFn: () => post(
      `/api/books/organizations/${organizationId}/contributions?company_id=${companyId}`,
      { kind: pay.kind, amount: Number(pay.amount), paid_on: pay.paidOn, year }),
    onSuccess: () => {
      toast.success('Взнос записан — налог уменьшится на уплаченное')
      setPay({ amount: '', paidOn: '', kind: 'fixed' })
      qc.invalidateQueries({ queryKey: ['tax-contributions'] })
      qc.invalidateQueries({ queryKey: ['books'] })
    },
    onError: () => toast.error('Не удалось записать взнос'),
  })

  const syncPay = useMutation({
    mutationFn: () => post<{ found: number; added: number; note: string }>(
      `/api/books/organizations/${organizationId}/contributions/sync?company_id=${companyId}&year=${year}`,
      {}),
    onSuccess: (r) => {
      toast.success(r.added ? `Забрано платежей: ${r.added}` : 'Новых платежей нет',
        { description: r.note })
      qc.invalidateQueries({ queryKey: ['tax-contributions'] })
    },
    onError: () => toast.error('Не удалось забрать взносы из учёта'),
  })

  const dropPay = useMutation({
    mutationFn: (id: string) =>
      del(`/api/books/contributions/${id}?company_id=${companyId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tax-contributions'] }),
  })

  const d = schedule.data
  const c = contrib.data
  // Показываем ближайшие сроки, а не весь год: список из 21 даты никто не читает.
  const ahead = (d?.items ?? []).filter((i) => i.state !== 'прошёл').slice(0, 6)
  const passed = (d?.items ?? []).filter((i) => i.state === 'прошёл').length

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0 gap-3">
        <div className="space-y-1.5">
          <CardTitle className="flex items-center gap-2">
            <CalendarClock className="h-5 w-5" /> Сроки и взносы
          </CardTitle>
          <CardDescription>
            Обязанности, вытекающие из режима, — независимо от задач в 1С
          </CardDescription>
        </div>
        {d?.regime && (
          <Badge variant="secondary" className="shrink-0">{d.regime.short}</Badge>
        )}
      </CardHeader>

      <CardContent className="space-y-5">
        {d?.note && (
          <p className="text-[13px] text-muted-foreground">{d.note}</p>
        )}

        {/* Ближайшие сроки */}
        {ahead.length > 0 && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Впереди
              </span>
              <span className="text-[11px] text-muted-foreground">
                за год {d!.items.length} · прошло {passed}
              </span>
            </div>
            <div className="divide-y divide-border/60 rounded-lg border border-border">
              {ahead.map((i, n) => (
                <div key={`${i.due}-${n}`}
                  className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[13px]">
                  <span className="min-w-0">
                    <span className="font-medium">{i.title}</span>
                    <span className="ml-2 text-[11px] text-muted-foreground">
                      {KIND_LABEL[i.kind] ?? i.kind}
                    </span>
                  </span>
                  <span className={cn('tabular-nums',
                    i.state === 'на этой неделе' ? 'font-medium text-amber-600 dark:text-amber-400'
                      : 'text-muted-foreground')}>
                    {ruDate(i.due)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Взносы ИП: сколько должен, что уплачено, чем уменьшается налог */}
        {c && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              <Wallet className="size-3.5" /> Взносы за {c.year} год
            </div>

            {c.due.known ? (
              <>
                <div className="grid gap-2 sm:grid-cols-3">
                  <Tile label="Фиксированные" value={money(c.due.fixed ?? 0)} />
                  <Tile label="1 % свыше 300 тыс." value={money(c.due.extra ?? 0)}
                    hint={`доход ${money(c.income)}`} />
                  <Tile label="Уплачено" value={money(c.due.paid ?? 0)}
                    hint={`из ${money(c.due.total ?? 0)}`} />
                </div>

                {/* Надёжность цифры видна всегда: суммы будущего года публикуют
                    заранее, но правят, и выдавать их за окончательные нельзя. */}
                {c.due.confidence !== 'law' && (
                  <div className="flex items-start gap-2 rounded-lg border border-amber-500/40
                                  bg-amber-500/5 px-3 py-2 text-[12px]">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
                    <span>{c.due.note ?? 'Суммы года требуют сверки с законом.'}</span>
                  </div>
                )}

                <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">Сумма платежа</Label>
                    <Input value={pay.amount} placeholder={String(c.due.fixed ?? '')}
                      onChange={(e) => setPay({ ...pay, amount: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">Дата уплаты</Label>
                    <Input type="date" value={pay.paidOn}
                      onChange={(e) => setPay({ ...pay, paidOn: e.target.value })} />
                  </div>
                  <div className="flex gap-2 self-end">
                    <Button disabled={!pay.amount || !pay.paidOn || addPay.isPending}
                      onClick={() => addPay.mutate()}>
                      <Plus className="mr-1 size-4" />Записать
                    </Button>
                    {/* Платёж уже есть в проводках (счёт 69.06): просить ввести его
                        второй раз значит заводить второй источник правды. */}
                    <Button variant="outline" disabled={syncPay.isPending}
                      onClick={() => syncPay.mutate()} title="Забрать платежи из проводок">
                      <RefreshCw className={cn('size-4', syncPay.isPending && 'animate-spin')} />
                    </Button>
                  </div>
                </div>

                {c.payments.length > 0 && (
                  <div className="divide-y divide-border/60 rounded-lg border border-border">
                    {c.payments.map((p) => (
                      <div key={p.id}
                        className="flex items-center justify-between gap-2 px-3 py-2 text-[13px]">
                        <span className="text-muted-foreground">{ruDate(p.paidOn)}</span>
                        <span className="flex items-center gap-3">
                          <span className="tabular-nums">{money(p.amount)}</span>
                          <Button size="icon" variant="ghost" className="size-8"
                            onClick={() => dropPay.mutate(p.id)}>
                            <Trash2 className="size-4 text-muted-foreground" />
                          </Button>
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                <p className="text-[12px] leading-relaxed text-muted-foreground">
                  Налог УСН «Доходы» и патента уменьшается на уплаченные взносы — по
                  дате платежа, а не начисления. На «Доходы минус расходы» взносы
                  уже входят в расходы, и второй раз не вычитаются.
                </p>
              </>
            ) : (
              <p className="text-[12px] text-muted-foreground">
                {c.due.note ?? 'Сумм взносов за этот год в справочнике нет.'}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-medium tabular-nums">{value}</div>
      {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  )
}
