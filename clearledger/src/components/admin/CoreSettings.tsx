/**
 * «Управление» → «Сервисы»: как настроены единый вход, лаунчер и платформенные сервисы.
 *
 * Раздел отвечает «как настроено» — реквизиты, состав, адреса. На вопрос «как сейчас»
 * (что отвечает, что упало) отвечает «Обзор», поэтому дублирующих индикаторов состояния
 * здесь нет. Ключи и секреты задаются в окружении стека и из интерфейса не правятся.
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2, KeyRound, Boxes, LayoutGrid } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { getCoreStatus } from '@/services/coreService'
import { listSsoApps } from '@/services/ssoService'

export function CoreSettings() {
  const st = useQuery({ queryKey: ['core-status'], queryFn: getCoreStatus, staleTime: 30_000 })
  // Обёртка обязательна: react-query передал бы в listSsoApps свой контекст вместо companyId.
  const apps = useQuery({ queryKey: ['sso-apps'], queryFn: () => listSsoApps(), staleTime: 60_000 })

  if (st.isLoading) {
    return <div className="flex items-center gap-2 text-muted-foreground py-8"><Loader2 className="h-4 w-4 animate-spin" /> Загрузка…</div>
  }
  const d = st.data
  const launcher = apps.data?.apps ?? []

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><KeyRound className="h-4 w-4 text-primary" /> Единый вход (SSO)</CardTitle></CardHeader>
        <CardContent className="text-sm space-y-1 text-muted-foreground">
          <div>Состояние: {d?.sso.enabled ? <span className="text-emerald-400">настроен</span> : <span className="text-zinc-400">не настроен</span>}</div>
          <div>Издатель: <span className="text-foreground font-mono">{d?.sso.issuer}</span> · kid <span className="text-foreground font-mono">{d?.sso.kid}</span> · ключей JWKS <span className="text-foreground">{d?.sso.jwksKeys ?? 0}</span></div>
          <div className="text-xs">Ключ подписи задаётся в окружении стека (SSO_SIGNING_KEY) — не редактируется из интерфейса в целях безопасности.</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><LayoutGrid className="h-4 w-4 text-primary" /> Приложения в лаунчере</CardTitle></CardHeader>
        <CardContent className="space-y-1">
          {launcher.map((a) => (
            <div key={a.code} className="flex items-center justify-between gap-2 text-sm rounded border px-3 py-1.5">
              <span>{a.name} <span className="text-muted-foreground font-mono text-xs">{a.code}</span></span>
              <span className="text-muted-foreground text-xs font-mono truncate max-w-[45%]">{a.base_url}</span>
            </div>
          ))}
          {launcher.length === 0 && <p className="text-sm text-muted-foreground">Каталог пуст (SSO_APPS не задан).</p>}
          <p className="text-xs text-muted-foreground pt-1">Каталог задаётся SSO_APPS в окружении или манифестами apps/*.yml.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><Boxes className="h-4 w-4 text-primary" /> Платформенные сервисы</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {(d?.services ?? []).map((s) => (
            <div key={s.code} className="flex items-center justify-between border-b last:border-0 py-1.5">
              <span>{s.name}</span>
              <Badge variant="outline" className="text-[10px]">{s.configured ? 'подключён' : 'не подключён'}</Badge>
            </div>
          ))}
          <p className="text-xs pt-2">
            Состав сервисов управляется профилями стека (STACK_SERVICES) при развёртывании;
            «не подключён» — норма, если сервис не заказан. Отвечает ли сервис прямо сейчас —
            видно в «Обзоре».
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
