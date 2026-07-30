/**
 * Раздел «Помощь» внутри «Топлива» - свод знания по этому продукту.
 *
 * Знание одно на пространство и живёт в приложении «Инфо». Но посреди работы туда
 * никто не уходит: человек стоит на «Контроле баланса» и хочет прочитать про
 * «Контроль баланса», а не листать инструкции по проектам и подключениям. Раздел
 * показывает те же статьи, суженные до продукта (`/api/info/tree?app_code=sales`),
 * поэтому расходиться с подсказкой правой рельсы ему нечем: отбор идёт по одним и
 * тем же привязкам.
 *
 * Пункт раздела - пласт знания, а не экран. Экраны видны внутри пункта списком, и у
 * каждой статьи подписано, к какому месту продукта она относится: из помощи можно
 * уйти прямо на тот экран, о котором читаешь.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { BookOpen, ExternalLink, FileText, HelpCircle, Loader2, Scale, Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { Markdown } from '@/components/info/Markdown'
import {
  getInfoArticle, getInfoTree, type InfoArticleRow, type InfoKind,
} from '@/services/infoService'
import { MGMT_MENU, fuelModeForKey } from '@/config/workspaceMenus'

/** Пункт раздела → что из свода показывать. */
const SLICES: Record<string, { title: string; hint: string; categories?: string[]; kinds?: InfoKind[] }> = {
  'help-start': {
    title: 'Как работать',
    hint: 'Из чего состоит рабочее место и в каком порядке им пользуются',
    categories: ['Работа в «Топливе»'],
  },
  'help-goods': {
    title: 'Товародвижение',
    hint: 'Резервуары, смены, книга остатков, расхождения и ведомость',
    categories: ['Товародвижение и резервуары'],
  },
  'help-money': {
    title: 'Цены и клиенты',
    hint: 'Ценообразование, маржа, корпоратив и розница',
    categories: ['Цены и клиенты', 'Магазин и общепит'],
  },
  'help-norms': {
    title: 'Нормы и учёт',
    hint: 'На чём стоят требования к учёту нефтепродуктов',
    kinds: ['norm'],
  },
  'help-docs': {
    title: 'Документы компании',
    hint: 'Регламенты и приказы организации, привязанные к «Топливу»',
    kinds: ['lnd'],
  },
}

const KIND_ICON: Record<InfoKind, typeof BookOpen> = {
  guide: BookOpen, norm: Scale, lnd: FileText, faq: HelpCircle,
}

export function FuelHelpPanel({ companyId, section }: { companyId: string; section: string }) {
  const slice = SLICES[section] ?? SLICES['help-start']
  const [, setParams] = useSearchParams()
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)

  const tree = useQuery({
    queryKey: ['info-tree', companyId, 'sales'],
    queryFn: () => getInfoTree(companyId, 'sales'),
  })
  const article = useQuery({
    queryKey: ['info-article', companyId, openId],
    queryFn: () => getInfoArticle(companyId, openId as string),
    enabled: !!openId,
  })

  // Плоский список статей пласта. Категории приходят внутри групп-пластов, поэтому
  // разбираем дерево целиком, а не полагаемся на порядок групп.
  const items = useMemo(() => {
    const out: (InfoArticleRow & { category: string })[] = []
    for (const g of tree.data?.groups ?? []) {
      const kindOk = !slice.kinds || slice.kinds.includes(g.key)
      for (const c of g.categories) {
        const catOk = !slice.categories || slice.categories.includes(c.title)
        if (kindOk && catOk) out.push(...c.articles.map((a) => ({ ...a, category: c.title })))
      }
      if (kindOk && !slice.categories) out.push(...g.loose.map((a) => ({ ...a, category: '' })))
    }
    const needle = q.trim().toLowerCase()
    return needle
      ? out.filter((a) => (a.title + ' ' + (a.summary ?? '')).toLowerCase().includes(needle))
      : out
  }, [tree.data, slice, q])

  /** Уйти на экран, о котором читаешь: тот же продукт, другой раздел рельсы. */
  const goToScreen = (key: string) => setParams((prev) => {
    const next = new URLSearchParams(prev)
    next.set('mode', fuelModeForKey(key))
    next.set('sub', key)
    return next
  }, { replace: false })

  const opened = article.data
  const openedKeys = (opened?.bindings ?? [])
    .filter((b) => b.appCode === 'sales' && b.sectionKey)
    .map((b) => b.sectionKey!)
    .filter((k) => MGMT_MENU.some((m) => m.key === k))

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0">
          <h3 className="text-base font-semibold leading-tight">{slice.title}</h3>
          <p className="text-xs text-muted-foreground">{slice.hint}</p>
        </div>
        <div className="relative ml-auto w-full max-w-xs">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск в этом пласте" className="h-8 pl-7 text-xs" />
        </div>
      </div>

      {tree.isLoading ? (
        <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          {section === 'help-docs'
            ? 'Регламентов организации по «Топливу» пока нет. Их заводят в приложении «Инфо» и привязывают к нужному экрану — тогда они появятся здесь и подсказкой на самом экране.'
            : 'В этом пласте пока пусто.'}
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(260px,340px)_1fr]">
          {/* Список статей пласта: у каждой видно, к какому экрану она относится. */}
          <div className="min-h-0 space-y-1 overflow-y-auto pr-1">
            {items.map((a) => {
              const Icon = KIND_ICON[a.kind] ?? BookOpen
              return (
                <button key={a.id} type="button" onClick={() => setOpenId(a.id)}
                  className={cn('w-full rounded-lg border px-3 py-2 text-left transition-colors',
                    openId === a.id ? 'border-primary/60 bg-primary/5' : 'border-border/60 hover:border-primary/40')}>
                  <div className="flex items-start gap-2">
                    <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium leading-snug">{a.title}</div>
                      {a.summary && <div className="mt-0.5 text-xs text-muted-foreground">{a.summary}</div>}
                      {a.scope === 'company' && (
                        <div className="mt-1 text-[10px] uppercase tracking-wide text-primary/80">документ компании</div>
                      )}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>

          {/* Читалка. Кнопки экранов сверху: из помощи уходят туда, о чём читают. */}
          <div className="min-h-0 overflow-y-auto rounded-lg border border-border/60 bg-card p-4">
            {!openId ? (
              <div className="py-10 text-center text-sm text-muted-foreground">
                Выберите статью слева.
              </div>
            ) : article.isLoading || !opened ? (
              <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
            ) : (
              <div className="mx-auto max-w-3xl">
                <h4 className="text-lg font-semibold">{opened.title}</h4>
                <div className="mt-1 flex flex-wrap items-center gap-2 border-b pb-2 text-[11px] text-muted-foreground">
                  <span>{opened.kindLabel}</span>
                  <span>· {opened.scope === 'company' ? 'документ компании' : 'платформа'}</span>
                  {opened.docNumber && <span>· {opened.docNumber}</span>}
                  {opened.effectiveDate && <span>· действует с {opened.effectiveDate}</span>}
                  {opened.sourceUrl && (
                    <a href={opened.sourceUrl} target="_blank" rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-primary hover:underline">
                      источник <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
                {openedKeys.length > 0 && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] text-muted-foreground">открыть экран:</span>
                    {Array.from(new Set(openedKeys)).map((k) => (
                      <Button key={k} size="sm" variant="outline" className="h-6 px-2 text-[11px]"
                        onClick={() => goToScreen(k)}>
                        {MGMT_MENU.find((m) => m.key === k)?.label ?? k}
                      </Button>
                    ))}
                  </div>
                )}
                <div className="mt-3">
                  <Markdown content={opened.bodyMd} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
