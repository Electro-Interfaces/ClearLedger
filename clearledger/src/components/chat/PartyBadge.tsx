/**
 * Подпись «кто это» для участника чата.
 *
 * В общей комнате сотрудник компании и внешний подрядчик выглядят одинаково — просто
 * имена. Разговор с ними разный: своему можно писать про внутренние дела, внешнему нет.
 * Поэтому у имени всегда видно принадлежность: свой сотрудник (и админ ли он) или
 * внешний участник и от какой организации.
 *
 * Права здесь не показываются — это отдельная сущность (роль доступа). Бейдж отвечает
 * только на вопрос «с кем я говорю».
 */
import { Building2, LifeBuoy, ShieldCheck, UserRound } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface PartyInfo {
  partyType?: 'internal' | 'partner' | 'vendor'
  role?: string
  orgName?: string | null
  position?: string | null
  online?: boolean
  lastSeenAt?: string | null
}

/** Подпись: «Поддержка платформы» / «Внешний · ООО Подрядчик» / «Администратор» / «Сотрудник». */
export function partyLabel(p: PartyInfo | undefined): string {
  if (!p) return ''
  if (p.partyType === 'vendor') return p.orgName ? `Поддержка платформы · ${p.orgName}` : 'Поддержка платформы'
  if (p.partyType === 'partner') return p.orgName ? `Внешний · ${p.orgName}` : 'Внешний участник'
  return p.role === 'admin' ? 'Администратор' : 'Сотрудник'
}

export function PartyBadge({ party, className, withIcon = true }: {
  party: PartyInfo | undefined
  className?: string
  withIcon?: boolean
}) {
  if (!party) return null
  const vendor = party.partyType === 'vendor'
  const external = party.partyType === 'partner'
  const admin = !external && !vendor && party.role === 'admin'
  const Icon = vendor ? LifeBuoy : external ? Building2 : admin ? ShieldCheck : UserRound

  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium leading-none',
        // Внешний участник выделен намеренно ярче: спутать его со своим — дороже,
        // чем лишний раз обратить внимание.
        vendor
          ? 'border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-400'
          : external
          ? 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400'
          : admin
            ? 'border-primary/30 bg-primary/10 text-primary'
            : 'border-border bg-muted/60 text-muted-foreground',
        className,
      )}
      title={party.position ? `${partyLabel(party)} · ${party.position}` : partyLabel(party)}
    >
      {withIcon && <Icon className="size-3" />}
      {vendor ? 'Поддержка' : external ? (party.orgName || 'Внешний') : admin ? 'Админ' : 'Сотрудник'}
    </span>
  )
}
