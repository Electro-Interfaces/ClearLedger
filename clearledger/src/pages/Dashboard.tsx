import { Link } from 'react-router-dom'
import { useFuelKpi, useShifts } from '@/hooks/useFuel'
import { getSettings } from '@/services/settingsService'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Fuel, Building2, ClipboardList, Truck, Settings } from 'lucide-react'
import { format } from 'date-fns'

export function Dashboard() {
  const settings = getSettings()
  const hasCredentials = !!settings.stsLogin && !!settings.stsPassword
  const { data: kpi } = useFuelKpi()
  const { data: shifts } = useShifts()

  if (!hasCredentials) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-6">
        <div className="flex items-center gap-3">
          <Fuel className="h-10 w-10 text-primary" />
          <h1 className="text-3xl font-bold">GIG Fuel Ledger</h1>
        </div>
        <p className="text-muted-foreground text-center max-w-md">
          Автоматизация учёта нефтепродуктов на АЗС.<br />
          Для начала работы настройте подключение к STS API.
        </p>
        <Link
          to="/settings"
          className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-primary-foreground hover:bg-primary/90"
        >
          <Settings className="h-4 w-4" />
          Настроить подключение
        </Link>
      </div>
    )
  }

  const recentShifts = shifts?.slice(-5).reverse() ?? []

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">GIG Fuel Ledger</h1>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-1">
              <Building2 className="h-4 w-4" /> Станции
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{kpi?.stationsCount ?? settings.stations.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-1">
              <ClipboardList className="h-4 w-4" /> Всего смен
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{kpi?.shiftsTotal ?? '...'}</p>
            {kpi && kpi.shiftsOpen > 0 && (
              <p className="text-xs text-orange-500">{kpi.shiftsOpen} открыт{kpi.shiftsOpen === 1 ? 'а' : 'ых'}</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-1">
              <Fuel className="h-4 w-4" /> Продажи
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-muted-foreground">—</p>
            <p className="text-xs text-muted-foreground">В сменных отчётах</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-1">
              <Truck className="h-4 w-4" /> Поступления
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-muted-foreground">—</p>
            <p className="text-xs text-muted-foreground">ТТН в сменах</p>
          </CardContent>
        </Card>
      </div>

      {recentShifts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Последние смены</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Смена</TableHead>
                  <TableHead>Открытие</TableHead>
                  <TableHead>Закрытие</TableHead>
                  <TableHead>Статус</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentShifts.map((s) => (
                  <TableRow key={s.shift}>
                    <TableCell>
                      <Link
                        to={`/shifts/${settings.stations[0]?.code ?? 0}/${s.shift}`}
                        className="text-primary hover:underline font-medium"
                      >
                        №{s.shift}
                      </Link>
                    </TableCell>
                    <TableCell>
                      {s.dt_open ? format(new Date(s.dt_open), 'dd.MM.yyyy HH:mm') : '—'}
                    </TableCell>
                    <TableCell>
                      {s.dt_close ? format(new Date(s.dt_close), 'dd.MM.yyyy HH:mm') : '—'}
                    </TableCell>
                    <TableCell>
                      <Badge variant={s.dt_close ? 'secondary' : 'default'}>
                        {s.dt_close ? 'Закрыта' : 'Открыта'}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="mt-3">
              <Link to="/shifts" className="text-sm text-primary hover:underline">
                Все смены →
              </Link>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default Dashboard
