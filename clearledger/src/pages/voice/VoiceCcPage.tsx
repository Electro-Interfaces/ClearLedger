/**
 * «Контакт-центры» — подключение КЦ к линии и допуск его операторов.
 *
 * Путь подключения: пригласить (код показывается один раз и действует 24 часа) →
 * КЦ вводит код у себя → сверить отпечаток ключа и включить. Дальше — приостановить,
 * возобновить, отозвать; «Отозвать» и «Заблокировать» — с подтверждением.
 *
 * Узел сейчас держит одно подключение: новое приглашение отзывает прежнее. Это
 * сказано на экране словами, а прежние подключения видны историей ниже.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Check, Copy, KeyRound, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { ПРИСУТСТВИЕ, когда } from './format'
import { Heading, NodeError } from './parts'

const СОСТОЯНИЕ: Record<voice.CcConnection['state'], string> = {
  invited: 'приглашён — ждём, пока КЦ введёт код',
  pending: 'КЦ подключился — сверьте отпечаток ключа',
  active: 'работает',
  suspended: 'приостановлен',
  revoked: 'отозван',
}

const ДОПУСК: Record<voice.CcOperator['state'], string> = {
  invited: 'ждёт допуска',
  admitted: 'допущен',
  blocked: 'заблокирован',
}

/** Отпечаток кусками по 4 знака — так его удобно читать вслух и сверять глазами. */
const кусками = (f: string) => f.replace(/(.{4})/g, '$1 ').trim()
const безПробелов = (f: string) => f.replace(/\s+/g, '')

export default function VoiceCcPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const подключения = useQuery({
    queryKey: ['voice-cc', companyId],
    queryFn: () => voice.ccConnections(companyId),
  })
  const [код, setКод] = useState<{ code: string; expiresAt: string } | null>(null)
  const [приглашаем, setПриглашаем] = useState(false)
  const [подтвердить, setПодтвердить] = useState(false)

  const все = подключения.data?.items ?? []
  const текущее = все.find(x => x.state !== 'revoked')
  const история = все.filter(x => x !== текущее)

  async function пригласить() {
    setПриглашаем(true)
    try {
      const r = await voice.ccInvite(companyId)
      setКод({ code: r.code, expiresAt: r.expiresAt })
      setПодтвердить(false)
      await qc.invalidateQueries({ queryKey: ['voice-cc', companyId] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Приглашение не создано')
    } finally {
      setПриглашаем(false)
    }
  }

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Контакт-центры"
        подпись="Какой контакт-центр принимает звонки линии и кого из его операторов вы допустили.">
        {подтвердить ? (
          <span className="flex flex-wrap items-center gap-2 text-sm">
            Прежнее подключение будет отозвано.
            <Button size="sm" onClick={() => void пригласить()} disabled={приглашаем}>Пригласить</Button>
            <Button variant="ghost" size="sm" onClick={() => setПодтвердить(false)}>Нет</Button>
          </span>
        ) : (
          <Button size="sm" onClick={() => (текущее ? setПодтвердить(true) : void пригласить())} disabled={приглашаем}>
            <KeyRound />Пригласить контакт-центр
          </Button>
        )}
      </Heading>

      {код && <InviteCode код={код} onClose={() => setКод(null)} />}

      {подключения.isLoading && <p role="status" className="text-sm">Читаем подключения у узла…</p>}
      {подключения.isError && <NodeError ошибка={подключения.error} что="прочитать подключения" />}
      {подключения.isSuccess && !текущее && !код && (
        <EmptyBlock иконка={Building2} текст="Контакт-центр не подключён"
          подсказка="Звонки линии принимает только узел: запасной сценарий и трубки узла. Пригласите контакт-центр — код действует 24 часа." />
      )}

      {текущее && <ConnectionCard к={текущее} />}
      {текущее && (текущее.state === 'active' || текущее.state === 'suspended') && <Operators к={текущее} />}

      {!!история.length && (
        <details className="rounded-xl border border-border bg-card p-4">
          <summary className="cursor-pointer text-sm font-medium">Прежние подключения ({история.length})</summary>
          <ul className="space-y-1 pt-2 text-sm">
            {история.map(x => (
              <li key={x.id} className="flex flex-wrap gap-x-3">
                <span className="font-mono text-xs">{x.id}</span>
                <span>{СОСТОЯНИЕ[x.state]}</span>
                <span className="text-muted-foreground">{x.ccIssuer ?? 'КЦ не подключался'} · с {когда(x.createdAt)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="text-xs text-muted-foreground">
        Узел держит одно подключение: новое приглашение отзывает прежнее. Несколько контакт-центров на одну линию с долями —
        открытый вопрос плана, экран для них готов, когда узел их поддержит.
      </p>
    </div>
  )
}

/** Код приглашения — один раз: после закрытия его не увидеть, только пригласить заново. */
function InviteCode({ код, onClose }: { код: { code: string; expiresAt: string }; onClose: () => void }) {
  const [скопирован, setСкопирован] = useState(false)
  return (
    <section aria-label="Код приглашения" className="space-y-2 rounded-xl border border-primary/35 bg-card p-4">
      <h2 className="font-headline text-base font-semibold">Код приглашения</h2>
      <p className="text-sm">Передайте код администратору контакт-центра. Код показывается один раз и действует до {когда(код.expiresAt)}.</p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="rounded-md border border-border bg-background px-3 py-2 font-mono text-base tracking-wider">{код.code}</code>
        <Button variant="outline" size="sm" onClick={async () => {
          try { await navigator.clipboard.writeText(код.code); setСкопирован(true) } catch { toast.error('Не удалось скопировать — выделите код вручную') }
        }}>{скопирован ? <Check /> : <Copy />}{скопирован ? 'Скопирован' : 'Скопировать'}</Button>
        <Button variant="ghost" size="sm" onClick={onClose}>Я передал код</Button>
      </div>
    </section>
  )
}

function ConnectionCard({ к }: { к: voice.CcConnection }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [отпечаток, setОтпечаток] = useState('')
  const [действие, setДействие] = useState<'suspended' | 'revoked' | null>(null)
  const [причина, setПричина] = useState('')
  const [идёт, setИдёт] = useState(false)
  const совпал = !!к.fingerprint && безПробелов(отпечаток) === к.fingerprint
  const отставание = (к.lastEventSeq ?? 0) - (к.ackedSeq ?? 0)

  async function сделать(f: () => Promise<unknown>, готово: string) {
    setИдёт(true)
    try {
      await f()
      toast.success(готово)
      setДействие(null)
      setПричина('')
      await qc.invalidateQueries({ queryKey: ['voice-cc', companyId] })
    } catch (e) {
      toast.error(e instanceof voice.VoiceError && e.status === 409 && к.state === 'pending'
        ? 'Отпечаток не совпал с ключом, который получил узел. Не включайте подключение и свяжитесь с контакт-центром.'
        : e instanceof Error ? e.message : 'Не получилось')
    } finally {
      setИдёт(false)
    }
  }

  return (
    <section aria-label="Подключение" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="mr-auto min-w-0">
          <h2 className="font-headline text-base font-semibold">{к.ccIssuer ?? 'Контакт-центр'}</h2>
          <p className={cn('text-sm', к.state === 'active' && 'text-success', к.state === 'suspended' && 'text-warning')}>{СОСТОЯНИЕ[к.state]}</p>
        </div>
        {к.state === 'active' && !действие && (
          <>
            <Button variant="outline" size="sm" onClick={() => setДействие('suspended')}>Приостановить</Button>
            <Button variant="outline" size="sm" onClick={() => setДействие('revoked')}>Отозвать</Button>
          </>
        )}
        {к.state === 'suspended' && !действие && (
          <>
            <Button size="sm" disabled={идёт} onClick={() => void сделать(() => voice.ccState(companyId, к.id, 'active'), 'Подключение возобновлено')}>Возобновить</Button>
            <Button variant="outline" size="sm" onClick={() => setДействие('revoked')}>Отозвать</Button>
          </>
        )}
        {(к.state === 'invited' || к.state === 'pending') && !действие && (
          <Button variant="outline" size="sm" onClick={() => setДействие('revoked')}>Отменить подключение</Button>
        )}
      </div>

      {действие && (
        <form className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-3"
          onSubmit={e => { e.preventDefault(); void сделать(() => voice.ccState(companyId, к.id, действие, причина.trim() || undefined),
            действие === 'revoked' ? 'Подключение отозвано' : 'Подключение приостановлено') }}>
          <span className="text-sm">
            {действие === 'revoked'
              ? 'Отозвать навсегда? Контакт-центр сразу перестанет получать звонки; вернуть — только новым приглашением.'
              : 'Приостановить? Контакт-центр перестанет получать звонки, пока вы не возобновите.'}
          </span>
          <Input value={причина} onChange={e => setПричина(e.target.value)} maxLength={200} aria-label="Причина"
            placeholder="причина — попадёт в журнал изменений" className="h-9 min-w-56 flex-1" />
          <Button type="submit" variant={действие === 'revoked' ? 'destructive' : 'default'} size="sm" disabled={идёт}>
            {действие === 'revoked' ? 'Отозвать' : 'Приостановить'}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setДействие(null)}>Нет</Button>
        </form>
      )}

      {к.state === 'pending' && к.fingerprint && (
        <div className="space-y-2 rounded-lg border border-primary/35 p-3">
          <p className="flex items-start gap-2 text-sm"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span>Отпечаток — короткая подпись ключа контакт-центра. Если он совпал, подключился именно ваш КЦ, а не тот,
              кто перехватил код. Попросите администратора КЦ продиктовать отпечаток по телефону или прислать письмом и сверьте.</span></p>
          <p className="text-sm">Узел получил ключ с отпечатком:</p>
          <code className="block break-all rounded-md border border-border bg-background px-3 py-2 font-mono text-sm">{кусками(к.fingerprint)}</code>
          <form className="flex flex-wrap items-center gap-2"
            onSubmit={e => { e.preventDefault(); if (совпал) void сделать(() => voice.ccActivate(companyId, к.id, безПробелов(отпечаток)), 'Подключение включено') }}>
            <Input value={отпечаток} onChange={e => setОтпечаток(e.target.value)} aria-label="Отпечаток от контакт-центра"
              placeholder="отпечаток, который сообщил контакт-центр" className="h-9 min-w-64 flex-1 font-mono text-xs" />
            <Button type="submit" size="sm" disabled={!совпал || идёт}>Совпал — включить</Button>
          </form>
          {!!отпечаток && !совпал && <p className="text-xs text-warning">Не совпадает. Не включайте, пока не выясните, откуда другой ключ.</p>}
        </div>
      )}

      {к.state !== 'invited' && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Поток событий</dt>
          <dd className={к.online ? 'text-success' : 'text-warning'}>
            {к.online ? 'на связи' : 'не на связи'}
            {отставание > 0 && <span className="text-muted-foreground"> · не подтверждено событий: {отставание}</span>}
          </dd>
          <dt className="text-muted-foreground">Подключён</dt><dd>{когда(к.createdAt)}</dd>
          {к.activatedAt && <><dt className="text-muted-foreground">Включён</dt><dd>{когда(к.activatedAt)}</dd></>}
        </dl>
      )}
      {к.state !== 'invited' && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">Подробнее: ключи и адреса</summary>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 pt-1">
            <dt>Подключение</dt><dd className="font-mono">{к.id}</dd>
            <dt>Издатель токенов КЦ</dt><dd className="font-mono">{к.ccIssuer ?? '—'}</dd>
            <dt>Отпечаток ключа</dt><dd className="break-all font-mono">{к.fingerprint ?? '—'}</dd>
            <dt>Ключи</dt><dd className="font-mono">{к.kids?.join(', ') || '—'}</dd>
            <dt>Окно оператора</dt><dd className="font-mono">{к.shellOrigin ?? '—'}</dd>
          </dl>
        </details>
      )}
    </section>
  )
}

function Operators({ к }: { к: voice.CcConnection }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const операторы = useQuery({
    queryKey: ['voice-cc-operators', companyId, к.id],
    queryFn: () => voice.ccOperators(companyId, к.id),
  })
  const [выбраны, setВыбраны] = useState<Set<string>>(new Set())
  const [блок, setБлок] = useState<string | null>(null)
  const [идёт, setИдёт] = useState(false)
  const строки = операторы.data?.items ?? []
  const ждут = строки.filter(x => x.state === 'invited')

  async function допуск(список: voice.CcOperator[], state: voice.CcOperator['state'], роль?: 'operator' | 'supervisor') {
    setИдёт(true)
    let ок = 0
    try {
      for (const o of список) {
        await voice.ccOperator(companyId, к.id, o.operatorId, {
          state, role: роль ?? (o.role === 'supervisor' ? 'supervisor' : 'operator'), lines: o.lines ?? undefined,
        })
        ок++
      }
      toast.success(state === 'admitted' ? `Допущено: ${ок}` : state === 'blocked' ? 'Оператор заблокирован' : 'Сохранено')
    } catch (e) {
      toast.error(`${ок ? `Сделано ${ок} из ${список.length}. ` : ''}${e instanceof Error ? e.message : 'Не получилось'}`)
    } finally {
      setИдёт(false)
      setВыбраны(new Set())
      setБлок(null)
      await qc.invalidateQueries({ queryKey: ['voice-cc-operators', companyId, к.id] })
    }
  }

  return (
    <section aria-label="Допуск операторов" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto font-headline text-base font-semibold">Допуск операторов</h2>
        {!!выбраны.size && (
          <Button size="sm" disabled={идёт} onClick={() => void допуск(строки.filter(x => выбраны.has(x.operatorId)), 'admitted')}>
            Допустить выбранных ({выбраны.size})
          </Button>
        )}
        {!выбраны.size && ждут.length > 1 && (
          <Button variant="outline" size="sm" disabled={идёт} onClick={() => void допуск(ждут, 'admitted')}>Допустить всех ждущих ({ждут.length})</Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">Операторы КЦ видны под псевдонимом, который дал контакт-центр. Имён и телефонов операторов узел не знает.</p>
      {операторы.isLoading && <p role="status" className="text-sm">Читаем реестр допуска…</p>}
      {операторы.isError && <NodeError ошибка={операторы.error} что="прочитать реестр допуска" />}
      {операторы.isSuccess && !строки.length && <p className="text-sm text-muted-foreground">Контакт-центр ещё не прислал ни одного оператора.</p>}
      {!!строки.length && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="w-8 py-1"><span className="sr-only">Выбрать</span></th>
                <th className="py-1 pr-3 font-normal">Оператор</th>
                <th className="py-1 pr-3 font-normal">Роль</th>
                <th className="py-1 pr-3 font-normal">Допуск</th>
                <th className="py-1 pr-3 font-normal">Сейчас</th>
                <th className="py-1 pr-3 font-normal">Линии</th>
                <th className="py-1 font-normal"><span className="sr-only">Действие</span></th>
              </tr>
            </thead>
            <tbody>
              {строки.map(o => (
                <tr key={o.operatorId} className="border-t border-border/60 align-top">
                  <td className="py-2">
                    {o.state !== 'admitted' && (
                      <input type="checkbox" aria-label={`Выбрать ${o.operatorId}`} checked={выбраны.has(o.operatorId)}
                        onChange={e => { const n = new Set(выбраны); if (e.target.checked) n.add(o.operatorId); else n.delete(o.operatorId); setВыбраны(n) }} />
                    )}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs">{o.operatorId}</td>
                  <td className="py-2 pr-3">
                    <select value={o.role === 'supervisor' ? 'supervisor' : 'operator'} aria-label="Роль" disabled={идёт}
                      onChange={e => void допуск([o], o.state, e.target.value as 'operator' | 'supervisor')}
                      className="h-8 rounded-md border border-input bg-card px-1.5 text-sm">
                      <option value="operator">оператор</option>
                      <option value="supervisor">начальник смены</option>
                    </select>
                  </td>
                  <td className={cn('py-2 pr-3', o.state === 'admitted' && 'text-success', o.state === 'blocked' && 'text-destructive')}>{ДОПУСК[o.state]}</td>
                  <td className="py-2 pr-3">{o.presence ? ПРИСУТСТВИЕ[o.presence] ?? o.presence : '—'}</td>
                  <td className="py-2 pr-3 font-mono text-xs">{o.lines?.length ? o.lines.join(', ') : 'все'}</td>
                  <td className="py-2">
                    {блок === o.operatorId ? (
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-xs">Заблокировать?</span>
                        <Button variant="destructive" size="xs" disabled={идёт} onClick={() => void допуск([o], 'blocked')}>Да</Button>
                        <Button variant="ghost" size="xs" onClick={() => setБлок(null)}>Нет</Button>
                      </span>
                    ) : (
                      <span className="flex flex-wrap gap-1.5">
                        {o.state !== 'admitted' && <Button variant="outline" size="xs" disabled={идёт} onClick={() => void допуск([o], 'admitted')}>Допустить</Button>}
                        {o.state !== 'blocked' && <Button variant="ghost" size="xs" onClick={() => setБлок(o.operatorId)}>Заблокировать</Button>}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
