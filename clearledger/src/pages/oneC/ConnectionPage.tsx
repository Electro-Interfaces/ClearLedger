import { Plug, Server, CheckCircle2, AlertCircle } from 'lucide-react'

export function ConnectionPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Подключение к 1С</h1>
        <p className="text-muted-foreground mt-1">
          Настройка связи с информационной базой 1С:Бухгалтерия
        </p>
      </div>

      <div className="rounded-lg border bg-card p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-muted flex items-center justify-center">
            <Server className="h-5 w-5 text-muted-foreground" />
          </div>
          <div>
            <p className="font-medium">Статус подключения</p>
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <AlertCircle className="h-3.5 w-3.5 text-yellow-500" />
              <span>Не настроено</span>
            </div>
          </div>
        </div>

        <div className="grid gap-4 pt-2">
          <div className="space-y-2">
            <label className="text-sm font-medium">Адрес сервера 1С</label>
            <input
              type="text"
              placeholder="http://192.168.40.31/acc/odata/standard.odata"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              disabled
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Имя базы</label>
            <input
              type="text"
              placeholder="GIG Base2"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              disabled
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Логин</label>
              <input
                type="text"
                placeholder="Администратор"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                disabled
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Пароль</label>
              <input
                type="password"
                placeholder="••••••••"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                disabled
              />
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 pt-2">
          <button className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground opacity-50 cursor-not-allowed">
            Подключить
          </button>
          <span className="text-xs text-muted-foreground">Функция в разработке</span>
        </div>
      </div>

      <div className="rounded-lg border bg-card p-6 space-y-3">
        <h3 className="font-medium flex items-center gap-2">
          <Plug className="h-4 w-4" />
          Что даёт подключение к 1С
        </h3>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li className="flex items-start gap-2">
            <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
            Реквизиты компании и учётная политика
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
            Справочники: номенклатура, контрагенты, счета
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
            Данные по закрытым периодам для сверки
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
            Историческая бухгалтерия: документы и проводки
          </li>
          <li className="flex items-start gap-2">
            <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
            Сверка первичных документов с данными 1С
          </li>
        </ul>
      </div>
    </div>
  )
}
