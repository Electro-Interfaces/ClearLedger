/**
 * «Сотрудники и переводы» — цели перевода одним местом.
 *
 * Сейчас одна цель живёт в трёх местах двух документов: паспорт (что КЦ может
 * предложить), правила приёма (куда звонит узел) и пульт оператора. Рассогласование
 * даёт отказ перевода посреди разговора (422 rule_forbidden). Здесь цель
 * настраивается один раз, а узел сам пишет её во все три места: новыми версиями
 * правил и паспорта одним шагом, с проверкой обоих. Паспорт при этом уходит в КЦ.
 *
 * Номер, куда звонить, знает только узел: в контакт-центр уходят код и подпись.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Info, Plus, Users, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { Heading, NodeError } from './parts'
import { черновикВида } from './useDraft'

type Строка = { code: string; label: string; kind: voice.TransferTarget['kind']; endpoint: string }

const КОД = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const КУДА = /^[A-Za-z]+\/[A-Za-z0-9._@+:-]+$/

const изДанных = (t?: voice.TransferTargets): Строка[] =>
  (t?.items ?? []).map(x => ({ code: x.code, label: x.label, kind: x.kind, endpoint: x.endpoint ?? '' }))

/** Ошибки строки до отправки: те же правила, что у узла (config.ts putTargets). */
function ошибкиСтроки(x: Строка, все: Строка[]) {
  const e: Partial<Record<keyof Строка, string>> = {}
  if (!КОД.test(x.code)) e.code = 'латиница, цифры и . _ : -'
  else if (все.filter(y => y.code === x.code).length > 1) e.code = 'код повторяется'
  if (!x.label.trim()) e.label = 'нужна подпись'
  else if (x.label.length > 200) e.label = 'длиннее 200 знаков'
  if (!КУДА.test(x.endpoint)) e.endpoint = 'PJSIP/<трубка> или PJSIP/<номер>@<транк>'
  return e
}

export default function VoiceTargetsPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const цели = useQuery({
    queryKey: ['voice-targets', companyId],
    queryFn: () => voice.transferTargets(companyId),
  })
  const черновикПравил = useQuery({
    queryKey: ['voice-config', companyId, 'reception', 'draft'],
    queryFn: () => черновикВида(companyId, 'reception'),
  })
  const черновикПаспорта = useQuery({
    queryKey: ['voice-config', companyId, 'passport', 'draft'],
    queryFn: () => черновикВида(companyId, 'passport'),
  })

  // Правка живёт локально до «Записать»; новые данные узла (другая ETag) — начинаем с них.
  const [строки, setСтроки] = useState<Строка[]>(() => изДанных(цели.data))
  const [основа, setОснова] = useState(цели.data?.etag)
  if (цели.data && цели.data.etag !== основа) {
    setОснова(цели.data.etag)
    setСтроки(изДанных(цели.data))
  }
  const [зачем, setЗачем] = useState('')
  const [идёт, setИдёт] = useState(false)
  const [сУзла, setСУзла] = useState<voice.Issue[]>([])

  const изменено = JSON.stringify(строки) !== JSON.stringify(изДанных(цели.data))
  const ошибки = строки.map(x => ошибкиСтроки(x, строки))
  const годно = изменено && ошибки.every(e => !Object.keys(e).length) && зачем.trim().length >= 3
  const поИсточнику = new Map((цели.data?.items ?? []).map(x => [x.code, x]))

  const править = (i: number, ч: Partial<Строка>) => setСтроки(строки.map((x, n) => (n === i ? { ...x, ...ч } : x)))

  async function записать() {
    if (!цели.data) return
    setИдёт(true)
    setСУзла([])
    try {
      await voice.putTransferTargets(companyId, цели.data.etag, строки, зачем.trim())
      toast.success('Цели записаны: правила приёма и паспорт обновлены, паспорт ушёл в контакт-центр')
      setЗачем('')
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['voice-targets', companyId] }),
        qc.invalidateQueries({ queryKey: ['voice-config', companyId] }),
        qc.invalidateQueries({ queryKey: ['voice-versions', companyId] }),
        qc.invalidateQueries({ queryKey: ['voice-changes', companyId] }),
      ])
    } catch (e) {
      if (e instanceof voice.VoiceError && e.code === 'config_invalid') setСУзла(e.issues ?? [])
      toast.error(e instanceof voice.VoiceError && e.status === 412
        ? 'Цели тем временем изменились — показываем текущие, повторите правку'
        : e instanceof Error ? e.message : 'Не записано')
      if (e instanceof voice.VoiceError && e.status === 412) await qc.invalidateQueries({ queryKey: ['voice-targets', companyId] })
    } finally {
      setИдёт(false)
    }
  }

  const черновики = [черновикПравил.data && `правил приёма r${черновикПравил.data.version}`,
    черновикПаспорта.data && `паспорта r${черновикПаспорта.data.version}`].filter(Boolean)

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Сотрудники и переводы"
        подпись="Кому оператор может перевести звонок. Одна цель сразу попадает в паспорт, правила приёма и пульт оператора." />

      {цели.isLoading && <p role="status" className="text-sm">Читаем цели у узла…</p>}
      {цели.isError && <NodeError ошибка={цели.error} что="прочитать цели перевода" />}

      {цели.data && (
        <>
          {цели.data.consistent
            ? <p className="flex items-start gap-2 text-sm"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                Все цели сходятся во всех трёх местах: перевод не получит отказа.</p>
            : <p className="flex items-start gap-2 text-sm"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                Есть расхождения: у отмеченных целей перевод может не пройти. «Записать» сведёт их в одно.</p>}

          {!строки.length && (
            <EmptyBlock иконка={Users} текст="Целей перевода нет"
              подсказка="Оператор не может перевести звонок сотруднику. Добавьте дежурного или отдел, куда звонить." />
          )}

          {!!строки.length && (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-card text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-normal">Подпись для оператора</th>
                    <th className="px-3 py-2 font-normal">Код</th>
                    <th className="px-3 py-2 font-normal">Кто это</th>
                    <th className="px-3 py-2 font-normal">Куда звонит узел</th>
                    <th className="px-3 py-2 font-normal">Где есть сейчас</th>
                    <th className="px-3 py-2 font-normal"><span className="sr-only">Убрать</span></th>
                  </tr>
                </thead>
                <tbody>
                  {строки.map((x, i) => {
                    const е = ошибки[i]
                    const было = поИсточнику.get(x.code)
                    const сУзлаСтроки = сУзла.filter(и => и.path.startsWith(`/items/${i}/`))
                    return (
                      <tr key={i} className="border-t border-border/60 align-top">
                        <td className="px-3 py-2">
                          <Input value={x.label} onChange={ev => править(i, { label: ev.target.value })} aria-label="Подпись"
                            aria-invalid={!!е.label} className="h-9 min-w-48" placeholder="Дежурный инженер" />
                          {е.label && <p className="pt-1 text-xs text-destructive">{е.label}</p>}
                        </td>
                        <td className="px-3 py-2">
                          <Input value={x.code} onChange={ev => править(i, { code: ev.target.value.trim() })} aria-label="Код"
                            aria-invalid={!!е.code} className="h-9 w-40 font-mono text-xs" placeholder="duty_engineer" />
                          {е.code && <p className="pt-1 text-xs text-destructive">{е.code}</p>}
                        </td>
                        <td className="px-3 py-2">
                          <select value={x.kind} onChange={ev => править(i, { kind: ev.target.value as Строка['kind'] })}
                            aria-label="Кто это" className="h-9 rounded-md border border-input bg-card px-2 text-sm">
                            <option value="client_staff">сотрудник заказчика</option>
                            <option value="external">внешний номер</option>
                          </select>
                        </td>
                        <td className="px-3 py-2">
                          <Input value={x.endpoint} onChange={ev => править(i, { endpoint: ev.target.value.trim() })} aria-label="Куда звонит узел"
                            aria-invalid={!!е.endpoint} className="h-9 w-56 font-mono text-xs" placeholder="PJSIP/duty" />
                          {е.endpoint && <p className="pt-1 text-xs text-destructive">{е.endpoint}</p>}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          {было ? <Places цель={было} /> : <span className="text-muted-foreground">новая</span>}
                          {сУзлаСтроки.map((и, n) => <p key={n} className="text-destructive">{и.message ?? и.code}</p>)}
                        </td>
                        <td className="px-1 py-2">
                          <Button variant="ghost" size="icon-xs" aria-label={`Убрать ${x.label || x.code}`}
                            onClick={() => setСтроки(строки.filter((_, n) => n !== i))}><X /></Button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          <Button variant="outline" size="sm"
            onClick={() => setСтроки([...строки, { code: '', label: '', kind: 'client_staff', endpoint: '' }])}>
            <Plus />Добавить цель
          </Button>

          {изменено && (
            <section aria-label="Записать цели" className="space-y-2 rounded-xl border border-primary/35 bg-card p-4">
              <p className="flex items-start gap-2 text-sm"><Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                Узел заведёт новые версии правил приёма и паспорта одним шагом и проверит оба. Новая версия паспорта сразу
                уйдёт в контакт-центр. Переадресации убранных целей удалятся, если на них не ссылаются «вне часов» и запасной сценарий.</p>
              {!!черновики.length && (
                <p className="flex items-start gap-2 text-sm"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                  <span>Есть черновик {черновики.join(' и ')}. Он начат от прежней версии: после записи целей применить его
                    не получится — его придётся отменить и начать заново (<Link to="/voice/versions" className="underline">Версии</Link>).</span></p>
              )}
              {сУзла.some(и => !и.path.startsWith('/items/')) && (
                <ul className="space-y-1 text-sm text-destructive">
                  {сУзла.filter(и => !и.path.startsWith('/items/')).map((и, n) => <li key={n}>{и.message ?? и.code}</li>)}
                </ul>
              )}
              <form className="flex flex-wrap items-center gap-2" onSubmit={e => { e.preventDefault(); if (годно) void записать() }}>
                <Input value={зачем} onChange={e => setЗачем(e.target.value)} maxLength={500} aria-label="Зачем меняем"
                  placeholder="Зачем меняем — попадёт в журнал изменений" className="min-w-60 flex-1" />
                <Button type="submit" disabled={!годно || идёт}>{идёт ? 'Записываем…' : 'Записать во все три места'}</Button>
                <Button type="button" variant="ghost" onClick={() => { setСтроки(изДанных(цели.data)); setСУзла([]) }}>Вернуть как было</Button>
              </form>
            </section>
          )}
        </>
      )}
    </div>
  )
}

/** Где цель есть сейчас: паспорт, правила, пульт — словами, расхождения отмечены. */
function Places({ цель }: { цель: voice.TransferTarget }) {
  const места = [
    { есть: цель.places.passport, имя: 'паспорт' },
    { есть: цель.places.reception, имя: 'правила' },
    { есть: цель.places.operatorControls, имя: 'пульт' },
  ]
  return (
    <div className="space-y-0.5">
      <p>
        {места.map((м, n) => (
          <span key={м.имя} className={cn(!м.есть && 'text-warning')}>
            {n > 0 && ' · '}{м.есть ? '' : 'нет: '}{м.имя}
          </span>
        ))}
      </p>
      {цель.issues.map((и, n) => (
        <p key={n} className={и.level === 'warning' ? 'text-muted-foreground' : 'text-destructive'}>{и.message ?? и.code}</p>
      ))}
    </div>
  )
}
