import { useSearchParams } from 'react-router-dom'
import { Boxes, FileText, Warehouse } from 'lucide-react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PurchaseBatchesPanel } from './PurchaseBatchesPanel'
import { ReceiptCostRegistry } from './ReceiptCostRegistry'
import { OpeningBalancesPanel } from './OpeningBalancesPanel'

export function CostingWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedView = searchParams.get('costingView')
  const view = requestedView === 'purchases' || requestedView === 'opening' ? requestedView : 'receipts'
  const setView = (value: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set('costingView', value)
      return next
    }, { replace: true })
  }

  return (
    <Tabs value={view} onValueChange={setView}>
      <TabsList variant="line" className="mb-2">
        <TabsTrigger value="receipts"><FileText />Партии ТТН</TabsTrigger>
        <TabsTrigger value="opening"><Warehouse />Начальные остатки</TabsTrigger>
        <TabsTrigger value="purchases"><Boxes />Распределение закупок</TabsTrigger>
      </TabsList>
      <TabsContent value="receipts"><ReceiptCostRegistry /></TabsContent>
      <TabsContent value="opening"><OpeningBalancesPanel /></TabsContent>
      <TabsContent value="purchases"><PurchaseBatchesPanel embedded /></TabsContent>
    </Tabs>
  )
}
