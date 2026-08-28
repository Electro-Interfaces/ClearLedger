import { useState } from 'react'
import { AlertTriangle, CheckCircle2, Database, Network, RadioTower } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { ScrollArea } from '@/components/ui/scroll-area'
import { CentralPanelLayout, type CentralMenuItem } from '@/components/workspace/CentralPanelLayout'
import { DEMO_DATA_MODEL, DEMO_DATA_QUALITY, DEMO_OBJECTS } from './demoData'
import { DEMO_SOURCES } from './demoPlatformData'

const MENU: CentralMenuItem[] = [
  { key: 'overview', label: 'Обзор источников' },
  { key: 'model', label: 'База пространства' },
  { key: 'quality', label: 'Качество данных' },
]

const stationChannel = (objectId: string) => objectId === 'object-forest' ? 'Резервный LTE' : 'Ethernet'

export function DemoSpaceDataView() {
  const [tab, setTab] = useState('overview')

  return (
    <CentralPanelLayout items={MENU} activeKey={tab} onSelect={setTab}>
      <ScrollArea className="h-full">
        <div className="p-4">
          {tab === 'overview' && <Overview />}
          {tab === 'model' && <Model />}
          {tab === 'quality' && <Quality />}
        </div>
      </ScrollArea>
    </CentralPanelLayout>
  )
}

function Overview() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-amber-500/35 bg-amber-500/5 p-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-600 dark:text-amber-400" />
          <div>
            <h2 className="font-medium">INC-2471 · АЗС Лесная</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Основной Ethernet недоступен. Шлюз работает через резервный LTE;
              overlay и критичные сервисы доступны.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricTile label="Объектов в модели" value="5" hint="сеть АЗС Полюс" />
        <MetricTile label="Основной Ethernet" value="4 из 5" tone="success" />
        <MetricTile label="Резервный LTE" value="1 объект" tone="warning" hint="АЗС Лесная" />
        <MetricTile label="Открытых инцидентов" value="1" tone="warning" hint="INC-2471" />
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="flex items-center gap-2 border-b px-4 py-3 text-sm font-medium">
            <RadioTower className="size-4 text-primary" /> Состояние объектов
          </div>
          <div className="divide-y">
            {DEMO_OBJECTS.map((object) => {
              const reserve = object.id === 'object-forest'
              return (
                <div key={object.id} className="grid gap-2 px-4 py-3 text-sm sm:grid-cols-[1fr_150px_170px] sm:items-center">
                  <div>
                    <div className="font-medium">{object.name}</div>
                    <div className="text-xs text-muted-foreground">{object.address}</div>
                  </div>
                  <span className={reserve ? 'text-amber-700 dark:text-amber-400' : 'text-emerald-700 dark:text-emerald-400'}>
                    {stationChannel(object.id)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {reserve ? '164 мс · потери 1,8%' : 'канал работает штатно'}
                  </span>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-3">
        {DEMO_SOURCES.map((source) => (
          <Card key={source.id}>
            <CardContent className="space-y-2 p-4">
              <div className="flex items-start gap-3">
                <span className="rounded-lg bg-primary/10 p-2 text-primary"><Database className="size-4" /></span>
                <div>
                  <div className="text-sm font-medium">{source.name}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{source.description}</div>
                </div>
              </div>
              <div className="border-t pt-2 text-xs text-muted-foreground">
                Проверено {source.id === 'source-stations' ? '2 минуты назад' : 'несколько минут назад'}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

function Model() {
  const totals = DEMO_DATA_MODEL.totals
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-medium">База пространства «Полюс Ритейл»</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Телеметрия нормализуется и связывается с объектами, людьми, документами и INC-2471.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricTile label="Сущностей" value={String(totals.entities)} />
        <MetricTile label="Записей" value={String(totals.records)} />
        <MetricTile label="Связано" value={`${totals.filled} из ${totals.records}`} tone="success" />
        <MetricTile label="Разрывов связей" value={String(totals.gaps)} tone="success" />
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {[
          ['L0', 'Снимок источников', 'Неизменённые статусы шлюзов и события каналов'],
          ['L1', 'Нормализованный слой', 'Единые значения Ethernet, LTE и доступности сервисов'],
          ['L2', 'База пространства', 'Связи с АЗС Лесная, INC-2471 и ответственными'],
        ].map(([code, title, description]) => (
          <Card key={code}>
            <CardContent className="p-4">
              <div className="text-xs font-semibold text-primary">{code}</div>
              <div className="mt-1 text-sm font-medium">{title}</div>
              <div className="mt-1 text-xs text-muted-foreground">{description}</div>
            </CardContent>
          </Card>
        ))}
      </div>
      {DEMO_DATA_MODEL.domains.map((domain) => (
        <Card key={domain.key}>
          <CardContent className="p-0">
            <div className="flex items-center gap-2 border-b px-4 py-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              <Network className="size-4" /> {domain.label}
            </div>
            <div className="divide-y">
              {domain.entities.map((entity) => (
                <div key={entity.key} className="grid gap-1 px-4 py-3 text-sm sm:grid-cols-[1fr_90px_1.4fr] sm:items-center">
                  <div><span className="font-medium">{entity.label}</span><span className="ml-2 font-mono text-[10px] text-muted-foreground">{entity.table}</span></div>
                  <span className="tabular-nums">{entity.records}</span>
                  <span className="text-xs text-muted-foreground">{entity.sources} → {entity.consumers}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function Quality() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-medium">Качество данных сети АЗС</h2>
        <p className="mt-1 text-xs text-muted-foreground">Один ожидаемый сигнал связан с действующим INC-2471.</p>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <MetricTile label="Проверок" value="3" />
        <MetricTile label="Пройдено" value="2" tone="success" />
        <MetricTile label="Требует внимания" value="1" tone="warning" />
      </div>
      {DEMO_DATA_QUALITY.groups.map((group) => (
        <Card key={group.label}>
          <CardContent className="p-0">
            <div className="border-b px-4 py-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">{group.label}</div>
            <div className="divide-y">
              {group.checks.map((check) => {
                const Icon = check.ok ? CheckCircle2 : AlertTriangle
                return (
                  <div key={check.key} className="flex items-start gap-3 px-4 py-3">
                    <Icon className={`mt-0.5 size-4 shrink-0 ${check.ok ? 'text-emerald-600' : 'text-amber-600'}`} />
                    <div>
                      <div className="text-sm font-medium">{check.label}</div>
                      <div className="mt-0.5 text-xs text-muted-foreground">{check.hint}</div>
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
