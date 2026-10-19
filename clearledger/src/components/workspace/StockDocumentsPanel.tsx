import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getStockDocuments } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { StationDocModal } from './StationDocModal'
import { TransfersBetweenBlock } from './TransfersBetweenBlock'
import { rowDrill } from './rowDrill'
import { ShowMore, useVisible } from '@/components/common/ShowMore'

const when = (iso: string) => new Date(iso).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })
const directions: Record<string, string> = { internal: 'Внутри станции', out: 'Отправка', in: 'Приёмка' }

export function StockDocumentsPanel({ companyId, kind, dateFrom, dateTo, stations }: {
  companyId: string; kind: 'transfer' | 'writeoff'; dateFrom?: string; dateTo?: string; stations?: string[]
}) {
  const [open, setOpen] = useState<{ packet: string; index: number } | null>(null)
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['stock-documents', companyId, kind, dateFrom, dateTo, stations?.join(',') ?? ''],
    queryFn: () => getStockDocuments({ kind, dateFrom, dateTo, stations }),
  })
  const shown = useVisible(data?.docs ?? [])
  if (isLoading) return <p role="status" className="p-4 text-muted-foreground">Загрузка документов…</p>
  if (error) return <div role="alert" className="p-4">Не удалось загрузить документы. <Button variant="outline" onClick={() => refetch()}>Повторить</Button></div>
  if (!data) return null
  return <div className="flex flex-col gap-4">
    <Card>
      <CardHeader>
        <CardTitle>{kind === 'transfer' ? 'Перемещения' : 'Списания'} станций</CardTitle>
        <CardDescription>Последние редакции документов, полученные центром. Отменённые и служебные документы исключены. Время московское.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-6">
        <p>Документов: <strong>{data.total}</strong></p>
        <p>Позиций: <strong>{data.positions}</strong></p>
        {kind === 'writeoff' && <p>Сумма известных оценок: <strong>{fmtMoney(data.amount ?? 0)}</strong></p>}
        {data.unvalued_positions > 0 && <p role="status">Без подтверждённой стоимости: {data.unvalued_positions} поз.</p>}
      </CardContent>
    </Card>
    {kind === 'transfer' && <TransfersBetweenBlock dateFrom={dateFrom} dateTo={dateTo} stations={stations} />}
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <caption className="sr-only">Текущие документы станций</caption>
        <thead><tr className="border-b text-left">
          <th className="p-3">Дата</th><th className="p-3">АЗС</th><th className="p-3">Документ</th>
          <th className="p-3">Место</th><th className="p-3">Позиций</th>
          {kind === 'writeoff' && <th className="p-3">Сумма</th>}
          <th className="p-3">Автор и основание</th>
        </tr></thead>
        <tbody>{shown.visible.map(doc => <tr key={`${doc.station_id}:${doc.source_uuid}`} {...rowDrill(
          () => setOpen({ packet: doc.packet_uuid, index: doc.doc_index }), `документ ${doc.number ?? ''}`, 'border-b',
        )}>
          <td className="p-3 whitespace-nowrap">{when(doc.doc_date)}</td><td className="p-3">{doc.station_id}</td>
          <td className="p-3">{doc.number || 'Без номера'}<div className="text-xs text-muted-foreground">{directions[doc.direction]}</div></td>
          <td className="p-3 whitespace-nowrap">{doc.place_from || 'Не указано'}{doc.place_to && ` → ${doc.place_to}`}</td>
          <td className="p-3">{doc.positions}</td>
          {kind === 'writeoff' && <td className="p-3 whitespace-nowrap">{doc.unvalued_positions ? 'Оценка неполная' : fmtMoney(doc.amount ?? 0)}</td>}
          <td className="p-3">{doc.author || 'Автор не передан'}<div className="text-xs text-muted-foreground">{doc.note}</div>
            {doc.classification_error && <div className="text-destructive">Требует проверки: {doc.classification_error}</div>}
          </td>
        </tr>)}</tbody>
      </table>
      {data.total === 0 && <p className="p-6 text-muted-foreground">За выбранный период документов нет.</p>}
      {data.total > 300 && <ShowMore {...shown} onMore={shown.more} onAll={shown.all} unit="документов" />}
    </div>
    {open && <StationDocModal packetUuid={open.packet} index={open.index} onClose={() => setOpen(null)} />}
  </div>
}
