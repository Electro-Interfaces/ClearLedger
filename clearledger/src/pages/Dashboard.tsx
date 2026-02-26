import { useNavigate } from 'react-router-dom'
import { KpiCards } from '@/components/dashboard/KpiCards'
import { RecentActivity } from '@/components/dashboard/RecentActivity'
import { QuickActions } from '@/components/dashboard/QuickActions'
import { ConnectorsStatus } from '@/components/dashboard/ConnectorsStatus'
import { CategoryChart } from '@/components/dashboard/CategoryChart'
import { StatusFunnel } from '@/components/dashboard/StatusFunnel'
import { useInboxCount, useKpi } from '@/hooks/useEntries'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Inbox, Upload, FileText, Settings } from 'lucide-react'

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

function OnboardingBanner() {
  const navigate = useNavigate()
  return (
    <Card className="border-dashed border-2">
      <CardContent className="py-8">
        <div className="text-center space-y-4">
          <h2 className="text-xl font-semibold">Добро пожаловать в ClearLedger</h2>
          <p className="text-muted-foreground max-w-md mx-auto">
            Начните работу — загрузите первые документы или настройте компанию.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <Button onClick={() => navigate('/input')}>
              <Upload className="size-4" />
              Загрузить документы
            </Button>
            <Button variant="outline" onClick={() => navigate('/input')}>
              <FileText className="size-4" />
              Ручной ввод
            </Button>
            <Button variant="outline" onClick={() => navigate('/settings')}>
              <Settings className="size-4" />
              Настройки
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function Dashboard() {
  const { data: kpi } = useKpi()
  const isEmpty = kpi && kpi.uploadedToday === 0 && kpi.totalVerified === 0 && kpi.inProcessing === 0 && kpi.errors === 0

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold tracking-tight">Панель управления</h1>

      {isEmpty && <OnboardingBanner />}

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

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <CategoryChart />
        <StatusFunnel />
      </div>
    </div>
  )
}
