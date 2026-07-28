/**
 * Правая панель «Инфо» — знание под открытую рабочую область.
 *
 * Отличие от кнопки «Инфо» в шапке: та открывает приложение целиком, а панель
 * приоритетно показывает то, что относится к продукту и разделу, где человек
 * сейчас находится (`/projects?sub=pr_tp` → «Проекты» · «Присоединение»).
 *
 * Панель не хранит своей копии текстов: тот же `/api/info/*` с фильтром по
 * контексту. Если для места ничего не заведено, она честно это говорит и ведёт
 * в приложение, а не показывает пустоту (docs/INFO.md §2).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Loader2, X, BookOpen, ChevronLeft, ExternalLink } from 'lucide-react'
import { getInfoContext, getInfoArticle } from '@/services/infoService'
import { appCodeForPath, productForPath } from '@/config/spaceProducts'
import { Markdown } from './Markdown'

export function InfoContextPanel({ companyId, onClose, embedded = false }: {
  companyId: string; onClose: () => void; embedded?: boolean
}) {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [openId, setOpenId] = useState<string | null>(null)

  // Контекст = приложение по маршруту + раздел рабочей области из `?sub=`.
  // Приложение — не только продукт разреза: «Управление» и «Данные» тоже реестровые,
  // и подсказка в них обязана знать, где человек, а не считать всё Учётом.
  const product = productForPath(pathname)
  const appCode = appCodeForPath(pathname)
  const sectionKey = params.get('sub')

  const ctx = useQuery({
    queryKey: ['info-ctx', companyId, appCode, sectionKey],
    queryFn: () => getInfoContext(companyId, appCode, sectionKey),
  })
  const article = useQuery({
    queryKey: ['info-article', companyId, openId],
    queryFn: () => getInfoArticle(companyId, openId as string),
    enabled: !!openId,
  })

  return (
    <aside className={embedded
      ? 'flex h-full w-full flex-col bg-background'
      : 'flex h-full w-full max-w-[420px] flex-col border-l border-border bg-background'}>
      {/* В доке шапку и крестик рисует сам док — вторая полоса выглядела бы ошибкой. */}
      <div className={`flex items-center gap-2 border-b px-3 py-2 ${embedded && !openId ? 'hidden' : ''}`}>
        {openId ? (
          <button type="button" onClick={() => setOpenId(null)}
            className="text-muted-foreground hover:text-foreground" aria-label="Назад к списку">
            <ChevronLeft className="h-4 w-4" />
          </button>
        ) : (
          <BookOpen className="h-4 w-4 text-muted-foreground" />
        )}
        <span className="flex-1 truncate text-xs font-semibold">
          {openId ? (article.data?.title ?? 'Статья') : `Инфо · ${product?.label ?? 'рабочая область'}`}
        </span>
        <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground" aria-label="Закрыть">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {openId ? (
          article.isLoading || !article.data
            ? <div className="flex justify-center py-8"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
            : (
              <>
                <div className="mb-2 text-[11px] text-muted-foreground">
                  {article.data.kindLabel}
                  {article.data.docNumber && ` · ${article.data.docNumber}`}
                  {article.data.effectiveDate && ` · с ${article.data.effectiveDate}`}
                </div>
                <Markdown content={article.data.bodyMd} />
                {article.data.sourceUrl && (
                  <a href={article.data.sourceUrl} target="_blank" rel="noopener noreferrer"
                    className="mt-3 inline-flex items-center gap-1 text-xs text-primary hover:underline">
                    Источник <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </>
            )
        ) : ctx.isLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
        ) : ctx.data?.empty ? (
          <div className="space-y-2 text-xs text-muted-foreground">
            <p>Для этой рабочей области пояснений пока нет.</p>
            <p>
              Знание пространства ведётся в приложении «Инфо»: инструкции по продуктам,
              отраслевые нормы, документы компании. Статью можно привязать к этому месту,
              и она появится здесь.
            </p>
            <Button size="sm" variant="outline" className="h-7 text-xs"
              onClick={() => { onClose(); navigate('/info') }}>
              Открыть «Инфо»
            </Button>
          </div>
        ) : (
          <div className="space-y-1.5">
            {(ctx.data?.items ?? []).map((a) => (
              <button key={a.id} type="button" onClick={() => setOpenId(a.id)}
                className="w-full rounded-md border border-border px-2 py-1.5 text-left hover:border-primary/50">
                <div className="flex items-center gap-1.5">
                  <span className="flex-1 truncate text-xs font-medium">{a.title}</span>
                  {/* Точное попадание в раздел важнее общей статьи продукта. */}
                  {a.exact && <span className="text-[10px] text-primary">этот раздел</span>}
                </div>
                {a.summary && <div className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{a.summary}</div>}
                <div className="mt-0.5 text-[10px] text-muted-foreground">
                  {a.kindLabel}{a.scope === 'company' ? ' · документ компании' : ''}
                </div>
              </button>
            ))}
            <button type="button" onClick={() => { onClose(); navigate('/info') }}
              className="w-full px-2 py-1 text-left text-[11px] text-muted-foreground hover:text-foreground">
              Всё знание пространства →
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}
