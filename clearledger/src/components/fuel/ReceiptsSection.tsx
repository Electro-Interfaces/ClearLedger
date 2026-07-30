/**
 * Раздел «Поступления» бух-модуля — управляющий журнал приёмок ТТН.
 * Вкладки: Журнал ТТН (KPI по топливу + фильтры + подтверждение приёмки) ·
 * По станциям (сливы, клик → журнал с фильтром станции) · Сводная.
 * Закупочные партии и FIFO-себестоимость находятся в «Продажи → Маржа и цены».
 *
 * Метрики сводной здесь свои: приёмку сверяют по МАССЕ, объём зависит от температуры.
 * Отклонение факта от документа - главный ответ раздела, поэтому оно стоит колонкой,
 * а не выводится читателем из двух других.
 */
import { useState } from 'react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ReceiptsJournal } from './ReceiptsJournal'
import { TtnByStationView } from './TtnByStationView'
import { PivotView } from '@/components/workspace/PivotView'
import { useFilters } from '@/contexts/FilterContext'
import { getFuelReceiptsPivot } from '@/services/fuel/fuelMappingService'

export function ReceiptsSection() {
  const [tab, setTab] = useState('journal')
  const [stationFilter, setStationFilter] = useState<number | null>(null)
  const { period } = useFilters()

  return (
    <div className="p-4">
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="journal">Журнал ТТН</TabsTrigger>
          <TabsTrigger value="stations">По станциям</TabsTrigger>
          <TabsTrigger value="pivot">Сводная</TabsTrigger>
        </TabsList>
        <TabsContent value="journal" className="mt-4">
          <ReceiptsJournal stationFilter={stationFilter} onClearStation={() => setStationFilter(null)} />
        </TabsContent>
        <TabsContent value="stations" className="mt-4">
          <TtnByStationView onStationClick={(code) => { setStationFilter(code); setTab('journal') }} />
        </TabsContent>
        <TabsContent value="pivot" className="mt-4">
          <PivotView
            source="receipts" storageKey="fuel-receipts-pivot"
            defaultDims={['supplier', 'fuel']}
            queryKey={{ from: period.from, to: period.to, station: stationFilter }}
            fetchLeaves={(dims) => getFuelReceiptsPivot({
              dims, dateFrom: period.from, dateTo: period.to,
              stationCode: stationFilter ?? undefined,
            })}
            dateFrom={period.from} dateTo={period.to}
            scopeLabel={stationFilter ? `АЗС ${stationFilter}` : 'все АЗС'}
            hint="приёмка сверяется по массе: отклонение считается суммой по разрезу" />
        </TabsContent>
      </Tabs>
    </div>
  )
}
