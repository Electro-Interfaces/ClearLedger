import { Plug } from 'lucide-react'
import { ConnectorCard } from './ConnectorCard'
import { EmptyState } from '@/components/common/EmptyState'
import type { Connector } from '@/types'

interface ConnectorGridProps {
  connectors: Connector[]
}

export function ConnectorGrid({ connectors }: ConnectorGridProps) {
  if (connectors.length === 0) {
    return (
      <EmptyState
        icon={Plug}
        title="Нет коннекторов"
        description="Создайте первый API-коннектор для автоматического получения данных."
      />
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {connectors.map((connector) => (
        <ConnectorCard key={connector.id} connector={connector} />
      ))}
    </div>
  )
}
