/**
 * Клиент SSO Ядра экосистемы (Фаза 0). Ledger — временный провайдер идентичности:
 * лаунчер получает каталог приложений и, по клику, короткоживущий URL перехода с
 * handoff-токеном. Бэкенд: routers/sso_router.py (вызывается ФРОНТОМ с bearer, не
 * редиректом — иначе токен не долетел бы).
 */
import { get, put } from './apiClient'

export interface SsoApp {
  code: string
  name: string
  base_url: string
  callback: string
  icon: string
  /**
   * Как открывать продукт:
   *   internal — маршрут этого же SPA (`route`): Управление, Чаты, Учёт;
   *   sso      — переход по handoff-токену (Координатор);
   *   link     — мост на своём домене, спросит свой вход (Заявки, Конференции).
   */
  mode?: 'sso' | 'link' | 'internal'
  /** Слой рабочего стола: admin — управление пространством; service — сервис; app — приложение. */
  layer?: 'admin' | 'service' | 'app'
  /** Маршрут внутри SPA — только для mode='internal'. */
  route?: string
  /** Короткое описание из реестра — подпись плитки на столе. */
  description?: string
}

export interface SsoCatalog {
  /** есть что показать (мосты/чат видны и без ключа SSO) */
  enabled: boolean
  /** настроен ли единый вход (handoff-приложения) */
  sso_enabled: boolean
  /** доступен ли универсальный сервис «Чат» (Matrix) — плитка в слое сервисов */
  chat_enabled: boolean
  apps: SsoApp[]
  /** коды приложений, доступных по роли в компании (RBAC-гейт стола); null = не ограничено */
  allowed_apps: string[] | null
}

/** Каталог приложений экосистемы для рабочего стола. companyId — для RBAC-гейта по роли. */
export async function listSsoApps(companyId?: string): Promise<SsoCatalog> {
  return get<SsoCatalog>('/api/sso/apps', companyId ? { company_id: companyId } : undefined)
}

/**
 * Продукты, у которых рядом уже есть собственная кнопка (Чат · Конференция — в шапке
 * и в рельсе взаимодействия). В списке «Приложения» их нет: один и тот же вход,
 * названный дважды в двух соседних местах, только удлиняет список.
 *
 * `plan` отсюда убран 06.08.2026: за этим кодом теперь «Задачи» — работа компании
 * со своей витриной, а кнопка «Поддержка» в шапке ведёт к поставщику программы. Оставь его
 * здесь — и продукт молча исчез бы из лаунчера.
 *
 * На рабочем столе пространства они остаются — там витрина всего, что подключено компании.
 */
export const SIDE_BUTTON_APPS = ['chat', 'conf']

/** Есть ли у продукта своя кнопка рядом (Чат · Конференция). */
export function hasSideButton(code: string): boolean {
  return SIDE_BUTTON_APPS.includes(code)
}

/**
 * Функции Ядра: экраны самого пространства, а не рабочие места продуктов.
 * Открываются в текущей вкладке — новая заводится для продуктов, чтобы стол
 * оставался открытым, а «Инфо» или «Данные» в стороне только теряются.
 */
const CORE_APPS = ['info', 'data', 'admin', 'pulse']

export function isCoreApp(code: string): boolean {
  return CORE_APPS.includes(code)
}

/** Каталог для лаунчера: без продуктов, у которых своя кнопка рядом. */
export function launcherApps(apps: SsoApp[]): SsoApp[] {
  return apps.filter((a) => !SIDE_BUTTON_APPS.includes(a.code))
}

/** Выпустить handoff-токен для приложения и получить URL перехода (открывать в новой вкладке). */
export async function authorizeApp(code: string, companyId?: string): Promise<string> {
  const r = await get<{ url: string; app: string; expires_in: number }>(
    '/api/sso/authorize', { app: code, company_id: companyId },
  )
  return r.url
}

/**
 * Избранные приложения каталога — тот же список, что «Закреплённые приложения»
 * в настройке пульта: у человека одно избранное на пространство, а не два.
 * Ручка живёт в SSO, а не в «Пульсе»: каталог открыт любому участнику.
 */
export async function getFavoriteApps(companyId: string): Promise<string[]> {
  const r = await get<{ codes: string[] }>('/api/sso/apps/favorites', { company_id: companyId })
  return r.codes
}

export async function saveFavoriteApps(companyId: string, codes: string[]): Promise<string[]> {
  const r = await put<{ codes: string[] }>(
    `/api/sso/apps/favorites?company_id=${encodeURIComponent(companyId)}`, { codes },
  )
  return r.codes
}
