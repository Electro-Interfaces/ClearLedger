/**
 * «Инфо» — рабочее место знания пространства.
 *
 * Слева дерево по пластам (инструкции платформы, отраслевые нормы, документы
 * компании), справа текст. Поиск не фильтрует дерево, а показывает свой список с
 * подсветкой: искать обычно проще, чем вспоминать, в каком разделе лежит.
 *
 * Один компонент на два входа: страница `/info` со стола (`variant='page'`) и
 * окно из шапки любого продукта (`variant='modal'`) — это одно приложение, а не
 * копия. Разница только в ведении: страница даёт заводить и править документы
 * компании, окно — чтение, потому что из шапки человек приходит искать ответ, а не
 * писать регламент. Контекстная выдача под открытую рабочую область живёт в
 * `InfoContextPanel` (правый док).
 *
 * Обе подачи — колонки на всю высоту со своей прокруткой: дерево из сотни статей и
 * регламент на 12 тысяч знаков не должны ездить одной общей полосой. Размер шрифта —
 * не украшение: такие тексты читают подолгу и с разных экранов, поэтому шаг
 * сохраняется между сессиями.
 */
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Loader2, Search, ChevronRight, ChevronDown, BookOpen, Scale, FileText, HelpCircle,
  ExternalLink, Workflow, Type, Plus, Pencil, Building2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  getInfoTree, getInfoArticle, searchInfo,
  type InfoKind, type InfoArticleRow, type InfoNode, type InfoTree,
} from '@/services/infoService'
import { Markdown } from './Markdown'
import { InfoArticleEditor } from './InfoArticleEditor'

const KIND_ICON: Record<InfoKind, typeof BookOpen> = {
  guide: BookOpen, norm: Scale, lnd: FileText, faq: HelpCircle,
}
const FONT_STEPS = [15, 16, 18, 20]
const FONT_KEY = 'info:fontStep'

/** Дерево разделов плоским списком: для формы документа и стартового экрана. */
function плоско(nodes: InfoNode[]): InfoNode[] {
  return nodes.flatMap((n) => [n, ...плоско(n.children ?? [])])
}

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
  const [editing, setEditing] = useState<'new' | 'current' | null>(null)
  const [fontStep, setFontStep] = useState(() => {
    const v = Number(localStorage.getItem(FONT_KEY))
    return Number.isFinite(v) && v >= 0 && v < FONT_STEPS.length ? v : 1
  })
  useEffect(() => { localStorage.setItem(FONT_KEY, String(fontStep)) }, [fontStep])

  // Пласт из адреса: пункт левого меню приложения ведёт сюда же с `?kind=`, а не
  // наружу. В окне из шапки меню нет, поэтому там всегда всё знание.
  const [params] = useSearchParams()
  const kind = variant === 'modal' ? null : params.get('kind')

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
  const groups = useMemo(
    () => (tree.data?.groups ?? []).filter((g) => !kind || g.key === kind),
    [tree.data, kind])
  const empty = useMemo(
    () => (kind ? groups.length === 0 : (tree.data?.total ?? 0) === 0),
    [kind, groups, tree.data])
  const modal = variant === 'modal'
  // Разделы для формы документа — все видимые: свои и платформенные. Дерево
  // теперь вложенное (приложение → разделы), поэтому разворачиваем его плоско:
  // иначе в форме остались бы одни приложения без разделов внутри.
  const categories = useMemo(
    () => (tree.data?.groups ?? []).flatMap((g) => плоско(g.categories))
      .filter((c, i, arr) => arr.findIndex((x) => x.id === c.id) === i),
    [tree.data])
  // Править можно только документ пространства: платформенные ведёт поставщик.
  const canEditCurrent = article.data?.scope === 'company'

  const editor = editing && (
    <InfoArticleEditor
      companyId={companyId}
      article={editing === 'current' ? article.data ?? null : null}
      categories={categories}
      onClose={() => setEditing(null)}
      onSaved={(id) => { setEditing(null); setSelected(id) }}
    />
  )

  if (tree.isLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  const aside = (
    <div className="flex min-h-0 w-full flex-col md:w-[300px] md:shrink-0 md:border-r md:border-border/60">
      <div className="p-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск по знанию пространства" className="h-9 pl-7 text-xs" />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
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
        ) : empty ? (
          <div className="px-2 py-6 text-xs text-muted-foreground">
            {kind === 'lnd'
              ? 'Документов компании пока нет. Их заводят кнопкой ниже: регламенты, приказы, инструкции организации.'
              : kind
                ? 'В этом пласте пока пусто.'
                : 'Знание пространства пока пустое. Сюда заводят инструкции, отраслевые нормы и документы компании: регламенты, приказы, чек-листы.'}
          </div>
        ) : (
          <div className="space-y-1">
            {groups.map((g) => {
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
                      {g.categories.map((c) => (
                        <Node key={c.id} node={c} groupKey={g.key} openCats={openCats}
                          onToggle={(k) => toggle(openCats, k, setOpenCats)}
                          selected={selected} onPick={setSelected} />
                      ))}
                      {g.loose.map((a) => <Item key={a.id} a={a} on={setSelected} active={selected === a.id} />)}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
      {/* Ведение — только в полноэкранном рабочем месте: из окна в шапке человек
          пришёл искать ответ, а не писать регламент. */}
      {!modal && (
        <div className="border-t border-border/60 p-2">
          <Button size="sm" variant="outline" className="h-8 w-full text-xs"
            onClick={() => setEditing('new')}>
            <Plus className="mr-1 h-3.5 w-3.5" /> Добавить документ компании
          </Button>
        </div>
      )}
    </div>
  )

  const reader = (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2">
        <span className="flex-1 truncate text-sm font-semibold">
          {article.data?.title ?? 'Инфо'}
        </span>
        {!modal && canEditCurrent && (
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setEditing('current')}>
            <Pencil className="mr-1 h-3.5 w-3.5" /> Править
          </Button>
        )}
        {/* Размер текста: регламенты читают подолгу и с разных экранов. */}
        <Type className="h-3.5 w-3.5 text-muted-foreground" />
        <button type="button" onClick={() => setFontStep((v) => Math.max(0, v - 1))}
          className="rounded px-1.5 text-xs text-muted-foreground hover:text-foreground" title="Мельче">A−</button>
        <button type="button" onClick={() => setFontStep((v) => Math.min(FONT_STEPS.length - 1, v + 1))}
          className="rounded px-1.5 text-sm text-muted-foreground hover:text-foreground" title="Крупнее">A+</button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4" style={{ fontSize: FONT_STEPS[fontStep] }}>
        {!selected ? (
          <Start groups={groups} onPick={setSelected}
            onAdd={modal ? undefined : () => setEditing('new')} />
        ) : article.isLoading || !article.data ? (
          <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : (
          <div className="mx-auto max-w-3xl">
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
          </div>
        )}
      </div>
    </div>
  )

  // Одна раскладка на обе подачи: две колонки на всю высоту, каждая со своей
  // прокруткой. Страница берёт высоту рабочей области, окно — высоту диалога.
  return (
    <>
      <div className={cn('flex min-h-0 flex-col md:flex-row',
        modal
          ? 'h-full'
          : 'h-[calc(100dvh-var(--header-height)-2.5rem)] overflow-hidden rounded-lg border border-border/60 bg-card')}>
        {aside}
        {reader}
      </div>
      {editor}
    </>
  )
}

/** Стартовый экран читалки: чем «Инфо» наполнено и с чего начать. */
function Start({ groups, onPick, onAdd }: {
  groups: InfoTree['groups']; onPick: (id: string) => void; onAdd?: () => void
}) {
  const first = groups.find((g) => g.key === 'guide') ?? groups[0]
  // Статьи лежат в глубине дерева (приложение → раздел → статьи), поэтому берём
  // первые из обхода, а не из верхнего узла: у него своих статей нет вовсе.
  const starters = (плоско(first?.categories ?? []).flatMap((c) => c.articles)
    .concat(first?.loose ?? [])).slice(0, 5)
  return (
    <div className="mx-auto max-w-3xl space-y-5 py-2">
      <div>
        <h3 className="text-lg font-semibold">Знание пространства</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Инструкции по работе в системе, отраслевые нормы и документы самой компании.
          Хранилище одно: то же знание всплывает подсказкой в правой рельсе, только там
          оно подобрано под открытый экран.
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {groups.map((g) => {
          const Icon = KIND_ICON[g.key] ?? BookOpen
          return (
            <div key={g.key} className="rounded-lg border border-border/60 p-3">
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium">{g.label}</span>
                <span className="ml-auto font-mono text-xs text-muted-foreground">{g.count}</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{g.hint}</p>
            </div>
          )
        })}
      </div>

      {starters.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            С чего начать
          </p>
          <div className="space-y-1">
            {starters.map((a) => (
              <button key={a.id} type="button" onClick={() => onPick(a.id)}
                className="block w-full rounded-md border border-border/60 px-3 py-2 text-left hover:border-primary/50">
                <div className="text-sm font-medium">{a.title}</div>
                {a.summary && <div className="text-xs text-muted-foreground">{a.summary}</div>}
              </button>
            ))}
          </div>
        </div>
      )}

      {onAdd && (
        <div className="rounded-lg border border-dashed border-border p-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Building2 className="h-4 w-4 text-muted-foreground" /> Документы компании
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Регламенты, приказы и инструкции организации ведутся здесь же. Если указать
            продукт и раздел, документ появится подсказкой на нужном экране.
          </p>
          <Button size="sm" variant="outline" className="mt-2 h-7 text-xs" onClick={onAdd}>
            <Plus className="mr-1 h-3.5 w-3.5" /> Добавить документ
          </Button>
        </div>
      )}
    </div>
  )
}

/**
 * Узел дерева: раздел, его статьи и вложенные разделы.
 *
 * Верхний уровень - приложение («Трек», «Проекты», «Поддержка»), под ним его
 * разделы. Плоский список сваливал в одну кучу девять разделов «Трека», шесть
 * «Проектов» и общие правила пространства, и нужное искали перебором.
 *
 * Рекурсия, а не два жёстких уровня: глубина - дело данных, а не разметки.
 * Отступ упирается в четвёртый уровень, дальше не растёт - иначе заголовок
 * уезжает за край узкой панели.
 */
function Node({ node, groupKey, openCats, onToggle, selected, onPick, depth = 0 }: {
  node: InfoNode; groupKey: string; openCats: Set<string>
  onToggle: (key: string) => void
  selected: string | null; onPick: (id: string) => void
  depth?: number
}) {
  const key = `${groupKey}:${node.id}`
  const open = openCats.has(key)
  return (
    <div>
      <button type="button" onClick={() => onToggle(key)}
        className={cn('flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-xs hover:bg-muted/60',
          depth === 0 && 'font-medium')}>
        <ChevronRight className={`h-3 w-3 shrink-0 transition-transform ${open ? 'rotate-90' : ''}`} />
        <span className="flex-1 truncate text-left">{node.title}</span>
        <span className="font-mono text-[10px] text-muted-foreground">{node.count}</span>
      </button>
      {open && (
        <div className={cn('space-y-0.5 border-l border-border/40 pl-2',
          depth >= 3 ? 'ml-[6px]' : 'ml-[15px]')}>
          {node.children.map((ch) => (
            <Node key={ch.id} node={ch} groupKey={groupKey} openCats={openCats}
              onToggle={onToggle} selected={selected} onPick={onPick} depth={depth + 1} />
          ))}
          {node.articles.map((a) => (
            <Item key={a.id} a={a} on={onPick} active={selected === a.id} />
          ))}
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
