/**
 * Реестр модулей «Баланс» — РАЗНЫЕ модули на одной платформе.
 *
 * Платформа (Источник/Канал/Разрез, L1–L4, эталон закрытых периодов) и архетип
 * «баланс» (приход − отпуск = потери + движок run_balance + UI-кирпичи) — ОБЩИЕ.
 * Но каждый модуль — самостоятельная сущность со СВОИМ доменным содержанием
 * (источники, сущности L2, семантика потерь, категории, единица ресурса).
 *
 * Баланс ЭЗС (energy/РусГидро, кВт·ч) и Баланс АЗС (fuel/ГИГ, литры) — это
 * ДВА РАЗНЫХ МОДУЛЯ, а не один с пресетами. Привязка к компании — через профиль.
 */
import type { ProfileId } from './profiles'

export interface BalanceCategory { id: string; label: string }
export interface BalanceLossType { id: string; label: string; kind: 'technological' | 'commercial' }

/** Контракт архетипа «баланс» — общий КАРКАС, который каждый модуль наполняет своим. */
export interface BalanceModuleDef {
  id: string                 // 'balance_ezs' | 'balance_azs' — идентичность модуля
  profileId: ProfileId       // к какому профилю привязан
  navLabel: string           // пункт меню («Баланс ЭЗС» / «Баланс АЗС»)
  title: string              // заголовок витрины
  subtitle: string
  unit: string               // единица ресурса: 'кВт·ч' | 'л'
  resource: string           // 'электроэнергия' | 'нефтепродукты'
  /** Объекты-носители баланса (ЭЗС / АЗС). */
  objectLabel: string        // 'ЭЗС' | 'АЗС'
  /** Категории полезного отпуска (редактируемый список, НЕ хардкод ЮЛ/ФЛ в коде). */
  categories: BalanceCategory[]
  supplierLabel: string      // 'Поставщик э/э' | 'Нефтебаза/поставщик'
  /** Семантика потерь модуля (специфична для ресурса). */
  lossTypes: BalanceLossType[]
  status: 'demo' | 'planned'
}

// ─── МОДУЛЬ 1: Баланс ЭЗС (energy / РусГидро) ───────────────────────────────
export const BALANCE_EZS: BalanceModuleDef = {
  id: 'balance_ezs',
  profileId: 'energy',
  navLabel: 'Баланс ЭЗС',
  title: 'Баланс электроэнергии',
  subtitle: 'Поступление − Полезный отпуск = Потери по каждой ЭЗС. Технологические (норматив) и коммерческие потери, маркер небаланса, тепловая карта, статус интервалов.',
  unit: 'кВт·ч',
  resource: 'электроэнергия',
  objectLabel: 'ЭЗС',
  categories: [
    { id: 'ul', label: 'ЮЛ' },
    { id: 'fl', label: 'ФЛ' },
  ],
  supplierLabel: 'Поставщик э/э',
  lossTypes: [
    { id: 'conversion', label: 'Конверсия AC/DC + кабель', kind: 'technological' },
    { id: 'standby', label: 'Собственные нужды / standby', kind: 'technological' },
    { id: 'commercial', label: 'Коммерческий небаланс (сверх норматива)', kind: 'commercial' },
  ],
  status: 'demo',
}

// ─── МОДУЛЬ 2: Баланс АЗС (fuel / ГИГ) — отдельный модуль, planned ───────────
export const BALANCE_AZS: BalanceModuleDef = {
  id: 'balance_azs',
  profileId: 'fuel',
  navLabel: 'Баланс АЗС',
  title: 'Баланс нефтепродуктов',
  subtitle: 'Приход (ТТН) − Реализация (смены) = Потери по каждой АЗС/резервуару. Естественная убыль, температурная коррекция по плотности, недостача/излишек ТМЦ.',
  unit: 'л',
  resource: 'нефтепродукты',
  objectLabel: 'АЗС',
  categories: [
    { id: 'retail', label: 'Розница' },
    { id: 'corp', label: 'Корп. карты' },
  ],
  supplierLabel: 'Нефтебаза / поставщик',
  lossTypes: [
    { id: 'natural', label: 'Естественная убыль (норма)', kind: 'technological' },
    { id: 'temperature', label: 'Температурная коррекция (плотность)', kind: 'technological' },
    { id: 'shortage', label: 'Недостача/излишек ТМЦ', kind: 'commercial' },
  ],
  status: 'planned',
}

const MODULES: BalanceModuleDef[] = [BALANCE_EZS, BALANCE_AZS]

/** Модуль баланса, подключённый профилю компании (или null, если профиль без баланса). */
export function balanceModuleForProfile(profileId: ProfileId): BalanceModuleDef | null {
  return MODULES.find((m) => m.profileId === profileId) ?? null
}
