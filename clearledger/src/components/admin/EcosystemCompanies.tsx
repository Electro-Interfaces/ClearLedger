/**
 * Уровень ЭКОСИСТЕМА → «Компании»: состав пространств контейнера.
 *
 * Раньше список компаний был панелью выбора над вкладками Центра управления. Когда
 * разделы стали маршрутами, выбор переехал в шапку, а состав контейнера — сюда:
 * это отдельный вопрос («кто живёт в контейнере»), а не настройка соседнего экрана.
 */
import { useNavigate } from 'react-router-dom'
import { Building2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { AddCompanyDialog } from '@/components/admin/CompanyProfile'
import { PROFILES } from '@/config/companyProfiles'
import { adminPath } from '@/config/adminNav'
import { useAdminCompany } from '@/hooks/useAdminSpace'

export function EcosystemCompanies() {
  const navigate = useNavigate()
  const { companies, selectCompany } = useAdminCompany()

  function manage(id: string) {
    selectCompany(id)
    navigate(adminPath('company', 'members'))
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-muted-foreground">Компаний в контейнере: {companies.length}</span>
        <AddCompanyDialog onCreated={(c) => manage(c.id)} />
      </div>

      {companies.length === 0 ? (
        <Card><CardContent className="py-10 text-center text-muted-foreground">Нет подключённых компаний</CardContent></Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {companies.map((c) => (
            <Card key={c.id}>
              <CardContent className="flex items-start gap-3 py-4">
                <span className="mt-1 size-3 shrink-0 rounded-full" style={{ background: c.color ?? '#888' }} />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{c.short_name || c.name}</div>
                  <div className="truncate font-mono text-xs text-muted-foreground">{c.slug}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {PROFILES.find((p) => p.id === c.profile_id)?.label ?? c.profile_id}
                    {c.inn ? ` · ИНН ${c.inn}` : ''}
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => manage(c.id)} title="Управлять компанией">
                  <Building2 className="h-4 w-4" />
                  <span className="ml-2 hidden sm:inline">Управлять</span>
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
