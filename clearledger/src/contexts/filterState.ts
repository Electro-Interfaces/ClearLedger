import type { FilterState } from './FilterContext'

function sameStringSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  const values = new Set(a)
  return b.every((value) => values.has(value))
}

export function sameFilterState(a: FilterState, b: FilterState): boolean {
  return a.period.from === b.period.from && a.period.to === b.period.to
    && a.stationCode === b.stationCode
    && sameStringSet(a.locationIds, b.locationIds)
    && sameStringSet(a.regionIds, b.regionIds)
    && sameStringSet(a.stationCodes, b.stationCodes)
    && sameStringSet(a.docTypeIds, b.docTypeIds)
}

export function activeFilterCount(state: FilterState): number {
  return (state.stationCode !== 'all' ? 1 : 0)
    + state.locationIds.length
    + state.regionIds.length
    + state.stationCodes.length
    + state.docTypeIds.length
}

export function clearFilterSelections(state: FilterState): FilterState {
  return {
    ...state,
    stationCode: 'all',
    locationIds: [],
    regionIds: [],
    stationCodes: [],
    docTypeIds: [],
  }
}
