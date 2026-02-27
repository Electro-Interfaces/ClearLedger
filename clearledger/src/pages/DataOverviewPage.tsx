import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  FileText, Wallet, Activity, Image, Users, Scale, ShieldCheck,
  type LucideIcon,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/data/StatusBadge'
import { SourceBadge } from '@/components/data/SourceBadge'
import { useCompany } from '@/contexts/CompanyContext'
import { useEntries, useKpi } from '@/hooks/useEntries'
import { useIsMobile } from '@/hooks/use-mobile'
import type { DataEntry } from '@/types'

const iconMap: Record<string, LucideIcon> = {
  FileText, Wallet, Activity, Image, Users, Scale, ShieldCheck,
}

const defaultFilter = { showArchived: false, showExcluded: false, showAllVersions: false }

export function DataOverviewPage() {
  const { effectiveCategories } = useCompany()
  const { data: entries = [], isLoading: entriesLoading } = useEntries(defaultFilter)
  const { data: kpi, isLoading: kpiLoading } = useKpi()
  const isMobile = useIsMobile()

  // Подсчёт по категориям и подкатегориям
  const categoryData = useMemo(() => {
    const byCat = new Map<string, { total: number; bySub: Map<string, number> }>()

    for (const e of entries) {
      let cat = byCat.get(e.categoryId)
      if (!cat) {
        cat = { total: 0, bySub: new Map() }
        byCat.set(e.categoryId, cat)
      }
      cat.total++
      cat.bySub.set(e.subcategoryId, (cat.bySub.get(e.subcategoryId) || 0) + 1)
    }

    return effectiveCategories.map((cat) => {
      const data = byCat.get(cat.id)
      const total = data?.total ?? 0
      const subcategories = cat.subcategories
        .map((sub) => ({ id: sub.id, label: sub.label, count: data?.bySub.get(sub.id) ?? 0 }))
        .filter((s) => s.count > 0)
        .sort((a, b) => b.count - a.count)
      return { ...cat, total, subcategories }
    })
  }, [entries, effectiveCategories])

  // Последние 10 документов
  const recentEntries = useMemo(() => {
    return [...entries]
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .slice(0, 10)
  }, [entries])

  // Лейблы категорий для таблицы
  const catLabelMap = useMemo(() => {
    const m = new Map<string, string>()
    for (const c of effectiveCategories) m.set(c.id, c.label)
    return m
  }, [effectiveCategories])

  if (entriesLoading) return <OverviewSkeleton />

  const totalDocs = entries.length

  return (
    <div className="space-y-6">
      {/* Заголовок + мини-KPI */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Данные</h1>
        {!kpiLoading && kpi && (
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span>Всего: <strong className="text-foreground">{totalDocs}</strong></span>
            <span>Сегодня: <strong className="text-foreground">{kpi.uploadedToday}</strong></span>
            {kpi.errors > 0 && (
              <Badge variant="destructive" className="text-xs">{kpi.errors} ошиб.</Badge>
            )}
          </div>
        )}
      </div>

      {/* Карточки категорий */}
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
        {categoryData.map((cat) => {
          const Icon = iconMap[cat.icon] ?? FileText
          return (
            <Link key={cat.id} to={`/data/${cat.id}`} className="group">
              <Card className="transition-colors group-hover:border-primary/50 h-full">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Icon className="size-5 text-muted-foreground" />
                      <CardTitle className="text-base">{cat.label}</CardTitle>
                    </div>
                    <span className="text-2xl font-bold tabular-nums">{cat.total}</span>
                  </div>
                </CardHeader>
                {cat.subcategories.length > 0 && (
                  <CardContent className="pt-0">
                    <div className="space-y-1">
                      {cat.subcategories.slice(0, 5).map((sub) => (
                        <div key={sub.id} className="flex items-center justify-between text-sm text-muted-foreground">
                          <span className="truncate mr-2">{sub.label}</span>
                          <span className="tabular-nums shrink-0">{sub.count}</span>
                        </div>
                      ))}
                      {cat.subcategories.length > 5 && (
                        <div className="text-xs text-muted-foreground/60">
                          +{cat.subcategories.length - 5} ещё
                        </div>
                      )}
                    </div>
                  </CardContent>
                )}
              </Card>
            </Link>
          )
        })}
      </div>

      {/* Последние документы */}
      {recentEntries.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Последние документы</h2>
          {isMobile ? (
            <RecentCardsMobile entries={recentEntries} catLabelMap={catLabelMap} />
          ) : (
            <RecentTable entries={recentEntries} catLabelMap={catLabelMap} />
          )}
        </div>
      )}
    </div>
  )
}

function RecentTable({ entries, catLabelMap }: { entries: DataEntry[]; catLabelMap: Map<string, string> }) {
  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Название</TableHead>
            <TableHead>Категория</TableHead>
            <TableHead>Источник</TableHead>
            <TableHead>Статус</TableHead>
            <TableHead className="text-right">Дата</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map((e) => (
            <TableRow key={e.id} className="cursor-pointer hover:bg-muted/50">
              <TableCell>
                <Link to={`/data/${e.categoryId}/${e.id}`} className="hover:underline font-medium">
                  {e.title}
                </Link>
              </TableCell>
              <TableCell className="text-muted-foreground">{catLabelMap.get(e.categoryId) ?? e.categoryId}</TableCell>
              <TableCell><SourceBadge source={e.source} /></TableCell>
              <TableCell><StatusBadge status={e.status} /></TableCell>
              <TableCell className="text-right text-muted-foreground tabular-nums whitespace-nowrap">
                {formatDate(e.createdAt)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}

function RecentCardsMobile({ entries, catLabelMap }: { entries: DataEntry[]; catLabelMap: Map<string, string> }) {
  return (
    <div className="space-y-2">
      {entries.map((e) => (
        <Link key={e.id} to={`/data/${e.categoryId}/${e.id}`}>
          <Card className="p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="font-medium truncate">{e.title}</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {catLabelMap.get(e.categoryId) ?? e.categoryId} &middot; {formatDate(e.createdAt)}
                </p>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <SourceBadge source={e.source} />
                <StatusBadge status={e.status} />
              </div>
            </div>
          </Card>
        </Link>
      ))}
    </div>
  )
}

function OverviewSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-32" />
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-36" />
        ))}
      </div>
      <Skeleton className="h-64" />
    </div>
  )
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}
