import { Upload, CheckCircle2, Clock, AlertTriangle, Send } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { useKpi } from '@/hooks/useEntries'

export function KpiCards() {
  const { data: kpi } = useKpi()

  const cards = [
    {
      label: 'Загружено сегодня',
      value: kpi?.uploadedToday ?? 0,
      icon: Upload,
      iconBg: 'hsl(217 91% 60% / 0.15)',
      iconColor: 'text-blue-500',
    },
    {
      label: 'Проверено всего',
      value: kpi?.totalVerified ?? 0,
      icon: CheckCircle2,
      iconBg: 'hsl(120 100% 40% / 0.15)',
      iconColor: 'text-green-500',
    },
    {
      label: 'В обработке',
      value: kpi?.inProcessing ?? 0,
      icon: Clock,
      iconBg: 'hsl(45 100% 55% / 0.15)',
      iconColor: 'text-yellow-500',
    },
    {
      label: 'Ошибки',
      value: kpi?.errors ?? 0,
      icon: AlertTriangle,
      iconBg: 'hsl(0 84% 60% / 0.15)',
      iconColor: 'text-red-500',
    },
    {
      label: 'Передано сегодня',
      value: kpi?.transferredToday ?? 0,
      icon: Send,
      iconBg: 'hsl(280 65% 60% / 0.15)',
      iconColor: 'text-purple-500',
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      {cards.map((card) => {
        const Icon = card.icon
        return (
          <Card
            key={card.label}
            style={{ boxShadow: 'var(--shadow-soft)' }}
          >
            <CardContent className="flex items-center gap-4">
              <div
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full"
                style={{ background: card.iconBg }}
              >
                <Icon className={`h-6 w-6 ${card.iconColor}`} />
              </div>
              <div>
                <p className="text-2xl font-bold tracking-tight">{card.value.toLocaleString('ru-RU')}</p>
                <p className="text-sm text-muted-foreground">{card.label}</p>
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
