/**
 * Качество справочника контрагентов — вкладка раздела «Контрагенты».
 *
 * Справочник приезжает из 1С как есть, со всеми болезнями: одно юрлицо двумя
 * карточками, карточка без ИНН, документы, которые ни с кем не связались. Пока это
 * не показано, обороты разреза тихо делятся между дублями, а «его документы»
 * находят половину — и человек этого не замечает, потому что каждый экран по
 * отдельности выглядит правдоподобно.
 *
 * Экран отвечает не «всё плохо», а «вот конкретные строки и что с ними делать»:
 * несведённые документы сводятся кнопкой прямо здесь. Дубли не сливаем — справочник
 * ведут в 1С, и слияние карточек это решение бухгалтера, а не витрины.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, CheckCircle2, Link2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import {
  getCounterpartyQuality, linkDocsToCounterparty, type CpQuality,
} from '@/services/booksService'

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const num = new Intl.NumberFormat('ru-RU')

export function CounterpartyQuality({ onOpen }: { onOpen?: (id: string) => void }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['books', 'cp-quality', companyId],
    queryFn: () => getCounterpartyQuality(companyId),
    enabled: !!companyId,
  })

  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  const d = q.data
  const unlinkedDocs = d.unlinkedDocs.reduce((s, u) => s + u.docs, 0)

  async function link(name: string, candidateId: string) {
    try {
      const r = await linkDocsToCounterparty(companyId, candidateId, name)
      toast.success(`Сведено документов: ${r.linked}`)
      qc.invalidateQueries({ queryKey: ['books'] })
      qc.invalidateQueries({ queryKey: ['references'] })
    } catch {
      toast.error('Не удалось свести документы')
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <Tile label="Документы сведены" ok={d.docsLinked === d.docsWithName}
          value={`${num.format(d.docsLinked)} из ${num.format(d.docsWithName)}`}
          hint={unlinkedDocs ? `${num.format(unlinkedDocs)} без карточки` : 'все с карточкой'} />
        <Tile label="Дубли по ИНН" ok={d.duplicatesByInn.length === 0}
          value={num.format(d.duplicatesByInn.length)}
          hint="одно юрлицо двумя карточками" />
        <Tile label="Дубли по имени" ok={d.duplicatesByName.length === 0}
          value={num.format(d.duplicatesByName.length)}
          hint="совпадают без кавычек и пробелов" />
        <Tile label="Без ИНН" ok={d.withoutInn.length === 0}
          value={num.format(d.withoutInn.length)}
          hint={`пустых карточек: ${num.format(d.emptyCards)}`} />
      </div>

      {d.unlinkedDocs.length > 0 && (
        <Section title="Документы без карточки контрагента"
          note="Имя в документе написано иначе или ИНН не приехал. Кандидат найден по ИНН
                или по имени без кавычек — сведение трогает только документы без ссылки.">
          <table className="w-full text-sm">
            <Head cols={['Имя в документе', 'ИНН', 'Документов', 'Сумма', 'Кандидат', '']} />
            <tbody>
              {d.unlinkedDocs.map((u) => (
                <tr key={u.name} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-3 py-1.5 max-w-[320px] truncate" title={u.name}>{u.name}</td>
                  <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{u.inn ?? '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{u.docs}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                    {money.format(u.amount)} ₽
                  </td>
                  <td className="px-3 py-1.5 max-w-[260px] truncate text-muted-foreground"
                    title={u.candidateName ?? ''}>
                    {u.candidateName ?? 'карточки нет — завести в 1С'}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    {u.candidateId && (
                      <Button size="sm" variant="outline" className="h-6 px-2 text-[11px]"
                        onClick={() => link(u.name, u.candidateId!)}>
                        <Link2 className="size-3 mr-1" /> Свести
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {d.duplicatesByInn.length > 0 && (
        <Section title="Дубли по ИНН"
          note="Заведомо одно юрлицо: обороты и долг делятся между карточками, и ни одна
                не показывает полной картины. Слияние — в 1С, здесь только видно, кого сливать.">
          <table className="w-full text-sm">
            <Head cols={['ИНН', 'Карточки', 'Документов', 'Договоров']} />
            <tbody>
              {d.duplicatesByInn.map((g) => (
                <tr key={g.key} className="border-b last:border-0 align-top">
                  <td className="px-3 py-1.5 tabular-nums">{g.key}</td>
                  <td className="px-3 py-1.5">
                    {g.cards.map((c) => (
                      <button key={c.id} onClick={() => onOpen?.(c.id)}
                        className="block text-left hover:text-primary hover:underline">
                        {c.name}{c.kpp ? ` · КПП ${c.kpp}` : ''}
                      </button>
                    ))}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                    {g.cards.map((c) => <div key={c.id}>{c.docs}</div>)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                    {g.cards.map((c) => <div key={c.id}>{c.contracts}</div>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {d.duplicatesByName.length > 0 && (
        <Section title="Дубли по имени"
          note="Совпадают после снятия кавычек и лишних пробелов. Бывает, что у одной
                карточки ИНН есть, а у другой нет — тогда документы делятся по написанию.">
          <table className="w-full text-sm">
            <Head cols={['Карточки', 'ИНН', 'Документов']} />
            <tbody>
              {d.duplicatesByName.map((g) => (
                <tr key={g.key} className="border-b last:border-0 align-top">
                  <td className="px-3 py-1.5">
                    {g.cards.map((c) => (
                      <button key={c.id} onClick={() => onOpen?.(c.id)}
                        className="block text-left hover:text-primary hover:underline">
                        {c.name}
                      </button>
                    ))}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums text-muted-foreground">
                    {g.cards.map((c) => <div key={c.id}>{c.inn ?? '—'}</div>)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                    {g.cards.map((c) => <div key={c.id}>{c.docs}</div>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {d.withoutInn.length > 0 && (
        <Section title="Карточки без ИНН"
          note="Сводятся с документами только по имени, поэтому легко разъезжаются.
                Показаны те, у кого есть документы, — по ним потеря заметнее всего.">
          <table className="w-full text-sm">
            <Head cols={['Контрагент', 'Документов', 'Сумма']} />
            <tbody>
              {d.withoutInn.filter((c) => c.docs > 0).slice(0, 40).map((c) => (
                <tr key={c.id} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-3 py-1.5">
                    <button onClick={() => onOpen?.(c.id)}
                      className="text-left hover:text-primary hover:underline">{c.name}</button>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{c.docs}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                    {money.format(c.amount)} ₽
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </div>
  )
}

function Tile({ label, value, hint, ok }: {
  label: string; value: string; hint?: string; ok?: boolean
}) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
          {ok
            ? <CheckCircle2 className="size-3.5 text-emerald-500" />
            : <AlertTriangle className="size-3.5 text-amber-500" />}
          {label}
        </div>
        <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
        {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  )
}

function Section({ title, note, children }: {
  title: string; note: string; children: React.ReactNode
}) {
  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <div className="px-3 py-2 border-b">
          <div className="text-sm font-medium">{title}</div>
          <div className="text-[11px] text-muted-foreground">{note}</div>
        </div>
        {children}
      </CardContent>
    </Card>
  )
}

function Head({ cols }: { cols: string[] }) {
  return (
    <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
      <tr className="border-b">
        {cols.map((c, i) => (
          <th key={i} className={`font-normal px-3 py-2 ${i > 1 ? 'text-right' : 'text-left'}`}>
            {c}
          </th>
        ))}
      </tr>
    </thead>
  )
}

export type { CpQuality }
