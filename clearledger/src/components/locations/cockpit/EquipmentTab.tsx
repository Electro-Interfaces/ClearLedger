/**
 * Оборудование станции — «от производителя».
 * ЭЗС: реальные поля из metadata (бренд/модель/коннекторы/мощность/OCPP).
 * АЗС: каркас ТРК/контроллера (задел) + резервуары из последней смены (реально).
 * Прочие типы: профильный каркас или мягкая заглушка.
 */
import { Card, CardContent } from '@/components/ui/card'
import { Cpu, Fuel, Gauge, Database, Zap, Box } from 'lucide-react'
import { useLocationTypes } from '@/hooks/useLocationTypes'
import { MetadataFieldsReader } from '@/components/manual/MetadataFieldsReader'
import { locationStationNumber } from '@/components/reconciliation/locationMapping'
import { useStationLastShift } from '@/hooks/useStationData'
import type { ServiceLocation } from '@/types/location'
import {
  Field, SectionCard, InfoRow, WipBadge, Placeholder, ScrollTab, EQUIPMENT_KEYS, typeFlags,
} from './shared'

export function EquipmentTab({ location }: { location: ServiceLocation }) {
  const types = useLocationTypes()
  const typeDef = types.find((t) => t.code === location.type)
  const meta = (location.metadata ?? {}) as Record<string, unknown>
  const flags = typeFlags(location.type)

  if (flags.isEv) {
    const equipFields = (typeDef?.fields ?? []).filter((f) => EQUIPMENT_KEYS.includes(f.key))
    // Считаем заполненным значение, отличное от пустого/нуля-заглушки.
    const has = (v: unknown) => v !== null && v !== undefined && String(v).trim() !== ''
    // Сводка «от производителя» — только заполненные поля (без вереницы «—»).
    const summary: { label: string; value: string; mono?: boolean }[] = [
      { label: 'Бренд', value: String(meta.manufacturer ?? '') },
      { label: 'Модель', value: String(meta.model ?? '') },
      { label: 'Серийный № (HubEx)', value: String(meta.serialNumber ?? ''), mono: true },
      { label: 'Макс. мощность', value: has(meta.maxPowerKw) ? `${meta.maxPowerKw} кВт` : '' },
      { label: 'Коннекторов', value: String(meta.connectorCount ?? '') },
      { label: 'Типы коннекторов', value: String(meta.connectorTypes ?? '') },
      { label: 'Протокол OCPP', value: String(meta.protocolOcpp ?? '') },
      { label: 'Стадия', value: String(meta.stage ?? '') },
    ].filter((f) => has(f.value))
    return (
      <ScrollTab>
        <Card>
          <CardContent className="pt-5 text-sm">
            {summary.length > 0 ? (
              <div className="grid grid-cols-2 gap-x-8 gap-y-2">
                {summary.map((f) => (
                  <Field key={f.label} label={f.label} value={f.value} mono={f.mono} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Характеристики не заполнены.</p>
            )}
          </CardContent>
        </Card>
        <SectionCard title="Все характеристики оборудования" icon={Zap}>
          <MetadataFieldsReader fields={equipFields} values={meta} />
        </SectionCard>
      </ScrollTab>
    )
  }

  if (flags.isFuel) return <FuelEquipment location={location} />

  if (flags.isRetail || flags.isFood) {
    return (
      <ScrollTab>
        <SectionCard title="Кассовое оборудование" icon={Cpu} muted action={<WipBadge />}>
          <InfoRow label="Касса / ФР" value="—" />
          <InfoRow label="Весы / сканеры" value="—" />
          <InfoRow label="Эквайринг" value="—" />
        </SectionCard>
        <p className="text-xs text-muted-foreground/70">
          Состав торгового оборудования будет подтягиваться из систем станции.
        </p>
      </ScrollTab>
    )
  }

  return (
    <ScrollTab>
      <Placeholder icon={Box} title="Оборудование не описано"
        text={`Для типа «${typeDef?.name ?? location.type}» состав оборудования не ведётся.`} />
    </ScrollTab>
  )
}

/** Оборудование АЗС: каркас ТРК/контроллера + реальные резервуары из последней смены. */
function FuelEquipment({ location }: { location: ServiceLocation }) {
  const stationId = locationStationNumber(location)
  const { reportQ, lastShift } = useStationLastShift(stationId)
  const tanks = reportQ.data?.tanks ?? []

  return (
    <ScrollTab>
      <SectionCard title="ТРК (топливораздаточные колонки)" icon={Fuel} muted action={<WipBadge>из PayTerm/STS</WipBadge>}>
        <InfoRow label="Кол-во колонок" value="—" />
        <InfoRow label="Марка ТРК" value="—" />
        <InfoRow label="Пистолетов" value="—" />
      </SectionCard>

      <SectionCard title="Контроллер / POS" icon={Cpu} muted action={<WipBadge>из PayTerm/STS</WipBadge>}>
        <InfoRow label="Модель контроллера" value="—" />
        <InfoRow label="ПО (Терминал/Нефтосервер)" value="—" />
        <InfoRow label="Серийный №" value="—" />
      </SectionCard>

      <SectionCard
        title="Резервуары" icon={Database} action={<Gauge className="h-4 w-4 text-muted-foreground" />}
      >
        {stationId == null && (
          <p className="text-sm text-muted-foreground">Станция не сопоставлена с STS — резервуары недоступны.</p>
        )}
        {stationId != null && reportQ.isLoading && (
          <p className="text-sm text-muted-foreground">Загрузка резервуаров…</p>
        )}
        {stationId != null && !reportQ.isLoading && tanks.length === 0 && (
          <p className="text-sm text-muted-foreground">Нет данных по резервуарам (нет закрытых смен).</p>
        )}
        {tanks.length > 0 && (
          <>
            <div className="mb-2 text-[11px] text-muted-foreground">
              по последней смене №{lastShift?.shift}
            </div>
            <div className="space-y-1.5">
              {tanks.map((t) => (
                <div key={t.tankNumber} className="flex flex-wrap items-center gap-2 border-b border-border/30 py-1.5 text-sm last:border-0">
                  <span className="font-mono text-xs text-muted-foreground">Рез. {t.tankNumber}</span>
                  <span className="font-medium">{t.fuelName}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    остаток {Math.round(t.rest).toLocaleString('ru-RU')} л
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </SectionCard>
    </ScrollTab>
  )
}
