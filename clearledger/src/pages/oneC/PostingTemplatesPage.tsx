/**
 * Страница «1С → Схема проведения».
 * Список шаблонов проводок по типу документа + ВидОперации.
 * Используется для подсветки факт vs план в Sheet документа (DocumentsPage).
 *
 * Источник — GET /api/posting-templates.
 * Глобальные шаблоны (company_id=NULL) сидятся при старте сервера.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { BookOpen, Globe, Building2, Loader2 } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { get } from '@/services/apiClient'

interface Expected {
  dt: string
  kt: string
  formula: string | null
  comment: string | null
}

interface PostingTemplate {
  id: string
  company_id: string | null
  doc_type: string
  operation_type: string | null
  name: string
  expected: Expected[]
  notes: string | null
  created_at: string
}

async function fetchTemplates(companyId: string): Promise<PostingTemplate[]> {
  return get<PostingTemplate[]>('/api/posting-templates', { company_id: companyId })
}

const DOC_TYPES = ['Все', 'ПТУ', 'ОРП', 'ОПЗС', 'КорректировкаПоступления']

export function PostingTemplatesPage() {
  const { companyId } = useCompany()
  const [docType, setDocType] = useState('Все')

  const { data, isLoading, error } = useQuery({
    queryKey: ['posting-templates', companyId],
    queryFn: () => fetchTemplates(companyId),
  })

  const filtered = (data ?? []).filter((t) => docType === 'Все' || t.doc_type === docType)

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <BookOpen className="h-6 w-6" />
          Схема проведения документов
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Эталонные проводки по типу документа и ВидуОперации. Используются для подсветки
          «факт vs план» при просмотре документа. Глобальные шаблоны помечены значком{' '}
          <Globe className="inline h-3 w-3" />. Шаблоны компании перекрывают глобальные.
        </p>
      </div>

      <Tabs value={docType} onValueChange={setDocType}>
        <TabsList>
          {DOC_TYPES.map((t) => (
            <TabsTrigger key={t} value={t}>{t}</TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value={docType} className="mt-4 space-y-3">
          {error && (
            <Card className="border-red-500/40">
              <CardContent className="pt-6 text-sm text-red-400">
                Ошибка: {error instanceof Error ? error.message : String(error)}
              </CardContent>
            </Card>
          )}
          {isLoading && (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin mr-2" />
              Загрузка...
            </div>
          )}
          {!isLoading && filtered.length === 0 && (
            <Card>
              <CardContent className="pt-6 text-sm text-muted-foreground text-center">
                Шаблонов нет.
              </CardContent>
            </Card>
          )}
          {filtered.map((t) => (
            <Card key={t.id}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-base flex items-center gap-2">
                      {t.company_id ? <Building2 className="h-4 w-4" /> : <Globe className="h-4 w-4 text-muted-foreground" />}
                      {t.name}
                    </CardTitle>
                    <CardDescription className="text-xs mt-1 flex items-center gap-2">
                      <Badge variant="outline">{t.doc_type}</Badge>
                      {t.operation_type && (
                        <Badge variant="outline" className="font-normal">
                          ВидОперации = {t.operation_type}
                        </Badge>
                      )}
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border/50 text-muted-foreground">
                      <th className="text-left font-medium py-1.5 w-20">Дт</th>
                      <th className="text-left font-medium py-1.5 w-20">Кт</th>
                      <th className="text-left font-medium py-1.5 w-48">Формула</th>
                      <th className="text-left font-medium py-1.5">Комментарий</th>
                    </tr>
                  </thead>
                  <tbody>
                    {t.expected.map((e, i) => (
                      <tr key={i} className="border-b border-border/30 last:border-0">
                        <td className="py-1.5 font-mono text-blue-300">{e.dt}</td>
                        <td className="py-1.5 font-mono text-amber-300">{e.kt}</td>
                        <td className="py-1.5 font-mono text-muted-foreground">{e.formula ?? '—'}</td>
                        <td className="py-1.5 text-muted-foreground">{e.comment ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {t.notes && (
                  <p className="text-[11px] text-muted-foreground mt-2 italic">{t.notes}</p>
                )}
              </CardContent>
            </Card>
          ))}
        </TabsContent>
      </Tabs>
    </div>
  )
}
