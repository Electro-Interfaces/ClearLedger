/**
 * Разделы страниц пространства: «Объекты», «Загрузка», «Документы», «Контрагенты».
 *
 * ПОЧЕМУ ЭТО ПОЯВИЛОСЬ (20.09.2026, замечание МАГа). В приложениях пространства
 * навигация двухуровневая: левая рельса выбирает приложение и его раздел, а
 * вертикальное меню рабочей области — пункт внутри раздела. У страниц самого
 * пространства второго уровня не было: они открывались одним экраном, и всё
 * внутреннее деление уезжало в табы под шапкой. Получалось три разных языка
 * навигации на одном рабочем столе — рельса, меню и табы, — причём табы
 * обрывались по ширине и терялись.
 *
 * Здесь один источник для всех таких страниц. Пункт пишется в адрес (`?sub=`),
 * как у разделов продукта: ссылка на конкретный пункт работает и открывается
 * туда же, откуда её дали.
 *
 * Пункты — только те, за которыми есть содержимое. Пустых заготовок «чтобы меню
 * выглядело полным» здесь нет: человек тратит на них время один раз, а доверие
 * к меню теряет навсегда.
 */
import {
  Boxes, Building2, FileCheck, FileSearch, FolderTree, Handshake,
  Mail, Map as MapIcon, Radio, ShieldCheck, Table2, Upload, Users,
} from 'lucide-react'
import type { ComponentType } from 'react'

export interface SpacePageItem {
  key: string
  label: string
  icon?: ComponentType<{ className?: string }>
  /** Подпись группы: разделитель в меню, как у разделов продукта. */
  group?: string
  /** Пункт только для профиля сети ЭЗС. */
  energyOnly?: boolean
}

export interface SpacePageMenu {
  /** Путь страницы в навигации. */
  path: string
  title: string
  items: SpacePageItem[]
}

export const SPACE_PAGE_MENUS: SpacePageMenu[] = [
  {
    path: '/objects',
    title: 'Объекты',
    items: [
      { key: 'registry', label: 'Реестр объектов', icon: Boxes },
      { key: 'map', label: 'Карта', icon: MapIcon, energyOnly: true },
      // Пробелы в паспорте — не украшение реестра, а рабочий список: по этим
      // station нельзя ни претензию написать, ни на карту поставить.
      { key: 'quality', label: 'Полнота паспортов', icon: ShieldCheck },
    ],
  },
  {
    path: '/intake',
    title: 'Загрузка',
    items: [
      // Прежние табы страницы: первичка — главный вход, остальное — каналы
      // поступления. В меню они читаются как разделы, а не как набор кнопок,
      // обрывающийся по ширине.
      { key: 'primary', label: 'Первичные документы', icon: FileCheck },
      { key: 'mail', label: 'Почта', icon: Mail },
      { key: 'files', label: 'Загрузка файлов', icon: Upload },
      { key: 'tables', label: 'Таблицы', icon: Table2 },
      { key: 'channels', label: 'Каналы и расписание', icon: Radio },
    ],
  },
  {
    path: '/files',
    title: 'Документы',
    items: [
      { key: 'explorer', label: 'Хранилище', icon: FolderTree },
    ],
  },
  {
    path: '/contractors',
    title: 'Контрагенты',
    items: [
      { key: 'counterparties', label: 'Контрагенты', icon: Building2 },
      { key: 'contracts', label: 'Договоры', icon: Handshake },
      { key: 'corp', label: 'Корпоративные клиенты', icon: Users, energyOnly: true },
      { key: 'quality', label: 'Качество данных', icon: FileSearch },
    ],
  },
]

export function spacePageMenu(path: string): SpacePageMenu | undefined {
  // Страница Ядра открывается и под адресом продукта («/sales/objects»),
  // поэтому сравниваем по хвосту, а не по началу: иначе меню было бы только у
  // прямого входа, а из рабочего места — нет.
  return SPACE_PAGE_MENUS.find(
    (m) => path === m.path || path.endsWith(m.path) || path.startsWith(`${m.path}/`))
}

/** Пункты страницы с учётом профиля компании. */
export function spacePageItems(path: string, isEnergy: boolean): SpacePageItem[] {
  return (spacePageMenu(path)?.items ?? []).filter((i) => !i.energyOnly || isEnergy)
}
