/**
 * Центр управления → «Обзор экосистемы». Живое состояние Ядра (версия/окружение,
 * SSO, реестр, счётчики) и платформенных сервисов (чат/конференции/почта).
 * Только суперадмин (эндпоинт core/status гейтит на бэкенде).
 */
import { useQuery } from '@tanstack/react-query'
import {
  Loader2, Activity, KeyRound, Boxes, Building2, Users,
  MessageSquare, Video, Mail, CheckCircle2, XCircle, MinusCircle, Circle,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { getCoreStatus, type CoreServiceStatus } from '@/services/coreService'

const SERVICE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  chat: MessageSquare, conf: Video, mail: Mail,
}

function serviceBadge(s: CoreServiceStatus) {
  switch (s.status) {
    case 'up':
      return <Badge className="gap-1 border-emerald-400/50 bg-transparent text-emerald-300/90" variant="outline"><CheckCircle2 className="h-3 w-3" /> Работает</Badge>
    case 'down':
      return <Badge className="gap-1" variant="destructive"><XCircle className="h-3 w-3" /> Недоступен</Badge>
    case 'configured':
      return <Badge className="gap-1 border-amber-400/50 bg-transparent text-amber-300/90" variant="outline"><Circle className="h-3 w-3" /> Настроен</Badge>
    default:
      return <Badge className="gap-1 border-zinc-600 bg-transparent text-zinc-400" variant="outline"><MinusCircle className="h-3 w-3" /> Не подключён</Badge>
  }
}

function Stat({ icon: Icon, label, value }: { icon: React.ComponentType<{ className?: string }>; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary shrink-0"><Icon className="h-4 w-4" /></div>
      <div className="min-w-0">
        <div className="text-lg font-semibold leading-tight tabular-nums">{value}</div>
        <div className="text-xs text-muted-foreground truncate">{label}</div>
      </div>
    </div>
  )
}

export function CoreOverview() {
  const q = useQuery({ queryKey: ['core-status'], queryFn: getCoreStatus, staleTime: 30_000, refetchInterval: 60_000 })

  if (q.isLoading) {
    return <div className="flex items-center gap-2 text-muted-foreground py-8"><Loader2 className="h-4 w-4 animate-spin" /> Загрузка состояния…</div>
  }
  if (q.isError || !q.data) {
    return <Card><CardContent className="py-8 text-center text-muted-foreground">Не удалось получить состояние Ядра</CardContent></Card>
  }
  const d = q.data

  return (
    <div className="space-y-4">
      {/* Ядро + SSO */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4 text-primary" /> Ядро экосистемы
            <Badge variant="outline" className="ml-1 font-mono text-[10px]">v{d.version}</Badge>
            <Badge variant="secondary" className="text-[10px]">{d.env}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Stat icon={Building2} label="Компании" value={d.counts.companies} />
          <Stat icon={Users} label="Пользователи" value={d.counts.users} />
          <Stat icon={Boxes} label="Приложения / модули" value={`${d.registry.apps} / ${d.registry.modules}`} />
          <Stat icon={KeyRound} label={d.sso.enabled ? `SSO · ${d.sso.issuer}` : 'SSO не настроен'}
            value={d.sso.enabled
              ? <span className="text-emerald-400">вкл</span>
              : <span className="text-zinc-400">выкл</span>} />
        </CardContent>
      </Card>

      {/* SSO деталь */}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><KeyRound className="h-4 w-4 text-primary" /> Единый вход (SSO)</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground flex flex-wrap gap-x-6 gap-y-1">
          <span>Издатель: <span className="text-foreground font-mono">{d.sso.issuer}</span></span>
          <span>kid: <span className="text-foreground font-mono">{d.sso.kid}</span></span>
          <span>Ключей JWKS: <span className="text-foreground">{d.sso.jwksKeys}</span></span>
          <span>Приложений в лаунчере: <span className="text-foreground">{d.sso.apps}</span></span>
        </CardContent>
      </Card>

      {/* Платформенные сервисы */}
      <Card>
        <CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-base"><Boxes className="h-4 w-4 text-primary" /> Платформенные сервисы</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {d.services.map((s) => {
            const Icon = SERVICE_ICON[s.code] ?? Circle
            return (
              <div key={s.code} className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                <span className="flex items-center gap-2 text-sm">
                  <Icon className="h-4 w-4 text-muted-foreground" /> {s.name}
                </span>
                {serviceBadge(s)}
              </div>
            )
          })}
          <p className="text-xs text-muted-foreground pt-1">
            Сервисы включаются по составу стека экосистемы (профили) и опциональны — «Не подключён» это норма.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
