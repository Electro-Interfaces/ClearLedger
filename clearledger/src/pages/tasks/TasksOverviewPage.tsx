/**
 * Раздел «Обзор» — ответ руководителю: сколько в работе, сколько горит, кто чем
 * занят. Не рабочее место: открывается не первым, а тогда, когда спрашивают
 * «как вообще дела».
 *
 * Цифра отсюда ведёт в реестр с готовым отбором — переход на корень продукта был
 * бы невыполненным обещанием.
 */
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { useDocsScope } from '@/hooks/useDocsScope'
import { TasksOverviewSection } from '@/components/tasks/TasksOverviewSection'
import { TrackExport } from '@/components/docs/TrackExport'

export function TasksOverviewPage() {
  const { company } = useCompany()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const scope = useDocsScope()
  // Период раздела «Отчёты». Явные даты в адресе остаются ради ссылок «вернуться
  // к тому же отчёту», своего регулятора экран не держит.
  const period = {
    from: params.get('date_from') ?? scope.period.from,
    to: params.get('date_to') ?? scope.period.to,
  }

  return (
    <div className="space-y-4 px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-base font-semibold">Поручения</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Как идёт работа компании за период. Любая цифра — вход в реестр с этим
            же отбором.
          </p>
        </div>
        <TrackExport
          href={`/api/docs/reports/export?${new URLSearchParams({
            report: 'errands', company_id: company.id,
            date_from: period.from, date_to: period.to }).toString()}`}
          fileName="Поручения Трека.xlsx"
          hint="Итоги и разрезы по людям, типам и объектам — книгой Excel" />
      </div>
      <TasksOverviewSection companyId={company.id} period={period}
        onDrill={(f) => {
          const n = new URLSearchParams({ view: 'registry' })
          // Обзор считает по всем задачам периода, поэтому и реестр открываем
          // без сужения по состоянию — иначе цифра и список разойдутся.
          if (f.assignee) n.set('assignee', f.assignee)
          if (f.type) n.set('type', f.type)
          if (f.object) n.set('object', f.object)
          navigate(`/tasks/company?${n.toString()}`)
        }} />
    </div>
  )
}

export default TasksOverviewPage
