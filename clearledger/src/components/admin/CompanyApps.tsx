/**
 * Раздел «Приложения»: какие продукты и модули подключены организации, а владельцу
 * контейнера — ещё и каталог платформы второй секцией (`AppCatalogSection`).
 *
 * Раньше это были два соседних раздела: «Приложения» организации и «Каталог» контейнера.
 * Чтобы ответить на один вопрос — что есть и что из этого включено — админ читал два
 * похожих экрана с одинаковыми карточками продуктов.
 *
 * Включение хранится на сервере (`eco_company_apps` / `eco_company_app_modules`), а не в
 * браузере. Правки — админ организации или суперадмин (`canManage`), как на бэкенде.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, Blocks } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import {
  listCompanyApps, setCompanyApp, setCompanyAppModule, type CompanyAppRec,
} from '@/services/registryService'
import { AppCatalogSection } from './AppCatalog'

export function CompanyApps({ companyId, canManage, isSuperadmin = false }: {
  companyId: string; canManage: boolean; isSuperadmin?: boolean
}) {
  const qc = useQueryClient()
  const key = ['company-apps', companyId]
  const q = useQuery({ queryKey: key, queryFn: () => listCompanyApps(companyId) })

  const appMut = useMutation({
    mutationFn: ({ appId, enabled }: { appId: string; enabled: boolean }) =>
      setCompanyApp(companyId, appId, enabled),
    onSuccess: () => { toast.success('Сохранено'); qc.invalidateQueries({ queryKey: key }) },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })
  const modMut = useMutation({
    mutationFn: ({ appId, code, enabled }: { appId: string; code: string; enabled: boolean }) =>
      setCompanyAppModule(companyId, appId, code, enabled),
    onSuccess: () => { toast.success('Сохранено'); qc.invalidateQueries({ queryKey: key }) },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground py-8">
        <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
      </div>
    )
  }
  const apps = q.data ?? []
  const busy = appMut.isPending || modMut.isPending

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Приложения и модули экосистемы, подключённые организации. Включение управляется здесь
        (серверный реестр), а не браузером.
      </p>
      {apps.map((app) => (
        <AppCard
          key={app.id}
          app={app}
          canManage={canManage}
          busy={busy}
          onToggleApp={(enabled) => appMut.mutate({ appId: app.id, enabled })}
          onToggleModule={(code, enabled) => modMut.mutate({ appId: app.id, code, enabled })}
        />
      ))}
      {apps.length === 0 && (
        <Card><CardContent className="py-10 text-center text-muted-foreground">Нет приложений</CardContent></Card>
      )}
      {/* Каталог платформы — ниже подключённых: сперва «что у этой организации», потом
          «что вообще есть». Владельцу контейнера, эндпоинты каталога и так гейтятся. */}
      {isSuperadmin && <AppCatalogSection />}
    </div>
  )
}

function AppCard({ app, canManage, busy, onToggleApp, onToggleModule }: {
  app: CompanyAppRec
  canManage: boolean
  busy: boolean
  onToggleApp: (enabled: boolean) => void
  onToggleModule: (code: string, enabled: boolean) => void
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Blocks className="h-4 w-4 text-primary" /> {app.name}
              <Badge variant="outline" className="font-mono text-[10px]">{app.code}</Badge>
            </CardTitle>
            {app.description && <CardDescription className="mt-1">{app.description}</CardDescription>}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-xs text-muted-foreground">{app.enabled ? 'Включено' : 'Выключено'}</span>
            <Switch checked={app.enabled} disabled={!canManage || busy} onCheckedChange={onToggleApp} />
          </div>
        </div>
      </CardHeader>
      {app.modules.length > 0 && (
        <CardContent className="pt-0">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {app.modules.map((m) => (
              <div
                key={m.code}
                className={`flex items-center justify-between gap-2 rounded-lg border px-3 py-2 ${app.enabled ? '' : 'opacity-50'}`}
              >
                <span className="text-sm flex items-center gap-2">
                  {m.name}
                  {m.isCore && <Badge variant="secondary" className="text-[10px]">ядро</Badge>}
                </span>
                <Switch
                  checked={m.enabled}
                  disabled={!canManage || busy || m.isCore || !app.enabled}
                  onCheckedChange={(v) => onToggleModule(m.code, v)}
                />
              </div>
            ))}
          </div>
        </CardContent>
      )}
    </Card>
  )
}
