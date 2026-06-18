/**
 * Встроенный набор типов точек — фолбэк фронта (офлайн) и источник меты
 * (иконки/лейблы) для известных кодов. Зеркало backend
 * (server/app/location_type_defaults.py). В API-режиме каталог приходит с бэка.
 */
import type { LocationTypeDef } from '@/types/locationType'

export const BUILTIN_LOCATION_TYPES: LocationTypeDef[] = [
  {
    id: 'builtin-fuel_station', companyId: null, code: 'fuel_station', name: 'АЗС',
    icon: 'Fuel', unit: 'л', nomenclatureKind: 'fuel', isBuiltin: true, sortOrder: 10,
    status: 'active', fields: [],
  },
  {
    id: 'builtin-ev_charging', companyId: null, code: 'ev_charging',
    name: 'Электрозарядная станция', icon: 'Zap', unit: 'кВт·ч',
    nomenclatureKind: 'energy', isBuiltin: true, sortOrder: 20, status: 'active',
    fields: [
      { key: 'serialNumber', label: 'Серийный № (HubEx)', type: 'text' },
      { key: 'ownerTitle', label: 'Владелец', type: 'text' },
      { key: 'federalSubject', label: 'Регион', type: 'text' },
      { key: 'cityName', label: 'Город', type: 'text' },
      { key: 'latitude', label: 'Широта', type: 'number' },
      { key: 'longitude', label: 'Долгота', type: 'number' },
      { key: 'manufacturer', label: 'Бренд', type: 'text' },
      { key: 'model', label: 'Модель', type: 'text' },
      { key: 'connectorCount', label: 'Кол-во коннекторов', type: 'number' },
      { key: 'connectorTypes', label: 'Типы коннекторов (коды)', type: 'text' },
      { key: 'maxPowerKw', label: 'Макс. мощность', type: 'number', unit: 'кВт' },
      { key: 'protocolOcpp', label: 'Протокол OCPP', type: 'select', options: ['Нет', 'OCPP 1.6', 'OCPP 2.0.1'] },
      { key: 'hubexAssetId', label: 'HubEx asset_id', type: 'number' },
      { key: 'hubexName', label: 'HubEx название', type: 'text' },
      { key: 'linkStatus', label: 'Статус связки HubEx', type: 'select', options: ['ok', 'review', 'conflict', 'test', 'no_match'] },
    ],
  },
  {
    id: 'builtin-retail', companyId: null, code: 'retail', name: 'Магазин / сопутка',
    icon: 'Store', unit: 'шт', nomenclatureKind: 'goods', isBuiltin: true,
    sortOrder: 30, status: 'active',
    fields: [
      { key: 'area', label: 'Площадь', type: 'number', unit: 'м²' },
      { key: 'format', label: 'Формат', type: 'text' },
    ],
  },
  {
    id: 'builtin-food', companyId: null, code: 'food', name: 'Общепит',
    icon: 'Utensils', unit: 'шт', nomenclatureKind: 'food', isBuiltin: true,
    sortOrder: 40, status: 'active',
    fields: [
      { key: 'seats', label: 'Посадочных мест', type: 'number' },
      { key: 'cuisine', label: 'Тип кухни', type: 'text' },
    ],
  },
  {
    id: 'builtin-warehouse', companyId: null, code: 'warehouse', name: 'Склад',
    icon: 'Warehouse', unit: '', nomenclatureKind: 'none', isBuiltin: true,
    sortOrder: 50, status: 'active',
    fields: [{ key: 'area', label: 'Площадь', type: 'number', unit: 'м²' }],
  },
  {
    id: 'builtin-office', companyId: null, code: 'office', name: 'Офис',
    icon: 'Building2', unit: '', nomenclatureKind: 'none', isBuiltin: true,
    sortOrder: 60, status: 'active', fields: [],
  },
  {
    id: 'builtin-other', companyId: null, code: 'other', name: 'Другое',
    icon: 'MapPin', unit: '', nomenclatureKind: 'none', isBuiltin: true,
    sortOrder: 70, status: 'active', fields: [],
  },
]
