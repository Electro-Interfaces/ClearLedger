/**
 * «Сверка с оператором связи» — детализация оператора против журнала узла.
 *
 * Узел сопоставляет звонки по номеру и началу ±60 с и находит три вида расхождений:
 * звонок есть у оператора, но узел его не видел (потеря), звонок есть только у узла
 * и длительность расходится больше чем на 5 с. Файл узел не хранит: остаются итог и
 * расхождения, номер — последними четырьмя цифрами. Выбранная сверка — в адресе
 * (`?id=`): на неё ссылаются «Отчёт за месяц» и журнал доступа.
 */
import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { FileSpreadsheet, Upload, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { когда, ктоСделал, объём, сек, число } from './format'
import { Heading, NodeError, Stat } from './parts'

const ПРЕДЕЛ_БАЙТ = 10 * 1024 * 1024

const ФОРМАТ: Record<voice.ReconciliationFormat, string> = {
  megafon_csv: 'МегаФон — «Детализация» (CSV)',
  generic_csv: 'Любой оператор — CSV по заголовкам',
}

const ВИД: Record<voice.ReconciliationItem['kind'], string> = {
  only_carrier: 'Нет у узла',
  only_node: 'Нет у оператора',
  duration: 'Длительность',
}

const ПОЯСНЕНИЕ: Record<voice.ReconciliationItem['kind'], string> = {
  only_carrier: 'оператор связи звонок провёл, а узел его не видел — потеря',
  only_node: 'узел звонок видел, а в детализации его нет',
  duration: 'разговор у оператора и у узла длился по-разному, больше чем на 5 с',
}

const день = (iso?: string) => (iso ? new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—')
const период = (r: voice.Reconciliation) => `${день(r.period?.from)} – ${день(r.period?.to)}`

export default function VoiceReconcilePage() {
  const { companyId } = useCompany()
  const [параметры, setПараметры] = useSearchParams()
  const выбрана = параметры.get('id')
  const список = useQuery({
    queryKey: ['voice-reconciliations', companyId],
    queryFn: () => voice.reconciliations(companyId),
  })

  function открыть(id: string | null) {
    const p = new URLSearchParams(параметры)
    if (id) p.set('id', id); else p.delete('id')
    setПараметры(p, { replace: true })
  }

  const сверки = список.data?.items ?? []

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Сверка с оператором связи"
        подпись="Детализация оператора против журнала узла: потерянные звонки и расхождения длительности. Файл узел не хранит — только итог и расхождения." />

      <UploadForm onDone={id => открыть(id)} />

      {выбрана && <Result id={выбрана} onClose={() => открыть(null)} />}

      <section aria-label="Сверки" className="min-w-0 space-y-2 rounded-xl border border-border bg-card p-4">
        <h2 className="font-headline text-base font-semibold">Сверки</h2>
        {список.isLoading && <p role="status" className="text-sm">Читаем сверки у узла…</p>}
        {список.isError && <NodeError ошибка={список.error} что="прочитать сверки" />}
        {список.isSuccess && !сверки.length && (
          <EmptyBlock иконка={FileSpreadsheet} текст="Сверок пока не было"
            подсказка="Загрузите детализацию входящих звонков из личного кабинета оператора связи — узел покажет, какие звонки он не видел." />
        )}
        {!!сверки.length && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="whitespace-nowrap py-1 font-normal">Период</th>
                  <th className="whitespace-nowrap py-1 pl-3 font-normal">Загружено</th>
                  <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">У оператора</th>
                  <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Совпало</th>
                  <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Нет у узла</th>
                  <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Нет у оператора</th>
                  <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Длительность</th>
                  <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Не разобрано</th>
                </tr>
              </thead>
              <tbody>
                {сверки.map(с => (
                  <tr key={с.id} className={cn('border-t border-border/60', с.id === выбрана && 'bg-primary/5')}>
                    <td className="whitespace-nowrap py-1.5">
                      <button type="button" onClick={() => открыть(с.id)} className="text-primary underline-offset-2 hover:underline">
                        {период(с)}
                      </button>
                    </td>
                    <td className="py-1.5 pl-3 text-xs text-muted-foreground">
                      {когда(с.uploadedAt)}{с.uploadedBy && `, ${ктоСделал(с.uploadedBy)}`}
                    </td>
                    <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(с.carrierRows)}</td>
                    <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(с.matched)}</td>
                    <td className={cn('whitespace-nowrap py-1.5 pl-3 text-right tabular-nums', (с.onlyCarrier ?? 0) > 0 && 'font-medium text-destructive')}>{число(с.onlyCarrier)}</td>
                    <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(с.onlyNode)}</td>
                    <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(с.durationMismatch)}</td>
                    <td className={cn('whitespace-nowrap py-1.5 pl-3 text-right tabular-nums', (с.badRows ?? 0) > 0 && 'text-warning')}>{число(с.badRows)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

// ——— Загрузка ———

function UploadForm({ onDone }: { onDone: (id: string) => void }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [формат, setФормат] = useState<voice.ReconciliationFormat>('megafon_csv')
  const [файл, setФайл] = useState<File | null>(null)
  const [идёт, setИдёт] = useState(false)
  const поле = useRef<HTMLInputElement>(null)
  const великоват = !!файл && файл.size > ПРЕДЕЛ_БАЙТ

  async function сверить() {
    if (!файл || великоват) return
    setИдёт(true)
    try {
      const r = await voice.uploadReconciliation(companyId, { format: формат, file: файл })
      toast.success(`Сверено: совпало ${число(r.matched)}, нет у узла ${число(r.onlyCarrier)}`)
      qc.setQueryData(['voice-reconciliation', companyId, r.id], r)
      await qc.invalidateQueries({ queryKey: ['voice-reconciliations', companyId] })
      // Новая сверка попадает в «Отчёт за месяц» её периода.
      await qc.invalidateQueries({ queryKey: ['voice-monthly', companyId] })
      setФайл(null)
      if (поле.current) поле.current.value = ''
      onDone(r.id)
    } catch (e) {
      toast.error(e instanceof Error ? `Сверка не удалась: ${e.message}` : 'Сверка не удалась')
    } finally {
      setИдёт(false)
    }
  }

  return (
    <section aria-label="Загрузить детализацию" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <h2 className="font-headline text-base font-semibold">Загрузить детализацию</h2>
      <p className="text-xs text-muted-foreground">
        CSV до 10 МБ с заголовком. Колонки узел находит по названию: «Дата и время» (или «Начало», «start»),
        «Номер звонящего» (или «Номер А», «caller», «from»), «Длительность» в секундах или ЧЧ:ММ:СС; «Направление» —
        если есть, исходящие узел пропустит. Время без пояса — местное по поясу линии. Период сверки — от первой до
        последней строки файла.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1 text-xs text-muted-foreground">
          <span className="block">Формат</span>
          <select value={формат} onChange={e => setФормат(e.target.value as voice.ReconciliationFormat)}
            className="h-9 min-w-0 max-w-[min(22rem,80vw)] rounded-md border border-input bg-background px-2 text-sm text-foreground">
            {Object.entries(ФОРМАТ).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="min-w-0 space-y-1 text-xs text-muted-foreground">
          <span className="block">Файл</span>
          <input ref={поле} type="file" accept=".csv,.txt,text/csv,text/plain"
            onChange={e => setФайл(e.target.files?.[0] ?? null)}
            className="block max-w-full text-sm text-foreground file:mr-2 file:rounded-md file:border file:border-border file:bg-background file:px-2 file:py-1 file:text-sm" />
        </label>
        <Button size="sm" disabled={!файл || великоват || идёт} onClick={() => void сверить()}>
          <Upload />{идёт ? 'Сверяем…' : 'Сверить'}
        </Button>
      </div>
      {великоват && <p className="text-xs text-destructive">Файл {объём(файл!.size)} — больше 10 МБ, узел его не примет. Разбейте период на части.</p>}
      {формат === 'megafon_csv' && (
        <p className="text-xs text-muted-foreground">Колонки МегаФона взяты по описанию выгрузки — если файл не разберётся, загрузите его как «любой оператор».</p>
      )}
    </section>
  )
}

// ——— Результат ———

function Result({ id, onClose }: { id: string; onClose: () => void }) {
  const { companyId } = useCompany()
  const [вид, setВид] = useState<voice.ReconciliationItem['kind'] | 'all'>('all')
  const q = useQuery({
    queryKey: ['voice-reconciliation', companyId, id],
    queryFn: () => voice.reconciliation(companyId, id),
  })
  const r = q.data
  const строки = (r?.items ?? []).filter(x => вид === 'all' || x.kind === вид)

  return (
    <section aria-label="Результат сверки" className="min-w-0 space-y-3 rounded-xl border border-primary/35 bg-card p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="mr-auto font-headline text-base font-semibold">Сверка {r ? `за ${период(r)}` : ''}</h2>
        <Button variant="ghost" size="icon" aria-label="Закрыть сверку" onClick={onClose}><X /></Button>
      </div>
      {q.isLoading && <p role="status" className="text-sm">Читаем сверку у узла…</p>}
      {q.isError && <NodeError ошибка={q.error} что="прочитать сверку" />}
      {r && (
        <>
          <p className="text-xs text-muted-foreground">
            {ФОРМАТ[r.format as voice.ReconciliationFormat] ?? r.format ?? 'CSV'} · загружено {когда(r.uploadedAt)}
            {r.uploadedBy && `, ${ктоСделал(r.uploadedBy)}`}
          </p>
          <div className="flex flex-wrap gap-x-8 gap-y-3">
            <Stat имя="Строк у оператора" значение={число(r.carrierRows)} />
            <Stat имя="Совпало" значение={число(r.matched)} />
            <Stat имя="Нет у узла" значение={число(r.onlyCarrier)} пояснение={ПОЯСНЕНИЕ.only_carrier}
              тон={(r.onlyCarrier ?? 0) > 0 ? 'warning' : undefined} />
            <Stat имя="Нет у оператора" значение={число(r.onlyNode)} пояснение={ПОЯСНЕНИЕ.only_node} />
            <Stat имя="Длительность" значение={число(r.durationMismatch)} пояснение={ПОЯСНЕНИЕ.duration} />
            <Stat имя="Не разобрано строк" значение={число(r.badRows)}
              тон={(r.badRows ?? 0) > 0 ? 'warning' : undefined} />
          </div>
          {!r.items?.length ? (
            <p className="text-sm text-muted-foreground">Расхождений нет: все звонки оператора узел видел, длительности сошлись.</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-1" role="group" aria-label="Вид расхождения">
                {(['all', 'only_carrier', 'only_node', 'duration'] as const).map(k => {
                  const n = k === 'all' ? r.items!.length : r.items!.filter(x => x.kind === k).length
                  return (
                    <Button key={k} size="sm" variant={вид === k ? 'default' : 'outline'} aria-pressed={вид === k}
                      disabled={!n} onClick={() => setВид(k)}>
                      {k === 'all' ? 'Все' : ВИД[k]} · {n}
                    </Button>
                  )
                })}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[34rem] text-sm">
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="whitespace-nowrap py-1 font-normal">Начало</th>
                      <th className="whitespace-nowrap py-1 pl-3 font-normal">Расхождение</th>
                      <th className="whitespace-nowrap py-1 pl-3 font-normal">Номер</th>
                      <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">У оператора</th>
                      <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">У узла</th>
                    </tr>
                  </thead>
                  <tbody>
                    {строки.map((x, i) => (
                      <tr key={`${x.at}-${i}`} className="border-t border-border/60">
                        <td className="whitespace-nowrap py-1.5">
                          {x.contactId
                            ? <Link to={`/voice/calls?id=${encodeURIComponent(x.contactId)}`} className="text-primary underline-offset-2 hover:underline">{когда(x.at)}</Link>
                            : когда(x.at)}
                        </td>
                        <td className={cn('whitespace-nowrap py-1.5 pl-3', x.kind === 'only_carrier' && 'text-destructive')} title={ПОЯСНЕНИЕ[x.kind]}>{ВИД[x.kind]}</td>
                        <td className="whitespace-nowrap py-1.5 pl-3 font-mono text-xs">{x.number ?? '—'}</td>
                        <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{x.carrierSec != null ? сек(x.carrierSec) : '—'}</td>
                        <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{x.nodeSec != null ? сек(x.nodeSec) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted-foreground">
                Номер — последними четырьмя цифрами: полного номера сверка не хранит. Звонок, который узел видел, открывается по времени начала.
              </p>
            </>
          )}
        </>
      )}
    </section>
  )
}
