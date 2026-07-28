/**
 * Иконка продукта по имени из реестра Ядра (`eco_apps.icon`, манифест `apps/<code>.yml`).
 *
 * Одна карта на все экраны, где продукты показаны значками: рабочий стол, лаунчер,
 * матрица доступа сотрудников. Неизвестное имя — `LayoutGrid`: продукт всё равно виден,
 * просто без своего значка.
 */
import {
  BarChart3, BookOpen, Building2, ClipboardList, Database, FileText, Gauge, HardHat,
  LayoutGrid, LifeBuoy, Megaphone, MessageCircle, MessagesSquare, ShieldCheck,
  ShoppingCart, Video, Wallet,
} from 'lucide-react'

export type AppIcon = typeof LayoutGrid

const ICONS: Record<string, AppIcon> = {
  'life-buoy': LifeBuoy,
  'clipboard-list': ClipboardList,
  'video': Video,
  'file-text': FileText,
  'messages-square': MessagesSquare,
  'message-circle': MessageCircle,
  'shield-check': ShieldCheck,
  'book-open': BookOpen,
  // Продукты разреза Учёта (config/spaceProducts.ts).
  'hard-hat': HardHat,
  'gauge': Gauge,
  'bar-chart-3': BarChart3,
  'wallet': Wallet,
  'database': Database,
  'building-2': Building2,
  'shopping-cart': ShoppingCart,
  'megaphone': Megaphone,
}

export function appIcon(name?: string | null): AppIcon {
  return (name && ICONS[name]) || LayoutGrid
}
