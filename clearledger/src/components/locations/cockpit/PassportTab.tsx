/**
 * Паспорт станции — свойства с точки зрения бизнеса и потребителя:
 * идентификация, тип, статусы, расположение, характеристики (кроме оборудования).
 */
import type { ReactNode } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Pencil, MapPin } from 'lucide-react'
import { useLocationTypes } from '@/hooks/useLocationTypes'
import { MetadataFieldsReader } from '@/components/manual/MetadataFieldsReader'
import { LOCATION_STATUS_META, type ServiceLocation } from '@/types/location'
import { Field, SectionCard, OP_META, EQUIPMENT_KEYS, ScrollTab } from './shared'

export function PassportTab({
  location,
  renderEdit,
}: {
  location: ServiceLocation
  renderEdit?: (location: ServiceLocation, child: ReactNode) => ReactNode
}) {
  const types = useLocationTypes()
  const typeDef = types.find((t) => t.code === location.type)
  const meta = (location.metadata ?? {}) as Record<string, unknown>
  const pp = (location.passport ?? {}) as Record<string, unknown>
  const curOp = location.operationalStatus ?? 'unknown'
  const lifeMeta = LOCATION_STATUS_META[location.status]

  // Координаты для блока «Расположение» (если есть в metadata — у ЭЗС).
  const lat = meta.latitude != null ? String(meta.latitude) : ''
  const lon = meta.longitude != null ? String(meta.longitude) : ''
  const owner = meta.ownerTitle != null ? String(meta.ownerTitle) : ''

  // Поля, вынесенные в блок «Расположение» (не дублируем в «Характеристиках»).
  const LOCATION_KEYS = ['latitude', 'longitude', 'ownerTitle', 'ownerId',
    'federalDistrict', 'federalSubject', 'cityName', 'placement']
  // Характеристики типа БЕЗ оборудования и без гео/владельца (они в карточках выше).
  const passportFields = (typeDef?.fields ?? []).filter(
    (f) => !EQUIPMENT_KEYS.includes(f.key) && !LOCATION_KEYS.includes(f.key),
  )

  return (
    <ScrollTab>
      <Card>
        <CardContent className="grid grid-cols-2 gap-x-8 gap-y-2 pt-5 text-sm">
          <Field label="Код / серийник" value={location.code} mono />
          <Field label="Тип" value={typeDef?.name ?? location.type} />
          <Field label="Жизненный статус" value={lifeMeta?.label ?? location.status} />
          <Field label="Операц. статус" value={OP_META[curOp]?.label ?? curOp} />
          {owner && <div className="col-span-2"><Field label="Владелец / сеть" value={owner} /></div>}
          <div className="col-span-2"><Field label="Адрес" value={location.address || '—'} /></div>
          {location.description && (
            <div className="col-span-2"><Field label="Описание" value={location.description} /></div>
          )}
        </CardContent>
      </Card>

      {(lat || lon || meta.federalDistrict != null || meta.federalSubject != null) && (
        <SectionCard title="Расположение" icon={MapPin}>
          <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
            {meta.federalDistrict != null && <Field label="Федеральный округ" value={String(meta.federalDistrict)} />}
            {meta.federalSubject != null && <Field label="Регион" value={String(meta.federalSubject)} />}
            {meta.cityName != null && <Field label="Город" value={String(meta.cityName)} />}
            {meta.placement != null && <Field label="Расположение" value={String(meta.placement)} />}
            {(lat || lon) && <Field label="Широта" value={lat || '—'} mono />}
            {(lat || lon) && <Field label="Долгота" value={lon || '—'} mono />}
          </div>
          {lat && lon && (
            <a
              href={`https://yandex.ru/maps/?pt=${lon},${lat}&z=16&l=map`}
              target="_blank" rel="noreferrer"
              className="mt-3 inline-block text-xs text-primary hover:underline"
            >
              Открыть на карте →
            </a>
          )}
        </SectionCard>
      )}

      <SectionCard title={`Характеристики · ${typeDef?.name ?? location.type}`}>
        <MetadataFieldsReader fields={passportFields} values={meta} />
      </SectionCard>

      {/* Учётные атрибуты из сводной выработки контрагента (слот obshaya) */}
      {(pp.locationClass != null || pp.speedClass != null || pp.installedOn != null
        || pp.decommissionedOn != null || pp.inventoryNumber != null || pp.isCorp != null) && (
        <SectionCard title="Учётные атрибуты (сводная контрагента)">
          <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
            {pp.locationClass != null && (
              <Field label="Размещение" value={pp.locationClass === 'highway' ? 'Трасса' : 'Город'} />
            )}
            {pp.speedClass != null && (
              <Field label="Класс станции" value={pp.speedClass === 'fast' ? 'Быстрая' : 'Медленная'} />
            )}
            {pp.installedOn != null && <Field label="Дата установки" value={String(pp.installedOn)} mono />}
            {pp.decommissionedOn != null && (
              <Field label="Выведена из эксплуатации" value={String(pp.decommissionedOn)} mono />
            )}
            {pp.inventoryNumber != null && (
              <Field label="Инвентарный номер (ОС)" value={String(pp.inventoryNumber)} mono />
            )}
            {pp.isCorp != null && <Field label="Корп-контур (каршеринг)" value="Да" />}
          </div>
        </SectionCard>
      )}

      {renderEdit?.(location, (
        <Button variant="outline"><Pencil className="mr-2 h-4 w-4" /> Редактировать паспорт</Button>
      ))}
    </ScrollTab>
  )
}
