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
import {
  ChevronDown, ChevronUp, ExternalLink, Loader2, Newspaper, RefreshCw, SlidersHorizontal,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useCompany } from '@/contexts/CompanyContext'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import {
  NewsBrief, NewsCard, NewsHero, NewsRow, StripTitle,
} from './MarketNewsFeed'
import {
  ActorsAdmin, LinkRow, NoActors, ParticipantRow, RoleFilter,
} from './MarketNewsActors'
import {
  createMarketActor, createMarketNews, createMarketNewsSource, fetchMarketNews,
  getMarketLinks, getMarketNewsSettings, getMarketParticipants, listMarketActors,
  patchMarketActor, rescanMarketMentions,
  ACTOR_KIND_LABEL,
  listMarketNews, listMarketNewsSources, listMarketOperators, patchMarketNews,
  patchMarketNewsSource, presetMarketNewsSources, putMarketNewsSettings,
  NEWS_CHANNEL_LABEL, NEWS_SOURCE_KIND_LABEL, NEWS_STATUS_LABEL, NEWS_TOPIC_LABEL,
  type MarketNewsItem, type MarketNewsSource, type MarketNewsTopic,
} from '@/services/marketService'

const ВИДЫ = [
  { k: 'feed', label: 'Лента' },
  { k: 'actors', label: 'Участники' },
  { k: 'links', label: 'Связи' },
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
  // Свёрнутая панель отдаёт ленте весь экран. Выбор запоминается: человек,
  // который читает ленту во весь экран, читает её так каждый раз.
  const [панель, setПанель] = useState<boolean>(() => {
    try { return localStorage.getItem('market-news-panel') !== 'off' } catch { return true }
  })
  const переключитьПанель = (открыта: boolean) => {
    setПанель(открыта)
    try { localStorage.setItem('market-news-panel', открыта ? 'on' : 'off') } catch { /* не критично */ }
  }
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
  // Разрезы по участникам: роль, выбранный участник и окно наблюдения.
  const [роль, setРоль] = useState('all')
  const [участник, setУчастник] = useState('')
  const [окно, setОкно] = useState('180')
  const [имяУчастника, setИмяУчастника] = useState('')
  const [видУчастника, setВидУчастника] = useState('vendor')
  const [псевдонимы, setПсевдонимы] = useState('')

  const лента = useQuery({
    queryKey: ['market-news', companyId, подача, тема, оператор, поиск, участник, роль],
    queryFn: () => listMarketNews(companyId, {
      status: подача === 'review' ? 'new' : ('feed' as never),
      ...(тема === 'all' ? {} : { topic: тема }),
      ...(оператор === 'all' ? {} : { operator_id: оператор }),
      ...(поиск.trim() ? { q: поиск.trim() } : {}),
      ...(участник ? { mention: участник } : {}),
      ...(роль === 'all' ? {} : { role: роль }),
      limit: 100,
    }),
    enabled: !!companyId && (подача === 'feed' || подача === 'review'),
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
  const участники = useQuery({
    queryKey: ['market-news-participants', companyId, роль, окно],
    queryFn: () => getMarketParticipants(companyId, {
      ...(роль === 'all' ? {} : { role: роль }), days: Number(окно),
    }),
    enabled: !!companyId && подача === 'actors',
  })
  const связи = useQuery({
    queryKey: ['market-news-links', companyId, роль, участник, окно],
    queryFn: () => getMarketLinks(companyId, {
      ...(роль === 'all' ? {} : { role: роль }),
      ...(участник ? { name: участник } : {}), days: Number(окно),
    }),
    enabled: !!companyId && подача === 'links',
  })
  const справочник = useQuery({
    queryKey: ['market-actors', companyId],
    queryFn: () => listMarketActors(companyId),
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
  const освежитьРазрезы = () => {
    qc.invalidateQueries({ queryKey: ['market-news-participants', companyId] })
    qc.invalidateQueries({ queryKey: ['market-news-links', companyId] })
    qc.invalidateQueries({ queryKey: ['market-actors', companyId] })
  }
  const датьУчастника = useMutation({
    mutationFn: () => createMarketActor(companyId, {
      name: имяУчастника, kind: видУчастника,
      aliases: псевдонимы.split(',').map((w) => w.trim()).filter(Boolean),
    }),
    onSuccess: () => { setИмяУчастника(''); setПсевдонимы(''); освежитьРазрезы() },
  })
  const правкаУчастника = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      patchMarketActor(companyId, id, body),
    onSuccess: освежитьРазрезы,
  })
  const перечитать = useMutation({
    mutationFn: () => rescanMarketMentions(companyId),
    onSuccess: () => { освежитьРазрезы(); освежить() },
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
  // Позиция в потоке и есть роль материала (как на главной «Ангара»): герой,
  // четыре строки «Свежего», пять заголовков «Коротко», остальное — карточками.
  // Героем не делаем материал без обложки: баннер был бы пустым.
  const герой = rows.find((n) => n.imageUrl) ?? rows[0] ?? null
  const остальные = rows.filter((n) => n.id !== герой?.id)
  const свежее = остальные.slice(0, 4)
  const коротко = остальные.slice(4, 9)
  const поток = остальные.slice(9)
  const counts = лента.data?.counts
  const ops = (операторы.data?.operators ?? []).map((o) => ({ id: o.id, name: o.name }))
  const byTopic = лента.data?.byTopic ?? {}
  const результат = обход.data
  const связиРоли = Object.fromEntries(
    (связи.data?.links ?? []).flatMap((l) => [l.a.role, l.b.role]).map((r) => [r, 1]))
  const отборов = [тема !== 'all', оператор !== 'all', !!поиск.trim()].filter(Boolean).length
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
      {!панель && (
        <div className="flex items-center justify-end gap-2" data-export-ignore>
          <PanelViewTabs tabs={ВИДЫ} value={подача} onChange={setПодача} />
          <Button size="sm" variant="ghost" className="h-7 text-xs"
            onClick={() => переключитьПанель(true)}>
            <ChevronDown className="mr-1.5 size-3.5" aria-hidden /> Панель
          </Button>
        </div>
      )}

      {панель && (
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
          <span className="ml-auto flex flex-wrap items-center gap-2" data-export-ignore>
            {(подача === 'feed' || подача === 'review') && (
              <>
                {/* Поля отбора занимали полосу над лентой и отодвигали новости за
                    край экрана: в свёрнутом виде кнопка называет число действующих
                    отборов, развёрнутый вид — те же поля одной строкой. */}
                <Popover>
                  <PopoverTrigger asChild>
                    <Button size="sm" variant={отборов ? 'default' : 'outline'} className="h-7 text-xs">
                      <SlidersHorizontal className="mr-1.5 size-3.5" aria-hidden />
                      Отбор{отборов ? ` · ${отборов}` : ''}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="end" className="w-[320px] space-y-2">
                    <Input value={поиск} onChange={(e) => setПоиск(e.target.value)}
                      placeholder="Поиск по заголовку" className="h-8 text-xs" />
                    <Select value={оператор} onValueChange={setОператор}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">Любой оператор</SelectItem>
                        {ops.map((o) => <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Select value={срок} onValueChange={setСрок}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="7">за неделю</SelectItem>
                        <SelectItem value="14">за две недели</SelectItem>
                        <SelectItem value="30">за месяц</SelectItem>
                        <SelectItem value="90">за три месяца</SelectItem>
                      </SelectContent>
                    </Select>
                    {отборов > 0 && (
                      <Button size="sm" variant="ghost" className="h-7 w-full text-xs"
                        onClick={() => { setПоиск(''); setОператор('all'); setТема('all') }}>
                        Сбросить отбор
                      </Button>
                    )}
                  </PopoverContent>
                </Popover>
                <Button size="sm" variant="outline" className="h-7 text-xs" disabled={обход.isPending}
                  onClick={() => обход.mutate(undefined)}>
                  {обход.isPending
                    ? <><Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden />Обходим…</>
                    : <><RefreshCw className="mr-1.5 size-3.5" aria-hidden />Обновить</>}
                </Button>
              </>
            )}
            <PanelViewTabs tabs={ВИДЫ} value={подача} onChange={setПодача} />
            <Button size="sm" variant="ghost" className="h-7 text-xs"
              onClick={() => переключитьПанель(false)}>
              <ChevronUp className="mr-1.5 size-3.5" aria-hidden /> Свернуть панель
            </Button>
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
      )}


      {результат && подача !== 'admin' && (
        <p className="-mt-1 px-1 text-xs text-muted-foreground">
          {результат.note
            ?? `принесено ${результат.added}`
              + (результат.sources.some((s) => s.error)
                ? `, с ошибкой источников: ${результат.sources.filter((s) => s.error).length}`
                : '')
              + (результат.pending
                ? `, в эту порцию не вошло ${результат.pending} — нажмите ещё раз`
                : '')}
        </p>
      )}

      {(подача === 'actors' || подача === 'links') && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
            <RoleFilter value={роль} counts={участники.data?.byRole ?? связиРоли}
              onChange={setРоль} />
            <Input value={участник} onChange={(e) => setУчастник(e.target.value)}
              placeholder="Участник: «Парус электро»" className="h-8 w-[220px] text-xs" />
            <Select value={окно} onValueChange={setОкно}>
              <SelectTrigger className="h-8 w-[180px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="30">за месяц</SelectItem>
                <SelectItem value="90">за три месяца</SelectItem>
                <SelectItem value="180">за полгода</SelectItem>
                <SelectItem value="365">за год</SelectItem>
              </SelectContent>
            </Select>
            {(роль !== 'all' || участник) && (
              <Button size="sm" variant="ghost" className="h-7 text-xs"
                onClick={() => { setРоль('all'); setУчастник('') }}>Сбросить</Button>
            )}
          </CardContent>
        </Card>
      )}

      {подача === 'actors' ? (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          {участники.isLoading && (
            <p className="flex items-center gap-2 p-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden /> Считаем участников…
            </p>
          )}
          {!участники.isLoading && (участники.data?.participants.length ?? 0) === 0 && (
            <NoActors kind="participants" />
          )}
          {(участники.data?.participants ?? [])
            .filter((p) => !участник || p.name.toLowerCase().includes(участник.toLowerCase()))
            .map((p) => (
              <ParticipantRow key={`${p.role}:${p.name}`} p={p}
                onNews={(имя) => { setУчастник(имя); setПодача('feed') }}
                onLinks={(имя) => { setУчастник(имя); setПодача('links') }} />
            ))}
        </div>
      ) : подача === 'links' ? (
        <div className="min-h-0 flex-1 space-y-2 overflow-auto">
          {связи.isLoading && (
            <p className="flex items-center gap-2 p-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden /> Ищем связи…
            </p>
          )}
          {!связи.isLoading && (связи.data?.links.length ?? 0) === 0 && <NoActors kind="links" />}
          {(связи.data?.links ?? []).map((l) => (
            <LinkRow key={`${l.a.name}|${l.b.name}`} l={l}
              onNews={(имя) => { setУчастник(имя); setПодача('feed') }} />
          ))}
          {(связи.data?.total ?? 0) > (связи.data?.links.length ?? 0) && (
            <p className="p-2 text-xs text-muted-foreground">
              Показаны первые {связи.data?.links.length} из {связи.data?.total} связей.
            </p>
          )}
        </div>
      ) : подача === 'admin' ? (
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
                  {результат.pending ? `, в эту порцию не вошло ${результат.pending}` : ''}
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

          <Card>
            <CardContent className="flex flex-wrap items-end gap-2 p-3">
              <Input value={имяУчастника} onChange={(e) => setИмяУчастника(e.target.value)}
                placeholder="Участник рынка: «Парус электро»" className="h-8 w-[260px] text-xs" />
              <Select value={видУчастника} onValueChange={setВидУчастника}>
                <SelectTrigger className="h-8 w-[240px] text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(ACTOR_KIND_LABEL).map(([k, label]) => (
                    <SelectItem key={k} value={k}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input value={псевдонимы} onChange={(e) => setПсевдонимы(e.target.value)}
                placeholder="Как ещё пишут, через запятую: Парус-электро, ПАРУС ЭЛЕКТРО"
                className="h-8 w-[380px] text-xs" />
              <Button size="sm" disabled={!имяУчастника || датьУчастника.isPending}
                onClick={() => датьУчастника.mutate()}>Добавить участника</Button>
              {датьУчастника.isError && (
                <span role="alert" className="text-xs text-destructive">
                  {(датьУчастника.error as Error).message}
                </span>
              )}
            </CardContent>
          </Card>

          <ActorsAdmin actors={справочник.data?.actors ?? []} loading={справочник.isLoading}
            onPatch={(id, body) => правкаУчастника.mutate({ id, body })}
            onRescan={() => перечитать.mutate()} rescanning={перечитать.isPending}
            rescanResult={перечитать.data} />

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
        <div className="min-h-0 flex-1 space-y-6 overflow-auto">
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

          {герой && <NewsHero n={герой} />}

          {rows.length > 1 && (
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
              <section className="space-y-7">
                {свежее.length > 0 && (
                  <div>
                    <StripTitle>Свежее</StripTitle>
                    {свежее.map((n) => <NewsRow key={n.id} n={n} />)}
                  </div>
                )}
                {поток.length > 0 && (
                  <div>
                    <StripTitle>Материалы</StripTitle>
                    <div className="grid gap-4 sm:grid-cols-2">
                      {поток.map((n) => <NewsCard key={n.id} n={n} />)}
                    </div>
                  </div>
                )}
              </section>

              <aside className="space-y-6 lg:sticky lg:top-2">
                {коротко.length > 0 && (
                  <div>
                    <StripTitle>Коротко</StripTitle>
                    {коротко.map((n) => <NewsBrief key={n.id} n={n} />)}
                  </div>
                )}
                <div>
                  <StripTitle>Источники</StripTitle>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {список.length === 0
                      ? 'Ни одного источника. Во вкладке «Управление» есть базовый набор.'
                      : `Лент и запросов: ${список.length}, из них работают ${
                          список.filter((s) => s.active).length}. Молчат дольше недели: ${
                          список.filter((s) => молчит(s.lastOkAt)).length}.`}
                  </p>
                  {список.filter((s) => s.lastError).slice(0, 3).map((s) => (
                    <p key={s.id} className="mt-2 text-xs text-destructive">
                      {s.title}: {s.lastError}
                    </p>
                  ))}
                </div>
              </aside>
            </div>
          )}

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
