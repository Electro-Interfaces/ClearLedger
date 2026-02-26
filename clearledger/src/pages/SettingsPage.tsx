import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { NavLink } from 'react-router-dom'
import { Building2, ChevronRight, Download } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { getSettings, saveSettings } from '@/services/settingsService'
import { exportAllData } from '@/services/exportService'
import type { AppSettings } from '@/services/settingsService'

export function SettingsPage() {
  const { companies, companyId } = useCompany()
  const [settings, setSettings] = useState<AppSettings>(getSettings)
  const [saved, setSaved] = useState(false)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    setSettings(getSettings())
  }, [])

  function handleSaveProfile() {
    saveSettings({ userName: settings.userName, userEmail: settings.userEmail })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  function handleSaveApp() {
    saveSettings({
      language: settings.language,
      dateFormat: settings.dateFormat,
      theme: settings.theme,
      defaultCompanyId: settings.defaultCompanyId,
    })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  async function handleExport() {
    setExporting(true)
    try {
      await exportAllData(companyId)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Настройки</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <NavLink to="/settings/companies" className="lg:col-span-2">
          <Card className="hover:bg-muted/50 transition-colors cursor-pointer">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                    <Building2 className="size-5 text-primary" />
                  </div>
                  <div>
                    <CardTitle>Управление компаниями</CardTitle>
                    <CardDescription>
                      {companies.length} {companies.length === 1 ? 'компания' : companies.length < 5 ? 'компании' : 'компаний'} — профили, категории документов, коннекторы
                    </CardDescription>
                  </div>
                </div>
                <ChevronRight className="size-5 text-muted-foreground" />
              </div>
            </CardHeader>
          </Card>
        </NavLink>

        <Card>
          <CardHeader>
            <CardTitle>Профиль</CardTitle>
            <CardDescription>Настройки пользователя</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Имя</Label>
              <Input
                value={settings.userName}
                onChange={(e) => setSettings({ ...settings, userName: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input
                value={settings.userEmail}
                onChange={(e) => setSettings({ ...settings, userEmail: e.target.value })}
                type="email"
              />
            </div>
            <div className="space-y-2">
              <Label>Роль</Label>
              <Input defaultValue="Администратор" readOnly className="text-muted-foreground" />
            </div>
            <Button onClick={handleSaveProfile}>Сохранить</Button>
            {saved && <span className="text-sm text-green-500 ml-3">Сохранено</span>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Приложение</CardTitle>
            <CardDescription>Общие настройки платформы</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Язык</Label>
              <Select
                value={settings.language}
                onValueChange={(v) => setSettings({ ...settings, language: v as AppSettings['language'] })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ru">Русский</SelectItem>
                  <SelectItem value="en">English</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Формат даты</Label>
              <Select
                value={settings.dateFormat}
                onValueChange={(v) => setSettings({ ...settings, dateFormat: v as AppSettings['dateFormat'] })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="dd.mm.yyyy">ДД.ММ.ГГГГ</SelectItem>
                  <SelectItem value="yyyy-mm-dd">ГГГГ-ММ-ДД</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Тема</Label>
              <Select
                value={settings.theme}
                onValueChange={(v) => setSettings({ ...settings, theme: v as AppSettings['theme'] })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="system">Системная</SelectItem>
                  <SelectItem value="light">Светлая</SelectItem>
                  <SelectItem value="dark">Тёмная</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Separator />
            <div className="space-y-2">
              <Label>Компания по умолчанию</Label>
              <Select
                value={settings.defaultCompanyId}
                onValueChange={(v) => setSettings({ ...settings, defaultCompanyId: v })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {companies.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={handleSaveApp}>Сохранить</Button>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Экспорт данных</CardTitle>
            <CardDescription>Выгрузка данных текущей компании для передачи в Слой 2 или резервного копирования</CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" onClick={handleExport} disabled={exporting}>
              <Download className="mr-2 h-4 w-4" />
              {exporting ? 'Экспорт...' : 'Скачать JSON'}
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
