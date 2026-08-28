import { useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Database, Filter, RadioTower } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { STORE_VIEWS } from '@/config/storeCatalog'
import { cn } from '@/lib/utils'
import { STORE_DEMO_STATIONS } from '@/services/storeDemoService'

type Tone = 'success' | 'warning' | 'danger' | 'neutral'

type DemoRow = {
  id: string
  cells: string[]
  stationId?: string
  status: string
  tone: Tone
}

type DemoMetric = {
  label: string
  value: string
  hint: string
  tone?: Tone
}

type DemoModel = {
  columns: string[]
  rows: DemoRow[]
  metrics: DemoMetric[]
  alerts: string[]
  activityLabel: string
  activityUnit: 'money' | 'count'
}

type DemoKind =
  | 'shift' | 'pricing' | 'sales' | 'basket' | 'abc' | 'receipt'
  | 'movement' | 'supplier' | 'recipe' | 'report' | 'catalog' | 'barcode'
  | 'cash' | 'marking' | 'documents' | 'network' | 'integration'

const VIEW_BY_KEY = new Map(STORE_VIEWS.map((view) => [view.key, view]))

const VIEW_KINDS: Record<string, DemoKind> = {
  shifts: 'shift',
  revaluation: 'pricing', 'price-mrc': 'pricing', pricing: 'pricing',
  assortment: 'sales', dynamics: 'sales',
  baskets: 'basket', abc: 'abc',
  'receipt-edo': 'receipt', receipts: 'receipt',
  transfers: 'movement', inventory: 'movement', writeoffs: 'movement', gains: 'movement', returns: 'movement',
  suppliers: 'supplier',
  recipes: 'recipe', menu: 'recipe',
  reports: 'report', turnover: 'report', purchases: 'report', 'no-cost': 'report',
  'pay-mix': 'report', people: 'report', 'purchase-diff': 'report',
  'catalog-health': 'catalog', nomenclature: 'catalog', categories: 'catalog', 'station-drafts': 'catalog',
  barcodes: 'barcode', 'barcode-collisions': 'barcode',
  kkt: 'cash', cheques: 'cash',
  gtin: 'marking', mrc: 'marking', mark_codes: 'marking', mark_intake: 'marking',
  withdrawal: 'marking', perm_mode: 'marking', gismt: 'marking',
  docs_supply: 'documents', docs_shifts: 'documents', docs_movement: 'documents',
  docs_stock: 'documents', docs_price: 'documents', docs_catering: 'documents',
  store_documents: 'documents', recompute: 'documents', 'cheque-journal': 'documents',
  station_health: 'network', agent_versions: 'network', downlink: 'network', storage: 'network',
  chain: 'integration', parity: 'integration', dedup: 'integration', cure: 'integration',
}

const RIGHT_COLUMNS = new Set([
  'Выручка', 'Сумма', 'Цена', 'Себестоимость', 'Маржа', 'Количество', 'Остаток',
  'Продано', 'Чеков', 'Поддержка', 'Уверенность', 'Lift', 'Доля', 'Расхождение',
  'Коды', 'Пакеты', 'Очередь', 'Ledger', '1С', 'Δ', 'Food cost',
])

const money = (value: number) => new Intl.NumberFormat('ru-RU', {
  maximumFractionDigits: 0,
}).format(value) + ' ₽'

const number = (value: number) => new Intl.NumberFormat('ru-RU', {
  maximumFractionDigits: 0,
}).format(value)

const rows = (...items: DemoRow[]) => items

const row = (
  id: string,
  cells: string[],
  status: string,
  tone: Tone = 'success',
  stationId?: string,
): DemoRow => ({ id, cells, status, tone, stationId })

const PRICE_ROWS = rows(
  row('price-1', ['Вода минеральная 0,5 л', 'АЗС 101', '48 ₽', '89 ₽', '46,1%'], 'В коридоре', 'success', '101'),
  row('price-2', ['Кофе американо 300 мл', 'АЗС 208', '43 ₽', '149 ₽', '71,1%'], 'Высокая маржа', 'success', '208'),
  row('price-3', ['Хот-дог классический', 'АЗС 315', '91 ₽', '229 ₽', '60,3%'], 'В коридоре', 'success', '315'),
  row('price-4', ['Молоко 1 л', 'АЗС 315', '77 ₽', '79 ₽', '2,5%'], 'Ниже пола', 'danger', '315'),
  row('price-5', ['Масло моторное 5W-30', 'АЗС 208', '642 ₽', '899 ₽', '28,6%'], 'Проверить KVI', 'warning', '208'),
)

const SALES_ROWS = rows(
  row('sale-1', ['Кофе американо 300 мл', 'Общепит', 'АЗС 208', '1 184', '176 416 ₽', '71,1%'], 'Лидер', 'success', '208'),
  row('sale-2', ['Вода минеральная 0,5 л', 'Напитки', 'АЗС 101', '862', '76 718 ₽', '46,1%'], 'Стабильно', 'success', '101'),
  row('sale-3', ['Хот-дог классический', 'Общепит', 'АЗС 315', '418', '95 722 ₽', '60,3%'], 'Рост 8,4%', 'success', '315'),
  row('sale-4', ['Шоколад молочный 90 г', 'Снеки', 'АЗС 101', '291', '40 449 ₽', '38,1%'], 'Стабильно', 'success', '101'),
  row('sale-5', ['Молоко 1 л', 'Молочная продукция', 'АЗС 315', '104', '12 376 ₽', '2,5%'], 'Маржа ниже пола', 'danger', '315'),
  row('sale-6', ['Стеклоомыватель 4 л', 'Автотовары', 'АЗС 208', '148', '48 692 ₽', '36,8%'], 'Запас 9 дней', 'warning', '208'),
)

const SHIFT_ROWS = rows(
  row('shift-1', ['№ 6418', 'АЗС 101', '24.08 · 08:03', '38 460 ₽', '164', '12 из 12'], 'Готова', 'success', '101'),
  row('shift-2', ['№ 6419', 'АЗС 208', '24.08 · 08:11', '46 920 ₽', '193', '12 из 12'], 'Готова', 'success', '208'),
  row('shift-3', ['№ 6420', 'АЗС 315', '24.08 · 08:27', '29 180 ₽', '121', '11 из 12'], 'Нет сверки кассы', 'warning', '315'),
  row('shift-4', ['№ 6415', 'АЗС 101', '23.08 · 20:06', '41 230 ₽', '176', '12 из 12'], 'Готова', 'success', '101'),
  row('shift-5', ['№ 6416', 'АЗС 208', '23.08 · 20:14', '52 840 ₽', '214', '10 из 12'], 'Ждёт 2 документа', 'danger', '208'),
)

const BASKET_ROWS = rows(
  row('basket-1', ['Кофе + хот-дог', '428', '9,9%', '36,2%', '2,41'], 'Связка для акции'),
  row('basket-2', ['Вода + шоколад', '216', '5,0%', '22,8%', '1,74'], 'Стабильная связка'),
  row('basket-3', ['Кофе + вода', '194', '4,5%', '16,4%', '1,12'], 'Слабая связь', 'warning'),
  row('basket-4', ['Чипсы + напиток', '181', '4,2%', '29,1%', '2,06'], 'Выкладка рядом'),
  row('basket-5', ['Масло + омыватель', '34', '0,8%', '18,7%', '1,63'], 'Сезонный спрос'),
)

const ABC_ROWS = rows(
  row('abc-1', ['Кофе американо 300 мл', 'АЗС 208', '176 416 ₽', '17,5%', 'A', '8 дней'], 'Держать наличие', 'success', '208'),
  row('abc-2', ['Хот-дог классический', 'АЗС 315', '95 722 ₽', '9,5%', 'A', '6 дней'], 'Держать наличие', 'success', '315'),
  row('abc-3', ['Вода минеральная 0,5 л', 'АЗС 101', '76 718 ₽', '7,6%', 'A', '11 дней'], 'Норма', 'success', '101'),
  row('abc-4', ['Масло моторное 5W-30', 'АЗС 208', '61 132 ₽', '6,0%', 'B', '37 дней'], 'Избыток', 'warning', '208'),
  row('abc-5', ['Молоко 1 л', 'АЗС 315', '12 376 ₽', '1,2%', 'C', '–3 шт.'], 'Минус на складе', 'danger', '315'),
  row('abc-6', ['Стеклоомыватель 4 л', 'АЗС 101', '11 844 ₽', '1,1%', 'C', '29 дней'], 'Медленный оборот', 'warning', '101'),
)

const RECEIPT_ROWS = rows(
  row('receipt-1', ['ПТУ-5841', 'АЗС 101', 'ООО «СеверТорг»', '23.08', '84 620 ₽', '0 ₽'], 'Принята', 'success', '101'),
  row('receipt-2', ['УПД-29174', 'АЗС 208', 'ООО «ФудЛайн»', '23.08', '126 430 ₽', '+1 240 ₽'], 'Есть расхождение', 'warning', '208'),
  row('receipt-3', ['ПТУ-5844', 'АЗС 315', 'ООО «АвтоХим»', '22.08', '47 980 ₽', '–3 180 ₽'], 'Требует решения', 'danger', '315'),
  row('receipt-4', ['УПД-29188', 'АЗС 101', 'ООО «Балтика Снэк»', '22.08', '61 240 ₽', '0 ₽'], 'Принята', 'success', '101'),
  row('receipt-5', ['ПТУ-5851', 'АЗС 208', 'ООО «СеверТорг»', '24.08', '92 110 ₽', '0 ₽'], 'Ждёт подтверждения', 'warning', '208'),
)

const SUPPLIER_ROWS = rows(
  row('supplier-1', ['ООО «СеверТорг»', 'АЗС 101, 208', '312 840 ₽', '8', '97%', '0,4%'], 'Надёжный'),
  row('supplier-2', ['ООО «ФудЛайн»', 'Вся сеть', '284 120 ₽', '11', '91%', '1,8%'], 'Контроль срока', 'warning'),
  row('supplier-3', ['ООО «АвтоХим»', 'АЗС 208, 315', '128 700 ₽', '4', '75%', '4,1%'], 'Пересмотреть условия', 'danger'),
  row('supplier-4', ['ООО «Балтика Снэк»', 'Вся сеть', '196 430 ₽', '7', '100%', '0%'], 'Без замечаний'),
)

const RECIPE_ROWS = rows(
  row('recipe-1', ['Кофе американо 300 мл', '1 184', '43 ₽', '149 ₽', '28,9%', '0,8%'], 'Версия 4 активна'),
  row('recipe-2', ['Хот-дог классический', '418', '91 ₽', '229 ₽', '39,7%', '2,4%'], 'Версия 3 активна'),
  row('recipe-3', ['Капучино 300 мл', '756', '57 ₽', '179 ₽', '31,8%', '1,1%'], 'Норма'),
  row('recipe-4', ['Сэндвич с курицей', '214', '126 ₽', '269 ₽', '46,8%', '6,2%'], 'Высокое списание', 'danger'),
  row('recipe-5', ['Чай облепиховый', '188', '52 ₽', '169 ₽', '30,8%', '3,1%'], 'Проверить норму', 'warning'),
)

const CATALOG_ROWS = rows(
  row('catalog-1', ['Вода минеральная 0,5 л', 'ВОД-050', 'Напитки', '89 ₽', '4601234567001'], 'Карточка полная'),
  row('catalog-2', ['Кофе американо 300 мл', 'КОФ-300', 'Общепит', '149 ₽', '2000000000101'], 'Карточка полная'),
  row('catalog-3', ['Молоко 1 л', 'МОЛ-100', 'Молочная продукция', '119 ₽', '4601234567004'], 'Маркируемый товар', 'warning'),
  row('catalog-4', ['Масло моторное 5W-30', 'МАС-530', 'Автотовары', '899 ₽', '4601234567005'], 'Карточка полная'),
  row('catalog-5', ['Сэндвич с курицей', 'СЭН-210', 'Общепит', '269 ₽', '2000000000128'], 'Нет фото', 'warning'),
  row('catalog-6', ['Напиток энергетический 0,45 л', 'ЭН-045', 'Напитки', '189 ₽', '4601234567099'], 'Ставка НДС устарела', 'danger'),
)

const BARCODE_ROWS = rows(
  row('barcode-1', ['4601234567001', 'Вода минеральная 0,5 л', '101, 208, 315', '1', '24.08 · 07:12'], 'Без конфликтов'),
  row('barcode-2', ['4601234567004', 'Молоко 1 л', '101, 208, 315', '1', '24.08 · 07:11'], 'Маркируемый'),
  row('barcode-3', ['2000000000101', 'Кофе американо 300 мл', '101, 208', '2', '23.08 · 19:43'], 'Две карточки', 'danger'),
  row('barcode-4', ['4601234567005', 'Масло моторное 5W-30', '208, 315', '1', '24.08 · 06:58'], 'Без конфликтов'),
  row('barcode-5', ['4601234567099', 'Энергетик 0,45 л', '315', '0', '22.08 · 18:06'], 'Не уехал в кассу', 'warning'),
)

const CASH_ROWS = rows(
  row('cash-1', ['АЗС 101 · № 6418', '24.08 · 08:03', '164', '38 460 ₽', '9 840 ₽', '28 620 ₽'], 'Фискализирована', 'success', '101'),
  row('cash-2', ['АЗС 208 · № 6419', '24.08 · 08:11', '193', '46 920 ₽', '12 140 ₽', '34 780 ₽'], 'Фискализирована', 'success', '208'),
  row('cash-3', ['АЗС 315 · № 6420', '24.08 · 08:27', '121', '29 180 ₽', '8 270 ₽', '20 910 ₽'], 'Ждёт ОФД', 'warning', '315'),
  row('cash-4', ['АЗС 208 · № 6416', '23.08 · 20:14', '214', '52 840 ₽', '13 980 ₽', '38 860 ₽'], 'Расхождение 460 ₽', 'danger', '208'),
)

const MARKING_ROWS = rows(
  row('mark-1', ['Молоко 1 л', '04601234567004', 'АЗС 101', '86', 'Продажа · 24.08 08:34'], 'Оборот корректен', 'success', '101'),
  row('mark-2', ['Молоко 1 л', '04601234567004', 'АЗС 315', '14', 'Приёмка · 23.08 17:20'], '3 кода не приняты', 'warning', '315'),
  row('mark-3', ['Сигареты Север', '04601234567120', 'АЗС 208', '148', 'Продажа · 24.08 08:41'], 'МРЦ совпадает', 'success', '208'),
  row('mark-4', ['Масло моторное 5W-30', '04601234567005', 'АЗС 208', '12', 'Остаток · 24.08 07:00'], 'GTIN без категории', 'danger', '208'),
  row('mark-5', ['Вода питьевая 0,5 л', '04601234567901', 'АЗС 101', '42', 'Проверка · 24.08 08:16'], 'Не маркируется', 'neutral', '101'),
)

const DOCUMENT_ROWS = rows(
  row('doc-1', ['Поставка', 'ПТУ-5841', 'АЗС 101', '23.08', '84 620 ₽', '12 из 12'], 'Готов к учёту', 'success', '101'),
  row('doc-2', ['Смена', '№ 6419', 'АЗС 208', '24.08', '46 920 ₽', '12 из 12'], 'Готов к учёту', 'success', '208'),
  row('doc-3', ['Инвентаризация', 'ИНВ-129', 'АЗС 315', '22.08', '–7 840 ₽', '9 из 12'], 'Требует решения', 'danger', '315'),
  row('doc-4', ['Переоценка', 'ПЕР-884', 'АЗС 101', '23.08', '+12 460 ₽', '11 из 12'], 'Ждёт кассу', 'warning', '101'),
  row('doc-5', ['Перемещение', 'ПМ-311', 'АЗС 208 → 315', '21.08', '18 240 ₽', '10 из 12'], 'Нет приёмки', 'warning', '208'),
  row('doc-6', ['Общепит', 'ВЫП-418', 'АЗС 208', '24.08', '14 880 ₽', '12 из 12'], 'Готов к учёту', 'success', '208'),
)

const REPORT_ROWS = rows(
  row('report-1', ['АЗС 101', '412 580 ₽', '248 700 ₽', '387 440 ₽', '0', '98%'], 'Готова', 'success', '101'),
  row('report-2', ['АЗС 208', '528 340 ₽', '314 280 ₽', '462 190 ₽', '2', '94%'], 'Есть замечания', 'warning', '208'),
  row('report-3', ['АЗС 315', '306 120 ₽', '186 900 ₽', '278 360 ₽', '5', '82%'], 'Требует разбора', 'danger', '315'),
)

const NETWORK_ROWS = rows(
  row('network-1', ['АЗС 101', '24.08 · 09:42', '1.101.5', '0', '146', '182 МБ'], 'Онлайн', 'success', '101'),
  row('network-2', ['АЗС 208', '24.08 · 09:41', '1.101.5', '2', '183', '224 МБ'], 'Онлайн · очередь', 'warning', '208'),
  row('network-3', ['АЗС 315', '24.08 · 07:18', '1.100.9', '4', '98', '164 МБ'], 'Нет связи 2 ч 24 мин', 'danger', '315'),
)

const INTEGRATION_ROWS = rows(
  row('integration-1', ['Вода минеральная 0,5 л', 'АЗС 101', '42', '42', '0'], 'Совпадает', 'success', '101'),
  row('integration-2', ['Кофе американо 300 мл', 'АЗС 208', '121', '119', '+2'], 'Расхождение', 'warning', '208'),
  row('integration-3', ['Молоко 1 л', 'АЗС 315', '–3', '4', '–7'], 'Критично', 'danger', '315'),
  row('integration-4', ['Масло моторное 5W-30', 'АЗС 208', '12', '12', '0'], 'Совпадает', 'success', '208'),
  row('integration-5', ['Стеклоомыватель 4 л', 'АЗС 101', '15', '18', '–3'], 'Проверить документ', 'warning', '101'),
)

function daysInRange(from: string, to: string): number {
  const first = new Date(`${from}T00:00:00Z`).getTime()
  const last = new Date(`${to}T00:00:00Z`).getTime()
  return Math.max(1, Math.round((last - first) / 86_400_000) + 1)
}

function metric(label: string, value: string, hint: string, tone?: Tone): DemoMetric {
  return { label, value, hint, tone }
}

function metrics(kind: DemoKind, factor: number): DemoMetric[] {
  const scaled = (value: number) => Math.max(1, Math.round(value * factor))
  const amount = (value: number) => money(value * factor)

  switch (kind) {
    case 'shift': return [
      metric('Закрыто смен', number(scaled(144)), 'за выбранный период'),
      metric('Готовы к учёту', number(scaled(141)), '97,9% смен'),
      metric('Выручка', amount(1_247_040), 'с НДС'),
      metric('Требуют разбора', number(scaled(3)), 'документы и касса', 'warning'),
    ]
    case 'pricing': return [
      metric('Позиций с ценой', number(scaled(1_842)), '98,6% ассортимента'),
      metric('Средняя маржа', '50,9%', 'по товарам с себестоимостью'),
      metric('Ниже пола маржи', number(scaled(7)), 'нужно решение', 'danger'),
      metric('Ждут кассу', number(scaled(12)), 'переоценки', 'warning'),
    ]
    case 'sales': return [
      metric('Выручка', amount(1_010_740), 'сопутка + общепит'),
      metric('Продано единиц', number(scaled(4_912)), '8 активных SKU в срезе'),
      metric('Средний чек', '235 ₽', '4 305 чеков'),
      metric('Валовая прибыль', amount(514_400), 'маржа 50,9%'),
    ]
    case 'basket': return [
      metric('Чеков разобрано', number(scaled(4_305)), 'товарный состав'),
      metric('Пар найдено', number(scaled(38)), 'lift выше 1,2'),
      metric('Лучшая связка', '2,41', 'lift кофе + хот-дог'),
      metric('Без допродажи', '61,8%', 'одна позиция в чеке', 'warning'),
    ]
    case 'abc': return [
      metric('Класс A', '18 SKU', '80,4% выручки'),
      metric('Класс B', '34 SKU', '14,6% выручки'),
      metric('Класс C', '126 SKU', '5,0% выручки'),
      metric('Риск наличия', '5 SKU', 'класс A с запасом < 3 дней', 'danger'),
    ]
    case 'receipt': return [
      metric('Поставок', number(scaled(31)), 'за период'),
      metric('Принято товара', amount(812_640), 'по факту станции'),
      metric('Расхождения', amount(4_420), '0,54% поставок', 'warning'),
      metric('Ждут решения', number(scaled(2)), 'накладные', 'danger'),
    ]
    case 'movement': return [
      metric('Документов', number(scaled(46)), 'движение за период'),
      metric('Сумма движения', amount(286_430), 'по себестоимости'),
      metric('Проведено', '93,5%', '43 из 46'),
      metric('Проблемных', number(scaled(3)), 'минусы и подтверждения', 'warning'),
    ]
    case 'supplier': return [
      metric('Поставщиков', '12', '4 основных'),
      metric('Закуплено', amount(921_320), 'за период'),
      metric('В срок', '91,7%', 'по дате приёмки'),
      metric('С расхождениями', '3', 'нужно решение', 'warning'),
    ]
    case 'recipe': return [
      metric('Активных блюд', '42', 'с действующей ТТК'),
      metric('Выручка кухни', amount(457_476), '45,3% магазина'),
      metric('Средний food cost', '34,6%', 'по актуальным ценам'),
      metric('Сверх нормы', '2 блюда', 'списание ингредиентов', 'danger'),
    ]
    case 'report': return [
      metric('Выручка сети', amount(1_247_040), 'по выбранным АЗС'),
      metric('Приход', amount(749_880), 'за период'),
      metric('Остаток', amount(1_128_000), 'розничная стоимость'),
      metric('Отклонений', number(scaled(7)), 'требуют разбора', 'warning'),
    ]
    case 'catalog': return [
      metric('Карточек товара', number(scaled(1_868)), 'центральный каталог'),
      metric('Полные карточки', '96,8%', 'цена, НДС, ШК, группа'),
      metric('Черновиков АЗС', number(scaled(9)), 'ждут признания', 'warning'),
      metric('Критичных ошибок', number(scaled(3)), 'мешают продаже', 'danger'),
    ]
    case 'barcode': return [
      metric('Штрихкодов', number(scaled(2_146)), 'по каталогу'),
      metric('В кассе', '98,9%', 'доступны для продажи'),
      metric('Коллизий', number(scaled(2)), 'один ШК — две карточки', 'danger'),
      metric('Не выгружено', number(scaled(5)), 'ждут кассу', 'warning'),
    ]
    case 'cash': return [
      metric('Кассовых смен', number(scaled(144)), 'закрыто'),
      metric('Чеков', number(scaled(4_305)), 'магазин и общепит'),
      metric('Фискальная выручка', amount(1_010_740), 'с НДС'),
      metric('Расхождения', amount(460), 'одна смена', 'danger'),
    ]
    case 'marking': return [
      metric('Кодов на остатке', number(scaled(1_284)), 'по трём АЗС'),
      metric('Продано кодов', number(scaled(436)), 'за период'),
      metric('Ошибок ГИС МТ', number(scaled(4)), 'не приняты операции', 'danger'),
      metric('Проверка кассы', '99,2%', 'успешных запросов'),
    ]
    case 'documents': return [
      metric('Документов', number(scaled(286)), 'в контуре магазина'),
      metric('Готовы к учёту', '94,1%', 'все подтверждения есть'),
      metric('Ждут решения', number(scaled(8)), 'есть расхождения', 'warning'),
      metric('На пересчёте', number(scaled(5)), 'изменены задним числом', 'danger'),
    ]
    case 'network': return [
      metric('Станций в сети', number(Math.max(1, Math.round(3 * factor))), 'из выбранного контура'),
      metric('На связи', number(Math.max(1, Math.round(2 * factor))), 'агенты отвечают'),
      metric('Пакетов', number(scaled(427)), 'принято за период'),
      metric('В очереди', number(scaled(6)), '2 станции', 'warning'),
    ]
    case 'integration': return [
      metric('Позиций сверено', number(scaled(1_842)), 'Ledger ↔ 1С'),
      metric('Совпало', '98,7%', 'по количеству'),
      metric('Расхождений', number(scaled(24)), 'нужно разобрать', 'warning'),
      metric('Дублей наследия', number(scaled(7)), 'несколько карточек 1С', 'danger'),
    ]
  }
}

function dataFor(viewKey: string, kind: DemoKind): Pick<DemoModel, 'columns' | 'rows' | 'alerts'> {
  switch (kind) {
    case 'shift': return {
      columns: ['Смена', 'АЗС', 'Закрыта', 'Выручка', 'Чеков', 'Готовность'],
      rows: SHIFT_ROWS,
      alerts: ['Смена № 6420 не получила сверку кассы.', 'По смене № 6416 не доехали два документа движения.'],
    }
    case 'pricing': return {
      columns: ['Товар', 'АЗС', 'Себестоимость', 'Цена', 'Маржа'],
      rows: PRICE_ROWS,
      alerts: ['Молоко на АЗС 315 продаётся ниже установленного пола маржи.', '12 переоценок ещё не подтверждены кассами.'],
    }
    case 'sales': return {
      columns: ['Товар', 'Категория', 'АЗС', 'Продано', 'Выручка', 'Маржа'],
      rows: SALES_ROWS,
      alerts: ['По молоку маржа снизилась до 2,5%.', 'Стеклоомывателя на АЗС 208 хватит на 9 дней при текущем темпе.'],
    }
    case 'basket': return {
      columns: ['Пара товаров', 'Чеков', 'Поддержка', 'Уверенность', 'Lift'],
      rows: BASKET_ROWS,
      alerts: ['61,8% чеков содержат только одну позицию.', 'Связка «кофе + хот-дог» даёт лучший потенциал допродажи.'],
    }
    case 'abc': return {
      columns: ['Товар', 'АЗС', 'Выручка', 'Доля', 'ABC', 'Остаток'],
      rows: ABC_ROWS,
      alerts: ['Пять товаров класса A имеют запас меньше трёх дней.', 'Молоко на АЗС 315 одновременно в классе C и в минусовом остатке.'],
    }
    case 'receipt': return {
      columns: ['Документ', 'АЗС', 'Поставщик', 'Дата', 'Сумма', 'Расхождение'],
      rows: RECEIPT_ROWS,
      alerts: ['ПТУ-5844 требует решения по недопоставке на 3 180 ₽.', 'ПТУ-5851 ожидает подтверждения администратора АЗС 208.'],
    }
    case 'movement': {
      const operation = ({
        transfers: 'Перемещение', inventory: 'Инвентаризация', writeoffs: 'Списание',
        gains: 'Оприходование', returns: 'Возврат',
      } as Record<string, string>)[viewKey] ?? 'Движение'
      return {
        columns: ['Товар', 'АЗС', 'Документ', 'Количество', 'Сумма', 'Ответственный'],
        rows: SALES_ROWS.map((source, index) => row(
          `${viewKey}-${index}`,
          [source.cells[0], source.cells[2], `${operation.slice(0, 3).toUpperCase()}-${318 + index}`, `${index % 2 ? '+' : '–'}${12 + index * 3} шт.`, `${2_840 + index * 1_320} ₽`, index % 2 ? 'А. Воронова' : 'И. Ковалёв'],
          index === 4 ? 'Требует подтверждения' : 'Проведено',
          index === 4 ? 'warning' : 'success',
          source.stationId,
        )),
        alerts: [`Один документ «${operation.toLowerCase()}» ждёт подтверждения.`, 'На АЗС 315 после движения остался минус по молоку.'],
      }
    }
    case 'supplier': return {
      columns: ['Поставщик', 'Контур', 'Сумма', 'Поставок', 'В срок', 'Расхождения'],
      rows: SUPPLIER_ROWS,
      alerts: ['«АвтоХим» доставил в срок только 75% поставок.', 'Доля расхождений «АвтоХим» выросла до 4,1%.'],
    }
    case 'recipe': return {
      columns: ['Блюдо', 'Продано', 'Себестоимость', 'Цена', 'Food cost', 'Списание'],
      rows: RECIPE_ROWS,
      alerts: ['По сэндвичу списание ингредиентов выше нормы.', 'У чая нужно проверить норму облепихового пюре.'],
    }
    case 'report': return {
      columns: ['АЗС', 'Выручка', 'Приход', 'Остаток', 'Расхождений', 'Готовность'],
      rows: REPORT_ROWS,
      alerts: [`Отчёт «${VIEW_BY_KEY.get(viewKey)?.label ?? 'Сеть'}» показывает пять отклонений на АЗС 315.`, 'АЗС 208 готова к передаче в бухгалтерию на 94%.'],
    }
    case 'catalog': return {
      columns: ['Товар', 'Артикул', 'Группа', 'Цена', 'Штрихкод'],
      rows: CATALOG_ROWS,
      alerts: ['Три ошибки каталога мешают продаже на кассе.', 'Девять черновиков со станций ждут признания в центральном каталоге.'],
    }
    case 'barcode': return {
      columns: ['Штрихкод', 'Товар', 'АЗС', 'Карточек', 'Последняя выгрузка'],
      rows: BARCODE_ROWS,
      alerts: ['Штрихкод кофе связан с двумя карточками.', 'Энергетик на АЗС 315 не выгружен в кассу.'],
    }
    case 'cash': return {
      columns: ['Смена', 'Закрыта', 'Чеков', 'Выручка', 'Наличные', 'Безналичные'],
      rows: CASH_ROWS,
      alerts: ['Смена № 6416 расходится с фискальным итогом на 460 ₽.', 'АЗС 315 ждёт подтверждения ОФД.'],
    }
    case 'marking': return {
      columns: ['Товар', 'GTIN', 'АЗС', 'Коды', 'Последнее событие'],
      rows: MARKING_ROWS,
      alerts: ['Три молочных кода на АЗС 315 не приняты ГИС МТ.', 'У моторного масла GTIN не сопоставлен с категорией.'],
    }
    case 'documents': return {
      columns: ['Вид', 'Документ', 'АЗС', 'Дата', 'Сумма', 'Готовность'],
      rows: DOCUMENT_ROWS,
      alerts: ['Инвентаризация ИНВ-129 требует решения по недостаче.', 'Перемещение ПМ-311 не подтверждено принимающей станцией.'],
    }
    case 'network': {
      const columns = viewKey === 'storage'
        ? ['АЗС', 'Последняя связь', 'Агент', 'Очередь', 'Пакеты', 'Хранение']
        : ['АЗС', 'Последняя связь', 'Агент', 'Очередь', 'Пакеты', 'Трафик']
      return {
        columns,
        rows: NETWORK_ROWS,
        alerts: ['АЗС 315 не выходила на связь 2 часа 24 минуты.', 'На АЗС 208 и 315 накопилось шесть пакетов.'],
      }
    }
    case 'integration': return {
      columns: ['Товар', 'АЗС', 'Ledger', '1С', 'Δ'],
      rows: INTEGRATION_ROWS,
      alerts: ['По молоку на АЗС 315 расхождение семь единиц.', 'Семь карточек 1С признаны дублями наследия.'],
    }
  }
}

function buildModel(viewKey: string, dateFrom: string, dateTo: string, stations: string[]): DemoModel {
  const kind = VIEW_KINDS[viewKey] ?? 'report'
  const factor = Math.max(0.08, (daysInRange(dateFrom, dateTo) / 24) * (stations.length / 3))
  const data = dataFor(viewKey, kind)
  return {
    ...data,
    rows: data.rows.filter((item) => !item.stationId || stations.includes(item.stationId)),
    metrics: metrics(kind, factor),
    alerts: data.alerts,
    activityLabel: ['sales', 'shift', 'pricing', 'receipt', 'movement', 'supplier', 'recipe', 'report', 'cash'].includes(kind)
      ? 'Оборот по выбранным АЗС' : 'Активность по выбранным АЗС',
    activityUnit: ['sales', 'shift', 'pricing', 'receipt', 'movement', 'supplier', 'recipe', 'report', 'cash'].includes(kind)
      ? 'money' : 'count',
  }
}

function Status({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <Badge variant="outline" className={cn(
      'rounded-md px-2 py-0.5 text-[10px] font-medium',
      tone === 'success' && 'border-emerald-500/35 bg-emerald-500/10 text-emerald-400',
      tone === 'warning' && 'border-amber-500/35 bg-amber-500/10 text-amber-300',
      tone === 'danger' && 'border-red-500/35 bg-red-500/10 text-red-300',
      tone === 'neutral' && 'text-muted-foreground',
    )}>
      {children}
    </Badge>
  )
}

export function StoreDemoRichView({ viewKey, dateFrom, dateTo, stations }: {
  viewKey: string
  dateFrom: string
  dateTo: string
  stations: string[]
}) {
  const [attentionOnly, setAttentionOnly] = useState(false)
  const view = VIEW_BY_KEY.get(viewKey)
  const model = useMemo(
    () => buildModel(viewKey, dateFrom, dateTo, stations),
    [viewKey, dateFrom, dateTo, stations],
  )
  const visibleRows = attentionOnly ? model.rows.filter((item) => item.tone === 'warning' || item.tone === 'danger') : model.rows
  const attentionCount = model.rows.filter((item) => item.tone === 'warning' || item.tone === 'danger').length
  const Icon = view?.icon ?? Database
  const activityValues = STORE_DEMO_STATIONS
    .filter((station) => stations.includes(station.id))
    .map((station, index) => ({
      label: station.name,
      value: [412_580, 528_340, 306_120][Number(station.id) === 101 ? 0 : Number(station.id) === 208 ? 1 : 2] * (daysInRange(dateFrom, dateTo) / 24),
      count: [146, 183, 98][Number(station.id) === 101 ? 0 : Number(station.id) === 208 ? 1 : 2],
      color: ['bg-primary', 'bg-cyan-500', 'bg-violet-500'][index % 3],
    }))
  const activityTotal = activityValues.reduce((sum, item) => sum + (model.activityUnit === 'money' ? item.value : item.count), 0) || 1

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[1440px] space-y-5 p-5 lg:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <Icon className="size-4 text-primary" aria-hidden="true" />
              {view?.title ?? view?.label ?? 'Магазин'}
            </h2>
            <p className="mt-1 max-w-5xl text-xs leading-relaxed text-muted-foreground">
              {view?.subtitle}
            </p>
          </div>
          <Badge variant="outline" className="rounded-md text-[10px] text-muted-foreground">Синтетические данные</Badge>
        </div>

        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          {model.metrics.map((item) => (
            <div key={item.label} className="rounded-lg border border-border/60 bg-card/40 p-3.5">
              <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{item.label}</div>
              <div className={cn(
                'mt-1.5 text-xl font-semibold tabular-nums',
                item.tone === 'warning' && 'text-amber-300',
                item.tone === 'danger' && 'text-red-300',
              )}>{item.value}</div>
              <div className="mt-1 text-[11px] text-muted-foreground">{item.hint}</div>
            </div>
          ))}
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
          <section className="min-w-0 rounded-lg border border-border/60 bg-card/30">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 px-4 py-3">
              <div>
                <h3 className="text-sm font-medium">Демо-срез</h3>
                <p className="mt-0.5 text-[11px] text-muted-foreground">{dateFrom} — {dateTo} · {stations.length} АЗС</p>
              </div>
              <div className="flex items-center gap-1">
                <Button size="xs" variant={attentionOnly ? 'ghost' : 'secondary'} onClick={() => setAttentionOnly(false)}>
                  Все данные
                </Button>
                <Button size="xs" variant={attentionOnly ? 'secondary' : 'ghost'} onClick={() => setAttentionOnly(true)}>
                  <Filter data-icon="inline-start" />
                  Требуют внимания · {attentionCount}
                </Button>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-xs">
                <thead className="bg-muted/20 text-muted-foreground">
                  <tr>
                    {model.columns.map((column) => (
                      <th key={column} className={cn(
                        'whitespace-nowrap px-3 py-2.5 text-left font-medium',
                        RIGHT_COLUMNS.has(column) && 'text-right',
                      )}>{column}</th>
                    ))}
                    <th className="px-3 py-2.5 text-left font-medium">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((item) => (
                    <tr key={item.id} className="border-t border-border/35 hover:bg-accent/25">
                      {item.cells.map((cell, index) => (
                        <td key={`${item.id}-${index}`} className={cn(
                          'whitespace-nowrap px-3 py-2.5',
                          index === 0 ? 'font-medium' : 'text-muted-foreground',
                          RIGHT_COLUMNS.has(model.columns[index]) && 'text-right tabular-nums',
                        )}>{cell}</td>
                      ))}
                      <td className="whitespace-nowrap px-3 py-2.5"><Status tone={item.tone}>{item.status}</Status></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {visibleRows.length === 0 && (
                <div className="flex items-center justify-center gap-2 p-8 text-sm text-muted-foreground">
                  <CheckCircle2 className="size-4 text-emerald-500" aria-hidden="true" />
                  В выбранном контуре нет строк, требующих внимания
                </div>
              )}
            </div>
          </section>

          <aside className="space-y-4">
            <section className="rounded-lg border border-border/60 bg-card/30 p-4">
              <h3 className="text-sm font-medium">{model.activityLabel}</h3>
              <div className="mt-4 space-y-3">
                {activityValues.map((item) => {
                  const raw = model.activityUnit === 'money' ? item.value : item.count
                  const percent = Math.max(6, (raw / activityTotal) * 100)
                  return (
                    <div key={item.label}>
                      <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
                        <span>{item.label}</span>
                        <span className="tabular-nums text-muted-foreground">
                          {model.activityUnit === 'money' ? money(item.value) : number(item.count)}
                        </span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted/40">
                        <div className={cn('h-full rounded-full', item.color)} style={{ width: `${percent}%` }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            <section className="rounded-lg border border-border/60 bg-card/30 p-4">
              <h3 className="flex items-center gap-2 text-sm font-medium">
                <AlertTriangle className="size-4 text-amber-400" aria-hidden="true" />
                Что требует внимания
              </h3>
              <div className="mt-3 space-y-2.5">
                {model.alerts.map((alert) => (
                  <div key={alert} className="rounded-md bg-amber-500/8 px-3 py-2 text-xs leading-relaxed text-amber-100/85">
                    {alert}
                  </div>
                ))}
              </div>
            </section>
          </aside>
        </div>

        {view?.blocks.length ? (
          <section className="rounded-lg border border-border/60 bg-card/30 p-4">
            <h3 className="text-sm font-medium">Что показывает экран</h3>
            <div className="mt-3 grid gap-x-6 gap-y-3 md:grid-cols-2 xl:grid-cols-3">
              {view.blocks.slice(0, 6).map((block) => (
                <div key={block.name}>
                  <div className="text-xs font-medium">{block.name}</div>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{block.desc}</p>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <div className="flex items-center gap-2 text-[10px] text-muted-foreground/70">
          <RadioTower className="size-3.5" aria-hidden="true" />
          Демо построено на синтетических данных АЗС 101, 208 и 315; реальные источники не запрашиваются.
        </div>
      </div>
    </div>
  )
}
