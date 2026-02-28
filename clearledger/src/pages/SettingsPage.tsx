import { useState, useEffect, useRef, useCallback } from 'react'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { NavLink } from 'react-router-dom'
import { Building2, ChevronRight, Download, Upload, FileJson, HardDrive, RotateCcw, Bell } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useTheme } from '@/hooks/useTheme'
import { useQueryClient } from '@tanstack/react-query'
import { getSettings, saveSettings } from '@/services/settingsService'
import { exportAllData } from '@/services/exportService'
import { importFromJson } from '@/services/importService'
import { getStorageUsage, formatBytes, type StorageUsage } from '@/services/storageMonitor'
import { resetOnboarding } from '@/components/onboarding/OnboardingWizard'
import { clearAll as clearNotifications } from '@/services/notificationService'
import { isApiEnabled } from '@/services/apiClient'
import { OneCConnectionForm } from '@/components/settings/OneCConnectionForm'
import { OneCSyncStatus } from '@/components/settings/OneCSyncStatus'
import { OneCSyncHistory } from '@/components/settings/OneCSyncHistory'
import { useOneCConnections } from '@/hooks/useOneCSync'
import type { AppSettings } from '@/services/settingsService'

function OneCIntegrationSection() {
  const { data: connections } = useOneCConnections()
  const connection = connections?.[0]

  return (
    <div className="lg:col-span-2 space-y-4">
      <OneCConnectionForm />
      {connection && (
        <>
          <OneCSyncStatus connectionId={connection.id} exchangePath={connection.exchangePath} />
          <OneCSyncHistory connectionId={connection.id} />
        </>
      )}
    </div>
  )
}

export function SettingsPage() {
  const { companies, companyId } = useCompany()
  const { theme: activeTheme, setTheme } = useTheme()
  const queryClient = useQueryClient()
  const [settings, setSettings] = useState<AppSettings>(getSettings)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [storageUsage, setStorageUsage] = useState<StorageUsage | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setSettings(getSettings())
    setStorageUsage(getStorageUsage())
  }, [])

  const handleImportFile = useCallback(async (file: File) => {
    if (!file.name.endsWith('.json')) {
      toast.error('Поддерживается только формат JSON')
      return
    }
    setImporting(true)
    try {
      const result = await importFromJson(file, companyId)
      if (result.errors.length > 0) {
        toast.error(result.errors[0])
      } else {
        toast.success(`Импортировано: ${result.imported}, пропущено: ${result.skipped}`)
        queryClient.invalidateQueries({ queryKey: ['entries'] })
        queryClient.invalidateQueries({ queryKey: ['connectors'] })
        setStorageUsage(getStorageUsage())
      }
    } catch {
      toast.error('Ошибка импорта')
    } finally {
      setImporting(false)
    }
  }, [companyId, queryClient])

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleImportFile(file)
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) handleImportFile(file)
    e.target.value = ''
  }

  function handleSaveProfile() {
    saveSettings({ userName: settings.userName, userEmail: settings.userEmail })
    toast.success('Профиль сохранён')
  }

  function handleSaveApp() {
    saveSettings({
      language: settings.language,
      dateFormat: settings.dateFormat,
      defaultCompanyId: settings.defaultCompanyId,
    })
    // Тема сохраняется и применяется через useTheme
    setTheme(settings.theme)
    toast.success('Настройки сохранены')
  }

  async function handleExport() {
    setExporting(true)
    try {
      await exportAllData(companyId)
      toast.success('Данные экспортированы')
    } catch {
      toast.error('Ошибка экспорта')
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
              <Input value="Русский" readOnly className="text-muted-foreground" />
              <p className="text-xs text-muted-foreground">Дополнительные языки будут доступны в следующей версии</p>
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
              <p className="text-xs text-muted-foreground">
                Текущая: {activeTheme === 'dark' ? 'тёмная' : 'светлая'}
              </p>
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

        <Card>
          <CardHeader>
            <CardTitle>Уведомления и онбординг</CardTitle>
            <CardDescription>Управление уведомлениями и первоначальной настройкой</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <RotateCcw className="size-4 text-muted-foreground" />
                <div>
                  <p className="text-sm font-medium">Онбординг</p>
                  <p className="text-xs text-muted-foreground">Повторить приветственный визард</p>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  resetOnboarding()
                  toast.success('Онбординг сброшен. Перейдите на дашборд для запуска.')
                }}
              >
                Сбросить
              </Button>
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Bell className="size-4 text-muted-foreground" />
                <div>
                  <p className="text-sm font-medium">Уведомления</p>
                  <p className="text-xs text-muted-foreground">Очистить все уведомления</p>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  clearNotifications()
                  queryClient.invalidateQueries({ queryKey: ['notifications'] })
                  toast.success('Уведомления очищены')
                }}
              >
                Очистить
              </Button>
            </div>
          </CardContent>
        </Card>

        {isApiEnabled() && <OneCIntegrationSection />}

        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                <HardDrive className="size-5 text-primary" />
              </div>
              <div>
                <CardTitle>Данные</CardTitle>
                <CardDescription>
                  Экспорт, импорт и хранилище
                  {storageUsage && (
                    <span className="ml-2 text-xs">
                      ({formatBytes(storageUsage.usedBytes)} / {formatBytes(storageUsage.totalBytes)}, {storageUsage.percent}%)
                    </span>
                  )}
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-3">
              <Button variant="outline" onClick={handleExport} disabled={exporting}>
                <Download className="mr-2 h-4 w-4" />
                {exporting ? 'Экспорт...' : 'Экспорт JSON'}
              </Button>
              <Button variant="outline" onClick={() => fileInputRef.current?.click()} disabled={importing}>
                <Upload className="mr-2 h-4 w-4" />
                {importing ? 'Импорт...' : 'Импорт JSON'}
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json"
                className="hidden"
                onChange={handleFileSelect}
              />
            </div>

            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
                dragOver
                  ? 'border-primary bg-primary/5'
                  : 'border-muted-foreground/25 hover:border-muted-foreground/50'
              }`}
            >
              <FileJson className="mx-auto h-8 w-8 text-muted-foreground mb-2" />
              <p className="text-sm text-muted-foreground">
                Перетащите JSON-файл для импорта данных
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Формат: экспорт ClearLedger (.json)
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
