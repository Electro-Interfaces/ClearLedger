import { Link } from 'react-router-dom'
import { getSettings } from '@/services/settingsService'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Fuel } from 'lucide-react'

export function ReceiptsPage() {
  const settings = getSettings()

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
      <h1 className="text-2xl font-bold">Поступления (ТТН)</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Просмотр поступлений</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">
            Поступления топлива привязаны к сменам. Откройте{' '}
            <Link to="/shifts" className="text-primary hover:underline">сменный отчёт</Link>
            {' '}чтобы увидеть ТТН по конкретной смене.
          </p>
          <p className="text-muted-foreground mt-2">
            Отдельный реестр поступлений с фильтрами по дате и поставщику — в следующей версии.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

export default ReceiptsPage
