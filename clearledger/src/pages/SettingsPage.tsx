import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { NavLink } from 'react-router-dom'
import { Building2, ChevronRight } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'

export function SettingsPage() {
  const { companies } = useCompany()

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
              <Input defaultValue="Михеев Андрей" />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input defaultValue="admin@clearledger.ru" type="email" />
            </div>
            <div className="space-y-2">
              <Label>Роль</Label>
              <Input defaultValue="Администратор" readOnly className="text-muted-foreground" />
            </div>
            <Button>Сохранить</Button>
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
              <Select defaultValue="ru">
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ru">Русский</SelectItem>
                  <SelectItem value="en">English</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Формат даты</Label>
              <Select defaultValue="dd.mm.yyyy">
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="dd.mm.yyyy">ДД.ММ.ГГГГ</SelectItem>
                  <SelectItem value="yyyy-mm-dd">ГГГГ-ММ-ДД</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Separator />
            <div className="space-y-2">
              <Label>Компания по умолчанию</Label>
              <Select defaultValue="npk">
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="npk">НПК</SelectItem>
                  <SelectItem value="rti">РТИ</SelectItem>
                  <SelectItem value="ts94">ТС-94</SelectItem>
                  <SelectItem value="ofptk">ОФ ПТК</SelectItem>
                  <SelectItem value="rushydro">РусГидро</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button>Сохранить</Button>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>OCR Настройки</CardTitle>
            <CardDescription>Параметры распознавания документов</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>OCR Provider</Label>
                <Select defaultValue="tesseract">
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="tesseract">Tesseract (локальный)</SelectItem>
                    <SelectItem value="google">Google Vision API</SelectItem>
                    <SelectItem value="yandex">Yandex Vision</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Минимальный порог уверенности (%)</Label>
                <Input type="number" defaultValue={70} min={0} max={100} />
              </div>
            </div>
            <Button>Сохранить</Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
