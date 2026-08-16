/**
 * Система налогообложения организации.
 *
 * Не настройка интерфейса, а основание расчёта: от режима зависит, какой налог
 * считать и с какой базы (docs/TAXES.md). До этого экрана режим правился прямо в
 * базе, а «Бухгалтерия» считала всем ОСНО — и показывала упрощенцу налог на
 * прибыль, которого он не платит.
 *
 * Смена режима не переписывает прошлое: прежняя запись закрывается днём раньше
 * новой, и налог прошлых периодов остаётся посчитанным по тогдашним правилам.
 * Поэтому здесь виден не «текущий режим», а история с датами.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Scale, Plus, Trash2, Info } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { get, post, put, del } from '@/services/apiClient'

interface Regime {
  code: string; name: string; short: string; object: string | null
  paysVat: boolean; paysProfitTax: boolean; combinable: boolean
  rate: number | null; limitIncome: number | null; note: string | null
}

interface OrgTax {
  organization: { id: string; name: string; legalForm: string | null }
  current: {
    code: string; name: string; short: string; rate: number | null
    paysVat: boolean; source: string | null; combined: string[]
  } | null
  history: {
    id: string; code: string; short: string; from: string; to: string | null
    rate: number | null; isPrimary: boolean; source: string | null
  }[]
  patents: {
    id: string; number: string | null; activity: string
    from: string; to: string; cost: number; paid: number
  }[]
}

const money = (v: number) => `${v.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽`
const ruDate = (s: string) => s.split('-').reverse().join('.')

/** Откуда система знает режим: догадка по учёту — не то же, что решение человека. */
const SOURCE_LABEL: Record<string, string> = {
  detected: 'определено по учёту',
  manual: 'указано вручную',
  '1c': 'из выгрузки 1С',
}

export function TaxRegimeCard({ organizationId }: { organizationId: string }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [code, setCode] = useState('')
  const [from, setFrom] = useState(() => `${new Date().getFullYear()}-01-01`)
  const [rate, setRate] = useState('')
  const [patentOpen, setPatentOpen] = useState(false)
  const [patent, setPatent] = useState({ activity: '', from: '', to: '', cost: '' })

  const tax = useQuery({
    queryKey: ['org-tax', companyId, organizationId],
    queryFn: () => get<OrgTax>(`/api/books/organizations/${organizationId}/tax`,
      { company_id: companyId }),
    enabled: !!organizationId,
  })

  const form = tax.data?.organization.legalForm ?? undefined
  const catalog = useQuery({
    queryKey: ['tax-regimes', companyId, form],
    queryFn: () => get<{ regimes: Regime[] }>('/api/books/tax-regimes',
      { company_id: companyId, ...(form ? { legal_form: form } : {}) }),
  })

  const save = useMutation({
    // company_id уходит строкой запроса: put/post клиента принимают только тело.
    mutationFn: () => put(
      `/api/books/organizations/${organizationId}/tax?company_id=${companyId}`,
      { regime_code: code, valid_from: from,
        rate: rate ? Number(rate) : null, is_primary: true }),
    onSuccess: () => {
      toast.success('Режим сохранён — налоги пересчитаются по нему')
      setCode(''); setRate('')
      qc.invalidateQueries({ queryKey: ['org-tax'] })
      qc.invalidateQueries({ queryKey: ['books'] })
    },
    onError: () => toast.error('Не удалось сохранить режим'),
  })

  const addPatent = useMutation({
    mutationFn: () => post(
      `/api/books/organizations/${organizationId}/patents?company_id=${companyId}`,
      { activity: patent.activity, valid_from: patent.from, valid_to: patent.to,
        cost: patent.cost ? Number(patent.cost) : null }),
    onSuccess: () => {
      toast.success('Патент заведён')
      setPatent({ activity: '', from: '', to: '', cost: '' }); setPatentOpen(false)
      qc.invalidateQueries({ queryKey: ['org-tax'] })
    },
    onError: () => toast.error('Не удалось завести патент'),
  })

  const dropPatent = useMutation({
    mutationFn: (id: string) => del(`/api/books/patents/${id}?company_id=${companyId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['org-tax'] }),
  })

  const d = tax.data
  const chosen = catalog.data?.regimes.find((r) => r.code === code)
  // Патенты показываем там, где они возможны: у юрлица их не бывает вовсе.
  const patentsAllowed = form === 'ip' || d?.current?.code === 'psn'
    || d?.current?.combined.includes('psn')

  // Льготные ставки субъектов: регион вправе снижать УСН до 1 % и 5 %, и считать
  // по федеральной там, где действует региональная, значит завышать налог.
  // Виды деятельности патента: перечень закрытый (ст. 346.43 НК), и свободный
  // текст здесь означал два патента на одно и то же под разными именами.
  const activities = useQuery({
    queryKey: ['patent-activities', companyId],
    queryFn: () => get<{ groups: { name: string; items: { code: number; name: string }[] }[] }>(
      '/api/books/patent-activities', { company_id: companyId }),
    enabled: patentsAllowed,
  })

  const regionRates = useQuery({
    queryKey: ['tax-region-rates', companyId, code],
    queryFn: () => get<{ rates: { region: string; rate: number; condition: string | null }[] }>(
      '/api/books/tax-region-rates', { company_id: companyId, regime_code: code }),
    enabled: !!code,
  })

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0 gap-3">
        <div className="space-y-1.5">
          <CardTitle className="flex items-center gap-2">
            <Scale className="h-5 w-5" /> Система налогообложения
          </CardTitle>
          <CardDescription>
            От неё зависит, какой налог считается и с какой базы
          </CardDescription>
        </div>
        {d?.current && (
          <Badge variant="secondary" className="shrink-0">
            {d.current.short}{d.current.rate ? ` · ${d.current.rate} %` : ''}
          </Badge>
        )}
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Действующий режим и откуда он известен. Источник виден всегда: догадка
            системы по проводкам не должна выдаваться за решение бухгалтера. */}
        <div className="rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-[13px]">
          {d?.current ? (
            <>
              <div className="font-medium">{d.current.name}</div>
              <div className="mt-0.5 text-muted-foreground">
                {d.current.paysVat ? 'плательщик НДС' : 'без НДС'}
                {d.current.source ? ` · ${SOURCE_LABEL[d.current.source] ?? d.current.source}` : ''}
                {d.current.combined.length > 0 ? ` · совмещается: ${d.current.combined.join(', ')}` : ''}
              </div>
            </>
          ) : (
            <div className="flex items-start gap-2 text-muted-foreground">
              <Info className="mt-0.5 h-4 w-4 shrink-0" />
              Режим не указан — налоги по этой организации не считаются. Выберите
              систему ниже: подставлять общую за вас система не станет, иначе на
              экране появится налог, которого может не быть.
            </div>
          )}
        </div>

        {/* Смена режима */}
        <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto_auto] sm:items-end">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Режим</Label>
            <Select value={code} onValueChange={setCode}>
              <SelectTrigger><SelectValue placeholder="Выберите систему" /></SelectTrigger>
              <SelectContent>
                {(catalog.data?.regimes ?? []).map((r) => (
                  <SelectItem key={r.code} value={r.code}>
                    <span className="flex flex-col items-start leading-tight">
                      <span>{r.name}</span>
                      <span className="text-[11px] text-muted-foreground">
                        {r.rate ? `${r.rate} %` : '—'}
                        {r.paysVat ? ' · с НДС' : ''}
                        {r.limitIncome ? ` · предел ${money(r.limitIncome)}` : ''}
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Действует с</Label>
            <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
              className="w-[150px]" />
          </div>
          <div className="space-y-1.5">
            {/* Региональная ставка: субъекты снижают УСН до 1 % и 5 %, и без этого
                поля система считала бы по федеральной — то есть завышала налог. */}
            <Label className="text-xs text-muted-foreground">Ставка, %</Label>
            <Input value={rate} onChange={(e) => setRate(e.target.value)}
              placeholder={chosen?.rate ? String(chosen.rate) : '—'} className="w-[90px]" />
          </div>
          <Button disabled={!code || save.isPending} onClick={() => save.mutate()}>
            Сохранить
          </Button>
        </div>
        {chosen?.note && (
          <p className="text-[12px] leading-relaxed text-muted-foreground">{chosen.note}</p>
        )}

        {/* Подсказка по регионам — именно подсказка: субъекты меняют ставки своими
            законами, полного списка у нас нет и не будет. Ввести можно любую. */}
        {(regionRates.data?.rates.length ?? 0) > 0 && (
          <div className="rounded-lg border border-dashed px-3 py-2 text-[12px]">
            <div className="mb-1 font-medium">Льготные ставки регионов</div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
              {regionRates.data!.rates.slice(0, 8).map((r, i) => (
                <button key={i} type="button" className="hover:text-primary hover:underline"
                  onClick={() => setRate(String(r.rate))}>
                  {r.region} — {r.rate} %
                  {r.condition ? ` (${r.condition})` : ''}
                </button>
              ))}
            </div>
            <div className="mt-1 text-[11px] text-muted-foreground/80">
              Список неполный: проверьте закон своего субъекта. Нажмите, чтобы подставить.
            </div>
          </div>
        )}

        {/* История: по ней видно, каким режимом считался прошлый период. */}
        {(d?.history.length ?? 0) > 0 && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              История
            </div>
            <div className="divide-y divide-border/60 rounded-lg border border-border">
              {d!.history.map((h) => (
                <div key={h.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[13px]">
                  <span>
                    {h.short}{h.rate ? ` · ${h.rate} %` : ''}
                    {!h.isPrimary && <span className="ml-1.5 text-muted-foreground">(совмещаемый)</span>}
                  </span>
                  <span className="text-muted-foreground">
                    с {ruDate(h.from)}{h.to ? ` по ${ruDate(h.to)}` : ' — действует'}
                    {h.source ? ` · ${SOURCE_LABEL[h.source] ?? h.source}` : ''}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Патенты: своя сущность, а не свойство режима — их несколько, у каждого
            свой срок и стоимость, и для «Экономики» это расход периода. */}
        {patentsAllowed && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Патенты
              </div>
              <Button size="sm" variant="outline" onClick={() => setPatentOpen((v) => !v)}>
                <Plus className="mr-1 size-4" />{patentOpen ? 'Свернуть' : 'Патент'}
              </Button>
            </div>

            {patentOpen && (
              <div className="grid gap-2 rounded-lg border border-dashed p-3 sm:grid-cols-4">
                <Select value={patent.activity}
                  onValueChange={(v) => setPatent({ ...patent, activity: v })}>
                  <SelectTrigger className="sm:col-span-2">
                    <SelectValue placeholder="Вид деятельности по НК" />
                  </SelectTrigger>
                  <SelectContent className="max-h-[320px]">
                    {(activities.data?.groups ?? []).map((g) => (
                      <div key={g.name}>
                        <div className="px-2 py-1.5 text-[11px] uppercase tracking-wider
                                        text-muted-foreground">{g.name}</div>
                        {g.items.map((a) => (
                          <SelectItem key={a.code} value={a.name}>
                            <span className="text-[13px]">{a.name}</span>
                          </SelectItem>
                        ))}
                      </div>
                    ))}
                  </SelectContent>
                </Select>
                <Input type="date" value={patent.from}
                  onChange={(e) => setPatent({ ...patent, from: e.target.value })} />
                <Input type="date" value={patent.to}
                  onChange={(e) => setPatent({ ...patent, to: e.target.value })} />
                <Input placeholder="Стоимость, ₽" value={patent.cost}
                  onChange={(e) => setPatent({ ...patent, cost: e.target.value })} />
                <Button className="sm:col-span-2"
                  disabled={!patent.activity || !patent.from || !patent.to || addPatent.isPending}
                  onClick={() => addPatent.mutate()}>
                  Завести патент
                </Button>
              </div>
            )}

            {(d?.patents.length ?? 0) > 0 ? (
              <div className="divide-y divide-border/60 rounded-lg border border-border">
                {d!.patents.map((p) => (
                  <div key={p.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[13px]">
                    <span className="min-w-0">
                      <span className="font-medium">{p.activity}</span>
                      <span className="ml-2 text-muted-foreground">
                        {ruDate(p.from)} — {ruDate(p.to)}
                      </span>
                    </span>
                    <span className="flex items-center gap-3">
                      <span className="tabular-nums">{money(p.cost)}</span>
                      <Button size="icon" variant="ghost" className="size-8"
                        onClick={() => dropPatent.mutate(p.id)}>
                        <Trash2 className="size-4 text-muted-foreground" />
                      </Button>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[12px] text-muted-foreground">
                Патентов нет. Стоимость патента — расход периода, известный заранее:
                заведите его, и он попадёт в налоги и «Экономику».
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
