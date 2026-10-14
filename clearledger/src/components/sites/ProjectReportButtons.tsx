/**
 * Выгрузка проекта: Excel со всеми листами и PDF-презентация для совещания и печати.
 * Оба формата — из одного серверного отчёта (`projectReportService`).
 */
import { useState } from 'react'
import { toast } from 'sonner'
import { FileSpreadsheet, FileText, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { downloadProjectPdf, downloadProjectXlsx } from '@/services/projectReportService'

export function ProjectReportButtons({ companyId, siteId, projectNo }: { companyId: string; siteId: string; projectNo?: string | null }) {
  const { company } = useCompany()
  const [busy, setBusy] = useState<'xlsx' | 'pdf' | null>(null)
  const run = async (kind: 'xlsx' | 'pdf') => {
    setBusy(kind)
    try {
      if (kind === 'xlsx') await downloadProjectXlsx(companyId, siteId, projectNo)
      else await downloadProjectPdf(companyId, siteId, company?.name || 'Пространство')
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Выгрузка не удалась') }
    finally { setBusy(null) }
  }
  return (
    <div className="flex items-center gap-1 shrink-0">
      <Button variant="outline" size="sm" className="h-8 text-sm" disabled={!!busy} onClick={() => void run('xlsx')}
        title="Excel проекта: сводка, чек-лист, работа, присоединение, бюджет, документы, полная история">
        {busy === 'xlsx' ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <FileSpreadsheet className="h-3.5 w-3.5 mr-1" />}Excel
      </Button>
      <Button variant="outline" size="sm" className="h-8 text-sm" disabled={!!busy} onClick={() => void run('pdf')}
        title="PDF-презентация проекта для совещания и печати">
        {busy === 'pdf' ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <FileText className="h-3.5 w-3.5 mr-1" />}PDF
      </Button>
    </div>
  )
}
