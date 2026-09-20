/**
 * Состав окна станции: четыре раздела, внутри каждого — виды.
 *
 * ПОЧЕМУ ПЕРЕСОБРАНО (20.09.2026, замечание МАГа). Вкладок стало одиннадцать, и
 * они шли вперемешку: «Обязательства» рядом с «Договорами», «Работа» отдельно от
 * «Статуса и диагностики», «Реализация» между «Треком» и «Снабжением». Ряд не
 * помещался по ширине и обрывался молча — про «Договоры» спрашивали, есть ли они
 * вообще. Одиннадцать равноправных вкладок — это не структура, а список.
 *
 * Разделов ровно четыре, и они отвечают на четыре разных вопроса о станции:
 *
 * | Раздел | Вопрос | Кто спрашивает |
 * |---|---|---|
 * | **Паспорт** | что это за станция | все: адрес, номера, железо, к чему подключена |
 * | **Право** | кто за неё отвечает и на каких условиях | договорная и претензионная работа |
 * | **Работа** | как она работает | эксплуатация и продажи |
 * | **Сервис** | что с ней делают | инженер и поддержка |
 *
 * Внутри раздела — виды (уровень «ВИД» канона рабочей области,
 * `docs/WORKSPACE_UX_PATTERN_PROMPT.md` §1). Вид переключается сегментами, а не
 * новой вкладкой: это одна тема, показанная с разных сторон.
 *
 * Разрез по продукту здесь по-прежнему не делается (решение МАГа 12.08.2026):
 * станция — ось работы, и все её стороны открываются из любого рабочего места.
 */
import type { ComponentType } from 'react'
import { Activity, ClipboardList, Network, Scale, Wrench } from 'lucide-react'

export interface CockpitView {
  /** Ключ вида внутри раздела. */
  k: string
  label: string
  /** Вид только для ЭЗС: у АЗС и офисов ему нечего показать. */
  evOnly?: boolean
}

export interface CockpitSection {
  value: string
  label: string
  icon: ComponentType<{ className?: string }>
  views: CockpitView[]
}

export const COCKPIT_SECTIONS: CockpitSection[] = [
  {
    value: 'passport',
    label: 'Паспорт',
    icon: ClipboardList,
    // Одна страница, а не три вида. Всё про саму станцию — как называется, где
    // стоит, из чего собрана, к каким системам подключена и под какими
    // идентификаторами там известна — читается подряд, сверху вниз. Резать это
    // на сегменты значит заставить человека искать серийник в трёх местах
    // (замечание МАГа 20.09.2026).
    views: [{ k: 'about', label: 'Описание' }],
  },
  {
    value: 'mapping',
    label: 'Маппинг',
    icon: Network,
    // Под какими ключами станция известна другим системам: витрине, HubEx,
    // зарядной сети, роумингу OCPI. Раньше это лежало внутри «Паспорта» одним
    // блоком «Интеграции» и отвечало только на половину вопроса — какие
    // источники подключены, но не какие у станции там номера
    // (замечание МАГа 20.09.2026).
    views: [{ k: 'ids', label: 'Идентификаторы и связи' }],
  },
  {
    value: 'legal',
    label: 'Право',
    icon: Scale,
    // Договорная сторона площадки: чем обвязана, кто поставил, какие условия и
    // санкции, что уже поставлено. Отсюда пишется претензия производителю.
    views: [
      { k: 'obligations', label: 'Обязательства' },
      { k: 'contracts', label: 'Все договоры' },
      { k: 'supply', label: 'Снабжение' },
    ],
  },
  {
    value: 'work',
    label: 'Работа',
    icon: Activity,
    // Как станция работает: на связи ли, что с приездами клиентов, сколько
    // отпустила и сколько принесла. «Состояние» и «Приезды» рядом намеренно:
    // «нет связи» и «связь есть, но ток не идёт» — соседние вопросы одного
    // разбора.
    views: [
      { k: 'diagnostics', label: 'Состояние' },
      { k: 'visits', label: 'Приезды', evOnly: true },
      { k: 'energy', label: 'Энергия', evOnly: true },
      { k: 'sales', label: 'Реализация' },
    ],
  },
  {
    value: 'service',
    label: 'Сервис',
    icon: Wrench,
    // Что со станцией делают люди: заявки, документы и поручения, разговоры.
    // Действия (заявка, поручение, чат) вынесены в шапку окна: они относятся к
    // станции целиком, а не к одному из её разделов.
    views: [
      { k: 'tickets', label: 'Заявки' },
      // Осмотр стоит вторым, а не последним: заявка заводится ПО итогам осмотра,
      // и инженер, стоящий у станции, ищет чек-лист рядом с заявками.
      { k: 'check', label: 'Осмотр', evOnly: true },
      { k: 'track', label: 'Документы и поручения' },
      { k: 'chats', label: 'Обсуждения' },
    ],
  },
]

export type CockpitVariant = 'intake' | 'full'

/**
 * Разделы для сырого ввода («Точки обслуживания»): только то, что относится к
 * самому объекту и его работе. Права и сервиса там нет — объект ещё не введён
 * в эксплуатацию, и показывать пустые договоры незачем.
 */
const INTAKE_SECTIONS = ['passport', 'mapping', 'work']

/**
 * Куда ведут прежние ключи вкладок. Ссылки на карточку живут в чужих экранах и
 * в закладках людей; молча открывать не тот раздел нельзя, а ломать ссылку —
 * тем более.
 */
export const LEGACY_TAB_MAP: Record<string, { section: string; view: string }> = {
  passport: { section: 'passport', view: 'about' },
  equipment: { section: 'passport', view: 'about' },
  integrations: { section: 'mapping', view: 'ids' },
  mapping: { section: 'mapping', view: 'ids' },
  obligations: { section: 'legal', view: 'obligations' },
  contracts: { section: 'legal', view: 'contracts' },
  supply: { section: 'legal', view: 'supply' },
  diagnostics: { section: 'work', view: 'diagnostics' },
  work: { section: 'work', view: 'visits' },
  energy: { section: 'work', view: 'energy' },
  sales: { section: 'work', view: 'sales' },
  service: { section: 'service', view: 'tickets' },
  check: { section: 'service', view: 'check' },
  track: { section: 'service', view: 'track' },
  chats: { section: 'service', view: 'chats' },
}

/** Разделы окна с учётом варианта и типа объекта. */
export function cockpitSectionsFor(
  variant: CockpitVariant = 'full', locationType?: string,
): CockpitSection[] {
  const isEv = !locationType || locationType === 'ev_charging' || locationType === 'ezs'
  const база = variant === 'intake'
    ? COCKPIT_SECTIONS.filter((s) => INTAKE_SECTIONS.includes(s.value))
    : COCKPIT_SECTIONS
  return база
    .map((s) => ({ ...s, views: s.views.filter((v) => !v.evOnly || isEv) }))
    .filter((s) => s.views.length > 0)
}

/** Раздел и вид по прежнему ключу вкладки (для ссылок и закладок). */
export function resolveLegacyTab(tab?: string | null): { section: string; view: string } {
  return (tab && LEGACY_TAB_MAP[tab]) || { section: 'passport', view: 'about' }
}
