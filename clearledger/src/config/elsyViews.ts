import { BookOpen, Boxes, Files, Handshake, LayoutDashboard, PlayCircle } from 'lucide-react'

export const ELSY_VIEWS = [
  { code: 'overview', label: 'Обзор', icon: LayoutDashboard },
  { code: 'work', label: 'Работа с нами', icon: Handshake },
  { code: 'documents', label: 'Документы', icon: Files },
  { code: 'services', label: 'Мои сервисы', icon: Boxes },
  { code: 'products', label: 'Продукты и демо', icon: PlayCircle },
  { code: 'help', label: 'Помощь', icon: BookOpen },
] as const

export type ElsyView = typeof ELSY_VIEWS[number]['code']

export function elsyView(value: string | null): ElsyView {
  return ELSY_VIEWS.find((view) => view.code === value)?.code || 'overview'
}
