import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { KpiCards } from '@/components/dashboard/KpiCards'
import { RecentActivity } from '@/components/dashboard/RecentActivity'
import { QuickActions } from '@/components/dashboard/QuickActions'
import { ConnectorsStatus } from '@/components/dashboard/ConnectorsStatus'
import { CategoryChart } from '@/components/dashboard/CategoryChart'
import { StatusFunnel } from '@/components/dashboard/StatusFunnel'
import { ActivityChart } from '@/components/dashboard/ActivityChart'
import { VerificationHealthWidget } from '@/components/dashboard/VerificationHealthWidget'
import { ReferenceStatusWidget } from '@/components/dashboard/ReferenceStatusWidget'
import { useInboxCount, useKpi } from '@/hooks/useEntries'
import { useCompany } from '@/contexts/CompanyContext'
import { computeExtendedKpi, getTopCounterparties, getSourceDistribution, getRecentErrors } from '@/services/dashboardService'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { Inbox, Upload, FileText, Settings, CalendarDays, TrendingDown, Clock, Users } from 'lucide-react'

const COLORS = ['hsl(217, 91%, 60%)', 'hsl(120, 100%, 40%)', 'hsl(45, 100%, 55%)', 'hsl(0, 84%, 60%)', 'hsl(280, 65%, 60%)', 'hsl(180, 70%, 45%)']

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
  const { companyId } = useCompany()
  const { data: kpi } = useKpi()
  const isEmpty = kpi && kpi.uploadedToday === 0 && kpi.totalVerified === 0 && kpi.inProcessing === 0 && kpi.errors === 0

  const { data: extKpi } = useQuery({
    queryKey: ['ext-kpi', companyId],
    queryFn: () => computeExtendedKpi(companyId),
  })

  const { data: topCp = [] } = useQuery({
    queryKey: ['top-cp', companyId],
    queryFn: () => getTopCounterparties(companyId, 5),
  })

  const { data: sourceDist = [] } = useQuery({
    queryKey: ['source-dist', companyId],
    queryFn: () => getSourceDistribution(companyId),
  })

  const { data: recentErrors = [] } = useQuery({
    queryKey: ['recent-errors', companyId],
    queryFn: () => getRecentErrors(companyId, 5),
  })

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold tracking-tight">Панель управления</h1>

      {isEmpty && <OnboardingBanner />}

      <KpiCards />

      {/* Extended KPI row */}
      {extKpi && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
            <CardContent className="flex items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full" style={{ background: 'hsl(180 70% 45% / 0.15)' }}>
                <CalendarDays className="h-6 w-6 text-teal-500" />
              </div>
              <div>
                <p className="text-2xl font-bold tracking-tight">{extKpi.weekCount}</p>
                <p className="text-sm text-muted-foreground">За неделю</p>
              </div>
            </CardContent>
          </Card>
          <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
            <CardContent className="flex items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full" style={{ background: 'hsl(0 84% 60% / 0.15)' }}>
                <TrendingDown className="h-6 w-6 text-red-500" />
              </div>
              <div>
                <p className="text-2xl font-bold tracking-tight">{extKpi.rejectionRate}%</p>
                <p className="text-sm text-muted-foreground">Процент отклонений</p>
              </div>
            </CardContent>
          </Card>
          <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
            <CardContent className="flex items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full" style={{ background: 'hsl(45 100% 55% / 0.15)' }}>
                <Clock className="h-6 w-6 text-yellow-500" />
              </div>
              <div>
                <p className="text-2xl font-bold tracking-tight">{extKpi.avgVerificationTimeMs ? formatDuration(extKpi.avgVerificationTimeMs) : '—'}</p>
                <p className="text-sm text-muted-foreground">Ср. верификация</p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Виджеты верификации и справочников */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <VerificationHealthWidget />
        <ReferenceStatusWidget />
      </div>

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

      <ActivityChart />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <CategoryChart />
        <StatusFunnel />
      </div>

      {/* New widgets row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Top counterparties */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Users className="size-4" />
              Топ контрагентов
            </CardTitle>
          </CardHeader>
          <CardContent>
            {topCp.length === 0 ? (
              <p className="text-sm text-muted-foreground">Нет данных</p>
            ) : (
              <div className="space-y-2">
                {topCp.map((cp) => (
                  <div key={cp.counterparty} className="flex items-center justify-between text-sm">
                    <span className="truncate max-w-[60%]">{cp.counterparty}</span>
                    <span className="text-muted-foreground font-medium">{cp.count}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Sources distribution */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">По источникам</CardTitle>
          </CardHeader>
          <CardContent>
            {sourceDist.length === 0 ? (
              <p className="text-sm text-muted-foreground">Нет данных</p>
            ) : (
              <div className="flex items-center gap-4">
                <ResponsiveContainer width={120} height={120}>
                  <PieChart>
                    <Pie data={sourceDist} dataKey="count" nameKey="label" cx="50%" cy="50%" outerRadius={55}>
                      {sourceDist.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
                <div className="space-y-1 text-xs">
                  {sourceDist.map((s, i) => (
                    <div key={s.source} className="flex items-center gap-1.5">
                      <div className="size-2.5 rounded-full shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
                      <span>{s.label}: {s.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent errors */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Последние ошибки</CardTitle>
          </CardHeader>
          <CardContent>
            {recentErrors.length === 0 ? (
              <p className="text-sm text-muted-foreground">Нет ошибок</p>
            ) : (
              <div className="space-y-2">
                {recentErrors.map((e) => (
                  <div key={e.reason} className="flex items-center justify-between text-sm">
                    <span className="truncate max-w-[70%] text-red-400">{e.reason}</span>
                    <span className="text-muted-foreground font-medium">{e.count}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function formatDuration(ms: number): string {
  if (ms < 60_000) return `${Math.round(ms / 1000)}с`
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}мин`
  return `${(ms / 3_600_000).toFixed(1)}ч`
}
