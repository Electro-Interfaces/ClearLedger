/**
 * Метка маркированного товара («Честный знак»).
 * Нейтральный zinc-стиль: маркировка — свойство товара, не алерт,
 * поэтому без цветового акцента (см. палитру badges в CLAUDE.md).
 */
export function ChzBadge() {
  return (
    <span
      title="Маркированный товар (Честный знак)"
      className="inline-flex items-center rounded-full border border-zinc-600 text-zinc-400 px-1.5 py-0.5 text-[9px] uppercase tracking-wide"
    >
      ЧЗ
    </span>
  )
}
