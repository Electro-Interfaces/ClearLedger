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
import { TasksOverviewSection } from '@/components/tasks/TasksOverviewSection'

export function TasksOverviewPage() {
  const { company } = useCompany()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const days = Number(params.get('days')) || 30

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-lg font-semibold">Обзор</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Как идёт работа компании за период. Любая цифра — вход в реестр с этим
          же отбором.
        </p>
      </div>
      <TasksOverviewSection companyId={company.id} days={days}
        onDays={(d) => setParams((p) => {
          const n = new URLSearchParams(p)
          n.set('days', String(d))
          return n
        }, { replace: true })}
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
