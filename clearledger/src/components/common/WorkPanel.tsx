/**
 * WorkPanel — левая панель рабочего места (заявки, чаты, навигация).
 * Параметризуется через panelId для разных страниц.
 */

import { useState } from 'react'
import { Search, Plus, MessageSquare, PanelLeftClose, TicketCheck } from 'lucide-react'
import { cn } from '@/lib/utils'

interface WorkItem {
  id: string
  title: string
  subtitle?: string
  timestamp?: string
  unread?: boolean
}

interface WorkPanelProps {
  panelId: string
  className?: string
  onCollapse?: () => void
}

/**
 * История сессий аудитора. Раньше здесь лежал выдуманный список («Сверка сумм
 * Q4 2025 — расхождения найдены») без единой пометки: выглядело как результат
 * реально проведённых проверок. Пока источника истории нет — честное пустое
 * состояние; список наполнит бэкенд, когда появится эндпоинт сессий.
 */
const ITEMS: Record<string, WorkItem[]> = {}

export function WorkPanel({ panelId, className, onCollapse }: WorkPanelProps) {
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const items = ITEMS[panelId] ?? []

  const filtered = search
    ? items.filter((i) => i.title.toLowerCase().includes(search.toLowerCase()))
    : items

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-slate-700 shrink-0">
        <span className="text-sm font-semibold">Аудитор</span>
        <div className="flex items-center gap-1">
          <button
            className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
            title="Новая сессия"
          >
            <Plus className="size-4" />
          </button>
          {onCollapse && (
            <button
              onClick={onCollapse}
              className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
              title="Свернуть панель"
            >
              <PanelLeftClose className="size-4" />
            </button>
          )}
        </div>
      </div>

      {/* ЗАЯВКИ section */}
      <div className="border-b border-slate-700">
        <div className="flex items-center gap-2 px-3 py-2">
          <TicketCheck className="size-3.5 text-slate-400" />
          <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Заявки</span>
          <span className="ml-auto text-xs text-slate-500">{0}</span>
        </div>
        <div className="px-3 pb-2 text-xs text-slate-500">
          Нет открытых заявок
        </div>
      </div>

      {/* ЧАТЫ section */}
      <div className="border-b border-slate-700">
        <div className="flex items-center gap-2 px-3 py-2">
          <MessageSquare className="size-3.5 text-slate-400" />
          <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Чаты</span>
          <span className="ml-auto text-xs text-slate-500">{filtered.length}</span>
        </div>
      </div>

      {/* Search */}
      <div className="px-3 py-2 shrink-0">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-3.5 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск..."
            className="w-full pl-7 pr-2 py-1.5 text-xs rounded-md border border-slate-700 bg-slate-800 text-slate-300 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
      </div>

      {/* Items list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-slate-500">
            Нет активных чатов
          </div>
        ) : (
          filtered.map((item) => (
            <button
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              className={cn(
                'w-full text-left px-3 py-2.5 border-b border-slate-800 hover:bg-slate-800 transition-colors',
                selectedId === item.id && 'bg-blue-900/20 border-l-2 border-l-blue-500'
              )}
            >
              <div className="flex items-start gap-2">
                <MessageSquare className="size-3.5 mt-0.5 text-slate-500 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1">
                    <span className="text-xs font-medium truncate">{item.title}</span>
                    {item.unread && (
                      <span className="size-1.5 rounded-full bg-blue-500 shrink-0" />
                    )}
                  </div>
                  {item.subtitle && (
                    <p className="text-[11px] text-slate-500 truncate mt-0.5">{item.subtitle}</p>
                  )}
                </div>
                {item.timestamp && (
                  <span className="text-[10px] text-slate-500 whitespace-nowrap shrink-0">
                    {item.timestamp}
                  </span>
                )}
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
