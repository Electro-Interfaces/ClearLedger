import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ConnectorGrid } from '@/components/connectors/ConnectorGrid'
import { mockConnectors } from '@/services/mockData'
import { useCompany } from '@/contexts/CompanyContext'

export function ConnectorsPage() {
  const { companyId } = useCompany()
  const connectors = mockConnectors.filter((c) => c.companyId === companyId || companyId === 'npk')

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">API-коннекторы</h1>
        <Button asChild>
          <Link to="/connectors/new">
            <Plus className="mr-2 h-4 w-4" />
            Новый коннектор
          </Link>
        </Button>
      </div>
      <ConnectorGrid connectors={connectors} />
    </div>
  )
}
