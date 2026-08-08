import { useCentralCommercialWrite } from './useStoreCommercialPolicy'

export function StoreCommercialPolicyNotice() {
  const centralWrite = useCentralCommercialWrite()
  if (centralWrite) return null
  return (
    <div className="rounded-lg border border-amber-400/30 bg-amber-500/[0.06] px-3 py-2 text-xs text-amber-100/80">
      Политика v1: коммерческие решения исполняет администратор АЗС в агенте.
      Товаровед сети ведёт канон НСИ, разбирает предложения и видит аналитику,
      но не перезаписывает цены, ассортимент и ТТК станции.
    </div>
  )
}
