/**
 * Панели учётных разрезов — центральная часть рабочего стола.
 * Управленческий / Финансовый / Бухгалтерский / Налоговый.
 * Каждая панель: вертикальное меню слева + рабочая область справа.
 */

import { useState } from 'react'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent } from '@/components/ui/card'
import {
  BarChart3, TrendingUp, PieChart, Target, Activity,
  Landmark, Wallet, ArrowUpDown, Scale,
  BookOpen, FileSpreadsheet, ClipboardCheck, FolderOpen,
  Receipt, Calculator, FileCheck, Shield,
} from 'lucide-react'

/* ── Общий компонент для раздела с карточками ── */

interface SectionCard {
  icon: React.ComponentType<{ className?: string }>
  title: string
  description: string
  status: 'ready' | 'wip' | 'planned'
}

function SectionGrid({ title, description, cards }: {
  title: string
  description: string
  cards: SectionCard[]
}) {
  const statusLabel: Record<SectionCard['status'], { text: string; color: string }> = {
    ready: { text: 'Готово', color: 'text-emerald-500' },
    wip: { text: 'В разработке', color: 'text-amber-500' },
    planned: { text: 'Планируется', color: 'text-muted-foreground' },
  }

  return (
    <div className="p-4 space-y-4">
      <div>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <div className="grid gap-2">
        {cards.map((card) => {
          const st = statusLabel[card.status]
          return (
            <Card key={card.title} className={card.status === 'planned' ? 'opacity-50' : ''}>
              <CardContent className="p-3">
                <div className="flex items-start gap-3">
                  <div className="h-8 w-8 rounded-lg bg-muted flex items-center justify-center shrink-0">
                    <card.icon className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium">{card.title}</p>
                      <span className={`text-[9px] ${st.color}`}>{st.text}</span>
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-0.5">{card.description}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

/* ── Управленческий учёт ── */

const MGMT_MENU: CentralMenuItem[] = [
  { key: 'overview', label: 'Обзор' },
  { key: 'revenue', label: 'Выручка' },
  { key: 'costs', label: 'Затраты' },
  { key: 'margins', label: 'Маржа' },
  { key: 'kpi', label: 'KPI' },
]

const MGMT_CARDS: Record<string, SectionCard[]> = {
  overview: [
    { icon: BarChart3, title: 'Дашборд', description: 'Сводная аналитика по всем станциям и периодам', status: 'wip' },
    { icon: Target, title: 'План/Факт', description: 'Сравнение плановых и фактических показателей', status: 'planned' },
    { icon: Activity, title: 'Динамика', description: 'Тренды продаж, остатков, маржинальности', status: 'planned' },
  ],
  revenue: [
    { icon: TrendingUp, title: 'По станциям', description: 'Выручка в разрезе станций и периодов', status: 'wip' },
    { icon: PieChart, title: 'По каналам', description: 'Наличные, карты, Яндекс, корпоративные', status: 'planned' },
    { icon: BarChart3, title: 'По топливу', description: 'Разбивка по видам ГСМ', status: 'planned' },
  ],
  costs: [
    { icon: Wallet, title: 'Себестоимость', description: 'Закупочные цены, транспорт, потери', status: 'planned' },
  ],
  margins: [
    { icon: TrendingUp, title: 'Маржинальность', description: 'По станциям, топливу, каналам', status: 'planned' },
  ],
  kpi: [
    { icon: Target, title: 'Показатели', description: 'Ключевые метрики эффективности', status: 'planned' },
  ],
}

export function ManagementPanel() {
  const [tab, setTab] = useState('overview')
  return (
    <CentralPanelLayout items={MGMT_MENU} activeKey={tab} onSelect={setTab}>
      <ScrollArea className="h-full">
        <SectionGrid
          title={MGMT_MENU.find((m) => m.key === tab)?.label ?? ''}
          description="Управленческий учёт — анализ данных для принятия решений"
          cards={MGMT_CARDS[tab] ?? []}
        />
      </ScrollArea>
    </CentralPanelLayout>
  )
}

/* ── Финансовый учёт ── */

const FIN_MENU: CentralMenuItem[] = [
  { key: 'overview', label: 'Обзор' },
  { key: 'cashflow', label: 'Денежный поток' },
  { key: 'receivables', label: 'Дебиторка' },
  { key: 'payables', label: 'Кредиторка' },
  { key: 'balance', label: 'Баланс' },
]

const FIN_CARDS: Record<string, SectionCard[]> = {
  overview: [
    { icon: Landmark, title: 'Финансовая сводка', description: 'Общая картина: доходы, расходы, сальдо', status: 'planned' },
    { icon: ArrowUpDown, title: 'Движение средств', description: 'Приход/расход по счетам и кассам', status: 'planned' },
  ],
  cashflow: [
    { icon: ArrowUpDown, title: 'Денежный поток', description: 'Поступления и выплаты по дням/неделям', status: 'planned' },
  ],
  receivables: [
    { icon: Scale, title: 'Дебиторская задолженность', description: 'Кто должен нам — контрагенты, сроки', status: 'planned' },
  ],
  payables: [
    { icon: Wallet, title: 'Кредиторская задолженность', description: 'Кому должны мы — поставщики, сроки', status: 'planned' },
  ],
  balance: [
    { icon: Landmark, title: 'Баланс', description: 'Активы, пассивы, собственный капитал', status: 'planned' },
  ],
}

export function FinancialPanel() {
  const [tab, setTab] = useState('overview')
  return (
    <CentralPanelLayout items={FIN_MENU} activeKey={tab} onSelect={setTab}>
      <ScrollArea className="h-full">
        <SectionGrid
          title={FIN_MENU.find((m) => m.key === tab)?.label ?? ''}
          description="Финансовый учёт — движение денежных средств и обязательства"
          cards={FIN_CARDS[tab] ?? []}
        />
      </ScrollArea>
    </CentralPanelLayout>
  )
}

/* ── Бухгалтерский учёт ── */

const ACC_MENU: CentralMenuItem[] = [
  { key: 'overview', label: 'Обзор' },
  { key: 'documents', label: 'Документы' },
  { key: 'postings', label: 'Проводки' },
  { key: 'registers', label: 'Регистры' },
  { key: 'reports', label: 'Отчётность' },
]

const ACC_CARDS: Record<string, SectionCard[]> = {
  overview: [
    { icon: BookOpen, title: 'Учётная политика', description: 'Настройки бухгалтерского учёта компании', status: 'planned' },
    { icon: ClipboardCheck, title: 'Контроль документов', description: 'Статус подготовки документов для 1С', status: 'wip' },
  ],
  documents: [
    { icon: FileSpreadsheet, title: 'Первичные документы', description: 'Подготовленные для загрузки в 1С', status: 'wip' },
    { icon: FolderOpen, title: 'Архив', description: 'Загруженные и проведённые в 1С', status: 'planned' },
  ],
  postings: [
    { icon: BookOpen, title: 'Журнал проводок', description: 'Дт/Кт, суммы, субконто — предпросмотр перед 1С', status: 'planned' },
  ],
  registers: [
    { icon: FileSpreadsheet, title: 'Регистры учёта', description: 'Остатки 41.01/41.02, обороты, сальдо', status: 'planned' },
  ],
  reports: [
    { icon: ClipboardCheck, title: 'Оборотно-сальдовая', description: 'ОСВ по счетам и субконто', status: 'planned' },
  ],
}

export function AccountingPanel() {
  const [tab, setTab] = useState('overview')
  return (
    <CentralPanelLayout items={ACC_MENU} activeKey={tab} onSelect={setTab}>
      <ScrollArea className="h-full">
        <SectionGrid
          title={ACC_MENU.find((m) => m.key === tab)?.label ?? ''}
          description="Бухгалтерский учёт — подготовка документов и проводок для 1С"
          cards={ACC_CARDS[tab] ?? []}
        />
      </ScrollArea>
    </CentralPanelLayout>
  )
}

/* ── Налоговый учёт ── */

const TAX_MENU: CentralMenuItem[] = [
  { key: 'overview', label: 'Обзор' },
  { key: 'vat', label: 'НДС' },
  { key: 'income', label: 'Прибыль' },
  { key: 'marking', label: 'Маркировка' },
  { key: 'reports', label: 'Декларации' },
]

const TAX_CARDS: Record<string, SectionCard[]> = {
  overview: [
    { icon: Receipt, title: 'Налоговый календарь', description: 'Сроки подачи деклараций и уплаты', status: 'planned' },
    { icon: Shield, title: 'Риски', description: 'Проверка на налоговые риски', status: 'planned' },
  ],
  vat: [
    { icon: Calculator, title: 'Книга покупок/продаж', description: 'НДС 22% — входящий и исходящий', status: 'planned' },
    { icon: FileCheck, title: 'Сверка НДС', description: 'Контроль корректности начисления НДС', status: 'planned' },
  ],
  income: [
    { icon: Receipt, title: 'Налог на прибыль', description: 'Расчёт налоговой базы', status: 'planned' },
  ],
  marking: [
    { icon: Shield, title: 'Честный ЗНАК', description: 'Маркировка сигарет и воды — контроль', status: 'planned' },
  ],
  reports: [
    { icon: FileCheck, title: 'Декларации', description: 'Подготовка налоговой отчётности', status: 'planned' },
  ],
}

export function TaxPanel() {
  const [tab, setTab] = useState('overview')
  return (
    <CentralPanelLayout items={TAX_MENU} activeKey={tab} onSelect={setTab}>
      <ScrollArea className="h-full">
        <SectionGrid
          title={TAX_MENU.find((m) => m.key === tab)?.label ?? ''}
          description="Налоговый учёт — НДС, прибыль, маркировка, декларации"
          cards={TAX_CARDS[tab] ?? []}
        />
      </ScrollArea>
    </CentralPanelLayout>
  )
}
