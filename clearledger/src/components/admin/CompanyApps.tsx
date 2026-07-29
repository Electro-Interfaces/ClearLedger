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
import { productModules } from '@/config/productAccess'
import { useCompany } from '@/contexts/CompanyContext'

export function CompanyApps({ companyId, canManage, isSuperadmin = false }: {
  companyId: string; canManage: boolean; isSuperadmin?: boolean
}) {
  const qc = useQueryClient()
  const { company } = useCompany()
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
  // Состав продукта берём из той же карты, что рисует меню и матрицу прав
  // (`productAccess`): иначе «какие модули подключены» и «на что можно выдать право»
  // отвечали бы разными списками.
  // Профиль берём у активной компании: у пространства она одна, а состав продукта
  // от профиля зависит («Топливо» у розницы состоит не из ЭЗС-меню).
  const sectionsOf = (code: string) => {
    const groups: { name: string; items: string[] }[] = []
    for (const m of productModules(code, company.profileId)) {
      const last = groups[groups.length - 1]
      if (last && last.name === m.group) last.items.push(m.label)
      else groups.push({ name: m.group, items: [m.label] })
    }
    return groups
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Из чего собрано рабочее пространство организации: подключённые продукты, их модули и
        разделы. Включение хранится в реестре Ядра, а не в браузере; кому эти разделы открыты —
        в «Ролях и доступе».
      </p>
      {apps.map((app) => (
        <AppCard
          key={app.id}
          app={app}
          canManage={canManage}
          busy={busy}
          sections={sectionsOf(app.code)}
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

function AppCard({ app, canManage, busy, sections, onToggleApp, onToggleModule }: {
  app: CompanyAppRec
  canManage: boolean
  busy: boolean
  /** Разделы продукта из карты доступа — состав тех продуктов, у которых нет модулей в реестре. */
  sections: { name: string; items: string[] }[]
  onToggleApp: (enabled: boolean) => void
  onToggleModule: (code: string, enabled: boolean) => void
}) {
  const sectionCount = sections.reduce((s, g) => s + g.items.length, 0)
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
          <div className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground/70">
            Модули — включаются организации
          </div>
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
      {/* У продуктов разреза (Проекты, Продажи, Финансы…) модулей в реестре нет: их состав —
          пункты меню, и включать по отдельности нечего. Раньше карточка такого продукта была
          пустой, и «какие модули подключены» оставалось без ответа. Показываем состав как
          есть, отмечая, что закрывается он ролью, а не выключателем. */}
      {app.modules.length === 0 && sectionCount > 0 && (
        <CardContent className="pt-0">
          <div className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground/70">
            Разделы продукта ({sectionCount}) — доступ выдаётся ролью
          </div>
          <div className={`space-y-1.5 ${app.enabled ? '' : 'opacity-50'}`}>
            {sections.map((g) => (
              <div key={g.name} className="flex flex-wrap items-baseline gap-1.5">
                <span className="text-[11px] text-muted-foreground/70">{g.name}:</span>
                {g.items.map((it) => (
                  <Badge key={it} variant="outline" className="text-[11px] font-normal">{it}</Badge>
                ))}
              </div>
            ))}
          </div>
        </CardContent>
      )}
      {app.modules.length === 0 && sectionCount === 0 && (
        <CardContent className="pt-0">
          <p className="text-xs text-muted-foreground">
            Продукт подключается целиком: отдельных модулей у него нет.
          </p>
        </CardContent>
      )}
    </Card>
  )
}
