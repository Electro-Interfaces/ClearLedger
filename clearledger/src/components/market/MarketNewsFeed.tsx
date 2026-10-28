/**
 * Подача новостной ленты рынка - по канону издания «Ангара» (`kka-site`,
 * `src/app/angar/news/page.tsx`), перенесённому на токены пространства.
 *
 * Раскладка новостного агентства, а не список строк:
 *   герой край-в-край - главный материал дня: обложка, тёмный градиент, рубрика,
 *     крупный заголовок, лид;
 *   «Свежее» - четыре строки с миниатюрой: быстрый просмотр того, что было;
 *   карточки - остальной поток крупно, в две колонки;
 *   сайдбар - «Коротко» (заголовки без фото) и состояние источников.
 *
 * Позиция в потоке и есть роль материала: [0] герой, [1..4] «Свежее»,
 * [5..9] «Коротко», дальше карточки. Героем не делаем материал без обложки -
 * баннер был бы пустым.
 *
 * Обложки приходят от обогащения: обход проходит редирект поисковой ленты и
 * берёт со страницы издания og:image, первые строки и признак видео. Там, где
 * издание ничего не отдало, рисуется не серый прямоугольник, а градиентная
 * заглушка с мотивом зарядной станции - пустое место в ленте читается как сбой.
 */
import { ArrowRight, Play } from 'lucide-react'
import {
  NEWS_TOPIC_LABEL, type MarketNewsItem, type MarketNewsTopic,
} from '@/services/marketService'

const дата = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
const деньМесяц = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' })

function когда(iso: string | null, длинно = false): string {
  if (!iso) return 'дата неизвестна'
  const d = new Date(iso)
  const дней = Math.floor((Date.now() - d.getTime()) / 86_400_000)
  if (дней <= 0) return 'сегодня'
  if (дней === 1) return 'вчера'
  return длинно ? деньМесяц.format(d) : дата.format(d)
}

function рубрика(n: MarketNewsItem): string {
  return NEWS_TOPIC_LABEL[n.topic as MarketNewsTopic] ?? 'Новости рынка'
}

/** Заглушка обложки: мотив зарядной станции, а не серый прямоугольник. */
function CoverFallback({ className = 'size-12' }: { className?: string }) {
  return (
    <span className="flex size-full items-center justify-center
                     bg-gradient-to-br from-primary/80 to-primary/30">
      <svg viewBox="0 0 48 48" className={`${className} text-primary-foreground/30`} fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        aria-hidden>
        <path d="M14 42V12a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v30" />
        <path d="M10 42h24" />
        <path d="M30 18h4a4 4 0 0 1 4 4v10a3 3 0 0 0 3 3" />
        <path d="M23 16l-5 9h7l-4 8" />
      </svg>
    </span>
  )
}

function Cover({ n, className, icon }: { n: MarketNewsItem; className?: string; icon?: string }) {
  return (
    <span className={`relative block overflow-hidden bg-muted ${className ?? ''}`}>
      {n.imageUrl
        ? <img src={n.imageUrl} alt="" loading="lazy" referrerPolicy="no-referrer"
            className="relative size-full object-cover transition-transform duration-500
                       group-hover:scale-105"
            onError={(e) => {
              const img = e.currentTarget
              img.hidden = true
              img.nextElementSibling?.removeAttribute('hidden')
            }} />
        : null}
      {n.imageUrl ? <span hidden className="absolute inset-0"><CoverFallback className={icon} /></span>
        : <CoverFallback className={icon} />}
      {n.media === 'video' && (
        <span className="absolute bottom-2 left-2 flex items-center gap-1 rounded-md
                         bg-background/85 px-2 py-0.5 text-xs font-medium text-foreground">
          <Play className="size-3" aria-hidden /> видео
        </span>
      )}
    </span>
  )
}

/** Главный материал: баннер во всю ширину панели с текстом поверх снимка. */
export function NewsHero({ n }: { n: MarketNewsItem }) {
  return (
    <a href={n.url} target="_blank" rel="noopener noreferrer"
      className="group relative flex min-h-[240px] items-end overflow-hidden rounded-xl border
                 border-border sm:min-h-[300px] lg:min-h-[340px]
                 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
      {/* Обложка кроет баннер целиком: при узкой картинке издания остальное
          поле добирается её же размытой копией, иначе половина героя — чёрный
          прямоугольник (видно на приёмке 29.10.2026). */}
      {n.imageUrl && (
        <span aria-hidden className="absolute inset-0 bg-cover bg-center blur-xl saturate-150"
          style={{ backgroundImage: `url("${n.imageUrl}")` }} />
      )}
      <Cover n={n} className="absolute inset-0 size-full" icon="size-20" />
      <span className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/45 to-black/5" />
      <span className="absolute inset-0 bg-gradient-to-r from-black/60 via-black/10 to-transparent" />
      <span className="relative z-10 w-full p-5 sm:p-7">
        <span className="block max-w-2xl">
          <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-white/80">
            {рубрика(n)}
          </span>
          <span className="font-headline line-clamp-3 text-xl font-bold leading-tight text-white
                           sm:text-3xl lg:text-4xl">
            {n.title}
          </span>
          {n.snippet && (
            <span className="mt-3 line-clamp-2 max-w-xl text-sm leading-relaxed text-white/80">
              {n.snippet}
            </span>
          )}
          <span className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-white/70">
            <span className="font-medium text-white/90">{n.sourceName ?? 'источник не указан'}</span>
            <span aria-hidden>·</span>
            <span>{когда(n.publishedAt, true)}</span>
            {n.operatorName && <><span aria-hidden>·</span><span>{n.operatorName}</span></>}
            {n.region && <><span aria-hidden>·</span><span>{n.region}</span></>}
          </span>
          <span className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-white
                           transition-colors group-hover:text-primary-foreground">
            Читать материал
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
          </span>
        </span>
      </span>
    </a>
  )
}

/** Строка «Свежего»: миниатюра, заголовок, издание и дата. */
export function NewsRow({ n }: { n: MarketNewsItem }) {
  return (
    <a href={n.url} target="_blank" rel="noopener noreferrer"
      className="group flex items-start gap-3 border-b border-border py-3 last:border-0
                 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
      <Cover n={n} className="h-16 w-24 shrink-0 rounded-lg border border-border sm:h-[72px] sm:w-32"
        icon="size-7" />
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-semibold uppercase tracking-wide text-primary">
          {рубрика(n)}
        </span>
        <span className="mt-0.5 line-clamp-3 text-sm font-semibold leading-snug transition-colors
                         group-hover:text-primary">
          {n.title}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          <span>{n.sourceName ?? 'источник не указан'}</span>
          <span aria-hidden>·</span>
          <span>{когда(n.publishedAt)}</span>
          {n.operatorName && <><span aria-hidden>·</span><span>{n.operatorName}</span></>}
        </span>
      </span>
    </a>
  )
}

/** Крупная карточка потока. */
export function NewsCard({ n }: { n: MarketNewsItem }) {
  return (
    <a href={n.url} target="_blank" rel="noopener noreferrer"
      className="group flex h-full flex-col overflow-hidden rounded-xl border border-border
                 bg-card shadow-soft transition hover:-translate-y-0.5 hover:shadow-medium
                 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
      <Cover n={n} className="aspect-video w-full" />
      <span className="flex flex-1 flex-col p-4">
        <span className="mb-2 block text-xs font-semibold uppercase tracking-wide text-primary">
          {рубрика(n)}
        </span>
        <span className="font-headline line-clamp-3 text-base font-semibold leading-snug
                         transition-colors group-hover:text-primary">
          {n.title}
        </span>
        {n.snippet && (
          <span className="mt-2 line-clamp-3 text-sm leading-relaxed text-muted-foreground">
            {n.snippet}
          </span>
        )}
        {n.actors.length > 0 && (
          <span className="mt-2 flex flex-wrap gap-1">
            {n.actors.slice(0, 4).map((a) => (
              <span key={`${a.role}:${a.name}`}
                className="rounded-md border border-border px-1.5 py-0.5 text-xs
                           text-muted-foreground">
                {a.name}
              </span>
            ))}
          </span>
        )}
        <span className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-3 text-xs
                         text-muted-foreground">
          <span className="font-medium text-foreground/80">{n.sourceName ?? 'источник не указан'}</span>
          <span aria-hidden>·</span>
          <span>{когда(n.publishedAt)}</span>
          {n.operatorName && <><span aria-hidden>·</span><span>{n.operatorName}</span></>}
          {n.region && <><span aria-hidden>·</span><span>{n.region}</span></>}
        </span>
      </span>
    </a>
  )
}

/** «Коротко»: заголовок без фото - то, что просматривают по диагонали. */
export function NewsBrief({ n }: { n: MarketNewsItem }) {
  return (
    <a href={n.url} target="_blank" rel="noopener noreferrer"
      className="group block border-b border-border py-3 last:border-0
                 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
      <span className="block text-xs font-semibold uppercase tracking-wide text-primary">
        {рубрика(n)}
      </span>
      <span className="mt-0.5 line-clamp-3 text-sm font-semibold leading-snug transition-colors
                       group-hover:text-primary">
        {n.title}
      </span>
      <span className="mt-1 block text-xs text-muted-foreground">
        {n.sourceName ?? 'источник не указан'} · {когда(n.publishedAt)}
      </span>
    </a>
  )
}

/** Заголовок полосы: подпись слева, ссылка-действие справа. */
export function StripTitle({ children, action }: {
  children: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3 border-b border-border pb-2">
      <h2 className="text-xs font-semibold uppercase tracking-[0.15em] text-muted-foreground">
        {children}
      </h2>
      {action}
    </div>
  )
}
