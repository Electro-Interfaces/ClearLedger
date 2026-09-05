import { Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { listCompanyApps } from '@/services/registryService'
import { Button } from '@/components/ui/button'

export function PulsePwaEntry() {
  const { companyId, canApp } = useCompany()
  const query = useQuery({ queryKey: ['company-apps', companyId], queryFn: () => listCompanyApps(companyId), retry: false })
  if (query.isPending) return <p role="status" className="p-6">Открываем пространство…</p>
  if (query.isError) return <div role="alert" className="space-y-3 p-6"><p>Не удалось открыть пространство.</p><Button onClick={() => void query.refetch()}>Повторить</Button></div>
  const enabled = query.data.find((app) => app.code === 'pulse')?.enabled !== false
  return <Navigate to={canApp('pulse') && enabled ? '/pulse' : '/'} replace />
}
