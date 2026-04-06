import { BookOpen, Building2, Package, Landmark } from 'lucide-react'

const referenceTypes = [
  {
    icon: Package,
    title: 'Номенклатура',
    description: 'Товары, ГСМ, услуги — единый справочник для маппинга',
    count: null,
  },
  {
    icon: Building2,
    title: 'Контрагенты',
    description: 'Поставщики, покупатели, контрагенты с реквизитами',
    count: null,
  },
  {
    icon: Landmark,
    title: 'План счетов',
    description: 'Счета бухгалтерского учёта, субконто',
    count: null,
  },
  {
    icon: BookOpen,
    title: 'Учётная политика',
    description: 'Настройки учёта, НДС, методы списания',
    count: null,
  },
]

export function ReferencesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Справочники 1С</h1>
        <p className="text-muted-foreground mt-1">
          Данные из информационной базы 1С для маппинга и сверки
        </p>
      </div>

      <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 p-4">
        <p className="text-sm text-yellow-600 dark:text-yellow-400">
          Подключение к 1С не настроено. Настройте подключение в разделе «Подключение».
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {referenceTypes.map((ref) => (
          <div key={ref.title} className="rounded-lg border bg-card p-5 space-y-2 opacity-60">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-lg bg-muted flex items-center justify-center">
                <ref.icon className="h-4.5 w-4.5 text-muted-foreground" />
              </div>
              <div>
                <p className="font-medium">{ref.title}</p>
                <p className="text-xs text-muted-foreground">
                  {ref.count !== null ? `${ref.count} записей` : 'Нет данных'}
                </p>
              </div>
            </div>
            <p className="text-sm text-muted-foreground">{ref.description}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
