/**
 * Центр управления → Экосистема → «Пользователи». Все пользователи экосистемы
 * (суперадмин-обзор). Управление составом — на уровне компании (вкладка «Сотрудники»).
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2, ShieldCheck } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { listAllUsers } from '@/services/userService'

export function EcosystemUsers() {
  const q = useQuery({ queryKey: ['ecosystem-users'], queryFn: listAllUsers, staleTime: 30_000 })

  if (q.isLoading) {
    return <div className="flex items-center gap-2 text-muted-foreground py-8"><Loader2 className="h-4 w-4 animate-spin" /> Загрузка…</div>
  }
  const users = q.data ?? []

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Все пользователи экосистемы ({users.length}). Управление составом и ролями — на уровне компании.
      </p>
      <div className="rounded-lg border divide-y">
        {users.map((u) => (
          <div key={u.id} className="flex items-center gap-3 px-3 py-2.5 flex-wrap">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium flex items-center gap-2">
                {u.name || '—'}
                {u.is_superadmin && (
                  <Badge variant="outline" className="gap-1 border-amber-400/50 bg-transparent text-amber-300/90 text-[10px]">
                    <ShieldCheck className="h-3 w-3" /> суперадмин
                  </Badge>
                )}
              </div>
              <div className="text-xs text-muted-foreground truncate">{u.email}</div>
            </div>
            <div className="flex flex-wrap gap-1 justify-end">
              {u.companies.map((c) => (
                <Badge key={c.slug} variant="outline" className="text-[10px] gap-1">
                  {c.name}
                  <span className={c.role === 'admin' ? 'text-primary' : 'text-muted-foreground'}>
                    {c.role === 'admin' ? 'админ' : 'польз.'}
                  </span>
                </Badge>
              ))}
              {u.companies.length === 0 && <span className="text-xs text-muted-foreground">без компаний</span>}
            </div>
          </div>
        ))}
        {users.length === 0 && <div className="px-3 py-8 text-center text-muted-foreground text-sm">Нет пользователей</div>}
      </div>
    </div>
  )
}
