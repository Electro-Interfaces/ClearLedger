/**
 * Раздел «Поступления» бух-модуля — управляющий журнал приёмок ТТН.
 * Вкладки: Журнал ТТН (KPI по топливу + фильтры + подтверждение приёмки + себестоимость) ·
 * По станциям (сливы, клик → журнал с фильтром станции) · Закупки (партии, FIFO).
 */
import { useState } from 'react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ReceiptsJournal } from './ReceiptsJournal'
import { TtnByStationView } from './TtnByStationView'
import { PurchaseBatchesPanel } from './PurchaseBatchesPanel'

export function ReceiptsSection() {
  const [tab, setTab] = useState('journal')
  const [stationFilter, setStationFilter] = useState<number | null>(null)

  return (
    <div className="p-4">
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="journal">Журнал ТТН</TabsTrigger>
          <TabsTrigger value="stations">По станциям</TabsTrigger>
          <TabsTrigger value="batches">Закупки</TabsTrigger>
        </TabsList>
        <TabsContent value="journal" className="mt-4">
          <ReceiptsJournal stationFilter={stationFilter} onClearStation={() => setStationFilter(null)} />
        </TabsContent>
        <TabsContent value="stations" className="mt-4">
          <TtnByStationView onStationClick={(code) => { setStationFilter(code); setTab('journal') }} />
        </TabsContent>
        <TabsContent value="batches" className="mt-0"><PurchaseBatchesPanel /></TabsContent>
      </Tabs>
    </div>
  )
}
