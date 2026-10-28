/**
 * «Новости рынка» — общая лента отрасли и разбор материалов.
 *
 * Лента — главный вид: её открывают, чтобы прочитать, что происходит вокруг сети.
 * Привязка к оператору, региону и точке делается из той же карточки — отдельного
 * экрана «привязок» нет, потому что привязывают ровно то, что сейчас читают.
 *
 * Разбор отделён от ленты одной кнопкой «Шум», и она стоит ровно столько же,
 * сколько «В ленту». Так сделано осознанно: в «Ангаре», где такой же конвейер
 * работает с июня 2026, треть собранного (40 материалов из 120) так и осталась в
 * очереди review — отклонить было так же трудоёмко, как принять.
 *
 * Источники показаны здесь же, вместе со своим здоровьем. Молчание ленты — факт:
 * обход «Ангара» встал на месяц, когда упал контейнер бота, и этого никто не
 * заметил, потому что нигде не было видно «источник не отвечает».
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Loader2, Newspaper, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { exportRows } from '@/components/workspace/analytics/exportRows'
import {
  createMarketNews, createMarketNewsSource, fetchMarketNews, listMarketNews,
  listMarketNewsSources, listMarketOperators, patchMarketNews, patchMarketNewsSource,
  presetMarketNewsSources,
  NEWS_CHANNEL_LABEL, NEWS_SOURCE_KIND_LABEL, NEWS_STATUS_LABEL, NEWS_TOPIC_LABEL,
  type MarketNewsItem, type MarketNewsSource, type MarketNewsTopic,
} from '@/services/marketService'

const ВИДЫ = [
  { k: 'feed', label: 'Лента' },
  { k: 'review', label: 'Разбор' },
  { k: 'sources', label: 'Источники' },
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

/** Источник молчит дольше недели — это факт, а не пустой экран.
 *  Считается вне компонента: `Date.now()` в рендере даёт нестабильный результат. */
function молчит(lastOkAt: string | null): boolean {
  return !lastOkAt || Date.now() - new Date(lastOkAt).getTime() > 7 * 86_400_000
}

/** Карточка новости: сначала читаемое, потом происхождение, потом разбор. */
function NewsCard({ n, operators, onPatch, busy }: {
  n: MarketNewsItem
  operators: { id: string; name: string }[]
  onPatch: (id: string, body: Record<string, unknown>) => void
  busy: boolean
}) {
  const подсказка = n.suggested && !n.operatorId ? n.suggested : null
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <a href={n.url} target="_blank" rel="noopener noreferrer"
          className="flex items-baseline gap-1.5 text-sm font-medium hover:underline">
          <span>{n.title}</span>
          <ExternalLink className="mt-0.5 size-3 shrink-0 text-muted-foreground" aria-hidden />
        </a>
        {n.snippet && <p className="line-clamp-2 text-xs text-muted-foreground">{n.snippet}</p>}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>{n.sourceName ?? n.sourceTitle ?? 'источник не указан'}</span>
          <span>{когда(n.publishedAt)}</span>
          <span>{NEWS_TOPIC_LABEL[n.topic] ?? n.topic}</span>
          <span>{NEWS_CHANNEL_LABEL[n.channel] ?? n.channel}</span>
          {n.operatorName && <span className="text-foreground">{n.operatorName}</span>}
          {n.playerName && !n.operatorName && <span className="text-foreground">{n.playerName}</span>}
          {n.region && <span>{n.region}</span>}
          {n.status !== 'kept' && (
            <span className="text-warning-foreground">{NEWS_STATUS_LABEL[n.status]}</span>
          )}
        </div>
        {/* Подсказка разбора названа подсказкой: совпадение слова в заголовке не
            делает новость новостью этой компании (docs/MARKET.md, принцип 2). */}
        {подсказка && (
          <p className="text-xs text-muted-foreground">
            Похоже на {подсказка.operatorName ?? подсказка.playerName}
            {подсказка.matched ? ` (совпало «${подсказка.matched}»)` : ''} — подтвердите, если так
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2" data-export-ignore>
          <Select value={n.operatorId ?? 'none'}
            onValueChange={(v) => onPatch(n.id, { operator_id: v === 'none' ? null : v })}>
            <SelectTrigger className="h-7 w-[220px] text-xs"><SelectValue placeholder="Чья новость" /></SelectTrigger>
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
              onClick={() => onPatch(n.id, { status: 'kept' })}>В ленту</Button>
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
      </CardContent>
    </Card>
  )
}

/** Источник: что это, когда отвечал в последний раз и сколько принёс. */
function SourceCard({ s, onToggle, onRun, running }: {
  s: MarketNewsSource
  onToggle: (id: string, active: boolean) => void
  onRun: (id: string) => void
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
        <p className="break-all text-xs text-muted-foreground">{s.url}</p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span className="tabular-nums">новостей {s.newsTotal}</span>
          <span className={тихо ? 'text-warning-foreground' : 'text-muted-foreground'}>
            {s.lastOkAt ? `последний ответ ${когда(s.lastOkAt)}` : 'ещё не отвечал'}
          </span>
          {s.lastError && <span className="text-destructive">{s.lastError}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2" data-export-ignore>
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
  // Добавление вручную: новость из канала или с выставки — тоже наблюдение.
  const [ручнойUrl, setРучнойUrl] = useState('')
  const [ручнойTitle, setРучнойTitle] = useState('')
  // Новый источник.
  const [видИсточника, setВидИсточника] = useState('search')
  const [имяИсточника, setИмяИсточника] = useState('')
  const [адресИсточника, setАдресИсточника] = useState('')

  const лента = useQuery({
    queryKey: ['market-news', companyId, подача, тема, оператор, поиск],
    queryFn: () => listMarketNews(companyId, {
      status: подача === 'review' ? 'new' : ('feed' as never),
      ...(тема === 'all' ? {} : { topic: тема }),
      ...(оператор === 'all' ? {} : { operator_id: оператор }),
      ...(поиск.trim() ? { q: поиск.trim() } : {}),
      limit: 100,
    }),
    enabled: !!companyId && подача !== 'sources',
  })
  const источники = useQuery({
    queryKey: ['market-news-sources', companyId],
    queryFn: () => listMarketNewsSources(companyId),
    enabled: !!companyId,
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
  const датьИсточник = useMutation({
    mutationFn: () => createMarketNewsSource(companyId, {
      title: имяИсточника, kind: видИсточника, url: адресИсточника,
      is_profile: видИсточника !== 'search',
    }),
    onSuccess: () => { setИмяИсточника(''); setАдресИсточника(''); освежить() },
  })
  const набор = useMutation({
    mutationFn: () => presetMarketNewsSources(companyId),
    onSuccess: освежить,
  })
  const переключить = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      patchMarketNewsSource(companyId, id, { active }),
    onSuccess: освежить,
  })

  const rows = лента.data?.news ?? []
  const counts = лента.data?.counts
  const ops = (операторы.data?.operators ?? []).map((o) => ({ id: o.id, name: o.name }))
  const byTopic = лента.data?.byTopic ?? {}
  const результат = обход.data

  return (
    <div ref={экран} className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Newspaper className="size-4 text-primary" aria-hidden />
            {counts
              ? `В ленте ${counts.kept}, в разборе ${counts.new}, отброшено ${counts.noise}`
              : 'Новости рынка'}
          </span>
          {/* Плитки темы — они же отборы (канон экранов-отчётов). */}
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

      {подача !== 'sources' && (
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

      {подача === 'sources' ? (
        <>
          <Card>
            <CardContent className="flex flex-wrap items-end gap-2 p-3">
              <Input value={имяИсточника} onChange={(e) => setИмяИсточника(e.target.value)}
                placeholder="Название: «Пункт Е — пресс-релизы»" className="h-8 w-[260px] text-xs" />
              <Select value={видИсточника} onValueChange={setВидИсточника}>
                <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(NEWS_SOURCE_KIND_LABEL).map(([k, label]) => (
                    <SelectItem key={k} value={k}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input value={адресИсточника} onChange={(e) => setАдресИсточника(e.target.value)}
                placeholder={видИсточника === 'search'
                  ? 'Запрос: site:punkt-e.ru или «зарядная станция» Забайкальский край'
                  : 'https://… адрес ленты или страницы новостей'}
                className="h-8 w-[420px] text-xs" />
              <Button size="sm" disabled={!имяИсточника || !адресИсточника || датьИсточник.isPending}
                onClick={() => датьИсточник.mutate()}>Добавить источник</Button>
              <Button size="sm" variant="outline" disabled={набор.isPending}
                onClick={() => набор.mutate()}>
                {набор.isPending ? 'Ставим набор…' : 'Поставить базовый набор'}
              </Button>
              {набор.data && (
                <span className="text-xs text-muted-foreground">
                  добавлено источников: {набор.data.added}
                </span>
              )}
              {датьИсточник.isError && (
                <span role="alert" className="text-xs text-destructive">
                  {(датьИсточник.error as Error).message}
                </span>
              )}
            </CardContent>
          </Card>
          <div className="min-h-0 flex-1 space-y-2 overflow-auto">
            {(источники.data?.sources ?? []).length === 0 && !источники.isLoading && (
              <p className="p-2 text-sm text-muted-foreground">
                Источников нет — нажмите «Поставить базовый набор».
              </p>
            )}
            {(источники.data?.sources ?? []).map((s) => (
              <SourceCard key={s.id} s={s} running={обход.isPending}
                onRun={(id) => обход.mutate(id)}
                onToggle={(id, active) => переключить.mutate({ id, active })} />
            ))}
          </div>
        </>
      ) : (
        <>
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
          <div className="min-h-0 flex-1 space-y-2 overflow-auto">
            {лента.isLoading && (
              <p className="flex items-center gap-2 p-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" aria-hidden /> Загружаем ленту…
              </p>
            )}
            {!лента.isLoading && rows.length === 0 && (
              <p className="p-2 text-sm text-muted-foreground">
                {подача === 'review'
                  ? 'Очередь разбора пуста — всё разобрано.'
                  : 'Лента пуста — нажмите «Обновить из источников».'}
              </p>
            )}
            {rows.map((n) => (
              <NewsCard key={n.id} n={n} operators={ops}
                busy={правка.isPending && правка.variables?.id === n.id}
                onPatch={(id, body) => правка.mutate({ id, body })} />
            ))}
            {(лента.data?.total ?? 0) > rows.length && (
              <p className="p-2 text-xs text-muted-foreground">
                Показаны первые {rows.length} из {лента.data?.total}. Сузьте отбор темой,
                оператором или поиском.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
