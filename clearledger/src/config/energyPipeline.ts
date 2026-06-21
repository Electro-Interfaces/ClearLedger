/**
 * Энергоцепочка РусГидро: Источник → Канал → Разрез — ЕДИНЫЙ источник правды.
 * Разрезы определяют потребность; источники/каналы выводятся ОБРАТНО от разрезов
 * (разрез → его каналы → их источники). Из этой модели согласованно питаются:
 * страница «Источники» (/sources), «Каналы» (/channels) и «Разрезы учёта».
 */
export type PipeStatus = 'active' | 'demo' | 'planned'

/** Подписи и стили статусов элементов энергоцепочки (бейджи на источниках/каналах/разрезах). */
export const PIPE_STATUS_META: Record<PipeStatus, { label: string; cls: string }> = {
  active:  { label: 'активен',     cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  demo:    { label: 'демо-модель', cls: 'bg-sky-500/15 text-sky-600 dark:text-sky-400' },
  planned: { label: 'в проработке', cls: 'bg-muted text-muted-foreground' },
}

export interface EnergySource {
  id: string
  label: string
  level: 'station' | 'company'      // привязка источника
  streams: string[]                 // какие потоки даёт
  status: PipeStatus
}
export interface EnergyChannel {
  id: string
  label: string
  sourceId: string                  // нормализует этот источник
  produces: string                  // что кладёт в L2
  status: PipeStatus
}
export interface EnergyCut {
  id: string
  label: string
  channelIds: string[]              // потребляет нормализованные потоки этих каналов
  desc: string
  status: PipeStatus
}

export const ENERGY_SOURCES: EnergySource[] = [
  { id: 'pu_ezs',   label: 'ПУ ЭЗС',              level: 'station', streams: ['Показания счётчика (приход/отпуск)'], status: 'planned' },
  { id: 'pk',       label: 'ПК ezs.rushydro.ru',  level: 'company', streams: ['Зарядные сессии', 'Платежи', 'Отчёт ЮЛ', 'RFID-привязки', 'Тарифы'], status: 'demo' },
  { id: 'supplier', label: 'Поставщик э/э',       level: 'station', streams: ['Счёт / показания ПУ поставщика'], status: 'planned' },
  { id: 'acquirer', label: 'Банк-эквайер',        level: 'company', streams: ['Зачисления', 'Холды'], status: 'demo' },
  { id: 'ofd',      label: 'ОФД',                 level: 'company', streams: ['Z-отчёт', 'Чеки (54-ФЗ)'], status: 'demo' },
  { id: 'tariffs',  label: 'Тарифы / НПА',        level: 'company', streams: ['Эталон тарифов'], status: 'demo' },
  { id: 'rent',     label: 'Договоры аренды',     level: 'company', streams: ['Реестр аренды', 'Платежи аренды'], status: 'planned' },
]

export const ENERGY_CHANNELS: EnergyChannel[] = [
  { id: 'ch_pk',       label: 'Канал ПК',             sourceId: 'pk',       produces: 'Сессии/платежи/ЮЛ/RFID/тарифы → L2', status: 'demo' },
  { id: 'ch_pu',       label: 'Канал ПУ ЭЗС',         sourceId: 'pu_ezs',   produces: 'Показания счётчиков → L2', status: 'planned' },
  { id: 'ch_supplier', label: 'Канал поставщика э/э', sourceId: 'supplier', produces: 'Счёт поставщика → L2', status: 'planned' },
  { id: 'ch_acq',      label: 'Канал эквайера',       sourceId: 'acquirer', produces: 'Зачисления/холды → L2', status: 'demo' },
  { id: 'ch_ofd',      label: 'Канал ОФД',            sourceId: 'ofd',      produces: 'Z-отчёт/чеки → L2', status: 'demo' },
  { id: 'ch_tariffs',  label: 'Канал тарифов/НПА',    sourceId: 'tariffs',  produces: 'Тарифы → L2', status: 'demo' },
  { id: 'ch_rent',     label: 'Канал аренды',         sourceId: 'rent',     produces: 'Договоры/платежи аренды → L2', status: 'planned' },
]

export const ENERGY_CUTS: EnergyCut[] = [
  { id: 'orders',    label: 'Заказы',          channelIds: ['ch_pk', 'ch_pu', 'ch_tariffs'], status: 'demo',
    desc: 'Зарядные сессии ПК ↔ отпуск ПУ ЭЗС; тарификация по НПА. Объём кВт·ч и выручка по заказам (ЮЛ/ФЛ, в т.ч. холд<факт).' },
  { id: 'corp',      label: 'Корпоратив',      channelIds: ['ch_pk', 'ch_tariffs'], status: 'demo',
    desc: 'Корпоративные клиенты (ЮЛ): постоплата, счета, сверка по договорам и тарифам.' },
  { id: 'rfid',      label: 'RFID',            channelIds: ['ch_pk'], status: 'demo',
    desc: 'Идентификация по RFID-картам/меткам — привязка зарядных сессий к клиенту.' },
  { id: 'eacq',      label: 'Эквайринг',       channelIds: ['ch_acq', 'ch_pk'], status: 'demo',
    desc: 'Банк-эквайер ↔ платежи ПК: зачисления, холды (холд<факт), комиссия, T+1.' },
  { id: 'ofd',       label: 'ОФД/чеки',        channelIds: ['ch_ofd', 'ch_pk', 'ch_acq'], status: 'demo',
    desc: 'ОФД (Z-отчёт) ↔ ПК ↔ эквайер — полнота пробития чеков (54-ФЗ), three-way выручки.' },
  { id: 'suppliers', label: 'Поставщики э/э',  channelIds: ['ch_pu', 'ch_supplier'], status: 'planned',
    desc: 'ПУ ЭЗС ↔ ПУ поставщика — верификация физобъёма закупки э/э (§4.1.1 ТЗ).' },
  { id: 'rent',      label: 'Аренда',          channelIds: ['ch_rent', 'ch_acq'], status: 'planned',
    desc: 'Договоры аренды (земля/площадки/оборудование ЭЗС) ↔ платежи — сверка взаиморасчётов.' },
]

export const ALL_ENERGY_CUT_IDS = ENERGY_CUTS.map((c) => c.id)

const byId = <T extends { id: string }>(arr: T[], id: string) => arr.find((x) => x.id === id)

export const energySource = (id: string) => byId(ENERGY_SOURCES, id)
export const energyChannel = (id: string) => byId(ENERGY_CHANNELS, id)
export const energyCut = (id: string) => byId(ENERGY_CUTS, id)

/** Каналы разреза. */
export function channelsForCut(cutId: string): EnergyChannel[] {
  const cut = byId(ENERGY_CUTS, cutId)
  return cut ? (cut.channelIds.map((id) => byId(ENERGY_CHANNELS, id)).filter(Boolean) as EnergyChannel[]) : []
}
/** Источники разреза (через его каналы), без дублей. */
export function sourcesForCut(cutId: string): EnergySource[] {
  const m = new Map<string, EnergySource>()
  for (const ch of channelsForCut(cutId)) { const s = byId(ENERGY_SOURCES, ch.sourceId); if (s) m.set(s.id, s) }
  return [...m.values()]
}
/** ОБРАТНО: каналы, нужные для набора разрезов (union). */
export function neededChannels(cutIds: string[]): EnergyChannel[] {
  const m = new Map<string, EnergyChannel>()
  for (const cid of cutIds) for (const ch of channelsForCut(cid)) m.set(ch.id, ch)
  return [...m.values()]
}
/** ОБРАТНО: источники, нужные для набора разрезов (union). */
export function neededSources(cutIds: string[]): EnergySource[] {
  const m = new Map<string, EnergySource>()
  for (const ch of neededChannels(cutIds)) { const s = byId(ENERGY_SOURCES, ch.sourceId); if (s) m.set(s.id, s) }
  return [...m.values()]
}
/** Разрезы, потребляющие канал. */
export function cutsForChannel(channelId: string): EnergyCut[] {
  return ENERGY_CUTS.filter((c) => c.channelIds.includes(channelId))
}
/** Разрезы, зависящие от источника (через его каналы). */
export function cutsForSource(sourceId: string): EnergyCut[] {
  const chIds = ENERGY_CHANNELS.filter((c) => c.sourceId === sourceId).map((c) => c.id)
  return ENERGY_CUTS.filter((c) => c.channelIds.some((id) => chIds.includes(id)))
}
