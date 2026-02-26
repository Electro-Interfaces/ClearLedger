import { ConnectorCard } from './ConnectorCard'
import type { Connector } from '@/types'

interface ConnectorGridProps {
  connectors: Connector[]
}

export function ConnectorGrid({ connectors }: ConnectorGridProps) {
  if (connectors.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        Нет настроенных коннекторов
      </div>
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
