/**
 * «Инфо» — рабочее место знания пространства.
 *
 * Слева дерево по пластам (инструкции платформы, отраслевые нормы, документы
 * компании), справа текст. Поиск не фильтрует дерево, а показывает свой список с
 * подсветкой: искать обычно проще, чем вспоминать, в каком разделе лежит.
 *
 * Один компонент на два входа: страница `/info` со стола (`variant='page'`) и
 * окно из шапки любого продукта (`variant='modal'`) — это одно приложение, а не
 * копия. Контекстная выдача под открытую рабочую область живёт в
 * `InfoContextPanel` (правый док).
 *
 * Размер шрифта — не украшение: регламент на 12 тысяч знаков читают подолгу и с
 * разных экранов, поэтому шаг сохраняется между сессиями.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Loader2, Search, ChevronRight, ChevronDown, BookOpen, Scale, FileText, HelpCircle,
  ExternalLink, Workflow, Type,
} from 'lucide-react'
import {
  getInfoTree, getInfoArticle, searchInfo,
  type InfoKind, type InfoArticleRow,
} from '@/services/infoService'
import { Markdown } from './Markdown'

const KIND_ICON: Record<InfoKind, typeof BookOpen> = {
  guide: BookOpen, norm: Scale, lnd: FileText, faq: HelpCircle,
}
const FONT_STEPS = [15, 16, 18, 20]
const FONT_KEY = 'info:fontStep'

function Snippet({ text }: { text: string }) {
  // Бэкенд отдаёт фрагмент с маркерами <<…>>: рисуем React-узлами, без HTML.
  const parts = text.split(/<<|>>/)
  return <>{parts.map((p, i) => (i % 2 === 1
    ? <mark key={i} className="rounded bg-amber-200 px-0.5 text-slate-900 dark:bg-amber-500/30 dark:text-amber-100">{p}</mark>
    : <span key={i}>{p}</span>))}</>
}

export function InfoCenter({ companyId, initialId, variant = 'page' }: {
  companyId: string; initialId?: string; variant?: 'page' | 'modal'
}) {
  const [q, setQ] = useState('')
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set(['guide', 'lnd']))
  const [openCats, setOpenCats] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<string | null>(initialId ?? null)
  const [fontStep, setFontStep] = useState(() => {
    const v = Number(localStorage.getItem(FONT_KEY))
    return Number.isFinite(v) && v >= 0 && v < FONT_STEPS.length ? v : 1
  })
  useEffect(() => { localStorage.setItem(FONT_KEY, String(fontStep)) }, [fontStep])

  const tree = useQuery({ queryKey: ['info-tree', companyId], queryFn: () => getInfoTree(companyId) })
  const found = useQuery({
    queryKey: ['info-search', companyId, q],
    queryFn: () => searchInfo(companyId, q),
    enabled: q.trim().length >= 2,
  })
  const article = useQuery({
    queryKey: ['info-article', companyId, selected],
    queryFn: () => getInfoArticle(companyId, selected as string),
    enabled: !!selected,
  })

  const toggle = (set: Set<string>, k: string, fn: (s: Set<string>) => void) => {
    const next = new Set(set)
    if (next.has(k)) next.delete(k); else next.add(k)
    fn(next)
  }
  const empty = useMemo(() => (tree.data?.total ?? 0) === 0, [tree.data])
  const modal = variant === 'modal'

  if (tree.isLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  if (empty) {
    return (
      <div className="p-4">
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Знание пространства пока пустое. Сюда заводят инструкции по продуктам, отраслевые
          нормы и документы компании — регламенты, приказы, чек-листы.
        </CardContent></Card>
      </div>
    )
  }

  const aside = (
    <div className={modal
      ? 'flex w-[300px] shrink-0 flex-col border-r border-border/60'
      : 'flex flex-col'}>
      <div className="p-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск по знанию пространства" className="h-9 pl-7 text-xs" />
        </div>
      </div>
      <div className={modal ? 'min-h-0 flex-1 overflow-y-auto px-2 pb-2' : 'px-2 pb-2'}>
        {q.trim().length >= 2 ? (
          <div className="space-y-1">
            <div className="px-1 py-1 text-[11px] text-muted-foreground">
              {found.isLoading ? 'ищем…' : `нашлось: ${found.data?.items.length ?? 0}`}
            </div>
            {(found.data?.items ?? []).map((a) => (
              <button key={a.id} type="button" onClick={() => setSelected(a.id)}
                className={`w-full rounded-md px-2 py-1.5 text-left text-xs hover:bg-muted/60 ${selected === a.id ? 'bg-muted' : ''}`}>
                <div className="font-medium">{a.title}</div>
                <div className="text-[11px] text-muted-foreground"><Snippet text={a.snippet} /></div>
              </button>
            ))}
          </div>
        ) : (
          <div className="space-y-1">
            {(tree.data?.groups ?? []).map((g) => {
              const Icon = KIND_ICON[g.key] ?? BookOpen
              const open = openGroups.has(g.key)
              return (
                <div key={g.key}>
                  {/* Пласт со счётчиком: сразу видно, чего в пространстве много,
                      а что ещё не заводили. */}
                  <button type="button" onClick={() => toggle(openGroups, g.key, setOpenGroups)}
                    className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1.5 text-xs font-semibold uppercase tracking-wide hover:bg-muted/60">
                    {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                    <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="flex-1 text-left">{g.label}</span>
                    <span className="font-mono text-[10px] text-muted-foreground">{g.count}</span>
                  </button>
                  {open && (
                    <div className="ml-3 space-y-0.5">
                      {g.categories.map((c) => {
                        const key = `${g.key}:${c.id}`
                        const co = openCats.has(key)
                        return (
                          <div key={c.id}>
                            <button type="button" onClick={() => toggle(openCats, key, setOpenCats)}
                              className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-xs hover:bg-muted/60">
                              <ChevronRight className={`h-3 w-3 shrink-0 transition-transform ${co ? 'rotate-90' : ''}`} />
                              <span className="flex-1 truncate text-left">{c.title}</span>
                              <span className="font-mono text-[10px] text-muted-foreground">{c.articles.length}</span>
                            </button>
                            {co && (
                              <div className="ml-[15px] space-y-0.5 border-l border-border/40 pl-2">
                                {c.articles.map((a) => <Item key={a.id} a={a} on={setSelected} active={selected === a.id} />)}
                              </div>
                            )}
                          </div>
                        )
                      })}
                      {g.loose.map((a) => <Item key={a.id} a={a} on={setSelected} active={selected === a.id} />)}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )

  const reader = (
    <div className={modal ? 'flex min-w-0 flex-1 flex-col' : ''}>
      <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2">
        <span className="flex-1 truncate text-sm font-semibold">
          {article.data?.title ?? 'Инфо'}
        </span>
        {/* Размер текста: регламенты читают подолгу и с разных экранов. */}
        <Type className="h-3.5 w-3.5 text-muted-foreground" />
        <button type="button" onClick={() => setFontStep((v) => Math.max(0, v - 1))}
          className="rounded px-1.5 text-xs text-muted-foreground hover:text-foreground" title="Мельче">A−</button>
        <button type="button" onClick={() => setFontStep((v) => Math.min(FONT_STEPS.length - 1, v + 1))}
          className="rounded px-1.5 text-sm text-muted-foreground hover:text-foreground" title="Крупнее">A+</button>
      </div>
      <div className={modal ? 'min-h-0 flex-1 overflow-y-auto px-5 py-4' : 'px-4 py-3'}
        style={{ fontSize: FONT_STEPS[fontStep] }}>
        {!selected ? (
          <div className="py-10 text-center text-sm text-muted-foreground">
            Выберите статью слева или найдите поиском.
          </div>
        ) : article.isLoading || !article.data ? (
          <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : (
          <>
            <h3 className="mb-1 text-lg font-semibold">{article.data.title}</h3>
            <div className="mb-3 flex flex-wrap items-center gap-2 border-b pb-2 text-[11px] text-muted-foreground">
              <span>{article.data.kindLabel}</span>
              <span>· {article.data.scope === 'company' ? 'документ компании' : 'платформа'}</span>
              {article.data.docNumber && <span>· {article.data.docNumber}</span>}
              {article.data.effectiveDate && <span>· действует с {article.data.effectiveDate}</span>}
              {article.data.sourceUrl && (
                <a href={article.data.sourceUrl} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-primary hover:underline">
                  источник <ExternalLink className="h-3 w-3" />
                </a>
              )}
              {article.data.processRef && (
                <span className="inline-flex items-center gap-1" title="Документ ведёт процесс в приложении">
                  <Workflow className="h-3 w-3" /> ведёт процесс
                </span>
              )}
            </div>
            <Markdown content={article.data.bodyMd} />
          </>
        )}
      </div>
    </div>
  )

  if (modal) return <div className="flex h-full min-h-0">{aside}{reader}</div>

  return (
    <div className="p-4 space-y-3">
      <div>
        <h2 className="text-base font-semibold">Инфо</h2>
        <p className="text-xs text-muted-foreground">
          Инструкции по продуктам, отраслевые нормы и документы компании. Открывается и
          отсюда, и подсказкой в рабочей области — это одно и то же знание.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[320px_1fr]">
        <Card className="self-start"><CardContent className="p-0">{aside}</CardContent></Card>
        <Card><CardContent className="p-0">{reader}</CardContent></Card>
      </div>
    </div>
  )
}

function Item({ a, on, active }: { a: InfoArticleRow; on: (id: string) => void; active: boolean }) {
  return (
    <button type="button" onClick={() => on(a.id)}
      className={`w-full truncate rounded px-1.5 py-1 text-left text-xs hover:bg-muted/60 ${active ? 'bg-muted font-medium' : ''}`}
      title={a.summary ?? a.title}>
      {a.title}
    </button>
  )
}
