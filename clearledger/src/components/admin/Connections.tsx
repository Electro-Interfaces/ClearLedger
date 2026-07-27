/**
 * «Управление» → «Подключения»: чем пространство связано с внешним миром.
 *
 * Два слоя в одном разделе. Сверху — каналы связи самой платформы (чат, почта,
 * конференции, единый вход): ими ходят оповещения и вход между продуктами. Ниже — витрина
 * прикладных подключений (`SpaceConnectors`): файловые каналы Учёта, живые интеграции
 * Координатора, кто их владелец и когда последний раз приносили данные.
 *
 * Настройка остаётся у владельца подключения — здесь только состояние и переход. Ключи
 * провайдеров живут в приложении, и дублировать их в двух местах нельзя: разъедутся.
 */
import { useQuery } from '@tanstack/react-query'
import {
  CheckCircle2, Circle, KeyRound, Loader2, Mail, MessageSquare, MinusCircle, Video, XCircle,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SpaceConnectors } from '@/components/channels/SpaceConnectors'
import { getCoreStatus, type CoreServiceStatus } from '@/services/coreService'

const SERVICE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  chat: MessageSquare, conf: Video, mail: Mail,
}

/** Что означает состояние сервиса — словами, а не цветом: раздел читают не каждый день. */
function stateOf(s: CoreServiceStatus): { label: string; cls: string; Icon: React.ComponentType<{ className?: string }> } {
  switch (s.status) {
    case 'up': return { label: 'Работает', cls: 'text-emerald-500', Icon: CheckCircle2 }
    case 'down': return { label: 'Недоступен', cls: 'text-destructive', Icon: XCircle }
    case 'configured': return { label: 'Настроен', cls: 'text-amber-500', Icon: Circle }
    default: return { label: 'Не подключён', cls: 'text-muted-foreground', Icon: MinusCircle }
  }
}

export function Connections() {
  const st = useQuery({
    queryKey: ['core-status'], queryFn: getCoreStatus,
    staleTime: 30_000, refetchInterval: 60_000,
  })
  const d = st.data

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5" /> Каналы связи пространства
          </CardTitle>
          <CardDescription>
            Ими ходят оповещения и переход между продуктами. Состав включается профилем
            стека при развёртывании; «не подключён» — норма, если сервис не заказан.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1.5">
          {st.isLoading && (
            <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Проверяем сервисы…
            </div>
          )}
          {(d?.services ?? []).map((s) => {
            const v = stateOf(s)
            const Icon = SERVICE_ICON[s.code] ?? Circle
            return (
              <div key={s.code} className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                <span className="flex items-center gap-2 text-sm">
                  <Icon className="h-4 w-4 text-muted-foreground" /> {s.name}
                </span>
                <span className={`flex items-center gap-1.5 text-xs ${v.cls}`}>
                  <v.Icon className="h-3.5 w-3.5" /> {v.label}
                </span>
              </div>
            )
          })}
          {d && (
            <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
              <span className="flex items-center gap-2 text-sm">
                <KeyRound className="h-4 w-4 text-muted-foreground" /> Единый вход
              </span>
              <span className={`flex items-center gap-1.5 text-xs ${
                d.sso.enabled ? 'text-emerald-500' : 'text-muted-foreground'}`}>
                {d.sso.enabled
                  ? <><CheckCircle2 className="h-3.5 w-3.5" /> Настроен</>
                  : <><MinusCircle className="h-3.5 w-3.5" /> Не настроен</>}
              </span>
            </div>
          )}
          <p className="pt-1 text-xs text-muted-foreground">
            Реквизиты (издатель, ключи, адреса) — в разделе «Сервисы» уровня контейнера;
            кому и о чём сообщать — в «Оповещениях».
          </p>
        </CardContent>
      </Card>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-[10px]">приложения</Badge>
          <span className="text-sm text-muted-foreground">
            Откуда организация берёт данные — одним списком, независимо от продукта-владельца
          </span>
        </div>
        <SpaceConnectors />
      </div>
    </div>
  )
}
