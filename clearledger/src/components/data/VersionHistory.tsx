import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { StatusBadge } from './StatusBadge'
import { formatDateTime } from '@/lib/formatDate'
import { History, Star, StarOff } from 'lucide-react'
import { getVersionHistory, setActiveVersion, type VersionInfo } from '@/services/versionService'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

interface VersionHistoryProps {
  entryId: string
}

export function VersionHistory({ entryId }: VersionHistoryProps) {
  const { companyId } = useCompany()
  const { category } = useParams<{ category: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [versions, setVersions] = useState<VersionInfo[]>([])

  useEffect(() => {
    getVersionHistory(companyId, entryId).then(setVersions)
  }, [companyId, entryId])

  if (versions.length <= 1) return null

  async function handleSetActive(versionId: string) {
    await setActiveVersion(companyId, versionId)
    queryClient.invalidateQueries({ queryKey: ['entries', companyId] })
    toast.success('Версия сделана актуальной')
    // Обновляем локальный список
    const updated = await getVersionHistory(companyId, entryId)
    setVersions(updated)
  }

  function handleNavigateToVersion(versionId: string) {
    if (versionId !== entryId) {
      navigate(`/data/${category}/${versionId}`)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <History className="size-4" />
          История версий ({versions.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {versions.map((v) => (
          <div
            key={v.id}
            className={`flex items-center gap-2 p-2 rounded-md text-sm cursor-pointer hover:bg-muted/50 ${v.id === entryId ? 'bg-muted/30 border border-border' : ''}`}
            onClick={() => handleNavigateToVersion(v.id)}
          >
            <Badge variant="outline" className="shrink-0">v{v.version}</Badge>
            <span className="flex-1 truncate">{v.title}</span>
            <StatusBadge status={v.status} />
            {v.isLatest ? (
              <Star className="size-3.5 text-yellow-500 shrink-0" />
            ) : (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-1.5"
                onClick={(e) => { e.stopPropagation(); handleSetActive(v.id) }}
                title="Сделать актуальной"
              >
                <StarOff className="size-3.5 text-muted-foreground" />
              </Button>
            )}
            <span className="text-xs text-muted-foreground shrink-0">{formatDateTime(v.createdAt)}</span>
          </div>
        ))}
        {versions.some((v) => v.note) && (
          <div className="space-y-1 pt-1">
            {versions.filter((v) => v.note).map((v) => (
              <p key={v.id} className="text-xs text-muted-foreground">
                v{v.version}: {v.note}
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
