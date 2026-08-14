/**
 * Переключатель организации — юрлица внутри учёта компании.
 *
 * Компания в шапке отвечает на вопрос «чей учёт»; организация — «какое юрлицо этого
 * учёта». У аутсорсера в одной базе 1С обычно ООО и ИП одного владельца, и без этого
 * выбора их НДС и прибыль складываются в одну цифру — тихо, без ошибки на экране.
 *
 * Стоит в шапке ВСЕГДА, а не только при нескольких юрлицах: место, где показано
 * текущее юрлицо, не должно появляться и исчезать — человек ищет его глазами там,
 * где видел в прошлый раз, и «сейчас смотрю на ООО» — такой же нужный факт, как и
 * возможность переключиться.
 */
import { Building2, Check, ChevronDown } from 'lucide-react'

import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'

export function OrganizationSelector() {
  const { organizations, organizationId, setOrganizationId, companyId } = useCompany()
  const { user } = useAuth()
  // Юрлицо, закреплённое правами. Сервер игнорирует заголовок у такого участника,
  // поэтому и переключатель не должен обещать выбор, которого не будет.
  const pinnedId = (user?.companies ?? []).find((c) => c.id === companyId)?.own_organization_id
  const pinned = pinnedId ? organizations.find((o) => o.id === pinnedId) : undefined
  const active = organizations.find((o) => o.id === organizationId)
  // Организаций может не быть вовсе (компания без своего учёта) — тогда переключатель
  // честно говорит об этом, а не притворяется, что выбор есть.
  const label = pinned ? pinned.name
    : active ? active.name
    : organizations.length ? 'Все организации'
    : 'Организация не заведена'

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={!!pinned}>
        <button title={pinned ? 'Юрлицо закреплено за вами правами доступа' : undefined}
          className="flex h-8 max-w-[220px] items-center gap-1.5 rounded-md border
                     border-border px-2.5 text-[13px] hover:bg-accent
                     disabled:cursor-default disabled:opacity-100"
          disabled={!!pinned}>
          <Building2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate">{label}</span>
          {!pinned && <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="center" className="w-64">
        {organizations.length === 0 && (
          <div className="px-2 py-3 text-[12px] text-muted-foreground">
            У компании нет ни одной организации. Заведите её в «Управлении» —
            без юрлица учёт не с чем связать.
          </div>
        )}
        {/* Сводный режим — законный, а не «фильтр не выбран»: картина по клиенту
            целиком нужна не реже, чем разрез по юрлицу. */}
        {organizations.length > 1 && (
          <DropdownMenuItem onClick={() => setOrganizationId(null)}
            className="flex items-center justify-between gap-2">
            <span>Все организации</span>
            {!organizationId && <Check className="h-3.5 w-3.5" />}
          </DropdownMenuItem>
        )}
        {organizations.map((o) => (
          <DropdownMenuItem key={o.id} onClick={() => setOrganizationId(o.id)}
            className="flex items-start justify-between gap-2">
            <span className="min-w-0">
              <span className="block truncate">{o.name}</span>
              {o.inn && (
                <span className={cn('block text-[11px] text-muted-foreground')}>
                  ИНН {o.inn}
                </span>
              )}
            </span>
            {organizationId === o.id && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
