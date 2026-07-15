/**
 * Раздел Настроек: Профиль организации (реквизиты активной компании).
 * Полное управление пользователями/компаниями/ролями — в разделе
 * «Администрирование» (/admin). Требует API-режим.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Building2, Loader2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import * as userService from '@/services/userService'

export function AdminSection() {
  const { company, companyId, isCompanyAdmin } = useCompany()
  const canEdit = isCompanyAdmin

  if (!isApiEnabled()) return null  // правка профиля требует бэкенд

  return (
    <OrgProfileCard
      companyId={companyId}
      canEdit={canEdit}
      initialName={company.name}
      initialInn={company.inn}
    />
  )
}

function OrgProfileCard({
  companyId, canEdit, initialName, initialInn,
}: { companyId: string; canEdit: boolean; initialName: string; initialInn?: string }) {
  const qc = useQueryClient()
  const [name, setName] = useState(initialName)
  const [inn, setInn] = useState(initialInn ?? '')

  const save = useMutation({
    mutationFn: () => userService.updateCompany(companyId, { name, inn: inn || undefined }),
    onSuccess: () => {
      toast.success('Профиль организации сохранён')
      qc.invalidateQueries()
    },
    onError: (e) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Building2 className="h-5 w-5" />
          Профиль организации
        </CardTitle>
        <CardDescription>Реквизиты текущей компании</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="orgName">Наименование</Label>
            <Input id="orgName" value={name} disabled={!canEdit}
              onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="orgInn">ИНН</Label>
            <Input id="orgInn" value={inn} disabled={!canEdit}
              onChange={(e) => setInn(e.target.value)} placeholder="—" />
          </div>
        </div>
        {canEdit && (
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            Сохранить
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
