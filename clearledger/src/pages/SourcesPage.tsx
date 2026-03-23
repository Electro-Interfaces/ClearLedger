import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Database, Globe, Building2, FileCheck, Landmark, Server } from 'lucide-react'

const SOURCE_TYPES = [
  {
    type: 'api',
    label: 'API',
    icon: Globe,
    sources: [
      { name: 'STS (Autooplata)', status: 'connected' as const, description: 'Сменные отчёты, ТТН, цены' },
      { name: 'TradeCorp', status: 'disconnected' as const, description: 'Процессинг, топливные карты' },
    ],
  },
  {
    type: 'ofd',
    label: 'ОФД',
    icon: Server,
    sources: [
      { name: 'ОФД (Оператор фискальных данных)', status: 'pending' as const, description: 'Фискальные чеки, Z-отчёты' },
    ],
  },
  {
    type: 'bank',
    label: 'Банки',
    icon: Landmark,
    sources: [
      { name: 'Россельхозбанк', status: 'disconnected' as const, description: 'Эквайринг, выписки' },
    ],
  },
  {
    type: 'counterparty',
    label: 'Контрагенты',
    icon: Building2,
    sources: [
      { name: 'БАЛТОП АО', status: 'disconnected' as const, description: 'УПД, ТТН, акты сверки' },
      { name: 'СУРГУТНЕФТЕГАЗ', status: 'disconnected' as const, description: 'УПД, договоры' },
    ],
  },
  {
    type: 'edo',
    label: 'ЭДО',
    icon: FileCheck,
    sources: [
      { name: 'Контур.Диадок', status: 'disconnected' as const, description: 'Электронные УПД, СФ' },
      { name: 'Честный ЗНАК', status: 'disconnected' as const, description: 'Маркировка товаров' },
    ],
  },
  {
    type: 'internal',
    label: '1С',
    icon: Database,
    sources: [
      { name: '1С ГИГ (OData)', status: 'pending' as const, description: 'Справочники, документы, проводки' },
    ],
  },
]

const STATUS_META = {
  connected: { label: 'Подключён', variant: 'default' as const, color: 'text-emerald-500' },
  disconnected: { label: 'Не подключён', variant: 'secondary' as const, color: 'text-muted-foreground' },
  pending: { label: 'Настраивается', variant: 'outline' as const, color: 'text-amber-500' },
}

export function SourcesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">Источники данных</h1>
        <p className="text-sm text-muted-foreground">Внешние системы с которыми работает компания</p>
      </div>

      {SOURCE_TYPES.map((group) => (
        <div key={group.type} className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
            <group.icon className="h-3.5 w-3.5" />
            {group.label}
          </h2>
          <div className="grid gap-2">
            {group.sources.map((src) => {
              const st = STATUS_META[src.status]
              return (
                <Card key={src.name} className="bg-card/50">
                  <CardContent className="py-3 px-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium">{src.name}</p>
                        <p className="text-xs text-muted-foreground">{src.description}</p>
                      </div>
                      <Badge variant={st.variant} className="text-[10px]">{st.label}</Badge>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

export default SourcesPage
