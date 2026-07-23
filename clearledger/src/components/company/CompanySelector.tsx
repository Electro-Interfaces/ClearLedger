import { useCompany } from '@/contexts/CompanyContext'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export function CompanySelector() {
  const { companyId, setCompanyId, companies } = useCompany()

  // Одна компания в контейнере — выбирать не из чего, селектор скрыт вовсе
  // (имя компании и так в шапке экосистемы / рабочего стола).
  if (companies.length <= 1) return null

  return (
    <Select value={companyId} onValueChange={setCompanyId}>
      {/* w-full+max-w вместо жёсткой ширины: на мобиле узкий центр шапки —
          фиксированные 200px не ужимались и наезжали на логотип/тему */}
      <SelectTrigger
        className="h-10 w-full min-w-[112px] max-w-[200px] text-sm font-medium bg-secondary border-border [&>span]:truncate"
      >
        <SelectValue placeholder="Выберите компанию" />
      </SelectTrigger>
      <SelectContent
        style={{ boxShadow: 'var(--shadow-large)' }}
      >
        {companies.map((c) => (
          <SelectItem key={c.id} value={c.id}>
            <div className="flex items-center gap-2">
              <div
                className="size-2.5 shrink-0 rounded-full"
                style={{ background: c.color }}
              />
              <span>{c.name}</span>
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
