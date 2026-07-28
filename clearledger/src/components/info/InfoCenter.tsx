/**
 * «Инфо» — рабочее место знания пространства.
 *
 * Слева дерево по пластам (инструкции платформы, отраслевые нормы, документы
 * компании), справа текст. Поиск не фильтрует дерево, а показывает свой список с
 * подсветкой: искать обычно проще, чем вспоминать, в каком разделе лежит.
 *
 * Тот же компонент открывается со стола (плитка «Инфо») и из шапки любого
 * продукта — это одно приложение, а не копия. Контекстная выдача под открытую
 * рабочую область живёт в `InfoContextPanel`.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Loader2, Search, ChevronRight, ChevronDown, BookOpen, Scale, FileText, HelpCircle, ExternalLink, Workflow } from 'lucide-react'
import {
  getInfoTree, getInfoArticle, searchInfo,
  type InfoKind, type InfoArticleRow,
} from '@/services/infoService'
import { Markdown } from './Markdown'

const KIND_ICON: Record<InfoKind, typeof BookOpen> = {
  guide: BookOpen, norm: Scale, lnd: FileText, faq: HelpCircle,
}

function Snippet({ text }: { text: string }) {
  // Бэкенд отдаёт фрагмент с маркерами <<…>>: рисуем React-узлами, без HTML.
  const parts = text.split(/<<|>>/)
  return <>{parts.map((p, i) => (i % 2 === 1
    ? <mark key={i} className="rounded bg-amber-200 px-0.5 text-slate-900 dark:bg-amber-500/30 dark:text-amber-100">{p}</mark>
    : <span key={i}>{p}</span>))}</>
}

export function InfoCenter({ companyId, initialId }: { companyId: string; initialId?: string }) {
  const [q, setQ] = useState('')
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set(['guide']))
  const [selected, setSelected] = useState<string | null>(initialId ?? null)

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

  const toggle = (k: string) => setOpenGroups((prev) => {
    const next = new Set(prev)
    if (next.has(k)) next.delete(k); else next.add(k)
    return next
  })

  const empty = useMemo(() => (tree.data?.total ?? 0) === 0, [tree.data])

  if (tree.isLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Инфо</h2>
          <p className="text-xs text-muted-foreground">
            Инструкции по продуктам, отраслевые нормы и документы компании. Открывается
            и отсюда, и подсказкой в рабочей области — это одно и то же знание.
          </p>
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Найти в знании пространства" className="h-8 w-[260px] pl-7 text-xs" />
        </div>
      </div>

      {empty ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Знание пространства пока пустое. Сюда заводят инструкции по продуктам, отраслевые
          нормы и документы компании — регламенты, приказы, чек-листы.
        </CardContent></Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[320px_1fr]">
          {/* дерево или результаты поиска */}
          <Card className="self-start">
            <CardContent className="p-2">
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
                        <button type="button" onClick={() => toggle(g.key)}
                          className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-semibold hover:bg-muted/60">
                          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                          <span className="flex-1 text-left">{g.label}</span>
                          <span className="font-mono text-[10px] text-muted-foreground">{g.count}</span>
                        </button>
                        {open && (
                          <div className="ml-4 space-y-0.5 border-l border-border/40 pl-2">
                            {g.categories.map((c) => (
                              <div key={c.id}>
                                <div className="px-1 pt-1 text-[10px] uppercase tracking-wide text-muted-foreground">{c.title}</div>
                                {c.articles.map((a) => <Item key={a.id} a={a} on={setSelected} active={selected === a.id} />)}
                              </div>
                            ))}
                            {g.loose.map((a) => <Item key={a.id} a={a} on={setSelected} active={selected === a.id} />)}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* текст статьи */}
          <Card>
            <CardContent className="p-4">
              {!selected ? (
                <div className="py-10 text-center text-sm text-muted-foreground">
                  Выберите статью слева или найдите поиском.
                </div>
              ) : article.isLoading || !article.data ? (
                <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
              ) : (
                <>
                  <div className="mb-2 border-b pb-2">
                    <h3 className="text-sm font-semibold">{article.data.title}</h3>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
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
                  </div>
                  <Markdown content={article.data.bodyMd} />
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
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
