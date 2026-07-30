/**
 * Клиент «Инфо» (/api/info/*) — знание пространства.
 *
 * Один источник на три входа: рабочее место со стола, кнопка в шапке продукта и
 * правая панель, подставляющая знание под открытую рабочую область. Панель не
 * держит своей копии текстов — тот же API с фильтром по контексту (docs/INFO.md).
 */
import { get, put, del } from './apiClient'

export type InfoKind = 'guide' | 'norm' | 'lnd' | 'faq'

export interface InfoArticleRow {
  id: string
  title: string
  summary: string | null
  kind: InfoKind
  kindLabel: string
  /** platform — ведёт поставщик, company — документ этого пространства. */
  scope: 'platform' | 'company'
  categoryId: string | null
  docNumber: string | null
  effectiveDate: string | null
  sourceUrl: string | null
  tags: string[]
  /** Документ ведёт процесс в приложении (например, чек-лист гейтов). */
  processRef: string | null
  updatedAt: string | null
  /** Только в контекстной выдаче: привязана именно к этому разделу. */
  exact?: boolean
}

export interface InfoArticleFull extends InfoArticleRow {
  bodyMd: string
  bindings: { appCode: string; sectionKey: string | null; weight: number }[]
}

export interface InfoTree {
  groups: {
    key: InfoKind; label: string; hint: string; count: number
    categories: { id: string; title: string; articles: InfoArticleRow[] }[]
    loose: InfoArticleRow[]
  }[]
  profile: string | null
  total: number
}

/** Всё дерево знания; `appCode` — свод одного продукта (раздел «Помощь» внутри него). */
export async function getInfoTree(companyId: string, appCode?: string): Promise<InfoTree> {
  return get<InfoTree>('/api/info/tree', { company_id: companyId, app_code: appCode || undefined })
}

export async function getInfoArticle(companyId: string, id: string): Promise<InfoArticleFull> {
  return get<InfoArticleFull>(`/api/info/articles/${id}`, { company_id: companyId })
}

/** Контекст рабочей области: что показать в правой панели. */
export async function getInfoContext(
  companyId: string, appCode: string, sectionKey?: string | null,
): Promise<{ appCode: string; sectionKey: string | null; items: InfoArticleRow[]; empty: boolean }> {
  return get('/api/info/context', {
    company_id: companyId, app_code: appCode, section_key: sectionKey || undefined,
  })
}

export async function searchInfo(
  companyId: string, q: string,
): Promise<{ query: string; items: (InfoArticleRow & { snippet: string })[] }> {
  return get('/api/info/search', { company_id: companyId, q })
}

export async function getInfoStats(companyId: string): Promise<{
  byKind: { kind: InfoKind; label: string; platform: number; company: number }[]
  apps: number; profile: string | null
}> {
  return get('/api/info/stats', { company_id: companyId })
}

export async function saveInfoArticle(
  companyId: string,
  body: Partial<{
    id: string; title: string; summary: string; body_md: string; kind: InfoKind
    status: string; doc_number: string; effective_date: string; source_url: string
    tags: string[]; category_id: string
    bindings: { app_code: string; section_key?: string | null; weight?: number }[]
  }>,
): Promise<{ ok: boolean; id: string }> {
  return put(`/api/info/articles?company_id=${companyId}`, body)
}

export async function deleteInfoArticle(companyId: string, id: string): Promise<unknown> {
  return del(`/api/info/articles/${id}?company_id=${companyId}`)
}
