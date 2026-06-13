/**
 * CatalogPage — галереи трёх справочников входного контура TradeLedger:
 * Источники (типы) · Каналы (шаблоны) · Разрезы сверки.
 * Читает /api/source-types, /api/channel-templates, /api/reconcile-rules.
 */
import { type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  getChannelTemplates,
  getReconcileRules,
  getSourceTypes,
  type ChannelTemplateItem,
  type ReconcileRuleItem,
  type SourceTypeItem,
} from '@/services/catalogService'

type BadgeVariant = 'default' | 'secondary' | 'outline'

function statusVariant(status: string): BadgeVariant {
  if (status === 'available' || status === 'imperative') return 'default'
  if (status === 'partial') return 'secondary'
  return 'outline'
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{children}</div>
}

function Loading() {
  return (
    <Grid>
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-40 w-full rounded-xl" />
      ))}
    </Grid>
  )
}

export function CatalogPage() {
  const sources = useQuery({ queryKey: ['catalog', 'source-types'], queryFn: getSourceTypes })
  const channels = useQuery({ queryKey: ['catalog', 'channel-templates'], queryFn: getChannelTemplates })
  const rules = useQuery({ queryKey: ['catalog', 'reconcile-rules'], queryFn: getReconcileRules })

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Каталоги входного контура</h1>
        <p className="text-sm text-muted-foreground">
          Источники · Каналы · Разрезы сверки — справочники, из которых собирается обработка данных компании.
        </p>
      </div>

      <Tabs defaultValue="sources">
        <TabsList>
          <TabsTrigger value="sources">Источники</TabsTrigger>
          <TabsTrigger value="channels">Каналы</TabsTrigger>
          <TabsTrigger value="rules">Разрезы сверки</TabsTrigger>
        </TabsList>

        <TabsContent value="sources" className="mt-4">
          {sources.isLoading ? (
            <Loading />
          ) : (
            <Grid>
              {(sources.data ?? []).map((s: SourceTypeItem) => (
                <Card key={s.source_type}>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-2">
                      <CardTitle className="text-base">{s.label}</CardTitle>
                      <Badge variant={statusVariant(s.status)}>{s.status}</Badge>
                    </div>
                    <CardDescription>
                      {s.category} · {s.source_type}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <p className="text-sm text-muted-foreground">{s.description}</p>
                    <div className="flex flex-wrap gap-1">
                      {s.available_doc_types.map((d) => (
                        <Badge key={d.id} variant="outline">
                          {d.name}
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </Grid>
          )}
        </TabsContent>

        <TabsContent value="channels" className="mt-4">
          {channels.isLoading ? (
            <Loading />
          ) : (
            <Grid>
              {(channels.data ?? []).map((c: ChannelTemplateItem) => (
                <Card key={c.id}>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-2">
                      <CardTitle className="text-base">{c.label}</CardTitle>
                      <Badge variant={statusVariant(c.status)}>{c.status}</Badge>
                    </div>
                    <CardDescription>
                      {c.category} · {c.streams.length} потоков · {c.stages.length} стадий
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <p className="text-sm text-muted-foreground">{c.description}</p>
                    <div className="flex flex-wrap gap-1">
                      {c.reconcile_rules.map((r) => (
                        <Badge key={r} variant="secondary">
                          {r}
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </Grid>
          )}
        </TabsContent>

        <TabsContent value="rules" className="mt-4">
          {rules.isLoading ? (
            <Loading />
          ) : (
            <Grid>
              {(rules.data ?? []).map((r: ReconcileRuleItem) => (
                <Card key={r.id}>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-2">
                      <CardTitle className="text-base">{r.label}</CardTitle>
                      <Badge variant={statusVariant(r.status)}>{r.status}</Badge>
                    </div>
                    <CardDescription>
                      {r.module} · ключ: {r.key.join(', ')}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <p className="text-sm text-muted-foreground">{r.description}</p>
                    <div className="flex flex-wrap gap-1">
                      {r.streams.map((st, i) => (
                        <Badge key={i} variant="outline">
                          {st.role}: {st.source_type}
                        </Badge>
                      ))}
                    </div>
                    {r.impl ? (
                      <p className="text-xs text-muted-foreground">impl: {r.impl}</p>
                    ) : null}
                  </CardContent>
                </Card>
              ))}
            </Grid>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
