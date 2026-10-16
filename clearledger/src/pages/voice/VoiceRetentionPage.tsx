/**
 * «Записи и хранение» — сколько узел хранит записи, расшифровки и номера, сколько места
 * занято и что удалено по сроку.
 *
 * Сроки — политика хранения узла (`/config/policy`): смена — новая версия политики с
 * причиной в журнале доступа, откат — на «Версиях и изменениях». Перед сменой экран
 * считает по журналу, сколько звонков потеряет записи, расшифровки или номер при ближайшей
 * чистке (узел чистит раз в час): удалённое не вернуть, и это нужно знать до нажатия.
 * Ниже — диск записей из `/health`, чистки по сроку (`purge.run`), досрочные удаления и
 * запреты удаления из журнала доступа.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Archive, HardDrive, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { Field, NumberInput } from './DraftParts'
import { дата, когда, ктоСделал, объём, число } from './format'
import { Heading, NodeError } from './parts'

const ДЕНЬ = 86_400_000

/** Пределы схемы `Policy`: вне их узел ответит 422, лучше сказать до отправки. */
const ПРЕДЕЛЫ: Record<keyof voice.Policy, [number, number] | null> = {
  recordingsDays: [1, 3650],
  transcriptsDays: [1, 3650],
  numberMonths: [1, 120],
  recordingDownload: null,
  fcrWindowMin: [1, 1440],
  shortAbandonSec: [0, 60],
  callbackDueSec: [60, 86400],
  alertSlPct: [0, 100],
  alertSlMinOffered: [1, 10000],
}

const ОБЯЗАТЕЛЬНЫЕ: (keyof voice.Policy)[] = ['recordingsDays', 'transcriptsDays', 'numberMonths', 'fcrWindowMin']

type Правка = Partial<voice.Policy>

function ошибкиПравки(п: Правка) {
  const плохо: string[] = []
  for (const [k, r] of Object.entries(ПРЕДЕЛЫ) as [keyof voice.Policy, [number, number] | null][]) {
    const v = п[k]
    if (!r) continue
    if (v === undefined) { if (ОБЯЗАТЕЛЬНЫЕ.includes(k)) плохо.push(k); continue }
    if (typeof v !== 'number' || v < r[0] || v > r[1]) плохо.push(k)
  }
  return плохо
}

function месяцевНазад(сейчас: number, n: number) {
  const d = new Date(сейчас)
  d.setUTCMonth(d.getUTCMonth() - n)
  return d.getTime()
}

interface Потери { записи: number; расшифровки: number; номера: number; всё: boolean; с: number; по: number }

/**
 * Сколько звонков потеряют записи, расшифровки и номер при ближайшей чистке после смены сроков.
 * Считаем по журналу звонков узла (`/calls`, без номеров — поиск не пишется в журнал доступа),
 * не больше 10 000 строк. Это оценка: запреты удаления и досрочно удалённое журнал не показывает.
 */
async function посчитатьПотери(cid: string, было: voice.Policy, стало: voice.Policy): Promise<Потери | null> {
  const сейчас = Date.now()
  const окна: { что: 'записи' | 'расшифровки' | 'номера'; с: number; по: number }[] = []
  if (стало.recordingsDays < было.recordingsDays) окна.push({ что: 'записи', с: сейчас - было.recordingsDays * ДЕНЬ, по: сейчас - стало.recordingsDays * ДЕНЬ })
  if (стало.transcriptsDays < было.transcriptsDays) окна.push({ что: 'расшифровки', с: сейчас - было.transcriptsDays * ДЕНЬ, по: сейчас - стало.transcriptsDays * ДЕНЬ })
  if (стало.numberMonths < было.numberMonths) окна.push({ что: 'номера', с: месяцевНазад(сейчас, было.numberMonths), по: месяцевНазад(сейчас, стало.numberMonths) })
  if (!окна.length) return null
  const с = Math.min(...окна.map(о => о.с))
  const по = Math.max(...окна.map(о => о.по))
  const итог: Потери = { записи: 0, расшифровки: 0, номера: 0, всё: true, с, по }
  let cursor: string | undefined
  for (let страница = 0; страница < 20; страница++) {
    const p = await voice.calls(cid, { from: new Date(с).toISOString(), to: new Date(по).toISOString(), cursor, limit: 500 })
    for (const r of p.items) {
      const конец = Date.parse(r.endedAt ?? r.startedAt)
      const начало = Date.parse(r.startedAt)
      for (const о of окна) {
        const t = о.что === 'номера' ? начало : конец
        if (t < о.с || t >= о.по) continue
        if (о.что === 'записи' && r.recorded) итог.записи++
        if (о.что === 'расшифровки' && r.transcribed) итог.расшифровки++
        if (о.что === 'номера' && !r.numberPurged && r.number) итог.номера++
      }
    }
    if (!p.next) return итог
    cursor = p.next
  }
  return { ...итог, всё: false }
}

export default function VoiceRetentionPage() {
  const { companyId } = useCompany()
  const политика = useQuery({
    queryKey: ['voice-config', companyId, 'policy', 'active'],
    queryFn: () => voice.configActive(companyId, 'policy'),
  })
  const здоровье = useQuery({
    queryKey: ['voice-health', companyId],
    queryFn: () => voice.health(companyId),
    refetchInterval: 60_000,
  })
  const чистки = useQuery({
    queryKey: ['voice-audit', companyId, 'purge.run'],
    queryFn: () => voice.audit(companyId, { action: 'purge.run', limit: 30 }),
  })
  const досрочно = useQuery({
    queryKey: ['voice-audit', companyId, 'retention-manual'],
    queryFn: async () => {
      const [уд, зап, сн] = await Promise.all(['recording.delete', 'retention.hold', 'retention.release']
        .map(action => voice.audit(companyId, { action, limit: 20 })))
      return [...уд.items, ...зап.items, ...сн.items].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 30)
    },
  })

  const п = политика.data?.data as voice.ConfigVersion<voice.Policy> | undefined
  const диск = здоровье.data?.parts?.disk

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Записи и хранение"
        подпись="Сколько узел хранит записи, расшифровки и номера звонящих, сколько места занято и что удалено по сроку." />

      {политика.isLoading && <p role="status" className="text-sm">Читаем политику хранения у узла…</p>}
      {политика.isError && <NodeError ошибка={политика.error} что="прочитать политику хранения" />}
      {п && политика.data?.etag && <PolicyCard п={п} etag={политика.data.etag} />}

      <section aria-label="Диск записей" className="space-y-2 rounded-xl border border-border bg-card p-4">
        <h2 className="flex items-center gap-2 font-headline text-base font-semibold"><HardDrive className="h-4 w-4 text-muted-foreground" />Диск записей</h2>
        {здоровье.isError && <NodeError ошибка={здоровье.error} что="узнать место на диске" />}
        {диск && <DiskBar диск={диск} />}
        <p className="text-xs text-muted-foreground">
          Прогноз заполнения появится, когда узел начнёт отдавать рост записей по дням. Сейчас ориентир — тревога
          «мало места» при свободных 10 %. При ровной нагрузке объём записей перестаёт расти через срок хранения: {п?.body.recordingsDays ?? 180} дней работы узла.
        </p>
      </section>

      <section aria-label="Чистка по сроку" className="space-y-2 rounded-xl border border-border bg-card p-4">
        <h2 className="font-headline text-base font-semibold">Удалено по сроку</h2>
        <p className="text-xs text-muted-foreground">Узел проверяет сроки раз в час. Строка появляется, только когда что-то удалено.</p>
        {чистки.isError && <NodeError ошибка={чистки.error} что="прочитать журнал чисток" />}
        {чистки.data && !чистки.data.items.length && (
          <EmptyBlock иконка={Archive} текст="По сроку пока ничего не удалялось"
            подсказка="Первая чистка удалит записи звонков старше срока хранения." />
        )}
        {!!чистки.data?.items.length && (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="bg-background text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-normal">Когда</th>
                  <th className="px-3 py-2 text-right font-normal">Записей</th>
                  <th className="px-3 py-2 text-right font-normal">Расшифровок</th>
                  <th className="px-3 py-2 text-right font-normal">Номеров → хеш</th>
                </tr>
              </thead>
              <tbody>
                {чистки.data.items.map(з => {
                  const d = (з.detail ?? {}) as { recordings?: number; transcripts?: number; numbers?: number }
                  return (
                    <tr key={з.id} className="border-t border-border/60">
                      <td className="whitespace-nowrap px-3 py-2">{когда(з.at)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{число(d.recordings)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{число(d.transcripts)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{число(d.numbers)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-label="Досрочные удаления и запреты" className="space-y-2 rounded-xl border border-border bg-card p-4">
        <h2 className="font-headline text-base font-semibold">Досрочные удаления и запреты удаления</h2>
        <p className="text-xs text-muted-foreground">
          Удалить записи звонка раньше срока или запретить их удаление (спор, проверка) можно в карточке звонка в
          {' '}<Link to="/voice/calls" className="text-primary underline-offset-2 hover:underline">журнале</Link>.
        </p>
        {досрочно.isError && <NodeError ошибка={досрочно.error} что="прочитать журнал доступа" />}
        {досрочно.data && !досрочно.data.length && <p className="text-sm text-muted-foreground">Не было.</p>}
        {!!досрочно.data?.length && (
          <ul className="space-y-1 text-sm">
            {досрочно.data.map(з => (
              <li key={з.id} className="flex flex-wrap gap-x-2">
                <span className="text-muted-foreground">{когда(з.at)}</span>
                <span>{ктоСделал(з.actor)}</span>
                <span>{з.action === 'recording.delete' ? 'удалил записи досрочно'
                  : з.action === 'retention.hold' ? `запретил удаление${typeof з.detail?.until === 'string' ? ` до ${дата(з.detail.until)}` : ''}`
                  : 'снял запрет удаления'}</span>
                {з.object && <Link to={`/voice/calls?id=${encodeURIComponent(з.object)}`} className="font-mono text-xs leading-5 text-primary hover:underline">{з.object}</Link>}
                {з.reason && <span className="text-muted-foreground">«{з.reason}»</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function DiskBar({ диск }: { диск: voice.HealthPart }) {
  const free = typeof диск.info?.freeBytes === 'number' ? диск.info.freeBytes : null
  const total = typeof диск.info?.totalBytes === 'number' ? диск.info.totalBytes : null
  const свободноPct = диск.value ?? (free != null && total ? (free / total) * 100 : null)
  if (свободноPct == null) {
    return <p className="text-sm text-muted-foreground">{диск.detail ?? 'Узел не смог узнать место на диске.'}</p>
  }
  const занятоPct = Math.max(0, Math.min(100, 100 - свободноPct))
  return (
    <div className="space-y-1.5">
      <div className="h-3 overflow-hidden rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={100}
        aria-valuenow={Math.round(занятоPct)} aria-label="Занято на диске записей">
        <div className={cn('h-full rounded-full', диск.state === 'down' ? 'bg-destructive' : диск.state === 'warn' ? 'bg-warning' : 'bg-primary')}
          style={{ width: `${занятоPct}%` }} />
      </div>
      <p className="text-sm">
        Свободно {Math.round(свободноPct)} %{free != null && total != null && <> — {объём(free)} из {объём(total)}, занято {объём(total - free)}</>}.
        {диск.state === 'warn' && <span className="text-warning"> Мало места: тревога поднимается, когда свободно меньше 10 %.</span>}
        {диск.state === 'down' && <span className="text-destructive"> Места почти нет: новые записи могут не сохраниться.</span>}
      </p>
    </div>
  )
}

function PolicyCard({ п, etag }: { п: voice.ConfigVersion<voice.Policy>; etag: string }) {
  const b = п.body
  const [правка, setПравка] = useState<Правка | null>(null)
  return (
    <section aria-label="Сроки хранения" className="space-y-2 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-start gap-2">
        <div className="mr-auto min-w-0">
          <h2 className="font-headline text-base font-semibold">Сроки хранения</h2>
          <p className="text-xs text-muted-foreground">
            Политика r{п.version}{п.appliedAt && `, действует с ${когда(п.appliedAt)}`}{п.appliedBy && `, ${ктоСделал(п.appliedBy)}`}.
            История и откат — на <Link to="/voice/versions?kind=policy" className="text-primary underline-offset-2 hover:underline">«Версиях и изменениях»</Link>.
          </p>
        </div>
        {!правка && <Button variant="outline" size="sm" onClick={() => setПравка({ ...b })}><Pencil />Изменить</Button>}
      </div>
      {правка
        ? <PolicyEdit было={b} правка={правка} setПравка={setПравка} etag={etag} />
        : (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Записи разговоров</dt><dd>{b.recordingsDays} дн. от конца звонка</dd>
            <dt className="text-muted-foreground">Расшифровки</dt><dd>{b.transcriptsDays} дн.</dd>
            <dt className="text-muted-foreground">Номер в журнале</dt><dd>{b.numberMonths} мес., затем хеш: строка звонка остаётся</dd>
            <dt className="text-muted-foreground">Скачивание записей</dt><dd>{b.recordingDownload ? 'разрешено, по причине и в журнал доступа' : 'запрещено, только прослушивание'}</dd>
          </dl>
        )}
      <p className="text-xs text-muted-foreground">
        Статистика и журнал доступа хранятся бессрочно и сроками не настраиваются: в них нет звука и номеров.
      </p>
    </section>
  )
}

function PolicyEdit({ было, правка, setПравка, etag }: {
  было: voice.Policy
  правка: Правка
  setПравка: (п: Правка | null) => void
  etag: string
}) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [шаг, setШаг] = useState<'правка' | 'подтверждение'>('правка')
  const [причина, setПричина] = useState('')
  const [понимаю, setПонимаю] = useState(false)
  const [идёт, setИдёт] = useState(false)
  const плохо = ошибкиПравки(правка)
  const стало = { ...было, ...правка } as voice.Policy
  const изменено = (Object.keys(ПРЕДЕЛЫ) as (keyof voice.Policy)[]).filter(k => стало[k] !== было[k])
  const короче = стало.recordingsDays < было.recordingsDays || стало.transcriptsDays < было.transcriptsDays || стало.numberMonths < было.numberMonths

  const потери = useQuery({
    queryKey: ['voice-retention-loss', companyId, было.recordingsDays, было.transcriptsDays, было.numberMonths,
      стало.recordingsDays, стало.transcriptsDays, стало.numberMonths],
    queryFn: () => посчитатьПотери(companyId, было, стало),
    enabled: шаг === 'подтверждение' && короче,
    staleTime: 60_000,
  })

  const поставить = (k: keyof voice.Policy) => (v: number | undefined) => setПравка({ ...правка, [k]: v })
  const подсказкаПредела = (k: keyof voice.Policy) => {
    const r = ПРЕДЕЛЫ[k]
    return r && плохо.includes(k) ? <span className="text-destructive">от {r[0]} до {r[1]}</span> : undefined
  }
  const былоПоле = (k: keyof voice.Policy) => (стало[k] !== было[k] ? String(было[k] ?? 'по умолчанию') : undefined)

  async function применить() {
    setИдёт(true)
    try {
      // Пустое необязательное поле — значение узла по умолчанию: в тело его не кладём.
      const тело = Object.fromEntries(Object.entries(стало).filter(([, v]) => v !== undefined)) as unknown as voice.Policy
      const r = await voice.putPolicy(companyId, etag, тело, причина.trim())
      toast.success(`Политика хранения r${r.data.version} действует. Ближайшая чистка — в течение часа.`)
      setПравка(null)
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['voice-config', companyId, 'policy'] }),
        qc.invalidateQueries({ queryKey: ['voice-versions', companyId] }),
        qc.invalidateQueries({ queryKey: ['voice-changes', companyId] }),
      ])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Узел не принял политику')
      if (e instanceof voice.VoiceError && e.status === 412) await qc.invalidateQueries({ queryKey: ['voice-config', companyId, 'policy'] })
    } finally {
      setИдёт(false)
    }
  }

  if (шаг === 'подтверждение') {
    const п = потери.data
    const годно = причина.trim().length >= 3 && (!короче || понимаю) && !потери.isLoading
    return (
      <div className="space-y-3 rounded-lg border border-border p-3">
        <ul className="list-disc space-y-0.5 pl-5 text-sm">
          {изменено.map(k => (
            <li key={k}>{ПОДПИСЬ[k]}: {String(было[k] ?? 'по умолчанию')} → <span className="font-medium">{String(стало[k] ?? 'по умолчанию')}</span></li>
          ))}
        </ul>
        {короче && (
          <div className="space-y-1 rounded-lg border border-warning/50 bg-warning/5 p-3 text-sm">
            {потери.isLoading && <p role="status">Считаем по журналу, что удалит ближайшая чистка…</p>}
            {потери.isError && <p>Не удалось посчитать по журналу: {потери.error instanceof Error ? потери.error.message : 'узел не ответил'}. Удаление всё равно произойдёт.</p>}
            {п && (
              <p>
                Ближайшая чистка (в течение часа) удалит{!п.всё && ' не меньше чем'}:
                {' '}записи {число(п.записи)} звонков, расшифровки {число(п.расшифровки)}, номера {число(п.номера)} заменит хешем.
                {' '}Это звонки с {дата(new Date(п.с).toISOString())} по {дата(new Date(п.по).toISOString())}
                {!п.всё && ' Посчитаны первые 10 000 звонков периода.'}
              </p>
            )}
            <p className="text-xs text-muted-foreground">Оценка по журналу звонков: звонки под запретом удаления чистка пропустит.</p>
            <label className="flex items-start gap-2 pt-1">
              <input type="checkbox" checked={понимаю} onChange={e => setПонимаю(e.target.checked)} className="mt-1" />
              <span>Понимаю: удалённые записи, расшифровки и номера не вернуть</span>
            </label>
          </div>
        )}
        <label className="block space-y-1 text-xs text-muted-foreground">
          <span className="block">Зачем меняете — попадёт в журнал доступа</span>
          <Textarea value={причина} onChange={e => setПричина(e.target.value)} maxLength={500} rows={2}
            placeholder="Например: решение заказчика о сокращении срока хранения записей" aria-label="Причина" />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant={короче ? 'destructive' : 'default'} disabled={!годно || идёт} onClick={() => void применить()}>
            {идёт ? 'Применяем…' : 'Применить'}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setШаг('правка')}>Назад</Button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="rounded-lg border border-border px-3">
        <Field имя={ПОДПИСЬ.recordingsDays} подсказка={подсказкаПредела('recordingsDays') ?? 'от конца звонка; по умолчанию 180'} было={былоПоле('recordingsDays')}>
          <NumberInput значение={правка.recordingsDays} onChange={поставить('recordingsDays')} единица="дн." подпись={ПОДПИСЬ.recordingsDays} min={1} />
        </Field>
        <Field имя={ПОДПИСЬ.transcriptsDays} подсказка={подсказкаПредела('transcriptsDays') ?? 'по умолчанию 180'} было={былоПоле('transcriptsDays')}>
          <NumberInput значение={правка.transcriptsDays} onChange={поставить('transcriptsDays')} единица="дн." подпись={ПОДПИСЬ.transcriptsDays} min={1} />
        </Field>
        <Field имя={ПОДПИСЬ.numberMonths} подсказка={подсказкаПредела('numberMonths') ?? 'затем номер заменяется хешем; повторы и FCR считаются по хешу'} было={былоПоле('numberMonths')}>
          <NumberInput значение={правка.numberMonths} onChange={поставить('numberMonths')} единица="мес." подпись={ПОДПИСЬ.numberMonths} min={1} />
        </Field>
        <Field имя={ПОДПИСЬ.recordingDownload} подсказка="Скачивание — по причине и с записью в журнал доступа" было={былоПоле('recordingDownload')}>
          <Switch checked={!!правка.recordingDownload} onCheckedChange={v => setПравка({ ...правка, recordingDownload: v })} aria-label={ПОДПИСЬ.recordingDownload} />
        </Field>
      </div>
      <details className="rounded-lg border border-border px-3 py-2">
        <summary className="cursor-pointer text-sm">Ещё в этой политике: окно FCR и пороги тревог</summary>
        <Field имя={ПОДПИСЬ.fcrWindowMin} подсказка={подсказкаПредела('fcrWindowMin') ?? 'повторный звонок в это окно — «вопрос не решён»'} было={былоПоле('fcrWindowMin')}>
          <NumberInput значение={правка.fcrWindowMin} onChange={поставить('fcrWindowMin')} единица="мин" подпись={ПОДПИСЬ.fcrWindowMin} min={1} />
        </Field>
        <Field имя={ПОДПИСЬ.shortAbandonSec} подсказка={подсказкаПредела('shortAbandonSec') ?? 'в SL и долю брошенных не входит'} было={былоПоле('shortAbandonSec')}>
          <NumberInput значение={правка.shortAbandonSec} onChange={поставить('shortAbandonSec')} единица="с" поУмолчанию={5} подпись={ПОДПИСЬ.shortAbandonSec} />
        </Field>
        <Field имя={ПОДПИСЬ.callbackDueSec} подсказка={подсказкаПредела('callbackDueSec')} было={былоПоле('callbackDueSec')}>
          <NumberInput значение={правка.callbackDueSec} onChange={поставить('callbackDueSec')} единица="с" поУмолчанию={1800} подпись={ПОДПИСЬ.callbackDueSec} min={60} />
        </Field>
        <Field имя={ПОДПИСЬ.alertSlPct} подсказка={подсказкаПредела('alertSlPct') ?? 'SL за последний час'} было={былоПоле('alertSlPct')}>
          <NumberInput значение={правка.alertSlPct} onChange={поставить('alertSlPct')} единица="%" поУмолчанию={80} подпись={ПОДПИСЬ.alertSlPct} />
        </Field>
        <Field имя={ПОДПИСЬ.alertSlMinOffered} подсказка={подсказкаПредела('alertSlMinOffered') ?? 'реже — тревоги не будет: мало звонков для вывода'} было={былоПоле('alertSlMinOffered')}>
          <NumberInput значение={правка.alertSlMinOffered} onChange={поставить('alertSlMinOffered')} поУмолчанию={10} подпись={ПОДПИСЬ.alertSlMinOffered} min={1} />
        </Field>
      </details>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={!!плохо.length || !изменено.length} onClick={() => { setПонимаю(false); setШаг('подтверждение') }}>Дальше</Button>
        <Button variant="ghost" size="sm" onClick={() => setПравка(null)}>Отмена</Button>
        {!изменено.length && <span className="self-center text-xs text-muted-foreground">Ничего не изменено</span>}
      </div>
    </div>
  )
}

const ПОДПИСЬ: Record<keyof voice.Policy, string> = {
  recordingsDays: 'Записи разговоров',
  transcriptsDays: 'Расшифровки',
  numberMonths: 'Номер в журнале',
  recordingDownload: 'Скачивание записей',
  fcrWindowMin: 'Окно FCR',
  shortAbandonSec: 'Коротко брошенный — ожидание меньше',
  callbackDueSec: 'Обратный звонок просрочен через',
  alertSlPct: 'Тревога: SL ниже',
  alertSlMinOffered: 'Тревога SL — не меньше звонков за час',
}
