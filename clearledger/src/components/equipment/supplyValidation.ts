import type { SupplyLinePayload } from '@/services/equipmentService'

/** Ключ и признак блокировки принадлежат форме, а не спецификации поставки. */
export type DraftLine = SupplyLinePayload & { _key: number; id?: string; locked?: boolean }

export const supplyLinesValid = (lines: DraftLine[]) =>
  lines.every((l) => l.locked || (Number.isFinite(l.qtyPlanned) && l.qtyPlanned > 0
    && (l.lineKind === 'spare' ? !!l.partId : Number.isInteger(l.qtyPlanned))
    && (l.unitPrice == null || (Number.isFinite(l.unitPrice) && l.unitPrice >= 0))))

export function supplyLinePayload(l: DraftLine): SupplyLinePayload {
  const p: Partial<DraftLine> = { ...l }
  delete p._key
  delete p.id
  delete p.locked
  return p as SupplyLinePayload
}
