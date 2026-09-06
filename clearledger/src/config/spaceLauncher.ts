/**
 * Каталог продуктов пространства, разложенный по строкам рабочего стола.
 *
 * Раскладка вынесена из `EcosystemHomePage`, потому что потребителей у неё стало
 * двое: стол (плитки и список) и меню приложений прямо в левом рельсе. Второй
 * список приложений завести нельзя — состав и порядок обязаны совпадать всюду,
 * иначе «Приложения» в рельсе и стол начнут расходиться на первой же правке.
 *
 * Место на столе задаёт рабочий контур, а не слой каталога: слой говорит, ЧТО это
 * (ядро/сервис/приложение), контур — про чей день (решение МАГа 01.08.2026).
 */
import {
  LayoutGrid, LifeBuoy, ClipboardList, ListChecks, Video, FileText, MessagesSquare,
  ShieldCheck, BookOpen, HardHat, Gauge, BarChart3, Wallet, Database, MessageCircle,
  Building2, ShoppingCart, Megaphone, Network, Calculator, Stethoscope, Activity,
  Briefcase, Bot,
} from 'lucide-react'
import type { SsoApp } from '@/services/ssoService'

/** Иконка по имени из реестра Ядра (`eco_apps.icon`, манифест `apps/<code>.yml`).
 *  Неизвестное имя — LayoutGrid: плитка появляется, просто без своего значка. */
export const APP_ICONS: Record<string, typeof FileText> = {
  'life-buoy': LifeBuoy,
  'clipboard-list': ClipboardList,
  'list-checks': ListChecks,
  'video': Video,
  'file-text': FileText,
  'messages-square': MessagesSquare,
  'message-circle': MessageCircle,
  'shield-check': ShieldCheck,
  'book-open': BookOpen,
  'activity': Activity,
  // Продукты разреза Учёта (config/spaceProducts.ts).
  'hard-hat': HardHat,
  'gauge': Gauge,
  'bar-chart-3': BarChart3,
  'wallet': Wallet,
  'database': Database,
  'building-2': Building2,
  'shopping-cart': ShoppingCart,
  'megaphone': Megaphone,
  'network': Network,
  'calculator': Calculator,
  'stethoscope': Stethoscope,
  // Рабочие места компании без объектов: «Услуги». «Бухгалтерия» и «Продажи» берут
  // book-open и bar-chart-3 — они выше. Незнакомое имя молча даёт LayoutGrid.
  'briefcase': Briefcase,
  // Аудитор — сквозной агент пространства.
  'bot': Bot,
}

/** Значок продукта по имени из реестра. */
export function appIcon(icon: string | undefined) {
  return APP_ICONS[icon ?? ''] ?? LayoutGrid
}

/**
 * Приложения клиентской стороны: продать, обслужить, поддержать. Остальные продукты —
 * внутренний контур (стройка сети, эксплуатация, связь, деньги). Деление по контуру,
 * а не по слою.
 */
// Рабочая строка стола. Порядок — как к продуктам обращаются за день: заявки,
// продажи, расчёты, товары, продвижение и состояние систем (решение МАГа
// 01.08.2026; отменяет вынос «Поддержки» в сервисы от 31.07.2026 — заявки
// оказались началом дня, а не общей утилитой вроде чата).
// «Топливо» и «Торговый центр» стоят здесь, а не в «Учёте» (решение МАГа
// 03.09.2026): это то, ЧЕМ торгуем, и открывают их раньше всего остального.
// «Интернет-магазин» и «Процессинг» отсюда убраны (решение МАГа 06.09.2026): пока
// у них нет своих экранов, они стоят в сервисах экосистемы, а не в рабочей строке дня.
export const COMMERCE_APPS = ['sales', 'support', 'revenue', 'retail_store']
// «Пульс» — рабочее место руководителя над ВСЕМ пространством, поэтому своя строка
// вверху стола. Круг узкий: у кого права нет, тот этой строки не увидит вовсе.
// «Монитор» стоит здесь (решение МАГа 03.09.2026): состояние оборудования сети —
// это «как идут дела и куда вмешаться», а не работа с покупателем.
// «Чаты», «Трек» и «Конференции» стоят здесь, а не в сервисах экосистемы (решение
// МАГа 05.09.2026): связь, документы и встречи — это то, чем ведут дела, а не
// утилита где-то внизу стола. Слой в реестре у них остался `service` — он говорит,
// ЧТО это, а строка стола говорит, ЗАЧЕМ к этому идут.
export const LEAD_APPS = ['pulse', 'monitor', 'chat', 'docs', 'conf']
// Строки «Сеть» больше нет (решение МАГа 06.09.2026): «Проекты» — учётная работа
// и стоят в «Учёте», «Сеть передачи данных» — служебный экран и уходит в «Системные»,
// «Диагностика» и так была там по слою. Отдельная строка на один продукт не нужна.
//
// Служебные экраны, у которых слой в реестре прикладной, а место — в «Системных».
export const SYSTEM_APPS = ['netlink']
// Сервис экосистемы — то, что обслуживает работу, а не ведёт её. После переноса
// связи и документов в «Управление» (05.09.2026) здесь остаётся продвижение;
// «Магазин» числился сервисом с тех пор, как был универсальным интернет-магазином,
// у розницы это полноценный продукт и стоит он в рабочей строке (03.09.2026).
export const SERVICE_APPS = ['marketing', 'shop', 'corp', 'processing']
// Учётная строка: содержание сети и деньги за неё — в том порядке, в каком
// цифра идёт от объекта к отчётности.
// «Проекты» идут первыми: стройка и присоединение объектов — начало учётной цепочки,
// дальше экономика, периметр и бухгалтерия.
const INTERNAL_ORDER = ['projects', 'econ', 'perimeter', 'books']

export interface LauncherSection {
  /** Ключ строки — им же различаются пустые строки при отрисовке. */
  key: 'lead' | 'commerce' | 'internal' | 'management'
  title: string
  hint?: string
  apps: SsoApp[]
}

/** Продукт заведён в реестре, но экранов в этом стеке у него нет. */
export function isOptionalApp(a: SsoApp) {
  return a.mode === 'internal' && !a.route
}

/**
 * Каталог → строки стола, в порядке дня. Пустые строки возвращаются тоже: стол
 * рисует «Учёт» всегда (там же живут сообщения «загрузка» и «нет приложений»),
 * а меню рельса само отбрасывает пустые.
 */
export function launcherSections(all: SsoApp[]): LauncherSection[] {
  // «Системные»: экраны самого пространства и всё, к чему обращаются не каждый день.
  // Отдельной строки «Сервисы экосистемы» больше нет (решение МАГа 06.09.2026) — её
  // состав переехал сюда же, следом за экранами управления.
  //
  // «Чаты», «Трек» и «Конференции» сюда НЕ попадают: слой в реестре у них `service`,
  // но место — в «Управлении» (решение МАГа 05.09.2026), и показывать их дважды нельзя.
  const management = [
    ...all.filter((a) => (a.layer === 'admin' || SYSTEM_APPS.includes(a.code))
      && !COMMERCE_APPS.includes(a.code)),
    ...SERVICE_APPS.map((code) => all.find((a) => a.code === code))
      .filter((a): a is SsoApp => !!a),
    ...all.filter((a) => a.layer === 'service' && a.layer !== undefined
      && !COMMERCE_APPS.includes(a.code) && !SERVICE_APPS.includes(a.code)
      && !LEAD_APPS.includes(a.code) && !SYSTEM_APPS.includes(a.code)),
  ]
  const apps = all.filter((a) => !SERVICE_APPS.includes(a.code) && !SYSTEM_APPS.includes(a.code)
    && (COMMERCE_APPS.includes(a.code) || LEAD_APPS.includes(a.code)
      || (a.layer !== 'admin' && a.layer !== 'service')))
  // Порядок строки задан явно: сводка, сеть, связь, документы, встречи.
  const lead = LEAD_APPS
    .map((code) => apps.find((a) => a.code === code))
    .filter((a): a is SsoApp => !!a)
  // Порядок рабочей строки задан явно, а не порядком реестра: он отражает,
  // в каком порядке к продуктам обращаются в течение дня.
  const commerce = COMMERCE_APPS
    .map((code) => apps.find((a) => a.code === code))
    .filter((a): a is SsoApp => !!a)
  const internal = apps
    .filter((a) => !COMMERCE_APPS.includes(a.code) && !LEAD_APPS.includes(a.code))
    .sort((a, b) => {
      const ia = INTERNAL_ORDER.indexOf(a.code), ib = INTERNAL_ORDER.indexOf(b.code)
      // Незаданные продукты идут следом за перечисленными, порядком реестра.
      return (ia < 0 ? INTERNAL_ORDER.length : ia) - (ib < 0 ? INTERNAL_ORDER.length : ib)
    })

  return [
    { key: 'lead', title: 'Управление', hint: 'как идут дела, связь и документы', apps: lead },
    { key: 'commerce', title: 'Клиенты и продажи', hint: 'кому продаём и как обслуживаем', apps: commerce },
    { key: 'internal', title: 'Учёт', hint: 'проекты, экономика, периметр и бухгалтерия', apps: internal },
    // Служебные экраны пространства (решение МАГа 06.09.2026): «Управление»,
    // «Подключения», «Данные», «Инфо», «Диагностика». К ним заходят не каждый день,
    // а когда что-то настраивают или разбирают, — поэтому строка стоит последней и
    // на столе сворачивается. Кому доступа нет, у того её и не будет: состав
    // приходит уже отфильтрованным по правам.
    { key: 'management', title: 'Системные', hint: 'настройка пространства и служебные данные', apps: management },
  ]
}
