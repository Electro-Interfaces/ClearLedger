import { useNavigate } from 'react-router-dom'
import { KpiCards } from '@/components/dashboard/KpiCards'
import { RecentActivity } from '@/components/dashboard/RecentActivity'
import { QuickActions } from '@/components/dashboard/QuickActions'
import { ConnectorsStatus } from '@/components/dashboard/ConnectorsStatus'
import { CategoryChart } from '@/components/dashboard/CategoryChart'
import { useInboxCount } from '@/hooks/useEntries'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Inbox } from 'lucide-react'

function InboxWidget() {
  const navigate = useNavigate()
  const { data: count = 0 } = useInboxCount()

  return (
    <Card
      className="cursor-pointer transition-colors hover:bg-muted/50"
      style={{ boxShadow: 'var(--shadow-soft)' }}
      onClick={() => navigate('/inbox')}
    >
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Inbox className="size-5" />
          Входящие
        </CardTitle>
      </CardHeader>
      <CardContent>
        {count > 0 ? (
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              <span className="text-2xl font-bold text-foreground">{count}</span>{' '}
              {count === 1 ? 'запись ожидает' : 'записей ожидают'} обработки
            </p>
            <Button size="sm">Обработать</Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Все записи обработаны</p>
        )}
      </CardContent>
    </Card>
  )
}

export function Dashboard() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold tracking-tight">Панель управления</h1>

      <KpiCards />

      <InboxWidget />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <RecentActivity />
        </div>
        <div className="flex flex-col gap-6">
          <QuickActions />
          <ConnectorsStatus />
        </div>
      </div>

      <CategoryChart />
    </div>
  )
}
