/**
 * ReferenceStatusWidget — виджет состояния справочников НСИ.
 *
 * Показывает количество записей по каждому справочнику + ссылки.
 */

import { useNavigate } from 'react-router-dom'
import { useReferenceStats } from '@/hooks/useReferences'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { BookOpen, Users, Building2, Package, FileText } from 'lucide-react'

export function ReferenceStatusWidget() {
  const navigate = useNavigate()
  const { data: stats } = useReferenceStats()

  if (!stats) return null

  const items = [
    { label: 'Контрагенты', count: stats.counterparties, icon: Users },
    { label: 'Организации', count: stats.organizations, icon: Building2 },
    { label: 'Номенклатура', count: stats.nomenclature, icon: Package },
    { label: 'Договоры', count: stats.contracts, icon: FileText },
  ]

  return (
    <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <BookOpen className="size-4" />
          Справочники НСИ
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2">
          {items.map((item) => (
            <div key={item.label} className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <item.icon className="size-3.5 text-muted-foreground" />
                <span>{item.label}</span>
              </div>
              <span className="font-medium tabular-nums">{item.count}</span>
            </div>
          ))}
        </div>

        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={() => navigate('/references')}
          >
            Справочники
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
