/**
 * «Осмотр» — чек-лист станции для инженера, который стоит рядом с ней.
 *
 * ЗАЧЕМ ОТДЕЛЬНЫЙ ВИД. Телеметрия отвечает, идёт ли ток. Она не отвечает, есть
 * ли на корпусе заводской номер, читается ли цена ДО оплаты, цела ли оклейка и
 * не выгорела ли табличка с телефоном поддержки. Это видно только на месте, а
 * спрашивают за это не по OCPP, а по закону: ЗоЗПП ст. 9 и 10, ФЗ-54 о
 * заводском номере на корпусе, КоАП ст. 14.8 и 9.11.
 *
 * ЧТО ВИДНО СРАЗУ. Четыре числа в шапке: в порядке / просрочено / нарушения /
 * не проверяли. Разделять последние два обязательно: «нарушение» — инженер был
 * и увидел беду, «не проверяли» — мы про станцию просто ничего не знаем. Свести
 * их в один процент значит объявить неосмотренный парк исправным.
 *
 * КАК ОТМЕЧАЮТ. Клик по пункту раскрывает три кнопки — в порядке / нарушение /
 * не применимо — плюс примечание и снимок. Отметка ложится ИСТОРИЕЙ: прежняя не
 * затирается, потому что вопрос «когда у этой станции последний раз была цела
 * оклейка» возникает ровно тогда, когда кто-то предъявляет претензию за
 * сегодняшнее состояние.
 *
 * МЕТРОЛОГИЯ И ТО — ОТДЕЛЬНЫМ БЛОКОМ СВЕРХУ. Поверка счётчика и график
 * обслуживания живут не отметкой осмотра, а полями железки: их надо считать по
 * всей сети сразу («у скольких поверка кончается в этом квартале»), а не
 * перечитывать примечания. Пункт «поверка не истекла» в чек-листе остаётся —
 * он про наклейку на счётчике, которую инженер видит глазами.
 *
 * ПАМЯТКИ — ИЗ «ИНФО», А НЕ СВОИ. Знание пространства ведётся в одном месте:
 * заводить у станции второе хранилище текстов значит развести две правды. Здесь
 * показываются статьи «Инфо», привязанные к этой станции, к её марке и к
 * разделу — по составному ключу, без нового поля в модели.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle, BookOpen, Camera, CheckCircle2, ClipboardCheck, Clock, Gauge,
  HelpCircle, Loader2, Minus, Wrench, XCircle,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { AuthImage } from '@/components/chat/AuthMedia'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import {
  addStationCheck, getStationCheck, getStationUpkeep, putStationUpkeep,
  type CheckVerdict, type StationCheckItem, type UpkeepTerm,
} from '@/services/opsService'
import { Markdown } from '@/components/info/Markdown'
import { getInfoArticle, getInfoContext } from '@/services/infoService'
import { locationField, type ServiceLocation } from '@/types/location'
import { ScrollTab, SectionCard } from './shared'

/** Вывод по пункту: значок, цвет и слово. Пять состояний, а не «да/нет». */
const ВЫВОД: Record<CheckVerdict, {
  label: string; cls: string; icon: typeof CheckCircle2
}> = {
  ok: { label: 'в порядке', cls: 'text-emerald-600 dark:text-emerald-400', icon: CheckCircle2 },
  stale: { label: 'срок вышел', cls: 'text-amber-600 dark:text-amber-400', icon: Clock },
  fail: { label: 'нарушение', cls: 'text-red-600 dark:text-red-400', icon: XCircle },
  never: { label: 'не проверяли', cls: 'text-muted-foreground', icon: HelpCircle },
  na: { label: 'не применимо', cls: 'text-muted-foreground', icon: Minus },
}

function дата(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU')
}

/** Строка пункта: состояние сверху, форма отметки — по клику. */
function ItemRow({ пункт, отметить, занят }: {
  пункт: StationCheckItem
  отметить: (state: string, note: string, file: File | null) => void
  занят: boolean
}) {
  const [открыт, setОткрыт] = useState(false)
  const [примечание, setПримечание] = useState('')
  const [файл, setФайл] = useState<File | null>(null)
  const в = ВЫВОД[пункт.verdict]
  const Значок = в.icon

  const записать = (state: string) => {
    отметить(state, примечание.trim(), файл)
    setОткрыт(false); setПримечание(''); setФайл(null)
  }

  return (
    <div className={cn('border-b border-border/40 last:border-0',
      пункт.verdict === 'fail' && 'bg-red-500/5')}>
      <button type="button" onClick={() => setОткрыт((v) => !v)}
        className="flex w-full items-start gap-2 px-2 py-2 text-left hover:bg-accent/30">
        <Значок className={cn('mt-0.5 size-4 shrink-0', в.cls)} />
        <div className="min-w-0 flex-1">
          <div className="text-sm">{пункт.label}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span className={в.cls}>{в.label}</span>
            {пункт.checkedOn && (
              <span>· {дата(пункт.checkedOn)}{пункт.checkedBy ? `, ${пункт.checkedBy}` : ''}</span>
            )}
            <span>· основание: {пункт.basis}</span>
            {пункт.photo && (
              <span className={пункт.unconfirmed ? 'text-amber-600 dark:text-amber-400' : ''}>
                · {пункт.unconfirmed ? 'без снимка' : 'нужен снимок'}
              </span>
            )}
          </div>
          {пункт.note && (
            <div className="mt-1 text-xs italic text-muted-foreground">{пункт.note}</div>
          )}
        </div>
      </button>

      {открыт && (
        <div className="space-y-3 border-t border-border/30 bg-muted/20 px-3 py-3">
          <p className="text-xs text-muted-foreground">{пункт.hint}</p>
          <p className="text-xs text-muted-foreground">
            Периодичность: раз в {пункт.days} дн.
            {пункт.fileId && ' · снимок прошлого осмотра ниже'}
          </p>

          {пункт.fileId && (
            <AuthImage path={`/api/files/${пункт.fileId}`}
              alt={пункт.fileName ?? 'снимок осмотра'}
              className="max-h-48 w-auto rounded border border-border/50" />
          )}

          <Input value={примечание} onChange={(e) => setПримечание(e.target.value)}
            placeholder="Что именно увидели (для «нарушения» — обязательно по существу)"
            className="h-8 text-sm" />

          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded border border-border/60 px-2 py-1 text-xs text-muted-foreground hover:bg-accent/40">
              <Camera className="size-3.5" />
              {файл ? файл.name : 'снимок с места'}
              <input type="file" accept="image/*" capture="environment" className="hidden"
                onChange={(e) => setФайл(e.target.files?.[0] ?? null)} />
            </label>
            <div className="ml-auto flex gap-2">
              <Button size="sm" variant="outline" disabled={занят}
                onClick={() => записать('ok')}>В порядке</Button>
              <Button size="sm" variant="outline" disabled={занят}
                className="border-red-500/40 text-red-600 hover:bg-red-500/10 dark:text-red-400"
                onClick={() => записать('fail')}>Нарушение</Button>
              <Button size="sm" variant="ghost" disabled={занят}
                onClick={() => записать('na')}>Не применимо</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/** Состояние срока: цвет и слово. «Не заполнено» — это не «в порядке». */
const СРОК: Record<UpkeepTerm['state'], string> = {
  ok: 'text-emerald-600 dark:text-emerald-400',
  soon: 'text-amber-600 dark:text-amber-400',
  overdue: 'text-red-600 dark:text-red-400',
  unknown: 'text-muted-foreground',
}

function осталось(т: UpkeepTerm): string {
  if (т.daysLeft === null) return т.stateLabel
  if (т.daysLeft < 0) return `просрочено на ${Math.abs(т.daysLeft)} дн.`
  return `осталось ${т.daysLeft} дн.`
}

/** Метрология счётчика и график ТО — поля станции-железки, а не места. */
function UpkeepCard({ location }: { location: ServiceLocation }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [правка, setПравка] = useState(false)
  const [форма, setФорма] = useState<Record<string, string>>({})

  const q = useQuery({
    queryKey: ['station-upkeep', companyId, location.id],
    queryFn: () => getStationUpkeep(companyId, location.id),
    enabled: !!companyId,
    staleTime: 60_000,
  })

  const сохранить = useMutation({
    mutationFn: () => putStationUpkeep(companyId, location.id, {
      meterSerial: форма.meterSerial,
      meterVerifiedOn: форма.meterVerifiedOn,
      meterVerifyUntil: форма.meterVerifyUntil,
      serviceIntervalDays: форма.serviceIntervalDays === undefined
        ? undefined : Number(форма.serviceIntervalDays || 0),
      lastServiceOn: форма.lastServiceOn,
    }),
    onSuccess: () => {
      toast.success('Записано')
      setПравка(false); setФорма({})
      void qc.invalidateQueries({ queryKey: ['station-upkeep', companyId, location.id] })
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось записать'),
  })

  if (q.isLoading || !q.data) return null

  const d = q.data
  // Железки за точкой нет — писать поверку некуда, и молчать об этом нельзя:
  // иначе пустые поля читаются как «поверка не нужна».
  if (!d.hasUnit || !d.meter || !d.service) {
    return (
      <SectionCard title="Метрология и обслуживание" icon={Gauge}>
        <p className="text-xs text-muted-foreground">{d.note}</p>
      </SectionCard>
    )
  }

  const м = d.meter
  const т = d.service
  const поле = (k: string, текущее: string | number | null | undefined) =>
    форма[k] ?? (текущее === null || текущее === undefined ? '' : String(текущее))

  return (
    <SectionCard title="Метрология и обслуживание" icon={Gauge}
      action={
        <Button size="sm" variant="ghost" className="h-7 text-xs"
          onClick={() => { setПравка((v) => !v); setФорма({}) }}>
          {правка ? 'Отмена' : 'Править'}
        </Button>
      }>
      {!правка ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-md border border-border/50 px-3 py-2">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Gauge className="size-3.5" /> поверка счётчика
            </div>
            <div className={cn('mt-1 text-sm font-medium', СРОК[м.state])}>
              {м.verifyUntil ? `до ${дата(м.verifyUntil)}` : 'не заполнена'}
            </div>
            <div className="text-xs text-muted-foreground">
              {осталось(м)}
              {м.serial && ` · счётчик ${м.serial}`}
            </div>
          </div>
          <div className="rounded-md border border-border/50 px-3 py-2">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Wrench className="size-3.5" /> обслуживание
            </div>
            <div className={cn('mt-1 text-sm font-medium', СРОК[т.state])}>
              {т.nextOn ? `до ${дата(т.nextOn)}` : 'не проводилось'}
            </div>
            <div className="text-xs text-muted-foreground">
              {осталось(т)} · раз в {т.intervalDays} дн.
              {т.intervalDefault && ' (норматив типа)'}
            </div>
          </div>
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {([
            ['meterSerial', 'Заводской номер счётчика', 'text', м.serial],
            ['meterVerifiedOn', 'Дата поверки', 'date', м.verifiedOn],
            ['meterVerifyUntil', 'Поверка действительна до', 'date', м.verifyUntil],
            ['lastServiceOn', 'Последнее ТО', 'date', т.lastOn],
            ['serviceIntervalDays', 'Интервал ТО, дней', 'number',
             т.intervalDefault ? '' : т.intervalDays],
          ] as const).map(([k, подпись, тип, текущее]) => (
            <label key={k} className="space-y-1 text-xs text-muted-foreground">
              <span>{подпись}</span>
              <Input type={тип} value={поле(k, текущее)} className="h-8 text-sm"
                placeholder={k === 'serviceIntervalDays'
                  ? `по нормативу ${т.intervalDays}` : undefined}
                onChange={(e) => setФорма((f) => ({ ...f, [k]: e.target.value }))} />
            </label>
          ))}
          <div className="sm:col-span-2 flex justify-end">
            <Button size="sm" disabled={сохранить.isPending}
              onClick={() => сохранить.mutate()}>Записать</Button>
          </div>
        </div>
      )}
      <p className="mt-3 text-xs text-muted-foreground">{d.note}</p>
    </SectionCard>
  )
}

/**
 * Памятки к станции: своя, по марке, по разделу.
 *
 * Ключи составные (`ops_station:brand:Setec`), спрашиваются одним запросом через
 * запятую. Своё хранилище текстов у станции не заводится: правится памятка в
 * «Инфо», там же ей ставится привязка — и она появляется здесь у всех станций
 * этой марки разом.
 */
function NotesCard({ location }: { location: ServiceLocation }) {
  const { companyId } = useCompany()
  const [открыта, setОткрыта] = useState<string | null>(null)

  const марка = locationField(location, 'manufacturer')
  const модель = locationField(location, 'model')
  const ключи = [
    `ops_station:loc:${location.id}`,
    марка && `ops_station:brand:${марка}`,
    марка && модель && `ops_station:brand:${марка}:${модель}`,
    'ops_station',
  ].filter(Boolean).join(',')

  const q = useQuery({
    queryKey: ['station-notes', companyId, ключи],
    queryFn: () => getInfoContext(companyId, 'ops', ключи),
    enabled: !!companyId,
    staleTime: 300_000,
  })
  const текст = useQuery({
    queryKey: ['info-article', companyId, открыта],
    queryFn: () => getInfoArticle(companyId, открыта as string),
    enabled: !!открыта,
  })

  const статьи = q.data?.items ?? []

  return (
    <SectionCard title="Памятки" icon={BookOpen}
      action={<a href="/info" className="text-xs text-primary hover:underline">
        Завести в «Инфо»
      </a>}>
      {!статьи.length ? (
        <p className="text-xs text-muted-foreground">
          Памяток к этой станции{марка ? ` и к марке «${марка}»` : ''} пока нет.
          Статья в «Инфо» с привязкой к ключу{' '}
          <code className="rounded bg-muted px-1">ops_station:brand:{марка || 'Марка'}</code>{' '}
          появится здесь у всех станций этой марки.
        </p>
      ) : (
        <div className="-mx-2 rounded-md border border-border/40">
          {статьи.map((a) => (
            <div key={a.id} className="border-b border-border/40 last:border-0">
              <button type="button"
                onClick={() => setОткрыта((v) => (v === a.id ? null : a.id))}
                className="flex w-full items-start gap-2 px-2 py-2 text-left hover:bg-accent/30">
                <BookOpen className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="text-sm">{a.title}</div>
                  <div className="text-xs text-muted-foreground">
                    {a.kindLabel}
                    {a.exact && ' · про эту станцию'}
                    {a.summary && ` · ${a.summary}`}
                  </div>
                </div>
              </button>
              {открыта === a.id && (
                <div className="border-t border-border/30 bg-muted/20 px-3 py-3 text-sm">
                  {текст.isLoading || !текст.data
                    ? <Loader2 className="size-4 animate-spin text-muted-foreground" />
                    : <Markdown content={текст.data.bodyMd} />}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  )
}

export function CheckTab({ location }: { location: ServiceLocation }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()

  const q = useQuery({
    queryKey: ['station-check', companyId, location.id],
    queryFn: () => getStationCheck(companyId, location.id),
    enabled: !!companyId,
    staleTime: 30_000,
  })

  const отметка = useMutation({
    mutationFn: (v: { itemKey: string; state: string; note: string; file: File | null }) =>
      addStationCheck(companyId, location.id,
        { itemKey: v.itemKey, state: v.state, note: v.note || undefined }, v.file),
    onSuccess: () => {
      toast.success('Отметка записана')
      void qc.invalidateQueries({ queryKey: ['station-check', companyId, location.id] })
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось записать отметку'),
  })

  if (q.isLoading) {
    return <ScrollTab><div className="flex justify-center py-10">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div></ScrollTab>
  }
  if (q.error || !q.data) {
    return <ScrollTab><p className="text-sm text-muted-foreground">
      {(q.error as Error)?.message || 'Чек-лист недоступен'}
    </p></ScrollTab>
  }

  const t = q.data.totals

  return (
    <ScrollTab>
      <SectionCard title="Состояние станции по осмотру" icon={ClipboardCheck}
        action={t.lastCheck
          ? <span className="text-xs text-muted-foreground">последний осмотр {дата(t.lastCheck)}</span>
          : <Badge variant="outline" className="text-[10px] font-normal">осмотров не было</Badge>}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {([
            ['ok', 'в порядке', t.ok],
            ['stale', 'срок вышел', t.stale],
            ['fail', 'нарушения', t.fail],
            ['never', 'не проверяли', t.never],
          ] as const).map(([k, подпись, знач]) => (
            <div key={k} className="rounded-md border border-border/50 px-3 py-2">
              <div className={cn('text-xl font-semibold tabular-nums', ВЫВОД[k].cls)}>{знач}</div>
              <div className="text-xs text-muted-foreground">{подпись}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          {t.ok} из {t.counted} пунктов в порядке ({t.okPct} %).
          {t.na > 0 && ` Не применимо к этой станции: ${t.na}.`}
          {t.unconfirmed > 0 && ` Отметок без снимка: ${t.unconfirmed} — подтвердить нечем.`}
          {' '}«Не проверяли» — это не «исправно»: про такой пункт мы просто ничего не знаем.
        </p>
      </SectionCard>

      <UpkeepCard location={location} />

      {q.data.groups.map((г) => {
        const беда = г.items.filter((i) => i.verdict === 'fail').length
        return (
          <SectionCard key={г.code} title={г.label}
            icon={беда ? AlertTriangle : undefined}
            action={беда
              ? <span className="text-xs text-red-500">нарушений: {беда}</span>
              : undefined}>
            <div className="-mx-2 rounded-md border border-border/40">
              {г.items.map((i) => (
                <ItemRow key={i.key} пункт={i} занят={отметка.isPending}
                  отметить={(state, note, file) =>
                    отметка.mutate({ itemKey: i.key, state, note, file })} />
              ))}
            </div>
          </SectionCard>
        )
      })}

      <NotesCard location={location} />

      <p className="text-xs text-muted-foreground">{q.data.note}</p>
    </ScrollTab>
  )
}
