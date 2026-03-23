import { useState } from 'react'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { getSettings, saveSettings, type AppSettings } from '@/services/settingsService'
import { stsTestConnection, clearToken } from '@/services/fuel/stsApiClient'
import { Loader2, CheckCircle2, XCircle, Wifi } from 'lucide-react'

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>(getSettings)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string; shiftsCount?: number } | null>(null)

  function update(key: keyof AppSettings, value: string | number) {
    setSettings((prev) => ({ ...prev, [key]: value }))
    setTestResult(null)
  }

  function handleSave() {
    saveSettings(settings)
    clearToken()
    toast.success('Настройки сохранены')
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const url = import.meta.env.DEV ? '/tms' : settings.stsApiUrl
      const result = await stsTestConnection(url, settings.stsLogin, settings.stsPassword)
      setTestResult(result)
      if (result.ok) {
        toast.success(`Подключение успешно! Найдено ${result.shiftsCount} смен`)
      } else {
        toast.error(`Ошибка: ${result.error}`)
      }
    } catch (err) {
      setTestResult({ ok: false, error: String(err) })
    } finally {
      setTesting(false)
    }
  }

  function handleAddStation() {
    const code = prompt('Код станции (число):')
    const name = prompt('Название станции:')
    if (!code || !name) return
    const stations = [...settings.stations, { code: Number(code), name }]
    setSettings((prev) => ({ ...prev, stations }))
  }

  function handleRemoveStation(code: number) {
    const stations = settings.stations.filter((s) => s.code !== code)
    setSettings((prev) => ({ ...prev, stations }))
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-bold">Настройки</h1>

      {/* STS API */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wifi className="h-5 w-5" />
            Подключение к STS API
          </CardTitle>
          <CardDescription>
            Данные для подключения к pos.autooplata.ru/tms
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="stsApiUrl">URL API</Label>
            <Input
              id="stsApiUrl"
              value={settings.stsApiUrl}
              onChange={(e) => update('stsApiUrl', e.target.value)}
              placeholder="https://pos.autooplata.ru/tms"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="stsLogin">Логин</Label>
              <Input
                id="stsLogin"
                value={settings.stsLogin}
                onChange={(e) => update('stsLogin', e.target.value)}
                placeholder="UserTest"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="stsPassword">Пароль</Label>
              <Input
                id="stsPassword"
                type="password"
                value={settings.stsPassword}
                onChange={(e) => update('stsPassword', e.target.value)}
                placeholder="••••••"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="stsSystemCode">Код системы (сети)</Label>
            <Input
              id="stsSystemCode"
              type="number"
              value={settings.stsSystemCode}
              onChange={(e) => update('stsSystemCode', Number(e.target.value))}
              className="w-32"
            />
          </div>

          <div className="flex items-center gap-3">
            <Button onClick={handleTest} disabled={testing || !settings.stsLogin}>
              {testing && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Проверить подключение
            </Button>
            <Button onClick={handleSave} variant="default">
              Сохранить
            </Button>
            {testResult && (
              <div className="flex items-center gap-1">
                {testResult.ok ? (
                  <>
                    <CheckCircle2 className="h-5 w-5 text-green-500" />
                    <span className="text-sm text-green-600">OK ({testResult.shiftsCount} смен)</span>
                  </>
                ) : (
                  <>
                    <XCircle className="h-5 w-5 text-red-500" />
                    <span className="text-sm text-red-600">{testResult.error}</span>
                  </>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Станции */}
      <Card>
        <CardHeader>
          <CardTitle>Станции АЗС</CardTitle>
          <CardDescription>
            Станции для загрузки сменных отчётов
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {settings.stations.map((s) => (
            <div key={s.code} className="flex items-center justify-between py-1">
              <div className="flex items-center gap-2">
                <Badge variant="outline">{s.code}</Badge>
                <span>{s.name}</span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground hover:text-destructive"
                onClick={() => handleRemoveStation(s.code)}
              >
                Убрать
              </Button>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={handleAddStation}>
            + Добавить станцию
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

export default SettingsPage
