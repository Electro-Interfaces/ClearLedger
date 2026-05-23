/**
 * Страница «1С → Справочники». Показывает что из БП мы планируем
 * реплицировать и текущий статус каждой сущности. Реальная репликация
 * подключается параллельным агентом через бэкенд.
 */

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { BookOpen, Building2, Users, Package, FileText, Warehouse, Landmark, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { getOneCConnection } from '@/services/oneCConnectionService'

interface RefEntity {
  key: string
  name: string
  description: string
  odataEntity: string
  icon: typeof BookOpen
  count: number | null
  lastSyncAt: string | null
}

const ENTITIES: RefEntity[] = [
  {
    key: 'organizations',
    name: 'Организации',
    description: 'Юр.лица клиента (для ГИГ — одна с ИНН 7839440090)',
    odataEntity: 'Catalog_Организации',
    icon: Building2,
    count: null,
    lastSyncAt: null,
  },
  {
    key: 'counterparties',
    name: 'Контрагенты',
    description: 'Поставщики, покупатели, прочие — для маппинга в документах',
    odataEntity: 'Catalog_Контрагенты',
    icon: Users,
    count: null,
    lastSyncAt: null,
  },
  {
    key: 'nomenclature',
    name: 'Номенклатура',
    description: 'Товары и услуги — топливо, сопутка, общепит',
    odataEntity: 'Catalog_Номенклатура',
    icon: Package,
    count: null,
    lastSyncAt: null,
  },
  {
    key: 'contracts',
    name: 'Договоры',
    description: 'Договоры с поставщиками и покупателями',
    odataEntity: 'Catalog_ДоговорыКонтрагентов',
    icon: FileText,
    count: null,
    lastSyncAt: null,
  },
  {
    key: 'warehouses',
    name: 'Склады',
    description: 'АЗС, магазины, прочие места хранения',
    odataEntity: 'Catalog_Склады',
    icon: Warehouse,
    count: null,
    lastSyncAt: null,
  },
  {
    key: 'bank_accounts',
    name: 'Банковские счета',
    description: 'Расчётные счета организации',
    odataEntity: 'Catalog_БанковскиеСчета',
    icon: Landmark,
    count: null,
    lastSyncAt: null,
  },
]

export function ReferencesPage() {
  const conn = getOneCConnection()
  const isConnected = conn.status === 'connected'

  function handleSyncAll() {
    if (!isConnected) {
      toast.error('Сначала подключитесь к 1С на вкладке «Подключение»')
      return
    }
    toast.info('Синхронизация подключается параллельным агентом — пока недоступна')
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Справочники из 1С</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Реплицированные сущности БП ГИГ. Используются для маппинга
          поступлений, сменных отчётов и сверки с эталоном.
        </p>
      </div>

      <Card className="py-3 gap-2">
        <CardContent className="pt-0 pb-0 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <BookOpen className="h-3.5 w-3.5" />
            <span>
              {isConnected ? (
                <>Подключение активно. {ENTITIES.length} типов сущностей готовы к репликации</>
              ) : (
                <>Подключение к 1С не настроено — справочники не реплицируются</>
              )}
            </span>
          </div>
          <Button size="sm" variant="outline" className="gap-1.5 h-7"
            onClick={handleSyncAll} disabled={!isConnected}>
            <RefreshCw className="h-3.5 w-3.5" />
            Синхронизировать все
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-2 sm:grid-cols-2">
        {ENTITIES.map((e) => {
          const Icon = e.icon
          return (
            <Card key={e.key} className="py-3 gap-2">
              <CardHeader className="pb-0">
                <div className="flex items-start gap-2">
                  <div className="flex items-center justify-center w-8 h-8 rounded-md bg-muted shrink-0">
                    <Icon className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <CardTitle className="text-sm flex items-center gap-2">
                      {e.name}
                      <Badge variant="outline" className="text-[9px] h-4 px-1 font-mono ml-auto">
                        {e.count ?? '—'}
                      </Badge>
                    </CardTitle>
                    <CardDescription className="text-[11px]">{e.description}</CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="pt-0 pb-0">
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                  <code className="font-mono bg-muted/40 px-1.5 py-0.5 rounded">
                    {e.odataEntity}
                  </code>
                  <span className="ml-auto">
                    {e.lastSyncAt ? `Синх. ${e.lastSyncAt}` : 'Не синхронизировано'}
                  </span>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
