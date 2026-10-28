/**
 * «Новости рынка» — лента отрасли, очередь разбора и настройка источников.
 *
 * Три вида одного раздела, и они отвечают на разные вопросы:
 *   Лента      — что происходит вокруг сети. Читают глазами: обложка, заголовок,
 *                первые строки, издание и дата. Кнопок разбора здесь нет —
 *                чтение не должно соревноваться с работой.
 *   Разбор     — очередь нового: привязать к оператору, уточнить рубрику,
 *                оставить в ленте или отбросить как шум.
 *   Управление — откуда поток: источники, их рубрики, здоровье и словарь отбора.
 *
 * Почему у карточек есть обложка. Поисковая лента Bing отдаёт ссылку через свой
 * счётчик, но это обычный редирект: пройдя его, обход забирает со страницы
 * издания og:image, первые строки и признак видео. Google News так не умеет —
 * адрес издания зашифрован в токене (проверено 28.10.2026), — поэтому он заведён
 * отдельным видом источника «широкий невод»: заголовки без обложек.
 *
 * Карточка без обложки — нормальная карточка, а не сломанная: серой заглушки с
 * иконкой здесь нет, место занимают заголовок и лид.
 *
 * Разбор отделён от ленты, и кнопка «Шум» стоит ровно столько же, сколько
 * «Оставить в ленте»: в «Ангаре», где такой же конвейер работает с июня 2026,
 * треть собранного (40 материалов из 120) осталась в очереди именно потому, что
 * отклонить было так же трудоёмко, как принять.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Loader2, Newspaper, Play, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useCompany } from '@/contexts/CompanyContext'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import {
  createMarketNews, createMarketNewsSource, fetchMarketNews, getMarketNewsSettings,
  listMarketNews, listMarketNewsSources, listMarketOperators, patchMarketNews,
  patchMarketNewsSource, presetMarketNewsSources, putMarketNewsSettings,
  NEWS_CHANNEL_LABEL, NEWS_SOURCE_KIND_LABEL, NEWS_STATUS_LABEL, NEWS_TOPIC_LABEL,
  type MarketNewsItem, type MarketNewsSource, type MarketNewsTopic,
} from '@/services/marketService'

const ВИДЫ = [
  { k: 'feed', label: 'Лента' },
  { k: 'review', label: 'Разбор' },
  { k: 'admin', label: 'Управление' },
] as const

const ТЕМЫ = Object.keys(NEWS_TOPIC_LABEL) as MarketNewsTopic[]

/** Дата всегда с годом: «12 окт» через полгода не отличить от прошлогоднего. */
const дата = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' })

function когда(iso: string | null): string {
  if (!iso) return 'дата неизвестна'
  const d = new Date(iso)
  const дней = Math.floor((Date.now() - d.getTime()) / 86_400_000)
  const текст = дата.format(d)
  if (дней <= 0) return `${текст} · сегодня`
  if (дней === 1) return `${текст} · вчера`
  return дней < 14 ? `${текст} · ${дней} дн назад` : текст
}

/** Источник молчит дольше недели — факт, а не пустой экран. Считается вне рендера. */
function молчит(lastOkAt: string | null): boolean {
  return !lastOkAt || Date.now() - new Date(lastOkAt).getTime() > 7 * 86_400_000
}

/* ─────────────────────────── Лента ─────────────────────────── */

/**
 * Карточка материала: обложка, заголовок, первые строки, издание и дата.
 *
 * Вся карточка — ссылка на публикацию: в новостной ленте читатель метит в
 * заголовок и в картинку одинаково, и ссылка только на тексте заставляла бы
 * целиться.
 */
function NewsCard({ n }: { n: MarketNewsItem }) {
  const видео = n.media === 'video'
  return (
    <a href={n.url} target="_blank" rel="noopener noreferrer"
      className="group flex h-full flex-col overflow-hidden rounded-xl border border-border
                 bg-card transition-colors hover:border-primary/40
                 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
      {n.imageUrl && (
        <span className="relative block aspect-video overflow-hidden bg-muted">
          <img src={n.imageUrl} alt="" loading="lazy" referrerPolicy="no-referrer"
            className="size-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
            onError={(e) => { (e.currentTarget.parentElement as HTMLElement).hidden = true }} />
          {видео && (
            <span className="absolute bottom-2 left-2 flex items-center gap-1 rounded-md
                             bg-foreground/80 px-2 py-0.5 text-xs text-background">
              <Play className="size-3" aria-hidden /> видео
            </span>
          )}
        </span>
      )}
      <span className="flex flex-1 flex-col gap-2 p-4">
        <span className="flex items-start gap-1.5">
          <span className="font-headline text-sm font-semibold leading-snug group-hover:underline">
            {n.title}
          </span>
          <ExternalLink className="mt-1 size-3 shrink-0 text-muted-foreground" aria-hidden />
        </span>
        {n.snippet && (
          <span className="line-clamp-3 text-xs leading-relaxed text-muted-foreground">
            {n.snippet}
          </span>
        )}
        <span className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-xs
                         text-muted-foreground">
          <span className="font-medium text-foreground/80">
            {n.sourceName ?? n.sourceTitle ?? 'источник не указан'}
          </span>
          <span aria-hidden>·</span>
          <span>{когда(n.publishedAt)}</span>
          <span aria-hidden>·</span>
          <span>{NEWS_TOPIC_LABEL[n.topic] ?? n.topic}</span>
          {!n.imageUrl && видео && <span className="text-foreground/80">· видео</span>}
          {n.operatorName && (
            <>
              <span aria-hidden>·</span>
              <span className="text-foreground/80">{n.operatorName}</span>
            </>
          )}
          {n.region && <><span aria-hidden>·</span><span>{n.region}</span></>}
        </span>
      </span>
    </a>
  )
}

/* ─────────────────────────── Разбор ─────────────────────────── */

/** Строка очереди: прочитать, привязать, оставить или отбросить. */
function ReviewRow({ n, operators, onPatch, busy }: {
  n: MarketNewsItem
  operators: { id: string; name: string }[]
  onPatch: (id: string, body: Record<string, unknown>) => void
  busy: boolean
}) {
  const подсказка = n.suggested && !n.operatorId ? n.suggested : null
  return (
    <Card>
      <CardContent className="flex gap-3 p-3">
        {n.imageUrl && (
          <img src={n.imageUrl} alt="" loading="lazy" referrerPolicy="no-referrer"
            className="hidden size-20 shrink-0 rounded-md object-cover sm:block"
            onError={(e) => { e.currentTarget.hidden = true }} />
        )}
        <div className="min-w-0 flex-1 space-y-2">
          <a href={n.url} target="_blank" rel="noopener noreferrer"
            className="flex items-baseline gap-1.5 text-sm font-medium hover:underline">
            <span className="line-clamp-2">{n.title}</span>
            <ExternalLink className="mt-0.5 size-3 shrink-0 text-muted-foreground" aria-hidden />
          </a>
          {n.snippet && <p className="line-clamp-2 text-xs text-muted-foreground">{n.snippet}</p>}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{n.sourceName ?? n.sourceTitle ?? 'источник не указан'}</span>
            <span>{когда(n.publishedAt)}</span>
            <span>{NEWS_CHANNEL_LABEL[n.channel] ?? n.channel}</span>
            {n.media === 'video' && <span className="text-foreground/80">видео</span>}
            {n.status !== 'kept' && (
              <span className="text-warning-foreground">{NEWS_STATUS_LABEL[n.status]}</span>
            )}
          </div>
          {подсказка && (
            <p className="text-xs text-muted-foreground">
              Похоже на {подсказка.operatorName ?? подсказка.playerName}
              {подсказка.matched ? ` (совпало «${подсказка.matched}»)` : ''} — подтвердите, если так
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2" data-export-ignore>
            <Select value={n.operatorId ?? 'none'}
              onValueChange={(v) => onPatch(n.id, { operator_id: v === 'none' ? null : v })}>
              <SelectTrigger className="h-7 w-[220px] text-xs">
                <SelectValue placeholder="Чья новость" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">— без оператора —</SelectItem>
                {operators.map((o) => <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={n.topic} onValueChange={(v) => onPatch(n.id, { topic: v })}>
              <SelectTrigger className="h-7 w-[180px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {ТЕМЫ.map((t) => <SelectItem key={t} value={t}>{NEWS_TOPIC_LABEL[t]}</SelectItem>)}
              </SelectContent>
            </Select>
            {n.status !== 'kept' && (
              <Button size="sm" variant="outline" disabled={busy}
                onClick={() => onPatch(n.id, { status: 'kept' })}>Оставить в ленте</Button>
            )}
            {n.status !== 'noise' && (
              <Button size="sm" variant="ghost" disabled={busy}
                onClick={() => onPatch(n.id, { status: 'noise' })}>Шум</Button>
            )}
            {n.status === 'noise' && (
              <Button size="sm" variant="ghost" disabled={busy}
                onClick={() => onPatch(n.id, { status: 'new' })}>Вернуть в разбор</Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/* ─────────────────────── Управление источниками ─────────────────────── */

function SourceRow({ s, onToggle, onRun, onTopic, running }: {
  s: MarketNewsSource
  onToggle: (id: string, active: boolean) => void
  onRun: (id: string) => void
  onTopic: (id: string, topic: string | null) => void
  running: boolean
}) {
  const тихо = молчит(s.lastOkAt)
  return (
    <Card className={s.active ? '' : 'opacity-60'}>
      <CardContent className="space-y-1.5 p-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-sm font-medium">{s.title}</span>
          <span className="text-xs text-muted-foreground">
            {NEWS_SOURCE_KIND_LABEL[s.kind] ?? s.kind}
            {s.isProfile ? ' · профильный' : ''}
            {s.operatorName ? ` · ${s.operatorName}` : ''}
          </span>
        </div>
        <p className="break-all font-mono text-xs text-muted-foreground">{s.url}</p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span className="tabular-nums">новостей {s.newsTotal}</span>
          <span className={тихо ? 'text-warning-foreground' : 'text-muted-foreground'}>
            {s.lastOkAt ? `последний ответ ${когда(s.lastOkAt)}` : 'ещё не отвечал'}
          </span>
          {s.lastError && <span className="text-destructive">{s.lastError}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2" data-export-ignore>
          <Select value={s.defaultTopic ?? 'auto'}
            onValueChange={(v) => onTopic(s.id, v === 'auto' ? null : v)}>
            <SelectTrigger className="h-7 w-[200px] text-xs">
              <SelectValue placeholder="Рубрика источника" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">рубрика по заголовку</SelectItem>
              {ТЕМЫ.map((t) => <SelectItem key={t} value={t}>{NEWS_TOPIC_LABEL[t]}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button size="sm" variant="outline" disabled={running || !s.active}
            onClick={() => onRun(s.id)}>Обойти сейчас</Button>
          <Button size="sm" variant="ghost" onClick={() => onToggle(s.id, !s.active)}>
            {s.active ? 'Выключить' : 'Включить'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export function MarketNewsPanel() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const экран = useRef<HTMLDivElement>(null)
  const [подача, setПодача] = useState<string>('feed')
  const [тема, setТема] = useState('all')
  const [оператор, setОператор] = useState('all')
  const [поиск, setПоиск] = useState('')
  const [срок, setСрок] = useState('14')
  const [ручнойUrl, setРучнойUrl] = useState('')
  const [ручнойTitle, setРучнойTitle] = useState('')
  const [видИсточника, setВидИсточника] = useState('search')
  const [имяИсточника, setИмяИсточника] = useState('')
  const [адресИсточника, setАдресИсточника] = useState('')
  const [рубрикаИсточника, setРубрикаИсточника] = useState('auto')
  const [слова, setСлова] = useState<{ include: string; exclude: string } | null>(null)

  const лента = useQuery({
    queryKey: ['market-news', companyId, подача, тема, оператор, поиск],
    queryFn: () => listMarketNews(companyId, {
      status: подача === 'review' ? 'new' : ('feed' as never),
      ...(тема === 'all' ? {} : { topic: тема }),
      ...(оператор === 'all' ? {} : { operator_id: оператор }),
      ...(поиск.trim() ? { q: поиск.trim() } : {}),
      limit: 100,
    }),
    enabled: !!companyId && подача !== 'admin',
  })
  const источники = useQuery({
    queryKey: ['market-news-sources', companyId],
    queryFn: () => listMarketNewsSources(companyId),
    enabled: !!companyId,
  })
  const настройки = useQuery({
    queryKey: ['market-news-settings', companyId],
    queryFn: () => getMarketNewsSettings(companyId),
    enabled: !!companyId && подача === 'admin',
  })
  const операторы = useQuery({
    queryKey: ['market-operators-brief', companyId],
    queryFn: () => listMarketOperators(companyId),
    enabled: !!companyId,
  })

  const освежить = () => {
    qc.invalidateQueries({ queryKey: ['market-news', companyId] })
    qc.invalidateQueries({ queryKey: ['market-news-sources', companyId] })
  }
  const обход = useMutation({
    mutationFn: (sourceId?: string) => fetchMarketNews(companyId, {
      since_days: Number(срок), ...(sourceId ? { source_id: sourceId } : {}),
    }),
    onSuccess: освежить,
  })
  const правка = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      patchMarketNews(companyId, id, body),
    onSuccess: освежить,
  })
  const добавить = useMutation({
    mutationFn: () => createMarketNews(companyId, { title: ручнойTitle, url: ручнойUrl }),
    onSuccess: () => { setРучнойUrl(''); setРучнойTitle(''); освежить() },
  })
  const набор = useMutation({
    mutationFn: () => presetMarketNewsSources(companyId),
    onSuccess: освежить,
  })
  const датьИсточник = useMutation({
    mutationFn: () => createMarketNewsSource(companyId, {
      title: имяИсточника, kind: видИсточника, url: адресИсточника,
      is_profile: !видИсточника.startsWith('search'),
      ...(рубрикаИсточника === 'auto' ? {} : { default_topic: рубрикаИсточника }),
    }),
    onSuccess: () => { setИмяИсточника(''); setАдресИсточника(''); освежить() },
  })
  const правкаИсточника = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      patchMarketNewsSource(companyId, id, body),
    onSuccess: освежить,
  })
  const сохранитьСловарь = useMutation({
    mutationFn: () => putMarketNewsSettings(companyId, {
      include_words: (слова?.include ?? '').split('\n').map((w) => w.trim()).filter(Boolean),
      exclude_words: (слова?.exclude ?? '').split('\n').map((w) => w.trim()).filter(Boolean),
      since_days: Number(срок),
    }),
    onSuccess: () => {
      setСлова(null)
      qc.invalidateQueries({ queryKey: ['market-news-settings', companyId] })
      освежить()
    },
  })

  const rows = лента.data?.news ?? []
  const counts = лента.data?.counts
  const ops = (операторы.data?.operators ?? []).map((o) => ({ id: o.id, name: o.name }))
  const byTopic = лента.data?.byTopic ?? {}
  const результат = обход.data
  const список = источники.data?.sources ?? []
  // Поля словаря показывают действующий отбор: свой, если он задан, иначе встроенный.
  // Пока человек их не трогал, сохранять нечего — кнопка недоступна.
  const текСлова = слова ?? {
    include: (настройки.data?.includeWords?.length
      ? настройки.data.includeWords : настройки.data?.defaultInclude ?? []).join('\n'),
    exclude: (настройки.data?.excludeWords?.length
      ? настройки.data.excludeWords : настройки.data?.defaultExclude ?? []).join('\n'),
  }

  return (
    <div ref={экран} className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Newspaper className="size-4 text-primary" aria-hidden />
            {counts
              ? `В ленте ${counts.kept + counts.new}, из них неразобранных ${counts.new}, отброшено ${counts.noise}`
              : 'Новости рынка'}
          </span>
          {подача !== 'admin' && (
            <span className="flex flex-wrap items-center gap-1" data-export-ignore>
              <Button size="sm" variant={тема === 'all' ? 'default' : 'outline'}
                className="h-7 text-xs" onClick={() => setТема('all')}>Все темы</Button>
              {ТЕМЫ.filter((t) => byTopic[t]).map((t) => (
                <Button key={t} size="sm" variant={тема === t ? 'default' : 'outline'}
                  className="h-7 text-xs" onClick={() => setТема(тема === t ? 'all' : t)}>
                  {NEWS_TOPIC_LABEL[t]} {byTopic[t]}
                </Button>
              ))}
            </span>
          )}
          <span className="ml-auto" data-export-ignore>
            <PanelViewTabs tabs={ВИДЫ} value={подача} onChange={setПодача} />
          </span>
          <span data-export-ignore>
            <ExportButton title="Новости рынка"
              subtitle={`${rows.length} материалов${тема === 'all' ? '' : ` · ${NEWS_TOPIC_LABEL[тема as MarketNewsTopic]}`}`}
              getEl={() => экран.current} />
          </span>
          <table hidden {...exportRows('Новости рынка', [
            'Дата', 'Заголовок', 'Издание', 'Тема', 'Оператор', 'Регион',
            'Состояние', 'Как получено', 'Ссылка',
          ], rows.map((n) => [
            n.publishedAt ? дата.format(new Date(n.publishedAt)) : '',
            n.title, n.sourceName, NEWS_TOPIC_LABEL[n.topic] ?? n.topic,
            n.operatorName ?? n.playerName, n.region,
            NEWS_STATUS_LABEL[n.status], NEWS_CHANNEL_LABEL[n.channel] ?? n.channel, n.url,
          ]))} />
        </CardContent>
      </Card>

      {подача !== 'admin' && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-2 p-3">
            <Input value={поиск} onChange={(e) => setПоиск(e.target.value)}
              placeholder="Поиск по заголовку" className="h-8 w-[260px] text-xs" />
            <Select value={оператор} onValueChange={setОператор}>
              <SelectTrigger className="h-8 w-[240px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любой оператор</SelectItem>
                {ops.map((o) => <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={срок} onValueChange={setСрок}>
              <SelectTrigger className="h-8 w-[170px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="7">за неделю</SelectItem>
                <SelectItem value="14">за две недели</SelectItem>
                <SelectItem value="30">за месяц</SelectItem>
                <SelectItem value="90">за три месяца</SelectItem>
              </SelectContent>
            </Select>
            <Button size="sm" variant="outline" disabled={обход.isPending}
              onClick={() => обход.mutate(undefined)}>
              {обход.isPending
                ? <><Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden />Обходим источники…</>
                : <><RefreshCw className="mr-1.5 size-3.5" aria-hidden />Обновить из источников</>}
            </Button>
            {результат && (
              <span className="text-xs text-muted-foreground">
                {результат.note
                  ?? `принесено ${результат.added}`
                    + (результат.sources.some((s) => s.error)
                      ? `, с ошибкой источников: ${результат.sources.filter((s) => s.error).length}`
                      : '')
                    + (результат.pending
                      ? `, осталось обойти ${результат.pending} — нажмите ещё раз`
                      : '')}
              </span>
            )}
          </CardContent>
        </Card>
      )}

      {подача === 'admin' ? (
        <div className="min-h-0 flex-1 space-y-3 overflow-auto">
          <Card>
            <CardContent className="space-y-3 p-3">
              <div className="flex flex-wrap items-end gap-2">
                <Input value={имяИсточника} onChange={(e) => setИмяИсточника(e.target.value)}
                  placeholder="Название: «Пункт Е — публикации»" className="h-8 w-[240px] text-xs" />
                <Select value={видИсточника} onValueChange={setВидИсточника}>
                  <SelectTrigger className="h-8 w-[230px] text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(NEWS_SOURCE_KIND_LABEL).map(([k, label]) => (
                      <SelectItem key={k} value={k}>{label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={рубрикаИсточника} onValueChange={setРубрикаИсточника}>
                  <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">рубрика по заголовку</SelectItem>
                    {ТЕМЫ.map((t) => <SelectItem key={t} value={t}>{NEWS_TOPIC_LABEL[t]}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Input value={адресИсточника} onChange={(e) => setАдресИсточника(e.target.value)}
                  placeholder={видИсточника.startsWith('search')
                    ? 'Запрос: site:punkt-e.ru или «зарядная станция» Забайкальский край'
                    : 'https://… адрес ленты или страницы новостей'}
                  className="h-8 w-[400px] text-xs" />
                <Button size="sm" disabled={!имяИсточника || !адресИсточника || датьИсточник.isPending}
                  onClick={() => датьИсточник.mutate()}>Добавить источник</Button>
                <Button size="sm" variant="outline" disabled={набор.isPending}
                  onClick={() => набор.mutate()}>
                  {набор.isPending ? 'Ставим набор…' : 'Поставить базовый набор'}
                </Button>
                <Button size="sm" variant="outline" disabled={обход.isPending}
                  onClick={() => обход.mutate(undefined)}>
                  {обход.isPending ? 'Обходим…' : 'Обойти все источники'}
                </Button>
              </div>
              {датьИсточник.isError && (
                <p role="alert" className="text-xs text-destructive">
                  {(датьИсточник.error as Error).message}
                </p>
              )}
              {набор.data && (
                <p className="text-xs text-muted-foreground">
                  добавлено источников: {набор.data.added}
                </p>
              )}
              {результат && (
                <p className="text-xs text-muted-foreground">
                  принесено {результат.added}
                  {результат.pending ? `, осталось обойти ${результат.pending}` : ''}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-2 p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-medium">Словарь отбора</span>
                <span className="text-xs text-muted-foreground">
                  по одному слову в строке; пусто — встроенный словарь
                  {настройки.data?.updatedBy ? ` · правил ${настройки.data.updatedBy}` : ''}
                </span>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <label className="space-y-1 text-xs">
                  <span className="text-muted-foreground">Берём материал, если встретилось</span>
                  <Textarea rows={6} className="font-mono text-xs" value={текСлова.include}
                    onChange={(e) => setСлова({ ...текСлова, include: e.target.value })} />
                </label>
                <label className="space-y-1 text-xs">
                  <span className="text-muted-foreground">Отбрасываем, если встретилось</span>
                  <Textarea rows={6} className="font-mono text-xs" value={текСлова.exclude}
                    onChange={(e) => setСлова({ ...текСлова, exclude: e.target.value })} />
                </label>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" disabled={слова === null || сохранитьСловарь.isPending}
                  onClick={() => сохранитьСловарь.mutate()}>Сохранить словарь</Button>
                <span className="text-xs text-muted-foreground">
                  Профильный источник проходит словарь целиком — у него одна тема.
                </span>
              </div>
            </CardContent>
          </Card>

          {список.length === 0 && !источники.isLoading && (
            <p className="p-2 text-sm text-muted-foreground">
              Источников нет — нажмите «Поставить базовый набор».
            </p>
          )}
          {список.map((s) => (
            <SourceRow key={s.id} s={s} running={обход.isPending}
              onRun={(id) => обход.mutate(id)}
              onTopic={(id, topic) => правкаИсточника.mutate({ id, body: { default_topic: topic } })}
              onToggle={(id, active) => правкаИсточника.mutate({ id, body: { active } })} />
          ))}
        </div>
      ) : подача === 'review' ? (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          <Card>
            <CardContent className="flex flex-wrap items-center gap-2 p-3">
              <Input value={ручнойUrl} onChange={(e) => setРучнойUrl(e.target.value)}
                placeholder="Ссылка на материал, который принесли руками"
                className="h-8 w-[360px] text-xs" />
              <Input value={ручнойTitle} onChange={(e) => setРучнойTitle(e.target.value)}
                placeholder="Заголовок" className="h-8 w-[300px] text-xs" />
              <Button size="sm" disabled={!ручнойUrl || !ручнойTitle || добавить.isPending}
                onClick={() => добавить.mutate()}>Добавить новость</Button>
              {добавить.isError && (
                <span role="alert" className="text-xs text-destructive">
                  {(добавить.error as Error).message}
                </span>
              )}
            </CardContent>
          </Card>
          {лента.isLoading && (
            <p className="flex items-center gap-2 p-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden /> Загружаем очередь…
            </p>
          )}
          {!лента.isLoading && rows.length === 0 && (
            <p className="p-2 text-sm text-muted-foreground">Очередь разбора пуста — всё разобрано.</p>
          )}
          {rows.map((n) => (
            <ReviewRow key={n.id} n={n} operators={ops}
              busy={правка.isPending && правка.variables?.id === n.id}
              onPatch={(id, body) => правка.mutate({ id, body })} />
          ))}
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto">
          {лента.isLoading && (
            <p className="flex items-center gap-2 p-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden /> Загружаем ленту…
            </p>
          )}
          {!лента.isLoading && rows.length === 0 && (
            <p className="p-2 text-sm text-muted-foreground">
              Лента пуста — нажмите «Обновить из источников»; сами источники
              настраиваются во вкладке «Управление».
            </p>
          )}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {rows.map((n) => <NewsCard key={n.id} n={n} />)}
          </div>
          {(лента.data?.total ?? 0) > rows.length && (
            <p className="p-2 text-xs text-muted-foreground">
              Показаны первые {rows.length} из {лента.data?.total}. Сузьте отбор темой,
              оператором или поиском.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
