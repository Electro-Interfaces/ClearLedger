import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useShifts } from '@/hooks/useFuel'
import { getSettings } from '@/services/settingsService'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, Fuel } from 'lucide-react'
import { format } from 'date-fns'

export function ShiftsPage() {
  const settings = getSettings()
  const [stationFilter, setStationFilter] = useState<string>('all')

  const stationId = stationFilter === 'all' ? undefined : Number(stationFilter)
  const { data: shifts, isLoading, error } = useShifts(stationId)

  if (!settings.stsLogin) {
    return (
      <div className="flex flex-col items-center justify-center h-[50vh] gap-4">
        <Fuel className="h-12 w-12 text-muted-foreground" />
        <p className="text-muted-foreground">Настройте подключение к STS API</p>
        <Link to="/settings" className="text-primary hover:underline">Перейти в настройки</Link>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Сменные отчёты</h1>
        <Select value={stationFilter} onValueChange={setStationFilter}>
          <SelectTrigger className="w-48">
            <SelectValue placeholder="Все станции" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все станции</SelectItem>
            {settings.stations.map((s) => (
              <SelectItem key={s.code} value={String(s.code)}>
                {s.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {isLoading ? 'Загрузка...' : `${shifts?.length ?? 0} смен`}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {error && (
            <div className="text-destructive py-4">
              Ошибка загрузки: {error instanceof Error ? error.message : 'Неизвестная ошибка'}
            </div>
          )}

          {shifts && shifts.length > 0 && (
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
                {shifts.map((shift) => (
                  <TableRow key={shift.shift}>
                    <TableCell>
                      <Link
                        to={`/shifts/${stationId ?? settings.stations[0]?.code ?? 0}/${shift.shift}`}
                        className="text-primary hover:underline font-medium"
                      >
                        №{shift.shift}
                      </Link>
                    </TableCell>
                    <TableCell>
                      {shift.dt_open ? format(new Date(shift.dt_open), 'dd.MM.yyyy HH:mm') : '—'}
                    </TableCell>
                    <TableCell>
                      {shift.dt_close ? format(new Date(shift.dt_close), 'dd.MM.yyyy HH:mm') : '—'}
                    </TableCell>
                    <TableCell>
                      {shift.dt_close ? (
                        <Badge variant="secondary">Закрыта</Badge>
                      ) : (
                        <Badge variant="default">Открыта</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {shifts && shifts.length === 0 && (
            <p className="text-muted-foreground text-center py-8">Смен не найдено</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default ShiftsPage
