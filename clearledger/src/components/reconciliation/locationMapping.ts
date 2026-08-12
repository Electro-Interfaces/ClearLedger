/**
 * Сопоставление справочника Location (TradeLedger) → параметры сверки.
 *
 * В TradeFrame станции брались из TradingPoint (external_id = код станции STS,
 * externalCodes c system='msto' = MSTO servicePointId). В TradeLedger сетей нет,
 * вместо TradingPoint — справочник `ServiceLocation` (типа 'fuel_station').
 *
 * ДОПУЩЕНИЕ (Location → номер станции STS):
 *   1) Если у точки есть привязка к источнику (sourceBindings[].config) с полем
 *      `station` (или `station_id`/`stationId`) — берём его как номер станции STS.
 *   2) Иначе пытаемся распарсить числовой `code` точки ("208" → 208).
 *   3) Если ничего не распозналось — станция не участвует в сверке (вернётся null).
 *
 * MSTO servicePointId берём из config привязок (`servicePointId`/`mstoServicePointId`)
 * либо из `metadata.mstoServicePointId(s)`. Если нигде нет — станция не сопоставится
 * с MSTO-заказами (для корп. сверки это не нужно).
 */

import type { ServiceLocation, LocationSourceBinding } from '@/types/location';
import type { StationInfo } from '@/types/mstoReconciliation';

function toNumber(value: unknown): number | null {
  if (value == null) return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const n = parseInt(String(value), 10);
  return Number.isFinite(n) ? n : null;
}

/** Поля config привязки, в которых может лежать номер станции STS */
const STATION_CONFIG_KEYS = ['station', 'station_id', 'stationId', 'stationNumber'];
/** Поля config/metadata, в которых может лежать MSTO servicePointId */
const MSTO_CONFIG_KEYS = ['servicePointId', 'mstoServicePointId', 'msto_service_point_id'];

function readNumberFromConfig(
  bindings: LocationSourceBinding[],
  keys: string[],
): number | null {
  for (const b of bindings) {
    for (const key of keys) {
      const v = b.config?.[key];
      const n = toNumber(v);
      if (n != null && n > 0) return n;
    }
  }
  return null;
}

/**
 * Извлечь номер станции STS для точки обслуживания.
 * @returns номер станции или null, если распознать не удалось
 */
export function locationStationNumber(location: ServiceLocation): number | null {
  // 1) Из привязок к источникам (config.station)
  const fromBinding = readNumberFromConfig(location.sourceBindings, STATION_CONFIG_KEYS);
  if (fromBinding != null) return fromBinding;

  // 2) Из номера станции в паспорте (у ЭЗС code — серийник, и parseInt давал
  //    «23» из «23E001329»)
  const fromPassport = toNumber((location.passport as Record<string, unknown> | undefined)?.stationNumber);
  if (fromPassport != null && fromPassport > 0) return fromPassport;

  // 3) Из числового кода точки ("208" → 208) — только если он целиком число
  const fromCode = /^\d+$/.test((location.code ?? '').trim()) ? toNumber(location.code) : null;
  if (fromCode != null && fromCode > 0) return fromCode;

  return null;
}

/** MSTO servicePointId(s) точки (из config привязок или metadata) */
export function locationMstoServicePointIds(location: ServiceLocation): number[] {
  const ids = new Set<number>();

  // Из config привязок
  for (const b of location.sourceBindings) {
    for (const key of MSTO_CONFIG_KEYS) {
      const n = toNumber(b.config?.[key]);
      if (n != null && n > 0) ids.add(n);
    }
  }

  // Из metadata (mstoServicePointId / mstoServicePointIds)
  const meta = location.metadata || {};
  const single = toNumber(meta['mstoServicePointId']);
  if (single != null && single > 0) ids.add(single);
  const arr = meta['mstoServicePointIds'];
  if (Array.isArray(arr)) {
    for (const v of arr) {
      const n = toNumber(v);
      if (n != null && n > 0) ids.add(n);
    }
  }

  return Array.from(ids);
}

/**
 * Преобразовать точку обслуживания в StationInfo для MSTO-сверки.
 * @returns StationInfo или null, если номер станции не распознан
 */
export function locationToStationInfo(location: ServiceLocation): StationInfo | null {
  const stsStationId = locationStationNumber(location);
  if (stsStationId == null) return null;

  const mstoIds = locationMstoServicePointIds(location);

  return {
    code: location.code || String(stsStationId),
    name: location.name || `АЗС ${stsStationId}`,
    description: location.description,
    stsStationId,
    mstoServicePointId: mstoIds[0],
    mstoServicePointIds: mstoIds.length > 0 ? mstoIds : undefined,
  };
}
