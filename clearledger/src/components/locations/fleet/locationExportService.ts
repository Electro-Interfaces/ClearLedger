/**
 * Выгрузка точек обслуживания в Excel/CSV (текущая выборка с учётом фильтров).
 * Паттерн скопирован из src/services/exportService.ts (XLSX + CSV с UTF-8 BOM),
 * но типизирован под ServiceLocation (свой набор колонок).
 */
import * as XLSX from 'xlsx'
import { LOCATION_STATUS_META, type ServiceLocation } from '@/types/location'
import type { LocationTypeDef } from '@/types/locationType'
import { OP_META } from '@/components/locations/cockpit/shared'
import { m } from './locationFleetService'

export interface ExportCtx { typeByCode: Map<string, LocationTypeDef> }
export interface LocationColumn { key: string; label: string; get: (l: ServiceLocation, ctx: ExportCtx) => string }

function fmtDate(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('ru-RU')
}

/**
 * Номер станции у карточек, где паспорт его не несёт: зеркала реестра Поддержки
 * (тип `ezs`) и объекты, заведённые до сверки с витриной. Берём числовой код
 * (у старых карточек code = номер) либо «№ 295» из названия — идентификатор
 * источника вида «nsp_0064» номером не считаем. Правда о номере живёт в
 * паспорте: это подпорка выгрузки, а не замена сверке реестра.
 */
export function numberFallback(l: ServiceLocation): string {
  if (/^\d+$/.test(l.code)) return l.code
  return l.name.match(/№\s*(\d+)/)?.[1] ?? ''
}

export const LOCATION_COLUMNS: LocationColumn[] = [
  // Первые две графы — то, чем станцию называет заказчик: номер и серийник.
  // «Код» — внутренний ключ карточки, читателю выгрузки он ничего не говорит,
  // поэтому уехал вниз под своим именем и вне набора по умолчанию.
  { key: 'number', label: 'Номер станции', get: (l) => m(l, 'number') || numberFallback(l) },
  { key: 'serialNumber', label: 'Серийный номер', get: (l) => m(l, 'serialNumber') },
  { key: 'name', label: 'Название', get: (l) => l.name },
  { key: 'type', label: 'Тип', get: (l, c) => c.typeByCode.get(l.type)?.name ?? l.type },
  { key: 'status', label: 'Жизненный статус', get: (l) => LOCATION_STATUS_META[l.status]?.label ?? l.status },
  { key: 'operationalStatus', label: 'Операц. статус', get: (l) => OP_META[l.operationalStatus ?? 'unknown']?.label ?? (l.operationalStatus ?? '') },
  { key: 'address', label: 'Адрес', get: (l) => l.address ?? '' },
  { key: 'ownerTitle', label: 'Владелец', get: (l) => m(l, 'ownerTitle') },
  { key: 'federalSubject', label: 'Регион', get: (l) => m(l, 'federalSubject') },
  { key: 'cityName', label: 'Город', get: (l) => m(l, 'cityName') },
  { key: 'manufacturer', label: 'Бренд', get: (l) => m(l, 'manufacturer') },
  { key: 'model', label: 'Модель', get: (l) => m(l, 'model') },
  { key: 'maxPowerKw', label: 'Мощность, кВт', get: (l) => m(l, 'maxPowerKw') },
  { key: 'connectorCount', label: 'Коннекторов', get: (l) => m(l, 'connectorCount') },
  { key: 'connectorTypes', label: 'Типы коннекторов', get: (l) => m(l, 'connectorTypes') },
  { key: 'protocolOcpp', label: 'Протокол OCPP', get: (l) => m(l, 'protocolOcpp') },
  { key: 'code', label: 'Код в системе', get: (l) => l.code },
  { key: 'hubexAssetId', label: 'HubEx asset_id', get: (l) => m(l, 'hubexAssetId') },
  { key: 'linkStatus', label: 'Связка HubEx', get: (l) => m(l, 'linkStatus') },
  { key: 'latitude', label: 'Широта', get: (l) => m(l, 'latitude') },
  { key: 'longitude', label: 'Долгота', get: (l) => m(l, 'longitude') },
  { key: 'bindingsCount', label: 'Привязок к источникам', get: (l) => String(l.sourceBindings.length) },
  { key: 'description', label: 'Описание', get: (l) => l.description ?? '' },
  // Даты про карточку в Учёте, а не про станцию в поле: заведение и последняя
  // правка записи. Прежние «Создана / Изменена» читались как ввод в эксплуатацию.
  { key: 'createdAt', label: 'Карточка заведена', get: (l) => fmtDate(l.createdAt) },
  { key: 'updatedAt', label: 'Карточка изменена', get: (l) => fmtDate(l.updatedAt) },
]

export const DEFAULT_EXPORT_COLUMNS = [
  'number', 'serialNumber', 'name', 'type', 'operationalStatus', 'ownerTitle',
  'federalSubject', 'linkStatus',
]

function triggerDownload(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function pickColumns(columnKeys: string[]): LocationColumn[] {
  const set = new Set(columnKeys)
  return LOCATION_COLUMNS.filter((c) => set.has(c.key))
}

function defaultName(ext: string): string {
  return `tradeledger-locations-${new Date().toISOString().slice(0, 10)}.${ext}`
}

export function exportLocationsToExcel(
  rows: ServiceLocation[], columnKeys: string[], ctx: ExportCtx, fileName?: string,
): void {
  const cols = pickColumns(columnKeys)
  const data = rows.map((l) => {
    const o: Record<string, string> = {}
    for (const c of cols) o[c.label] = c.get(l, ctx)
    return o
  })
  const ws = XLSX.utils.json_to_sheet(data)
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Точки')
  const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })
  triggerDownload(
    new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
    fileName ?? defaultName('xlsx'),
  )
}

export function exportLocationsToCsv(
  rows: ServiceLocation[], columnKeys: string[], ctx: ExportCtx, fileName?: string,
): void {
  const cols = pickColumns(columnKeys)
  const esc = (s: string) => (/[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s)
  const header = cols.map((c) => esc(c.label)).join(';')
  const lines = rows.map((l) => cols.map((c) => esc(c.get(l, ctx))).join(';'))
  // UTF-8 BOM — чтобы Excel корректно открыл кириллицу.
  const content = '﻿' + [header, ...lines].join('\r\n')
  triggerDownload(new Blob([content], { type: 'text/csv;charset=utf-8' }), fileName ?? defaultName('csv'))
}
