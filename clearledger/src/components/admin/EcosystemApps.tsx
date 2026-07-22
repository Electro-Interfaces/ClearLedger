/**
 * Центр управления → Экосистема → «Каталог приложений». Список приложений и модулей,
 * которые можно подключить к системе, + настройка приложения при подключении
 * (описание/адрес/конфиг/активность). Включение компаниям — на уровне компании.
 * Только суперадмин (эндпоинты /registry/apps гейтят на бэкенде).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, Blocks, Settings2, ChevronDown } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { getAppCatalog, updateApp, type CatalogApp } from '@/services/registryService'

export function EcosystemApps() {
  const q = useQuery({ queryKey: ['app-catalog'], queryFn: getAppCatalog })

  if (q.isLoading) {
    return <div className="flex items-center gap-2 text-muted-foreground py-8"><Loader2 className="h-4 w-4 animate-spin" /> Загрузка каталога…</div>
  }
  const apps = q.data ?? []

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Приложения и модули, доступные для подключения к системе. Настройка приложения — по кнопке
        «Настроить». Включение конкретным компаниям — на уровне компании (вкладка «Приложения»).
      </p>
      {apps.map((a) => <AppCatalogCard key={a.id} app={a} />)}
      {apps.length === 0 && (
        <Card><CardContent className="py-8 text-center text-muted-foreground">Каталог пуст</CardContent></Card>
      )}
    </div>
  )
}

function AppCatalogCard({ app }: { app: CatalogApp }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [desc, setDesc] = useState(app.description ?? '')
  const [url, setUrl] = useState(app.baseUrl ?? '')
  const [active, setActive] = useState(app.isActive)
  const [cfg, setCfg] = useState(JSON.stringify(app.config ?? {}, null, 2))

  const save = useMutation({
    mutationFn: () => {
      let config: Record<string, unknown>
      try {
        config = cfg.trim() ? JSON.parse(cfg) : {}
      } catch {
        throw new Error('Конфигурация — невалидный JSON')
      }
      return updateApp(app.id, { description: desc, base_url: url, config, is_active: active })
    },
    onSuccess: () => { toast.success('Настройки сохранены'); qc.invalidateQueries({ queryKey: ['app-catalog'] }) },
    onError: (e) => toast.error((e as Error).message),
  })

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base flex-wrap">
              <Blocks className="h-4 w-4 text-primary shrink-0" /> {app.name}
              <Badge variant="outline" className="font-mono text-[10px]">{app.code}</Badge>
              <Badge variant="secondary" className="text-[10px]">{app.kind}</Badge>
              {!app.isActive && <Badge variant="outline" className="text-[10px] border-zinc-600 text-zinc-400">выключено</Badge>}
            </CardTitle>
            {app.description && <p className="text-sm text-muted-foreground mt-1">{app.description}</p>}
          </div>
          <Button variant="outline" size="sm" className="gap-1.5 shrink-0" onClick={() => setOpen((o) => !o)}>
            <Settings2 className="h-4 w-4" /> Настроить
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-0 space-y-3">
        {/* Модули приложения */}
        <div>
          <div className="text-xs font-medium text-muted-foreground mb-1.5">Модули ({app.modules.length})</div>
          <div className="flex flex-wrap gap-1.5">
            {app.modules.map((m) => (
              <Badge key={m.code} variant="outline" className="text-[11px] gap-1" title={m.description ?? undefined}>
                {m.name}
                {m.isCore && <span className="text-primary">ядро</span>}
                {!m.defaultOn && <span className="text-muted-foreground">off</span>}
              </Badge>
            ))}
            {app.modules.length === 0 && <span className="text-xs text-muted-foreground">без модулей</span>}
          </div>
        </div>

        {/* Настройка при подключении */}
        {open && (
          <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label className="text-xs">Описание</Label>
                <Input value={desc} onChange={(e) => setDesc(e.target.value)} /></div>
              <div className="space-y-1.5"><Label className="text-xs">Адрес (base URL)</Label>
                <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" /></div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Конфигурация (JSON)</Label>
              <textarea value={cfg} onChange={(e) => setCfg(e.target.value)} rows={5} spellCheck={false}
                className="w-full rounded-md border bg-background px-3 py-2 text-sm font-mono" />
              <p className="text-[11px] text-muted-foreground">
                Параметры интеграции приложения. Секреты (ключи/пароли) — в окружении стека, НЕ сюда.
              </p>
            </div>
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <Switch checked={active} onCheckedChange={setActive} /> Активно в экосистеме
              </label>
              <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
                {save.isPending && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />} Сохранить
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
